"""Supabase project helpers — the sole read/write path for projects,
project_assets (stored as JSON in documents), script_versions.

Field mapping between the Flask app's expected surface and the actual
Supabase `projects` schema:

    documents (JSONB) is used as our overflow bucket for fields the
    evolum-studio Supabase schema doesn't have:
        idea_text, synopsis_text (mirrored to `synopsis` column),
        script_text, characters (list), world (dict),
        assets (list of {kind, name, path, size_bytes, content_type, created_at}),
        deck_local_path, sizzle_local_path, analysis_local_path,
        brain_path.

    Boolean flags the templates expect (has_script / has_deck / has_sizzle /
    has_analysis) are computed on read, never persisted.

Every function takes the Supabase client (from db.get_sb()) and the
authenticated user's UUID id. Ownership is enforced on read+write; a
missing/not-owned project returns None or False from these helpers.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from functools import lru_cache
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from db import get_sb


# ─── Legacy Supabase Storage URL support ─────────────────────────────────
# Existing projects have deliverables stored as signed Supabase Storage URLs
# on first-class columns (deck_url, analysis_report_url, actor_prep_url,
# actor_booked_url), NOT in documents JSONB. We surface those as synthetic
# assets so templates + /project/<id>/asset/<kind> work without a DB migration.
_LEGACY_URL_KINDS = (
    # (kind used by templates/download-route,  column,               display name,                 mime)
    ("deck",          "deck_url",            "Pitch Deck (.pptx)",         "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ("analysis",      "analysis_report_url", "Script Analysis (.pdf)",     "application/pdf"),
    ("audition_prep", "actor_prep_url",      "Audition Prep (.pdf)",       "application/pdf"),
    ("booked_role",   "actor_booked_url",    "Booked-Role Packet (.pdf)",  "application/pdf"),
)


def _decode_signed_url_exp(url: str):
    """Return the JWT `exp` claim (unix ts) from a Supabase-signed URL, or None."""
    try:
        token = (parse_qs(urlparse(url).query).get("token") or [""])[0]
        if not token:
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        exp = payload.get("exp")
        return int(exp) if exp else None
    except Exception:
        return None


def _parse_supabase_signed_url(url: str):
    """Extract (bucket, object_path) from a `/storage/v1/object/sign/<bucket>/<path>` URL."""
    m = re.search(r"/storage/v1/object/sign/([^/]+)/(.+?)(?:\?|$)", url)
    return (m.group(1), m.group(2)) if m else None


@lru_cache(maxsize=256)
def _fresh_signed_url_cached(bucket: str, path: str, window: int) -> str:
    """Mint a fresh 7-day signed URL via the Supabase Storage API. `window` is
    a coarse time-bucket that gives the lru_cache a soft TTL (same key within
    the same window returns the cached fresh URL — one API call per 6 days
    per object, not per page-render).

    Raises on any failure — lru_cache does NOT cache exceptions, so transient
    Supabase errors won't poison the cache with empty-string fallbacks."""
    sb = get_sb()
    res = sb.storage.from_(bucket).create_signed_url(path, 60 * 60 * 24 * 7)
    new_url = None
    if isinstance(res, dict):
        new_url = res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
    if not new_url:
        raise RuntimeError(f"Supabase sign returned no URL for {bucket}/{path}")
    if new_url.startswith("/"):
        new_url = os.environ.get("SUPABASE_URL", "").rstrip("/") + new_url
    return new_url


def _ensure_fresh_url(url: str) -> str:
    """If a Supabase signed URL expires within the next hour, re-sign it.
    Returns the original URL on any failure — a stale link is better than a
    500 on the page render."""
    if not url or "/storage/v1/object/sign/" not in url:
        return url
    exp = _decode_signed_url_exp(url)
    now = int(time.time())
    if exp and exp > now + 3600:
        return url
    parsed = _parse_supabase_signed_url(url)
    if not parsed:
        return url
    bucket, path = parsed
    window = now // (60 * 60 * 24 * 6)  # 6-day cache bucket
    try:
        return _fresh_signed_url_cached(bucket, path, window)
    except Exception:
        return url


def _synthesize_assets_from_urls(row: dict, existing_kinds: set) -> list:
    """Turn populated legacy URL columns into synthetic asset entries.
    Skips kinds already present in documents.assets (local file wins per-kind)."""
    out = []
    for kind, col, name, mime in _LEGACY_URL_KINDS:
        if kind in existing_kinds:
            continue
        url = (row.get(col) or "").strip()
        if not url:
            continue
        out.append({
            "kind": kind,
            "name": name,
            "path": "",  # empty path → /project/<id>/asset/<kind> falls through to URL redirect
            "size_bytes": 0,  # unknown; templates treat 0 as "external"
            "content_type": mime,
            "created_at": row.get("updated_at") or row.get("created_at") or "",
            "source": "supabase_url",
        })
    return out


