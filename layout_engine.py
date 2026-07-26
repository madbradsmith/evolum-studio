#!/usr/bin/env python3
"""
layout_engine.py — Developum AI / Evolum Script Analysis V3.1 categorized intelligence planner

Purpose:
    Converts approved_brain_output.json into slide_plan.json.

    V3.1 SCRIPT ANALYSIS STANDARD
    - Preserves the existing deck slide-plan contract: {title, slides, slide_count}
    - Keeps image/text separation and image-plan metadata
    - Fixes the old overlay preset syntax issue
    - Adds categorized intelligence blocks so the downstream products can surface
      everything the brain already knows instead of flattening it
    - Adds safe optional API enrichment for script-specific story moments
      without requiring the API to run
    - Adds a report_header contract for the Script Analysis top page
    - Adds safer title/protagonist/category cleanup for downstream reports
    - Adds optional external comparable metadata hooks when OMDB_API_KEY is present

Usage:
    python3 layout_engine.py /path/to/approved_brain_output.json

Optional API enrichment:
    Set DAI_ENABLE_API_ENRICHMENT=1 and OPENAI_API_KEY in the environment.
    If unavailable or failed, the engine falls back silently to local logic.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_INPUT = Path("approved_brain_output.json")
DEFAULT_OUTPUT = Path("slide_plan.json")

MIN_WORDS = 24
TARGET_WORDS = 44
MAX_WORDS = 68

# Fields that are intentionally large/internal and should not be dumped blindly
# into human-facing report sections.
INTERNAL_OR_LARGE_FIELDS = {
    "image_plan",
    "character_stats",
    "presentation_modes",
    "presentation_controls",
    "layout_strategy",
    "slide_blueprint",
    "document_layouts",
}


# =============================================================================
# SHARED CLEANUP HELPERS
# =============================================================================

def clean(text: Any) -> str:
    return " ".join(str(text or "").replace("\u25a0", " ").split()).strip()


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return [value]
    if clean(value):
        return [clean(value)]
    return []


def list_text(items: Any, max_items: int = 8, sep: str = "\n") -> str:
    out: List[str] = []
    for item in as_list(items)[:max_items]:
        if isinstance(item, dict):
            if item.get("character"):
                character = clean(item.get("character"))
                dynamic = clean(item.get("dynamic"))
                function = clean(item.get("function"))
                text = f"{character}: {dynamic} — {function}" if dynamic or function else character
            elif item.get("title"):
                title = clean(item.get("title"))
                why = clean(item.get("why"))
                text = f"{title}: {why}" if why else title
            else:
                parts = [f"{clean(k)}: {clean(v)}" for k, v in item.items() if clean(v)]
                text = " · ".join(parts)
        else:
            text = clean(item)
        if text:
            out.append(text)
    return sep.join(out)


def key_value_text(mapping: Any, max_items: int = 8, sep: str = "\n") -> str:
    if not isinstance(mapping, dict):
        return clean(mapping)
    lines: List[str] = []
    for key, value in list(mapping.items())[:max_items]:
        if isinstance(value, (list, tuple)):
            val = ", ".join(clean(v) for v in value if clean(v))
        elif isinstance(value, dict):
            val = "; ".join(f"{clean(k)}: {clean(v)}" for k, v in value.items() if clean(v))
        else:
            val = clean(value)
        if val:
            lines.append(f"{humanize_key(key)}: {val}")
    return sep.join(lines)


def humanize_key(key: Any) -> str:
    key = clean(key).replace("_", " ").replace("-", " ")
    if not key:
        return ""
    return " ".join(part.capitalize() for part in key.split())


def first_value(data: Dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if clean(value):
            return clean(value)
    return default


def dedupe_doubled_name(value: Any) -> str:
    """Fix artifacts like CLARICECLARICE or DR. LECTERDR. LECTER."""
    text = clean(value)
    if not text:
        return ""
    compact = re.sub(r"\s+", " ", text).strip()
    half = len(compact) // 2
    if len(compact) % 2 == 0 and compact[:half].strip().lower() == compact[half:].strip().lower():
        return compact[:half].strip()
    words = compact.split()
    if len(words) % 2 == 0 and words[: len(words)//2] == words[len(words)//2:]:
        return " ".join(words[: len(words)//2])
    return compact


def normalize_character_list(items: Any, max_items: int = 8) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in as_list(items):
        if isinstance(item, dict):
            raw = item.get("character") or item.get("name") or item.get("title") or ""
        else:
            raw = item
        name = dedupe_doubled_name(raw)
        if not name:
            continue
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= max_items:
            break
    return out


def infer_project_title(data: Dict[str, Any]) -> str:
    title = first_value(data, "title", "project_title", "name", default="")
    if title and title.lower() not in {"untitled", "project", "none", "unknown"}:
        return title
    for key in ["script_title", "uploaded_title", "original_title"]:
        val = clean(data.get(key, ""))
        if val and val.lower() not in {"untitled", "unknown"}:
            return val
    return "Untitled"


def infer_protagonist(data: Dict[str, Any]) -> str:
    protagonist = dedupe_doubled_name(first_value(data, "protagonist", default=""))
    if protagonist and protagonist.lower() not in {"unknown", "lead", "the protagonist"}:
        return protagonist
    profile = data.get("protagonist_profile")
    if isinstance(profile, dict):
        name = dedupe_doubled_name(profile.get("name", ""))
        if name:
            return name
    characters = normalize_character_list(data.get("characters", []), max_items=1)
    if characters:
        return characters[0]
    stats = data.get("character_stats", {})
    if isinstance(stats, dict) and stats:
        candidates = []
        banned = {"and", "then", "more", "script", "what", "that", "but", "yes", "no"}
        for name, stat in stats.items():
            cleaned = dedupe_doubled_name(name)
            if not cleaned or cleaned.lower() in banned:
                continue
            score = 0
            if isinstance(stat, dict):
                score = int(stat.get("dialogue_count", 0) or 0) * 3 + int(stat.get("action_count", 0) or 0)
            candidates.append((score, cleaned))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]
    return "Lead"


def report_safe_excerpt(text: Any, max_chars: int = 220) -> str:
    return clip_text(clean(text), max_chars)


def word_count(text: str) -> int:
    return len(clean(text).split())


def sentence_split(text: str) -> List[str]:
    text = clean(text)
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def can_merge(a: str, b: str, max_words: int = MAX_WORDS) -> bool:
    return word_count(f"{a} {b}") <= max_words


def group_sentences(sentences: List[str]) -> List[str]:
    if not sentences:
        return []

    chunks: List[str] = []
    current = ""

    for sent in sentences:
        sent = clean(sent)
        if not current:
            current = sent
            continue

        trial = f"{current} {sent}".strip()
        current_words = word_count(current)
        trial_words = word_count(trial)

        if current_words < MIN_WORDS and trial_words <= MAX_WORDS:
            current = trial
            continue

        if trial_words <= TARGET_WORDS:
            current = trial
            continue

        chunks.append(current)
        current = sent

    if current:
        chunks.append(current)

    merged: List[str] = []
    for chunk in chunks:
        if merged and word_count(chunk) < MIN_WORDS and can_merge(merged[-1], chunk):
            merged[-1] = f"{merged[-1]} {chunk}".strip()
        else:
            merged.append(chunk)

    if len(merged) >= 2 and word_count(merged[-1]) < MIN_WORDS and can_merge(merged[-2], merged[-1]):
        merged[-2] = f"{merged[-2]} {merged[-1]}".strip()
        merged.pop()

    return merged


def clip_text(text: str, max_chars: int) -> str:
    text = clean(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def sanitize_slide_title(title: str) -> str:
    title = clean(title).replace("#", "")
    return title or "Untitled"


# =============================================================================
# USER UPLOAD OVERRIDES
# =============================================================================

def apply_user_upload_overrides(data: Dict[str, Any], input_path: Path) -> Dict[str, Any]:
    # Only check work-dir-adjacent paths — never CWD fallbacks, which can pick up stale data
    dai_work_dir = os.environ.get("DAI_WORK_DIR", "")
    override_candidates = []
    if dai_work_dir:
        override_candidates.append(Path(dai_work_dir) / "user_upload_context.json")
    override_candidates += [
        input_path.parent / "user_upload_context.json",
    ]

    for candidate in override_candidates:
        if not candidate.exists():
            continue
        try:
            override_payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue

        submitted_logline = clean(override_payload.get("logline", ""))
        submitted_synopsis = clean(override_payload.get("synopsis", ""))
        submitted_title = clean(override_payload.get("title", ""))

        if submitted_title:
            data["title"] = submitted_title
            print(f"✅ Using uploaded title override: {candidate}")
        if submitted_logline:
            data["logline"] = submitted_logline
            print(f"✅ Using uploaded logline override: {candidate}")
        if submitted_synopsis:
            data["synopsis"] = submitted_synopsis
            print(f"✅ Using uploaded synopsis override: {candidate}")

        return data

    return data


# =============================================================================
# IMAGE PLAN HELPERS
# =============================================================================

def normalize_image_options(options: Any) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    if not isinstance(options, list):
        return normalized

    for item in options:
        if not isinstance(item, dict):
            continue
        normalized.append({
            "rank": item.get("rank"),
            "score": item.get("score"),
            "option_id": clean(item.get("option_id")),
            "label": clean(item.get("label")),
            "focus": clean(item.get("focus")),
            "image_query": clean(item.get("image_query")),
            "image_tags": item.get("image_tags", []) if isinstance(item.get("image_tags"), list) else [],
            "image_path": clean(item.get("image_path")),
            "image_name": clean(item.get("image_name")),
            "image_source": clean(item.get("image_source")),
        })
    return normalized


def build_image_plan_lookup(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    image_plan = data.get("image_plan", [])
    lookup: Dict[str, Dict[str, Any]] = {}

    if not isinstance(image_plan, list):
        return lookup

    for item in image_plan:
        if not isinstance(item, dict):
            continue

        title_key = clean(item.get("slide_title", "")).lower()
        if not title_key:
            continue

        payload = {
            "image_query": clean(item.get("image_query", "")),
            "image_tags": item.get("image_tags", []) if isinstance(item.get("image_tags"), list) else [],
            "image_score": item.get("image_score"),
            "image_options": normalize_image_options(item.get("image_options", [])),
            "image_path": clean(item.get("image_path", "")),
            "image_name": clean(item.get("image_name", "")),
            "image_source": clean(item.get("image_source", "")),
            "selected_option_id": clean(item.get("selected_option_id", "")),
            "visual_family": clean(item.get("visual_family", "")),
            "file_strategy": item.get("file_strategy", {}) if isinstance(item.get("file_strategy"), dict) else {},
        }
        lookup[title_key] = payload

    return lookup


def lookup_image_meta(slide_title: str, image_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    key = clean(slide_title).lower()
    if key in image_lookup:
        return dict(image_lookup[key])

    # loose matching makes "Story Engine" find "Conflict Engine" / "Visual Style" less brittle
    for known_key, meta in image_lookup.items():
        if key and (key in known_key or known_key in key):
            return dict(meta)

    if "title" in image_lookup:
        return dict(image_lookup["title"])

    return {
        "image_query": "",
        "image_tags": [],
        "image_score": None,
        "image_options": [],
        "image_path": "",
        "image_name": "",
        "image_source": "none",
        "selected_option_id": "",
        "visual_family": "",
        "file_strategy": {},
    }


# =============================================================================
# OPTIONAL API ENRICHMENT
# =============================================================================

def api_enabled() -> bool:
    return clean(os.environ.get("DAI_ENABLE_API_ENRICHMENT", "")).lower() in {"1", "true", "yes", "on"}


def openai_key() -> str:
    return clean(os.environ.get("OPENAI_API_KEY", ""))


def enrich_story_moments_with_api(data: Dict[str, Any], max_items: int = 6) -> List[str]:
    """
    Optional, safe API enrichment for script-specific story moments.
    If API is disabled, unavailable, or fails, this returns [].
    """
    if not api_enabled() or not openai_key():
        return []

    title = first_value(data, "title", default="the project")
    protagonist = first_value(data, "protagonist", default="the protagonist")
    payload = {
        "title": title,
        "protagonist": protagonist,
        "logline": clean(data.get("logline", "")),
        "synopsis": clean(data.get("synopsis", ""))[:2000],
        "core_conflict": clean(data.get("core_conflict", "")),
        "reversal": clean(data.get("reversal", "")),
        "theme": clean(data.get("theme", "")),
    }

    prompt = (
        "Generate script-specific key story moments for a premium screenplay analysis report. "
        "Return ONLY valid JSON: {\"moments\":[\"...\"]}. "
        "Each moment must be concrete, tied to this exact script, 6-12 words, and not generic. "
        "Do not summarize the logline. Do not begin with 'the protagonist faces'. "
        "Use clean human-readable beat names, like 'Clarice earns Lecter’s first real attention'. "
        f"Return {max_items} moments.\n\n"
        f"DATA:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    request_body = json.dumps({
        "model": os.environ.get("DAI_OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": "You write concise, script-specific screenplay analysis bullets."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
        "max_tokens": 350,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=request_body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {openai_key()}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=18) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return [clean(x) for x in parsed.get("moments", []) if clean(x)][:max_items]
    except Exception as exc:
        print(f"⚠️ API enrichment skipped: {exc}")
        return []


def fallback_story_moments(data: Dict[str, Any], max_items: int = 6) -> List[str]:
    explicit = data.get("key_moments") or data.get("story_moments")
    moments = [clean(x) for x in as_list(explicit) if clean(x)]
    if moments:
        return moments[:max_items]

    title = infer_project_title(data)
    protagonist = infer_protagonist(data)
    conflict = clean(data.get("core_conflict", ""))
    reversal = clean(data.get("reversal", ""))
    engine = clean(data.get("story_engine", ""))
    synopsis = clean(data.get("synopsis", ""))

    sentences = sentence_split(synopsis)
    picked: List[str] = []

    if engine:
        picked.append(report_safe_excerpt(engine, 78))
    if conflict and conflict not in picked:
        picked.append(report_safe_excerpt(conflict, 78))

    if sentences:
        indexes = [0, max(0, len(sentences)//3), max(0, (len(sentences)*2)//3), len(sentences)-1]
        for idx in indexes:
            if 0 <= idx < len(sentences):
                moment = report_safe_excerpt(sentences[idx], 78)
                if moment and moment not in picked:
                    picked.append(moment)

    if reversal and reversal not in picked:
        picked.append(report_safe_excerpt(reversal, 78))

    if not picked:
        memorization = [clean(x) for x in as_list(data.get("memorization_beats")) if clean(x)]
        picked.extend(memorization)

    if not picked:
        picked = [
            f"{protagonist} enters the pressure of {title}",
            report_safe_excerpt(conflict, 78),
            report_safe_excerpt(reversal, 78),
        ]

    cleaned: List[str] = []
    banned = {"Opening power move", "First pressure turn", "Status shift or reveal", "Control reset"}
    for item in picked:
        item = clean(item).strip("•- ")
        if not item or item in banned:
            continue
        if item not in cleaned:
            cleaned.append(item)
    return cleaned[:max_items]

def story_moments(data: Dict[str, Any], max_items: int = 6) -> List[str]:
    return enrich_story_moments_with_api(data, max_items=max_items) or fallback_story_moments(data, max_items=max_items)


# =============================================================================
# LAYOUT META HELPERS
# =============================================================================

def stage_to_layout(stage: str, current_layout: str) -> str:
    stage = clean(stage).lower()
    mapping = {
        "title": "hero_full_bleed",
        "closing": "hero_full_bleed",
        "hook": "split_left_text",
        "setup": "bottom_story_card",
        "escalation": "split_right_text",
        "turn": "split_left_text",
        "aftermath": "bottom_story_card",
        "character": "character_focus",
        "world": "quote_overlay",
        "tone": "quote_overlay",
        "themes": "quote_overlay",
        "conflict": "split_left_text",
        "stakes": "split_right_text",
        "engine": "bottom_story_card",
        "why_now": "bottom_story_card",
        "market": "clean_grid",
        "producer_read": "clean_grid",
        "story_core": "bottom_story_card",
        "character_intel": "character_focus",
        "performance": "split_right_text",
        "scene_intel": "clean_grid",
        "visual_intel": "quote_overlay",
    }
    return mapping.get(stage, clean(current_layout) or "split_left_text")


def box_for_layout(layout: str) -> Dict[str, Any]:
    presets: Dict[str, Dict[str, Any]] = {
        "hero_full_bleed": {
            "x": 0.055, "y": 0.68, "w": 0.89, "h": 0.22,
            "align": "left", "theme": "dark_glass",
        },
        "split_left_text": {
            "x": 0.055, "y": 0.14, "w": 0.39, "h": 0.68,
            "align": "left", "theme": "dark_glass",
        },
        "split_right_text": {
            "x": 0.555, "y": 0.14, "w": 0.39, "h": 0.68,
            "align": "left", "theme": "dark_glass",
        },
        "bottom_story_card": {
            "x": 0.055, "y": 0.61, "w": 0.89, "h": 0.25,
            "align": "left", "theme": "dark_glass",
        },
        "character_focus": {
            "x": 0.055, "y": 0.64, "w": 0.58, "h": 0.24,
            "align": "left", "theme": "dark_glass",
        },
        "quote_overlay": {
            "x": 0.14, "y": 0.36, "w": 0.72, "h": 0.22,
            "align": "center", "theme": "light_glass",
        },
        "clean_grid": {
            "x": 0.08, "y": 0.14, "w": 0.84, "h": 0.66,
            "align": "left", "theme": "clean",
        },
    }
    return presets.get(layout, presets["split_left_text"])


def title_size(layout: str) -> int:
    if layout == "hero_full_bleed":
        return 28
    if layout == "quote_overlay":
        return 24
    if layout == "clean_grid":
        return 22
    return 21


def body_size(layout: str) -> int:
    if layout == "hero_full_bleed":
        return 13
    if layout == "clean_grid":
        return 14
    if layout == "quote_overlay":
        return 17
    return 15


def build_layout_meta(slide_title: str, body: str, layout: str, stage: str, image_meta: Dict[str, Any]) -> Dict[str, Any]:
    image_path = clean(image_meta.get("image_path", ""))
    image_name = clean(image_meta.get("image_name", ""))
    image_source = clean(image_meta.get("image_source", "none")) or "none"
    selected_option_id = clean(image_meta.get("selected_option_id", ""))

    overlay_box = box_for_layout(layout)

    return {
        "background_image": image_path,
        "use_background_image": bool(image_path),
        "full_bleed": True,
        "overlay_box": overlay_box,
        "text_style": {
            "title_size": title_size(layout),
            "body_size": body_size(layout),
            "title_weight": "bold",
            "body_weight": "regular",
            "line_spacing": 1.08,
            "tracking": 0,
            "case": "auto",
        },
        "render_hints": {
            "apply_gradient_scrim": True,
            "safe_margins": True,
            "respect_aspect_ratio": True,
            "crop_mode": "cover",
            "avoid_text_on_faces": True,
            "prefer_empty_space_for_text": True,
        },
        "layout_version": "v3_1_script_analysis_standard",
        "deck_layout_family": layout,
        "display_title": sanitize_slide_title(slide_title),
        "display_body": body,
        "display_stage": clean(stage),
        "image_path": image_path,
        "image_name": image_name,
        "image_source": image_source,
        "selected_option_id": selected_option_id,
        "visual_family": clean(image_meta.get("visual_family", "")),
    }


# =============================================================================
# SLIDE / CATEGORY BUILDERS
# =============================================================================

def add_slide(
    plan: List[Dict[str, Any]],
    image_lookup: Dict[str, Dict[str, Any]],
    title: str,
    body: str,
    layout: str = "text",
    stage: str = "",
    category: str = "",
    max_chars_override: Optional[int] = None,
) -> None:
    body = clean(body)
    if layout != "title" and not body:
        return

    slide_title = sanitize_slide_title(title)
    stage_clean = clean(stage)
    smart_layout = stage_to_layout(stage_clean, layout)
    image_meta = lookup_image_meta(slide_title, image_lookup)

    if max_chars_override is not None:
        max_chars = max_chars_override
    elif smart_layout == "hero_full_bleed":
        max_chars = 150
    elif smart_layout in {"split_left_text", "split_right_text", "bottom_story_card"}:
        max_chars = 310
    elif smart_layout == "character_focus":
        max_chars = 280
    elif smart_layout == "quote_overlay":
        max_chars = 220
    else:
        max_chars = 430

    clipped_body = clip_text(body, max_chars)
    layout_meta = build_layout_meta(slide_title, clipped_body, smart_layout, stage_clean, image_meta)

    plan.append({
        "title": slide_title,
        "body": clipped_body,
        "layout": smart_layout,
        "stage": stage_clean,
        "category": clean(category),
        "image_query": clean(image_meta.get("image_query", "")),
        "image_tags": image_meta.get("image_tags", []) if isinstance(image_meta.get("image_tags"), list) else [],
        "image_score": image_meta.get("image_score"),
        "image_options": normalize_image_options(image_meta.get("image_options", [])),
        "image_path": layout_meta["image_path"],
        "image_name": layout_meta["image_name"],
        "image_source": layout_meta["image_source"],
        "selected_option_id": layout_meta["selected_option_id"],
        "visual_family": layout_meta["visual_family"],
        "full_bleed": layout_meta["full_bleed"],
        "use_background_image": layout_meta["use_background_image"],
        "background_image": layout_meta["background_image"],
        "overlay_box": layout_meta["overlay_box"],
        "text_style": layout_meta["text_style"],
        "render_hints": layout_meta["render_hints"],
        "layout_version": layout_meta["layout_version"],
        "deck_layout_family": layout_meta["deck_layout_family"],
        "display_title": layout_meta["display_title"],
        "display_body": layout_meta["display_body"],
        "display_stage": layout_meta["display_stage"],
    })


def add_category_slides(
    plan: List[Dict[str, Any]],
    image_lookup: Dict[str, Dict[str, Any]],
    category_name: str,
    entries: List[Dict[str, str]],
    stage: str,
    max_items_per_slide: int = 3,
) -> None:
    usable = [e for e in entries if clean(e.get("label")) and clean(e.get("value"))]
    if not usable:
        return

    for idx in range(0, len(usable), max_items_per_slide):
        group = usable[idx: idx + max_items_per_slide]
        title = category_name if idx == 0 else f"{category_name} ({idx // max_items_per_slide + 1})"
        body_lines: List[str] = []
        for entry in group:
            body_lines.append(f"{entry['label'].upper()}\n{entry['value']}")
        add_slide(
            plan,
            image_lookup,
            title,
            "\n\n".join(body_lines),
            "clean_grid",
            stage,
            category=category_name,
            max_chars_override=620,
        )


def split_synopsis_cinematic(text: str) -> List[Dict[str, str]]:
    sentences = group_sentences(sentence_split(text))
    if not sentences:
        return []

    labels = [
        ("Synopsis", "setup", "narrative_setup"),
        ("Synopsis (2)", "escalation", "narrative_escalation"),
        ("Synopsis (3)", "turn", "narrative_turn"),
        ("Synopsis (4)", "aftermath", "narrative_aftermath"),
    ]

    slides: List[Dict[str, str]] = []
    for idx, chunk in enumerate(sentences):
        title, stage, layout = labels[min(idx, len(labels) - 1)]
        slides.append({"title": title, "body": chunk, "stage": stage, "layout": layout})
    return slides


# =============================================================================
# INTELLIGENCE CATALOG
# =============================================================================

def build_intelligence_catalog(data: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    title = first_value(data, "title", default="Project")
    protagonist = first_value(data, "protagonist", default="Lead")

    catalog: Dict[str, List[Dict[str, str]]] = {
        "Story Core": [
            {"label": "Logline", "value": clean(data.get("logline", ""))},
            {"label": "Story Engine", "value": clean(data.get("story_engine", ""))},
            {"label": "Core Conflict", "value": clean(data.get("core_conflict", ""))},
            {"label": "Reversal", "value": clean(data.get("reversal", ""))},
            {"label": "Theme", "value": clean(data.get("theme", "")) or list_text(data.get("themes", []), 4)},
            {"label": "World", "value": clean(data.get("setting", "")) or clean(data.get("world", ""))},
            {"label": "Tone", "value": clean(data.get("tone", ""))},
        ],
        "Producer Intelligence": [
            {"label": "Executive Summary", "value": clean(data.get("executive_summary", ""))},
            {"label": "Commercial Positioning", "value": clean(data.get("commercial_positioning", ""))},
            {"label": "Audience Profile", "value": list_text(data.get("audience_profile", []), 8)},
            {"label": "Strength Index", "value": key_value_text(data.get("strength_index", {}), 8)},
            {"label": "Packaging Potential", "value": clean(data.get("packaging_potential", ""))},
            {"label": "Market Projections", "value": key_value_text(data.get("market_projections", {}), 8)},
            {"label": "Comparables", "value": list_text(data.get("comparable_films", data.get("tone_comparables", [])), 5)},
            {"label": "External Comparable Metadata", "value": list_text(optional_external_comparable_metadata(data), 5)},
        ],
        "Character Intelligence": [
            {"label": "Protagonist", "value": protagonist},
            {"label": "Protagonist Summary", "value": clean(data.get("protagonist_summary", ""))},
            {"label": "Profile", "value": key_value_text(data.get("protagonist_profile", {}), 5)},
            {"label": "Character Leverage", "value": clean(data.get("character_leverage", ""))},
            {"label": "Relationship Map", "value": list_text(data.get("relationship_leverage_map", []), 8)},
            {"label": "Top Characters", "value": ", ".join(normalize_character_list(data.get("characters", []), 8))},
        ],
        "Performance Intelligence": [
            {"label": "Actor Objective", "value": clean(data.get("actor_objective", ""))},
            {"label": "Playable Tactics", "value": list_text(data.get("playable_tactics", []), 8)},
            {"label": "Emotional Triggers", "value": list_text(data.get("emotional_triggers", []), 8)},
            {"label": "Audition Danger Zones", "value": list_text(data.get("audition_danger_zones", []), 8)},
            {"label": "Reader Chemistry Tips", "value": list_text(data.get("reader_chemistry_tips", []), 8)},
            {"label": "Memorization Beats", "value": list_text(data.get("memorization_beats", []), 8)},
            {"label": "Role Arc Map", "value": list_text(data.get("role_arc_map", []), 8)},
            {"label": "Pressure Ladder", "value": list_text(data.get("pressure_ladder", []), 8)},
            {"label": "Emotional Continuity", "value": list_text(data.get("emotional_continuity", []), 8)},
            {"label": "Costume / Behavior", "value": list_text(data.get("costume_behavior_clues", []), 8)},
            {"label": "Set Ready Checklist", "value": list_text(data.get("set_ready_checklist", []), 8)},
        ],
        "Scene & Moment Intelligence": [
            {"label": "Key Story Moments", "value": list_text(story_moments(data, max_items=8), 8)},
            {"label": "Stakes", "value": clean(data.get("stakes", ""))},
            {"label": "Hook", "value": clean(data.get("hook", ""))},
            {"label": "Why This Movie", "value": clean(data.get("why_this_movie", ""))},
        ],
        "Visual & Document Intelligence": [
            {"label": "Layout Strategy", "value": key_value_text(data.get("layout_strategy", {}), 8)},
            {"label": "Presentation Controls", "value": key_value_text(data.get("presentation_controls", {}), 8)},
            {"label": "Slide Blueprint", "value": key_value_text(data.get("slide_blueprint", {}), 8)},
            {"label": "Document Layouts", "value": key_value_text(data.get("document_layouts", {}), 6)},
            {"label": "Image Plan", "value": summarize_image_plan(data.get("image_plan", []))},
        ],
    }

    # Capture small extra brain fields that are not already categorized.
    known = {"title", "protagonist", "logline", "synopsis", "tagline", "story_engine", "core_conflict", "reversal", "theme", "themes", "world", "setting", "tone", "executive_summary", "commercial_positioning", "audience_profile", "strength_index", "packaging_potential", "market_projections", "comparable_films", "tone_comparables", "protagonist_summary", "protagonist_profile", "character_leverage", "relationship_leverage_map", "characters", "actor_objective", "playable_tactics", "emotional_triggers", "audition_danger_zones", "reader_chemistry_tips", "memorization_beats", "role_arc_map", "pressure_ladder", "emotional_continuity", "costume_behavior_clues", "set_ready_checklist", "key_moments", "story_moments", "stakes", "hook", "why_this_movie"} | INTERNAL_OR_LARGE_FIELDS

    extra_entries: List[Dict[str, str]] = []
    for key, value in data.items():
        if key in known:
            continue
        if isinstance(value, (str, int, float, bool)) and clean(value):
            extra_entries.append({"label": humanize_key(key), "value": clean(value)})
        elif isinstance(value, list) and value and len(value) <= 12:
            extra_entries.append({"label": humanize_key(key), "value": list_text(value, 12)})
        elif isinstance(value, dict) and value and len(value) <= 10:
            extra_entries.append({"label": humanize_key(key), "value": key_value_text(value, 10)})
    if extra_entries:
        catalog["Additional Brain Signals"] = extra_entries

    return {category: [entry for entry in entries if clean(entry.get("value"))] for category, entries in catalog.items()}


def summarize_image_plan(image_plan: Any, max_items: int = 6) -> str:
    if not isinstance(image_plan, list):
        return ""
    lines: List[str] = []
    for item in image_plan[:max_items]:
        if not isinstance(item, dict):
            continue
        title = clean(item.get("slide_title", "Visual"))
        family = clean(item.get("visual_family", ""))
        tags = item.get("image_tags", []) if isinstance(item.get("image_tags"), list) else []
        tag_text = ", ".join(clean(t) for t in tags[:5] if clean(t))
        detail = family or tag_text or clean(item.get("image_query", ""))[:90]
        if detail:
            lines.append(f"{title}: {detail}")
    return "\n".join(lines)



# =============================================================================
# SCRIPT ANALYSIS V3.1 REPORT CONTRACT HELPERS
# =============================================================================

def build_script_analysis_header(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Downstream reports can use this to fix the top-page problem without guessing.
    It avoids stuffing long prose into score boxes and keeps hero data clean.
    """
    title = infer_project_title(data)
    protagonist = infer_protagonist(data)
    world = first_value(data, "world", "genre", default="")
    setting = clean(data.get("setting", ""))
    tone = clean(data.get("tone", ""))
    tagline = clean(data.get("tagline", "")) or clean(data.get("logline", ""))

    return {
        "layout_version": "script_analysis_v3_1",
        "title": title,
        "subtitle": "EVOLUM Full Script Analysis Report",
        "hero_statement": f"{title} puts {protagonist} at the center of {world}, with a tone that feels {tone}." if world and tone else f"{title} centers {protagonist}.",
        "identity_rows": [
            {"label": "Lead", "value": protagonist, "type": "text"},
            {"label": "Genre / World", "value": world, "type": "text"},
            {"label": "Tone", "value": tone, "type": "text"},
            {"label": "Tagline", "value": tagline, "type": "text_long"},
        ],
        "story_snapshot": [
            {"label": "Theme", "value": clean(data.get("theme", "")) or list_text(data.get("themes", []), 3)},
            {"label": "Core Conflict", "value": clean(data.get("core_conflict", ""))},
            {"label": "Story Engine", "value": clean(data.get("story_engine", ""))},
            {"label": "Reversal", "value": clean(data.get("reversal", ""))},
        ],
        "world_detail": setting or world,
    }