# ─── POSTER LIBRARY PICKER ────────────────────────────────────────────────
# Maps a project's analyzed world/genre → a random poster from the FAL-generated
# asset library at /static/asset_library/posters. Loaded lazily + cached; the
# manifest is read from disk once per process.

# world (from brain's detect_world) → poster genre slug (from prompt taxonomy)
_WORLD_TO_POSTER_GENRE = {
    "feature / action espionage thriller": "action_espionage",
    "feature / contained urban thriller":  "contained_urban",
    "feature / legal / courtroom drama":   "legal_courtroom",
    "feature / fantasy satire comedy":     "fantasy_satire",
    "feature / nightlife comedy":          "nightlife_comedy",
    "feature / sports drama":              "sports_drama",
    "feature / crime drama":               "crime_drama",
    "feature / drama":                     "drama",
}


@lru_cache(maxsize=1)
def _poster_manifest() -> dict:
    """Load /static/asset_library/posters_manifest.json. Returns empty dict if
    the file doesn't exist yet (library still being generated)."""
    for candidate in (
        "/opt/evolum/static/asset_library/posters_manifest.json",
        os.path.join(os.path.dirname(__file__), "static/asset_library/posters_manifest.json"),
    ):
        if os.path.exists(candidate):
            try:
                return json.loads(open(candidate).read())
            except Exception:
                return {}
    return {}


def pick_poster_for_project(project: dict) -> str:
    """Return the poster URL for a project. Prefers the project's OWN
    `poster_url` (real, custom, project-specific artwork stored in Supabase);
    falls back to a genre-appropriate silhouette from the library only when
    the project has no custom poster (typical for brand-new projects)."""
    # First choice: the project's own custom poster (already re-signed by _row_view)
    if project.get("poster_url"):
        return project["poster_url"]

    manifest = _poster_manifest()
    posters = manifest.get("posters", [])
    if not posters:
        return ""
    # world can come from either the row's analysis_data JSONB (legacy) or
    # future brain output stored in documents
    world = ""
    ad = project.get("analysis_data") or {}
    if isinstance(ad, dict):
        world = (ad.get("world") or "").strip()
    if not world:
        world = "feature / drama"
    genre = _WORLD_TO_POSTER_GENRE.get(world, "drama")
    matching = [p for p in posters if p.get("genre") == genre]
    if not matching:
        matching = [p for p in posters if p.get("genre") == "drama"] or posters
    # Deterministic pick keyed on project id so the same project always shows the
    # same poster across page loads
    pid = project.get("id", "")
    if pid:
        idx = int(hash(pid) % len(matching))
    else:
        idx = 0
    return matching[idx].get("path", "")


def _load_docs(row: dict) -> dict:
    docs = row.get("documents")
    if isinstance(docs, str):
        try:
            return json.loads(docs)
        except Exception:
            return {}
    return docs or {}