def build_commercial_score_cards(data: Dict[str, Any]) -> List[Dict[str, str]]:
    strength = data.get("strength_index", {}) if isinstance(data.get("strength_index"), dict) else {}
    projections = data.get("market_projections", {}) if isinstance(data.get("market_projections"), dict) else {}
    cards: List[Dict[str, str]] = []
    if strength.get("marketability") or strength.get("concept"):
        cards.append({"label": "Commercial Potential", "value": clean(str(strength.get("marketability") or strength.get("concept"))), "type": "score"})
    if projections.get("audience_reach"):
        cards.append({"label": "Audience Appeal", "value": clean(projections.get("audience_reach")), "type": "text"})
    if projections.get("estimated_budget_tier"):
        cards.append({"label": "Budget Range", "value": clean(projections.get("estimated_budget_tier")), "type": "text"})
    if projections.get("franchise_potential"):
        cards.append({"label": "Franchise", "value": clean(projections.get("franchise_potential")), "type": "text"})
    return cards


def optional_external_comparable_metadata(data: Dict[str, Any], max_items: int = 3) -> List[Dict[str, str]]:
    """
    Optional OMDb-compatible enrichment hook. OMDb uses IMDb IDs/data and returns
    public comparable metadata where available. If no key is configured, return
    existing comps without external calls.
    """
    comps = as_list(data.get("comparable_films") or data.get("tone_comparables"))
    titles: List[str] = []
    for comp in comps:
        if isinstance(comp, dict):
            title = clean(comp.get("title", ""))
        else:
            title = clean(comp)
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= max_items:
            break

    api_key = clean(os.environ.get("OMDB_API_KEY", ""))
    if not api_key:
        return [{"title": t, "source": "brain_comparable"} for t in titles]

    enriched: List[Dict[str, str]] = []
    for title in titles:
        try:
            url = "https://www.omdbapi.com/?" + urllib.parse.urlencode({"apikey": api_key, "t": title})
            with urllib.request.urlopen(url, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("Response") == "True":
                enriched.append({
                    "title": clean(payload.get("Title", title)),
                    "year": clean(payload.get("Year", "")),
                    "genre": clean(payload.get("Genre", "")),
                    "box_office": clean(payload.get("BoxOffice", "")),
                    "imdb_rating": clean(payload.get("imdbRating", "")),
                    "source": "omdb_imdb_metadata",
                })
            else:
                enriched.append({"title": title, "source": "brain_comparable"})
        except Exception:
            enriched.append({"title": title, "source": "brain_comparable"})
    return enriched


# =============================================================================
# MAIN SLIDE PLAN
# =============================================================================

def _build_producer_deck(data: Dict[str, Any], title: str) -> List[Dict[str, Any]]:
    """Producer's Deck — 5-6 tight slides for quick reads and pre-meeting sends."""
    protagonist = infer_protagonist(data)
    logline = clean(data.get("logline", ""))
    tagline = clean(data.get("tagline", "")) or logline
    synopsis = clean(data.get("synopsis", ""))
    protagonist_summary = clean(data.get("protagonist_summary", ""))
    comparable_films = data.get("comparable_films", [])
    market_projections = data.get("market_projections", {})

    plan: List[Dict[str, Any]] = []
    image_lookup = build_image_plan_lookup(data)

    # 1. Title — poster + title only, no tagline text on slide
    add_slide(plan, image_lookup, title, "", "title", "title", category="Deck Spine")

    # 2. Logline
    if logline:
        add_slide(plan, image_lookup, "Logline", logline, "analysis", "hook", category="Deck Spine")

    # 3. Story — condensed synopsis (first 320 chars)
    story_body = synopsis[:320] if synopsis else clean(data.get("story_engine", ""))
    if story_body:
        add_slide(plan, image_lookup, "The Story", story_body, "analysis", "story_core", category="Deck Spine")

    # 4. Lead Character
    protagonist_body = protagonist_summary or protagonist
    if protagonist_body:
        add_slide(plan, image_lookup, protagonist or "Lead", protagonist_body, "text", "character", category="Deck Spine")

    # 5. Comparables + Market (combined or separate)
    if comparable_films:
        comp_titles = "  ·  ".join(
            f.get("title", str(f)) if isinstance(f, dict) else str(f)
            for f in comparable_films[:3]
        )
        market_note = ""
        if isinstance(market_projections, dict) and market_projections.get("distribution_angle"):
            market_note = f"\n{market_projections['distribution_angle']}"
        add_slide(plan, image_lookup, "Comparables", comp_titles + market_note, "analysis", "market", category="Deck Spine")

    # 6. Closing
    closing_body = clean(data.get("tagline") or data.get("story_engine") or title)
    add_slide(plan, image_lookup, "Closing", closing_body[:140], "title", "closing", category="Deck Spine")

    return plan


def build_slide_plan(data: Dict[str, Any]) -> Dict[str, Any]:
    title = infer_project_title(data)
    protagonist = infer_protagonist(data)
    deck_mode = (data.get("deck_mode") or "full").strip().lower()
    world = clean(data.get("world", ""))
    setting = clean(data.get("setting", ""))
    world_body = setting if setting else world
    logline = clean(data.get("logline", ""))
    tagline = clean(data.get("tagline", "")) or logline
    synopsis = clean(data.get("synopsis", ""))

    story_engine = clean(data.get("story_engine", ""))
    core_conflict = clean(data.get("core_conflict", ""))
    reversal = clean(data.get("reversal", ""))
    why_this_movie = clean(data.get("why_this_movie", ""))

    hook = clean(data.get("hook", ""))
    stakes = clean(data.get("stakes", ""))
    tone = clean(data.get("tone", ""))

    themes = data.get("themes", "")
    if isinstance(themes, list):
        themes_text = "\n".join(clean(x) for x in themes if clean(x))
    else:
        themes_text = clean(themes)

    theme_field = clean(data.get("theme", ""))
    if not why_this_movie:
        why_this_movie = theme_field or reversal

    plan: List[Dict[str, Any]] = []
    image_lookup = build_image_plan_lookup(data)

    # Producer's Deck — short form, exit early
    if deck_mode == "producer":
        producer_slides = _build_producer_deck(data, title)
        seen: set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for slide in producer_slides:
            key = f"{slide.get('title', '')}::{slide.get('body', '')}"
            if key not in seen:
                deduped.append(slide)
                seen.add(key)
        return {
            "title": title,
            "slides": deduped,
            "slide_count": len(deduped),
            "deck_mode": "producer",
            "layout_engine_version": "v3_1_script_analysis_standard",
        }

    # Full Deck spine — preserved for existing deck builder behavior.
    # Title slide body is intentionally blank — let the poster carry the page.
    add_slide(plan, image_lookup, title, "", "title", "title", category="Deck Spine")
    add_slide(plan, image_lookup, "Logline", logline, "analysis", "hook", category="Deck Spine")

    for slide in split_synopsis_cinematic(synopsis):
        add_slide(plan, image_lookup, slide["title"], slide["body"], slide["layout"], slide["stage"], category="Deck Spine")

    protagonist_summary = clean(data.get("protagonist_summary", ""))
    protagonist_body = protagonist_summary or protagonist
    add_slide(plan, image_lookup, protagonist or "Protagonist", protagonist_body, "text", "character", category="Deck Spine")
    add_slide(plan, image_lookup, "World", world_body, "text", "world", category="Deck Spine")
    if hook and hook != logline:
        add_slide(plan, image_lookup, "Hook", hook, "analysis", "hook", category="Deck Spine")
    if core_conflict:
        add_slide(plan, image_lookup, "Conflict", core_conflict, "analysis", "conflict", category="Deck Spine")
    if stakes and stakes != core_conflict:
        add_slide(plan, image_lookup, "Stakes", stakes, "analysis", "stakes", category="Deck Spine")
    add_slide(plan, image_lookup, "Tone", tone, "text", "tone", category="Deck Spine")

    if story_engine:
        add_slide(plan, image_lookup, "Story Engine", story_engine, "analysis", "engine", category="Deck Spine")
    if reversal:
        add_slide(plan, image_lookup, "Reversal", reversal, "analysis", "turn", category="Deck Spine")
    if themes_text:
        add_slide(plan, image_lookup, "Themes", themes_text, "text", "themes", category="Deck Spine")
    if why_this_movie and why_this_movie not in {story_engine, core_conflict, logline}:
        add_slide(plan, image_lookup, "Why This Movie", why_this_movie, "analysis", "why_now", category="Deck Spine")

    comparable_films = data.get("comparable_films", [])
    if comparable_films:
        comp_titles = "  ·  ".join(
            f.get("title", str(f)) if isinstance(f, dict) else str(f)
            for f in comparable_films[:3]
        )
        add_slide(plan, image_lookup, "Comparables", comp_titles, "analysis", "market", category="Deck Spine")

    market_projections = data.get("market_projections", {})
    if market_projections:
        proj_parts = []
        if market_projections.get("estimated_budget_tier"):
            proj_parts.append(f"Budget: {market_projections['estimated_budget_tier']}")
        if market_projections.get("distribution_angle"):
            proj_parts.append(f"Distribution: {market_projections['distribution_angle']}")
        if market_projections.get("awards_potential"):
            proj_parts.append(f"Awards: {market_projections['awards_potential']}")
        if market_projections.get("franchise_potential"):
            proj_parts.append(f"Franchise: {market_projections['franchise_potential']}")
        if proj_parts:
            add_slide(plan, image_lookup, "Market Projections", "  ·  ".join(proj_parts), "analysis", "market", category="Deck Spine")

    closing_body = clean(data.get("tagline") or data.get("story_engine") or title)
    add_slide(plan, image_lookup, "Closing", closing_body[:140], "title", "closing", category="Deck Spine")

    # Deduplicate exact duplicate title+body pairs.
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for slide in plan:
        key = f"{slide.get('title', '')}::{slide.get('body', '')}::{slide.get('category', '')}"
        if key in seen:
            continue
        deduped.append(slide)
        seen.add(key)
    plan = deduped

    # Hard cap at 15 slides — keep Title (first) and Closing (last), trim middle
    MAX_SLIDES = 15
    if len(plan) > MAX_SLIDES:
        closing = plan[-1]
        plan = plan[:MAX_SLIDES - 1] + [closing]

    catalog = build_intelligence_catalog(data)

    return {
        "title": title,
        "slides": plan,
        "slide_count": len(plan),
        "deck_mode": "full",
        "layout_engine_version": "v3_1_script_analysis_standard",
        "script_analysis_header": build_script_analysis_header(data),
        "commercial_score_cards": build_commercial_score_cards(data),
        "external_comparable_metadata": optional_external_comparable_metadata(data),
        "intelligence_catalog": catalog,
        "api_enrichment_enabled": api_enabled(),
    }


def main() -> None:
    _dai_work_dir = os.environ.get("DAI_WORK_DIR", "")

    input_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else DEFAULT_INPUT
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        raise SystemExit(1)

    data = read_json(input_path)
    data = apply_user_upload_overrides(data, input_path)

    slide_plan = build_slide_plan(data)

    if _dai_work_dir:
        out_dir = Path(_dai_work_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = DEFAULT_OUTPUT.parent

    out_path = out_dir / "slide_plan.json"
    out_path.write_text(json.dumps(slide_plan, indent=2), encoding="utf-8")

    print("✅ Slide plan generated")
    print(f"✅ Slides: {slide_plan['slide_count']}")


if __name__ == "__main__":
    main()