def _row_view(row: dict) -> dict:
    """Add computed fields the templates + downstream code expect."""
    docs = _load_docs(row)
    # Legacy fallback: existing projects store the logline on the first-class
    # `logline` column, not in documents.idea_text — surface it either way.
    row["idea_text"]       = docs.get("idea_text") or row.get("logline") or ""
    row["synopsis_text"]   = row.get("synopsis") or docs.get("synopsis_text", "")
    row["script_text"]     = docs.get("script_text", "")
    row["characters_json"] = json.dumps(docs.get("characters", []))
    row["world_json"]      = json.dumps(docs.get("world", {}))
    row["world_override"]  = docs.get("world_override", "")  # user's genre pick, blank = defer to classifier
    row["brain_path"]      = docs.get("brain_path", "")
    row["deck_path"]       = docs.get("deck_local_path", "")
    row["sizzle_path"]     = docs.get("sizzle_local_path", "")
    row["analysis_path"]   = docs.get("analysis_local_path", "")

    # Refresh expired Supabase Storage signed URLs on legacy first-class columns.
    # No-op for empty strings or non-signed URLs; lru_cache keeps this cheap.
    # Track any URLs that got refreshed so we can PERSIST them back to the row —
    # that way the next read reuses the fresh URL instead of resigning again
    # (Supabase's sign endpoint is intermittently flaky under load).
    url_writeback = {}
    def _refresh_col(col):
        old = row.get(col) or ""
        new = _ensure_fresh_url(old)
        row[col] = new
        if new and new != old and "/storage/v1/object/sign/" in new:
            url_writeback[col] = new
    for _kind, col, _name, _mime in _LEGACY_URL_KINDS:
        _refresh_col(col)
    _refresh_col("cover_image_url")
    _refresh_col("poster_url")
    if url_writeback and row.get("id"):
        try:
            get_sb().table("projects").update(url_writeback).eq("id", row["id"]).execute()
        except Exception:
            pass  # write-back is optimization, not correctness

    # Decode analysis_data JSONB (Supabase may hand it back as a string).
    ad = row.get("analysis_data")
    if isinstance(ad, str):
        try:
            row["analysis_data"] = json.loads(ad)
        except Exception:
            row["analysis_data"] = {}
    elif not isinstance(ad, dict):
        row["analysis_data"] = {}

    row["has_script"]      = bool(docs.get("script_text"))
    row["has_deck"]        = bool(row.get("deck_url") or docs.get("deck_local_path"))
    row["has_sizzle"]      = bool(docs.get("sizzle_local_path"))
    row["has_analysis"]    = bool(row.get("analysis_report_url") or docs.get("analysis_local_path"))

    # Merge documents.assets with synthesized assets from legacy Supabase URL
    # columns. Local wins per-kind.
    local_assets = docs.get("assets", [])
    existing_kinds = {a.get("kind") for a in local_assets}
    row["assets"]          = list(local_assets) + _synthesize_assets_from_urls(row, existing_kinds)

    # Effective poster URL: project's own custom poster if present, else
    # a genre-appropriate silhouette from the library. Templates should read
    # `project.effective_poster_url` for a single source of truth.
    row["effective_poster_url"] = pick_poster_for_project(row)
    # Legacy alias kept for the template that already reads it
    row["poster_library_url"] = row["effective_poster_url"]

    row["_docs"]           = docs   # so callers who need to write back keep the bucket
    return row


def list_projects_for_user(user_id: str) -> list[dict]:
    sb = get_sb()
    r = (sb.table("projects").select("*").eq("user_id", user_id)
         .order("updated_at", desc=True).execute())
    return [_row_view(dict(p)) for p in (r.data or [])]


def get_project(project_id: str, user_id: str) -> dict | None:
    """Fetch a project by id if the user owns it."""
    sb = get_sb()
    r = (sb.table("projects").select("*")
         .eq("id", project_id).eq("user_id", user_id).limit(1).execute())
    if not r.data:
        return None
    return _row_view(dict(r.data[0]))


def get_public_project_by_slug(slug: str) -> dict | None:
    """Fetch a project by slug FOR PUBLIC VIEW — only returns the row if
    public_page_enabled is true. No user_id check; anyone can read a
    published project's public view."""
    if not slug or not slug.strip():
        return None
    sb = get_sb()
    r = (sb.table("projects").select("*")
         .eq("slug", slug.strip()).eq("public_page_enabled", True).limit(1).execute())
    if not r.data:
        return None
    return _row_view(dict(r.data[0]))


def get_filmmaker_display_name(user_id: str) -> str:
    """Look up a filmmaker's public display name from profiles.name.
    Returns "" if not found. Used to render "By <name>" on the public page."""
    if not user_id:
        return ""
    try:
        sb = get_sb()
        r = sb.table("profiles").select("name").eq("id", user_id).limit(1).execute()
        if r.data:
            return (r.data[0].get("name") or "").strip()
    except Exception:
        pass
    return ""


def user_owns_project(project_id: str, user_id: str) -> bool:
    sb = get_sb()
    r = (sb.table("projects").select("id")
         .eq("id", project_id).eq("user_id", user_id).limit(1).execute())
    return bool(r.data)


def create_project(user_id: str, title: str, project_type: str = "filmmaker") -> str:
    """Insert a new project. Returns the new project's UUID."""
    sb = get_sb()
    row = {
        "user_id": user_id,
        "title": title[:200],
        "project_type": project_type[:64],
        "status": "draft",
        "documents": {},
    }
    r = sb.table("projects").insert(row).execute()
    return r.data[0]["id"] if r.data else ""


def update_project_fields(project_id: str, user_id: str, patch: dict) -> dict | None:
    """Apply a partial update. Handles both first-class columns (title,
    synopsis, status) and documents-bucket fields (idea_text, script_text,
    characters_json, world_json)."""
    if not user_owns_project(project_id, user_id):
        return None
    sb = get_sb()

    # Split incoming patch into first-class column updates + docs updates
    first_class = {}
    if "title" in patch:  first_class["title"]  = str(patch["title"])[:200]
    if "status" in patch: first_class["status"] = str(patch["status"])[:64]
    if "synopsis_text" in patch:
        first_class["synopsis"] = str(patch["synopsis_text"])[:4000]

    docs_patch: dict = {}
    if "idea_text" in patch:      docs_patch["idea_text"]     = str(patch["idea_text"])[:4000]
    if "synopsis_text" in patch:  docs_patch["synopsis_text"] = str(patch["synopsis_text"])[:4000]
    if "script_text" in patch:    docs_patch["script_text"]   = str(patch["script_text"])[:2_000_000]
    if "characters_json" in patch:
        try: docs_patch["characters"] = json.loads(patch["characters_json"])
        except Exception: docs_patch["characters"] = []
    if "world_json" in patch:
        try: docs_patch["world"] = json.loads(patch["world_json"])
        except Exception: docs_patch["world"] = {}

    # Genre picker: user-selected world override. Stored in documents.world_override
    # so the pipeline can read it. Empty string = clear the override, use classifier.
    if "world_override" in patch:
        val = str(patch["world_override"] or "").strip()[:80]
        docs_patch["world_override"] = val

    # Public sharing fields — first-class columns on the projects table.
    # Owner-set only; the /api/projects/<id> PATCH route enforces ownership.
    if "public_page_enabled" in patch:
        first_class["public_page_enabled"] = bool(patch["public_page_enabled"])
    if "public_blurb" in patch:
        first_class["public_blurb"] = str(patch["public_blurb"] or "")[:600]
    if "supporter_stripe_link" in patch:
        first_class["supporter_stripe_link"] = str(patch["supporter_stripe_link"] or "")[:400]
    if "slug" in patch:
        # normalize slug: lowercase, alphanumeric + hyphens only, max 60 chars
        raw = str(patch["slug"] or "").lower().strip()
        clean = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")[:60]
        if clean:
            first_class["slug"] = clean

    if docs_patch:
        # Merge — fetch existing documents JSONB, apply overlay, write back.
        r = (sb.table("projects").select("documents").eq("id", project_id).limit(1).execute())
        existing = _load_docs(r.data[0]) if r.data else {}
        existing.update(docs_patch)
        first_class["documents"] = existing

    if not first_class:
        return get_project(project_id, user_id)

    from datetime import datetime, timezone
    first_class["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb.table("projects").update(first_class).eq("id", project_id).execute()
    return get_project(project_id, user_id)


def delete_project(project_id: str, user_id: str) -> bool:
    if not user_owns_project(project_id, user_id):
        return False
    sb = get_sb()
    sb.table("projects").delete().eq("id", project_id).execute()
    return True


def record_asset(project_id: str, user_id: str, asset_kind: str,
                 asset_name: str, asset_path: str, size_bytes: int,
                 content_type: str = "") -> bool:
    """Append an asset entry to documents.assets and flip the relevant
    first-class column (deck_url etc. left NULL for local artifacts;
    documents.<kind>_local_path is set for the local file path)."""
    if not user_owns_project(project_id, user_id):
        return False
    sb = get_sb()
    from datetime import datetime, timezone

    r = sb.table("projects").select("documents").eq("id", project_id).limit(1).execute()
    docs = _load_docs(r.data[0]) if r.data else {}
    docs.setdefault("assets", []).insert(0, {
        "kind": asset_kind,
        "name": asset_name,
        "path": asset_path,
        "size_bytes": int(size_bytes),
        "content_type": content_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # Set local-path bookkeeping the templates read
    if asset_kind == "deck":     docs["deck_local_path"]     = asset_path
    if asset_kind == "sizzle":   docs["sizzle_local_path"]   = asset_path
    if asset_kind == "analysis": docs["analysis_local_path"] = asset_path
    if asset_kind == "brain":    docs["brain_path"]          = asset_path

    patch = {"documents": docs, "updated_at": datetime.now(timezone.utc).isoformat()}
    if asset_kind == "deck":     patch["status"] = "decking"
    if asset_kind == "sizzle":   patch["status"] = "ready"
    sb.table("projects").update(patch).eq("id", project_id).execute()
    return True


def latest_asset_of_kind(project_id: str, user_id: str, kind: str) -> dict | None:
    """Return the newest asset entry of the given kind for this project."""
    if not user_owns_project(project_id, user_id):
        return None
    sb = get_sb()
    r = sb.table("projects").select("documents").eq("id", project_id).limit(1).execute()
    if not r.data:
        return None
    docs = _load_docs(r.data[0])
    for a in docs.get("assets", []):
        if a.get("kind") == kind:
            return a
    return None


def all_assets(project_id: str, user_id: str) -> list[dict]:
    if not user_owns_project(project_id, user_id):
        return []
    sb = get_sb()
    r = sb.table("projects").select("documents").eq("id", project_id).limit(1).execute()
    if not r.data:
        return []
    return _load_docs(r.data[0]).get("assets", [])
