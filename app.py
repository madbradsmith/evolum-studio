# =====================================================
# ===== EVOLUM MASTER APP STRUCTURE (VX BETA) =========
# =====================================================

# ===== IMPORTS / SETUP START =========================
# FULL v1_0 BUILD 1.1 — STABLE

from flask import Flask, request, render_template, send_file, jsonify, abort, session, redirect, url_for
from pathlib import Path
from functools import wraps
import json
import io
import contextlib
import shutil
import subprocess
import os
import importlib.util
import re
import time
import uuid
from datetime import datetime
from urllib.parse import unquote, quote

from flask_login import current_user, login_required


def subscription_required(view):
    """Tool-surface gate: must be logged in AND have an active subscription.

    Anonymous → bounced to /sign-in (with ?next=).  Logged-in but unsubscribed
    → bounced to /billing.  The decorator composes login_required, so anyone
    not signed in flows through the auth login_view first.
    """
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not getattr(current_user, "subscription_active", False):
            return redirect(url_for("billing.billing_page"))
        return view(*args, **kwargs)
    return wrapped

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from pptx import Presentation
from dai_tools import build_actor_prep_pdf, build_actor_booked_pdf, build_simple_analysis_pdf
from pypdf import PdfReader

from db import get_sb, init_db
from projects_supabase import (
    list_projects_for_user, get_project, user_owns_project,
    create_project as sb_create_project, update_project_fields,
    delete_project as sb_delete_project, record_asset,
    latest_asset_of_kind, all_assets, _load_docs,
    get_public_project_by_slug, get_filmmaker_display_name,
)
from auth import auth_bp, init_login
from billing import billing_bp


# ===== IMPORTS / SETUP END ===========================

# ===== GLOBAL CONFIG / PATHS START ===================
app = Flask(__name__)

_REFINE_BUILDER_MODULE = None
_LATEST_SLIDE_PAYLOAD_CACHE = {"key": None, "payload": None}
app.secret_key = os.environ.get("SECRET_KEY") or "dev-only-replace-in-prod"

# Auth + billing wiring
init_db()
init_login(app)
app.register_blueprint(auth_bp)
app.register_blueprint(billing_bp)


def subscription_required(f):
    """Gate a route on (logged in) AND (subscription_active). For JSON/POST
    endpoints we return a structured error; for GET we redirect to /billing
    so the user lands on the upgrade surface."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.is_json or request.method == "POST":
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for("auth.signin"))
        if not current_user.subscription_active:
            if request.is_json or request.method == "POST":
                return jsonify({"error": "Subscription required"}), 402
            return redirect(url_for("billing.billing_page"))
        return f(*args, **kwargs)
    return wrapper

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
STATUS_FILE = BASE_DIR / "status.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DEMO_DECK = BASE_DIR / "static" / "NOT_TODAY_Pitch_Deck_FINAL.pdf"

LATEST_PPTX = OUTPUT_DIR / "latest.pptx"
LATEST_PDF = OUTPUT_DIR / "latest.pdf"

LATEST_ANALYSIS_JSON = OUTPUT_DIR / "latest_analysis_report.json"
LATEST_ANALYSIS_PDF = OUTPUT_DIR / "latest_analysis_report.pdf"
LATEST_ACTOR_PREP_PDF = OUTPUT_DIR / "latest_actor_prep_report.pdf"
LATEST_ACTOR_BOOKED_PDF = OUTPUT_DIR / "latest_actor_booked_report.pdf"
LATEST_DECK_MANIFEST_JSON = OUTPUT_DIR / "latest_deck_manifest.json"

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".fdx", ".docx", ".doc", ".rtf", ".fountain", ".spmd", ".highland"}


def _rtf_to_text(raw: bytes) -> str:
    """Minimal RTF→text extractor. Strips control words + groups, keeps content.
    Enough for Final Draft's RTF export; not a full RTF parser."""
    import re as _re
    try:
        s = raw.decode("utf-8", errors="ignore")
    except Exception:
        s = raw.decode("latin-1", errors="ignore")
    # Strip binary blobs
    s = _re.sub(r"\\pict\b[^}]*}", "", s)
    s = _re.sub(r"\\bin\d+[^}]*}", "", s)
    # Convert escaped chars
    s = s.replace("\\'92", "'").replace("\\'93", '"').replace("\\'94", '"').replace("\\'96", "-").replace("\\'97", "-")
    s = s.replace("\\line", "\n").replace("\\par", "\n").replace("\\tab", "\t")
    # Strip control words like \fs24 \b0
    s = _re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    # Strip lingering braces
    s = s.replace("{", "").replace("}", "")
    # Cleanup
    lines = [line.strip() for line in s.splitlines()]
    lines = [l for l in lines if l]
    return "\n".join(lines)


def _fountain_to_text(raw: bytes) -> str:
    """Fountain is plaintext + light markdown. We just decode it."""
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return raw.decode("latin-1", errors="ignore")


def extract_script_text(file) -> str:
    """Parse an uploaded screenplay into plain text. Handles .txt / .pdf / .fdx /
    .docx / .doc / .rtf / .fountain / .spmd / .highland. Returns "" on total
    failure so the caller can fall back to the paste-directly path."""
    import xml.etree.ElementTree as ET
    from zipfile import ZipFile
    import io

    filename = (file.filename or "").lower()

    if filename.endswith(".txt"):
        return file.read().decode("utf-8", errors="ignore")

    if filename.endswith((".fountain", ".spmd", ".highland")):
        # Highland uses .highland (which is a ZIP with fountain inside) — try both
        raw = file.read()
        if filename.endswith(".highland"):
            try:
                with ZipFile(io.BytesIO(raw)) as z:
                    for name in z.namelist():
                        if name.endswith(".fountain") or name.endswith(".spmd"):
                            return z.read(name).decode("utf-8", errors="ignore")
            except Exception:
                pass
        return _fountain_to_text(raw)

    if filename.endswith(".pdf"):
        try:
            reader = PdfReader(file)
            return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception:
            return ""

    if filename.endswith(".fdx"):
        # FDX rewrite: preserve paragraph Type structure (Scene Heading, Character,
        # Dialogue, Action, etc.) so downstream parsers can distinguish them.
        # Previous version dropped Type info — that was the "iffy FDX" bug.
        try:
            raw = file.read()
            root = ET.fromstring(raw)
            out_lines = []
            for p in root.iter("Paragraph"):
                p_type = (p.get("Type") or "").strip()
                # Extract all Text descendants, joining with empty string
                text_parts = [t.text for t in p.iter("Text") if t.text]
                text = "".join(text_parts).strip()
                if not text:
                    if p_type == "Scene Heading":
                        continue  # skip empty scene headings
                    out_lines.append("")  # preserve blank line as structural separator
                    continue
                if p_type == "Scene Heading":
                    # Ensure it looks like a scene heading to downstream parsers
                    if not text.upper().startswith(("INT.", "EXT.", "INT/", "EXT/", "I/E.")):
                        # If Type says Scene Heading but text doesn't start with INT/EXT,
                        # prepend INT. as a safe default
                        text = "INT. " + text
                    out_lines.append("")
                    out_lines.append(text.upper())
                elif p_type == "Character":
                    out_lines.append("")
                    out_lines.append(text.upper())
                elif p_type == "Dialogue":
                    out_lines.append("    " + text)
                elif p_type == "Parenthetical":
                    out_lines.append("        " + text)
                elif p_type == "Transition":
                    out_lines.append("")
                    out_lines.append(text.upper() + ":")
                else:  # Action, Shot, General, etc.
                    out_lines.append(text)
            return "\n".join(out_lines).strip()
        except Exception as e:
            print(f"⚠️  FDX parse failed: {e}", flush=True)
            return ""

    if filename.endswith(".rtf"):
        try:
            return _rtf_to_text(file.read())
        except Exception:
            return ""

    if filename.endswith(".docx") or filename.endswith(".doc"):
        try:
            raw = file.read()
            with ZipFile(io.BytesIO(raw)) as z:
                xml_bytes = z.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            lines = []
            for p in root.findall(".//w:p", ns):
                texts = [t.text for t in p.findall(".//w:t", ns) if t.text]
                line = "".join(texts).strip()
                if line:
                    lines.append(line)
            return "\n".join(lines)
        except Exception:
            return ""

    return ""

ACCESS_CODES = [
    "beta1",
    "beta2",
    "beta3",
    "beta4", 
    "beta5",
    "beta6",
    "beta7",
    "beta8",
    "beta9",
    "beta10",
    "beta11",
    "beta12",    
    "beta13",
    "beta14",
    "beta15",
    "beta16",
    "beta17",
    "beta18",
    "beta19",
    "beta20",
    "vip",
    "madbrad",
]

BETA_ACCESS_LOGS_DIR = BASE_DIR / "beta_access_logs"
BETA_ACCESS_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def is_render_env() -> bool:
    return os.environ.get("RENDER", "").lower() == "true"


def has_beta_access() -> bool:
    return session.get("beta_access") is True


def log_beta_access(access_code: str, status: str):
    safe_code = "".join(ch for ch in access_code if ch.isalnum() or ch in ("-", "_")).strip() or "unknown"
    code_dir = BETA_ACCESS_LOGS_DIR / safe_code
    code_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ip_addr = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    user_agent = request.headers.get("User-Agent", "unknown")
    log_line = f"{timestamp} | {status} | code={access_code} | ip={ip_addr} | ua={user_agent}\n"

    log_file = code_dir / "access_log.txt"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(log_line)

    print(log_line.strip())


def log_usage(event, **kwargs):
    parts = [f"{k}={v}" for k, v in kwargs.items()]
    
    if parts:
        line = f"USAGE | {event} | " + " | ".join(parts)
    else:
        line = f"USAGE | {event}"
    
    print(line, flush=True)


def set_status(text: str):
    try:
        existing = json.loads(STATUS_FILE.read_text(encoding="utf-8")) if STATUS_FILE.exists() else {}
    except Exception:
        existing = {}
    existing["state"] = text
    STATUS_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def get_status() -> str:
    if not STATUS_FILE.exists():
        return "IDLE"
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return data.get("state", "IDLE") or "IDLE"
    except Exception:
        return "IDLE"


def allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def clear_latest_targets():
    for path in (LATEST_PPTX, LATEST_PDF):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def newest_generated_file(ext: str):
    excluded = {LATEST_PPTX.name, LATEST_PDF.name}
    files = [p for p in OUTPUT_DIR.glob(f"pitch_deck_v*{ext}") if p.name not in excluded]

    if not files:
        return None

    return max(files, key=lambda p: p.stat().st_mtime)

def find_latest_slide_plan_file():
    candidates = []

    direct_candidates = [
        BASE_DIR / "slide_plan.json",
        OUTPUT_DIR / "slide_plan.json",
        BASE_DIR / "pipeline" / "slide_plan.json",
        BASE_DIR / "pipeline" / "compile" / "slide_plan.json",
    ]
    for path in direct_candidates:
        if path.exists():
            candidates.append(path)

    search_roots = [
        BASE_DIR,
        OUTPUT_DIR,
        BASE_DIR / "projects",
        BASE_DIR / "pipeline",
    ]
    seen = set()
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("slide_plan.json"):
            if path in seen:
                continue
            seen.add(path)
            candidates.append(path)

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)

def safe_relpath(path_obj):
    try:
        return str(path_obj.relative_to(BASE_DIR))
    except Exception:
        return str(path_obj)


def resolve_quiet_image_for_slide(slide_title, stage, layout, slide_number):
    visuals_root = BASE_DIR / "visuals"

    if not visuals_root.exists():
        return None

    exts = ("*.jpg", "*.jpeg", "*.png", "*.webp")
    candidates = []

    for ext in exts:
        candidates.extend(visuals_root.rglob(ext))

    if not candidates:
        return None

    title_words = str(slide_title).lower().replace("(", " ").replace(")", " ").split()

    for candidate in candidates:
        name = candidate.stem.lower()

        for word in title_words:
            if len(word) >= 4 and word in name:
                return candidate

    return candidates[0]

def build_refine_slide_payload(slide_plan_data: dict, slide_plan_file=None):
    project_title = safe_text(slide_plan_data.get("title"), "UNTITLED PROJECT")
    raw_slides = slide_plan_data.get("slides") or []
    slide_plan_file = Path(slide_plan_file) if slide_plan_file else None
    project_dir = find_latest_project_dir(slide_plan_file)

    mapped_slides = []
    last_used_image_name = ""

    for index, slide in enumerate(raw_slides):
        if not isinstance(slide, dict):
            continue

        stage = safe_text(slide.get("stage"), "").lower()
        layout = safe_text(slide.get("layout"), "").lower()
        title = safe_text(slide.get("title"), f"Slide {index + 1}")

        body = safe_text(
            slide.get("body")
            or slide.get("content")
            or slide.get("text")
            or slide.get("copy"),
            "",
        )

        slide_type = title

        if stage == "title" or layout == "title":
            slide_type = "Title Slide"
        elif "logline" in title.lower():
            slide_type = "Logline"
        elif "synopsis" in title.lower():
            slide_type = "Synopsis"
        elif stage == "character":
            slide_type = "Characters"
        elif stage == "why_now":
            slide_type = "Why This Project"

        subtitle = ""

        if stage == "title" or layout == "title":
            subtitle = project_title if title.strip().lower() != project_title.strip().lower() else ""
        elif title.lower() in {
            "logline",
            "synopsis",
            "synopsis (2)",
            "hook",
            "conflict",
            "stakes",
            "world",
            "tone",
            "story engine",
            "reversal",
            "why this movie",
            "protagonist",
        }:
            subtitle = title
        elif stage:
            subtitle = stage.replace("_", " ").title()
        elif layout:
            subtitle = layout.replace("_", " ").title()

        caption_bits = []

        if stage:
            caption_bits.append(f"Stage: {stage.replace('_', ' ').title()}")

        if layout:
            caption_bits.append(f"Layout: {layout.replace('_', ' ').title()}")

        configured_image_path = safe_text(slide.get("image_path"), "")
        configured_image_name = safe_text(slide.get("image_name"), "")
        configured_image_url = safe_text(slide.get("image_url"), "")
        image_options = normalize_manifest_image_options(slide.get("image_options") or [])
        selected_option_id = safe_text(slide.get("selected_option_id"), "")

        resolved_image = None
        if configured_image_path:
            try:
                configured_candidate = Path(configured_image_path)
                if not configured_candidate.is_absolute():
                    configured_candidate = (BASE_DIR / configured_candidate).resolve()
                else:
                    configured_candidate = configured_candidate.resolve()
                if configured_candidate.exists() and configured_candidate.is_file():
                    resolved_image = configured_candidate
            except Exception:
                resolved_image = None

        if resolved_image is None:
            resolved_image = resolve_quiet_image_for_slide(
                slide_title=title,
                stage=stage,
                layout=layout,
                slide_number=index + 1,
            )

        image_name = configured_image_name or (resolved_image.name if resolved_image else "")
        image_url = configured_image_url or project_file_url_for_path(configured_image_path)
        if not image_url and resolved_image:
            image_url = f"/project-file?path={safe_relpath(resolved_image)}"

        if image_name:
            caption_bits.append(f"Image: {image_name}")

        caption = " • ".join(caption_bits) if caption_bits else f"Generated slide {index + 1}"

        mapped_slides.append({
            "type": slide_type,
            "title": title,
            "subtitle": subtitle,
            "body": body,
            "caption": caption,
            "accent": "#ffb347",
            "layout": layout,
            "stage": stage,
            "source_index": index,
            "image_name": image_name,
            "image_url": image_url,
            "image_options": image_options,
            "selected_option_id": selected_option_id,
        })

    return {
        "title": project_title,
        "slide_count": len(mapped_slides),
        "slides": mapped_slides,
    }


def load_deck_builder_module():
    global _REFINE_BUILDER_MODULE
    if _REFINE_BUILDER_MODULE is not None:
        return _REFINE_BUILDER_MODULE

    builder_path = BASE_DIR / "deck_builder_MADBRAD_BRAIN_V_1.py"
    if not builder_path.exists():
        _REFINE_BUILDER_MODULE = False
        return None

    try:
        spec = importlib.util.spec_from_file_location("deck_builder_madbrad_brain_v1", builder_path)
        if not spec or not spec.loader:
            _REFINE_BUILDER_MODULE = False
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _REFINE_BUILDER_MODULE = module
        return module
    except Exception as e:
        print(f"⚠️ Could not load deck builder for refine image mapping: {e}", flush=True)
        _REFINE_BUILDER_MODULE = False
        return None


def find_latest_project_dir(slide_plan_file=None):
    if slide_plan_file and slide_plan_file.exists():
        return slide_plan_file.parent
    return BASE_DIR


def ensure_relative_to_base(path: Path) -> bool:
    try:
        path.resolve().relative_to(BASE_DIR.resolve())
        return True
    except Exception:
        return False


def resolve_refine_image_for_slide(project_dir, deck_title, slide, slide_number, last_used_name=""):
    explicit_candidates = []
    for key in ("image_path", "image", "image_file", "preview_image"):
        value = slide.get(key)
        if value:
            explicit_candidates.append(Path(str(value)))

    for candidate in explicit_candidates:
        resolved = candidate if candidate.is_absolute() else (project_dir / candidate)
        if resolved.exists() and ensure_relative_to_base(resolved):
            return resolved.resolve()

    builder = load_deck_builder_module()
    if not builder:
        return None

    visuals_dir = project_dir / "visuals"
    approved_brain_output_path = project_dir / "approved_brain_output.json"
    brain_output = {}
    if approved_brain_output_path.exists():
        try:
            brain_output = json.loads(approved_brain_output_path.read_text(encoding="utf-8"))
        except Exception:
            brain_output = {}
    elif (BASE_DIR / "approved_brain_output.json").exists():
        try:
            brain_output = json.loads((BASE_DIR / "approved_brain_output.json").read_text(encoding="utf-8"))
        except Exception:
            brain_output = {}

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            image_path = builder.find_image_for_slide(
                visuals_dir=visuals_dir,
                deck_title=deck_title,
                slide_title=safe_text(slide.get("title"), f"Slide {slide_number}"),
                slide_number=slide_number,
                brain_output=brain_output,
                last_used_name=last_used_name,
                slide_body=safe_text(slide.get("body"), ""),
            )
    except Exception as e:
        print(f"⚠️ Refine image resolution failed for slide {slide_number}: {e}", flush=True)
        return None

    if not image_path or not Path(image_path).exists():
        return None

    image_path = Path(image_path).resolve()
    if not ensure_relative_to_base(image_path):
        return None

    return image_path


def build_project_file_url(image_path: Path) -> str:
    rel = image_path.resolve().relative_to(BASE_DIR.resolve())
    return "/project-file?path=" + quote(str(rel).replace('\\', '/'))


def make_slide_payload_cache_key(slide_plan_file=None):
    if not slide_plan_file or not slide_plan_file.exists():
        return "missing"
    parts = [f"slide:{slide_plan_file}:{slide_plan_file.stat().st_mtime_ns}"]
    project_dir = find_latest_project_dir(slide_plan_file)
    abo = project_dir / "approved_brain_output.json"
    if not abo.exists():
        abo = BASE_DIR / "approved_brain_output.json"
    if abo.exists():
        parts.append(f"abo:{abo}:{abo.stat().st_mtime_ns}")
    builder_path = BASE_DIR / "deck_builder_MADBRAD_BRAIN_V_1.py"
    if builder_path.exists():
        parts.append(f"builder:{builder_path.stat().st_mtime_ns}")
    return "|".join(parts)


def publish_latest_outputs(pptx_source, pdf_source):
    if pptx_source and pptx_source.exists():
        shutil.copy2(pptx_source, LATEST_PPTX)

    if pdf_source and pdf_source.exists():
        shutil.copy2(pdf_source, LATEST_PDF)


def safe_text(value, fallback="-"):
    if value is None:
        return fallback
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value if str(v).strip())
    value = str(value).strip()
    return value or fallback


def wrap_text(text, font_name="Helvetica", font_size=11, max_width=500):
    words = safe_text(text, "").split()
    if not words:
        return []

    lines = []
    current = words[0]

    for word in words[1:]:
        trial = f"{current} {word}"
        if stringWidth(trial, font_name, font_size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word

    lines.append(current)
    return lines


def draw_wrapped_text(pdf, text, x, y, max_width=500, font_name="Helvetica", font_size=11, leading=15):
    lines = wrap_text(text, font_name=font_name, font_size=font_size, max_width=max_width)
    pdf.setFont(font_name, font_size)
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y



# Beta-gate before_request handler removed in Session 2.
# Authentication is now route-level (@login_required, @subscription_required).


# ===== BETA ACCESS ROUTES START ======================
@app.route("/beta-access", methods=["POST"])
def beta_access():
    access_code = (request.form.get("access_code") or "").strip()

    if access_code in ACCESS_CODES:
        session["beta_access"] = True
        session["beta_code"] = access_code
        log_beta_access(access_code, "ACCESS GRANTED")
        log_usage("beta_access", code=access_code, success=True)
        return redirect(url_for("workspace"))

    log_beta_access(access_code or "blank", "ACCESS FAILED")
    log_usage("beta_access", code=access_code or "blank", success=False)
    return redirect(url_for("signin"))


# ===== CORE ROUTES START =============================
@app.route("/")
def index():
    return render_template("landing.html")


# Canonical kebab-case routes (match the design sitemap from new_evolum/).
# Existing short-name routes below are kept as 301 aliases for safety.
#
# Gating policy:
#   subscription_required → tool surfaces that drive the product value
#                           (workspace, deck builder, project room,
#                           audition tool, self-tape room, booked role).
#   login_required        → personal surfaces that need an identity but
#                           don't drive billing yet (investor deal room
#                           intake, supporter feed once we add follows).
#   public                → catalog/discovery surfaces and marketing pages.
@app.route("/filmmaker-workspace")
@subscription_required
def filmmaker_workspace():
    projects = list_projects_for_user(current_user.id)
    return render_template("workspace.html", projects=projects)


@app.route("/workspace")
def workspace():
    return redirect(url_for("filmmaker_workspace"), code=301)


@app.route("/project-room")
@app.route("/project")
def project_room_legacy():
    """Legacy single-project-room URLs now redirect to the workspace.
    Per-project surfaces live at /project/<id>."""
    return redirect(url_for("filmmaker_workspace"), code=301)


# Human-readable labels for the genre picker dropdown.
WORLD_DISPLAY = [
    ("feature / action espionage thriller", "Espionage / Action Thriller"),
    ("feature / contained urban thriller",  "Contained Urban Thriller"),
    ("feature / legal / courtroom drama",   "Legal / Courtroom Drama"),
    ("feature / fantasy satire comedy",     "Fantasy Satire / Comedy"),
    ("feature / fantasy adventure",         "Fantasy Adventure"),
    ("feature / nightlife comedy",          "Nightlife Comedy"),
    ("feature / sports drama",              "Sports Drama"),
    ("feature / crime drama",               "Crime Drama"),
    ("feature / crime family",              "Crime Family / Mafia"),
    ("feature / horror",                    "Horror"),
    ("feature / psychological thriller",    "Psychological Thriller"),
    ("feature / sci-fi action",             "Sci-Fi Action"),
    ("feature / sci-fi horror",             "Sci-Fi Horror"),
    ("feature / animation family",          "Animation / Family"),
    ("feature / drama",                     "Drama (default)"),
]


def _classifier_suggestion_for_project(project: dict) -> dict:
    """Run classify_world_with_confidence against a project's script_text.
    Returns {'world', 'confidence', 'alternatives'} or None if no script yet."""
    if not project:
        return None
    script_text = project.get("script_text") or ""
    if not script_text.strip():
        return None
    try:
        import single_brain_orchestrator_v3 as _brain
        return _brain.classify_world_with_confidence(script_text)
    except Exception as e:
        print(f"⚠️  classifier suggestion failed: {e}", flush=True)
        return None


@app.route("/pitch-deck")
@subscription_required
def pitch_deck():
    """Pitch deck builder surface. When ?project=<id> is supplied, the page
    runs the deterministic pipeline against the project's saved script + idea."""
    project_id = request.args.get("project", type=str)
    project = get_project(project_id, current_user.id) if project_id else None
    suggestion = _classifier_suggestion_for_project(project)
    return render_template("deck.html", project=project,
                           suggestion=suggestion, world_display=WORLD_DISPLAY)


@app.route("/deck")
def deck():
    return redirect(url_for("pitch_deck"), code=301)


@app.route("/actor-casting")
def actor_casting():
    """Actor door/discovery surface (catalog of roles) — public browse."""
    return render_template("actor-casting.html")


@app.route("/audition")
@subscription_required
def audition():
    """Audition prep surface."""
    project_id = request.args.get("project", type=str)
    project = get_project(project_id, current_user.id) if project_id else None
    suggestion = _classifier_suggestion_for_project(project)
    return render_template("audition.html", project=project,
                           suggestion=suggestion, world_display=WORLD_DISPLAY)


@app.route("/booked-role")
@subscription_required
def booked_role():
    """Booked role analysis surface."""
    project_id = request.args.get("project", type=str)
    project = get_project(project_id, current_user.id) if project_id else None
    suggestion = _classifier_suggestion_for_project(project)
    return render_template("booked_role.html", project=project,
                           suggestion=suggestion, world_display=WORLD_DISPLAY)


@app.route("/script-analyzer")
@subscription_required
def script_analyzer_page():
    """Script analysis surface."""
    project_id = request.args.get("project", type=str)
    project = get_project(project_id, current_user.id) if project_id else None
    suggestion = _classifier_suggestion_for_project(project)
    return render_template("script_analyzer.html", project=project,
                           suggestion=suggestion, world_display=WORLD_DISPLAY)


# ----- The Doors + Catalog surfaces -----
@app.route("/catalog")
def catalog():
    """Public catalog — browse without login."""
    return render_template("catalog.html")


@app.route("/festival-calendar")
def festival_calendar():
    return render_template("festival-calendar.html")


@app.route("/investor-deal-room")
def investor_deal_room():
    """Public door — anyone can browse. Pledging/NDA flow requires sign-in."""
    return render_template("investor-deal-room.html")


@app.route("/supporter-feed")
def supporter_feed():
    """Public door — anyone can browse. Pledging requires sign-in."""
    return render_template("supporter-feed.html")


@app.route("/self-tape-room")
@subscription_required
def self_tape_room():
    return render_template("self-tape-room.html")


@app.route("/the-lot")
def the_lot():
    return render_template("the-lot.html")


# ----- Auth alias -----
@app.route("/sign-in")
def sign_in_alias():
    return redirect(url_for("auth.signin"), code=301)


# ----- Legal / info pages (real content, not stubs) -----
@app.route("/pricing")
def pricing_page():
    return render_template("pricing.html")


@app.route("/sponsor")
def sponsor_page():
    return render_template("sponsor.html")


@app.route("/rewards")
def rewards_page():
    # Referral system isn't wired yet — this page ships as the "shape" per PI's ask.
    # Placeholder personal stats + a synthesized referral URL so the copy button works.
    if current_user.is_authenticated:
        # short deterministic slug so a repeat visit shows the same link
        slug_seed = str(getattr(current_user, "id", "guest"))
        ref_code = "ev" + str(abs(hash(slug_seed)))[:6]
        referral_url = f"https://evolumstudio.com/join?ref={ref_code}"
    else:
        ref_code = "evXXXXXX"
        referral_url = f"https://evolumstudio.com/join?ref={ref_code}"
    stats = {
        "invited": 0,
        "stuck": 0,
        "weeks_banked": 0,
        "tier_name": "The Spark",
    }
    return render_template("rewards.html", stats=stats, referral_url=referral_url)


@app.route("/house-rules")
def house_rules_page():
    return render_template("house_rules.html")


@app.route("/faq")
def faq_page():
    return render_template("faq.html")


@app.route("/terms")
def terms_page():
    return render_template("terms.html")


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@app.route("/acceptable-use")
def acceptable_use_page():
    return render_template("acceptable_use.html")


@app.route("/legacy")
def legacy_spa():
    """Old SPA — used for end-to-end testing of the four tools until the
    new design pages are wired up to the tool endpoints (Session 2)."""
    return render_template(
        "index.html",
        is_render=is_render_env(),
        gate_locked=not has_beta_access(),
        gate_error=None,
        base_path_prefix=str(BASE_DIR) + "/",
    )


@app.route("/status")
def status():
    return jsonify({"status": get_status()})


@app.route("/api/auth/me")
def api_auth_me():
    """Frontend identity probe."""
    if not current_user.is_authenticated:
        return jsonify({}), 401
    # notify_new_roles lives in profiles.documents (Supabase-mapped)
    notify = False
    try:
        sb = get_sb()
        r = sb.table("profiles").select("documents").eq("id", current_user.id).limit(1).execute()
        if r.data:
            docs = _load_docs(r.data[0])
            notify = bool(docs.get("notify_new_roles"))
    except Exception:
        pass
    return jsonify({
        "user_name":  getattr(current_user, "name", "") or "",
        "name":       getattr(current_user, "name", "") or "",
        "user_email": getattr(current_user, "email", "") or "",
        "plan":       getattr(current_user, "plan", "") or "",
        "subscription_active": bool(getattr(current_user, "subscription_active", False)),
        "notify_new_roles": notify,
    })


# ===== Actor-side endpoints — now stored on profiles.documents ==============
@app.route("/api/profile", methods=["GET", "POST"])
@login_required
def api_profile():
    """Actor profile: GET returns current, POST upserts. Stored in
    profiles.documents.actor_profile so we don't add columns to public.profiles."""
    sb = get_sb()
    r = sb.table("profiles").select("documents").eq("id", current_user.id).limit(1).execute()
    docs = _load_docs(r.data[0]) if r.data else {}
    if request.method == "GET":
        return jsonify(docs.get("actor_profile", {})), 200
    data = request.get_json(silent=True) or {}
    prof = {
        "stage_name":    (data.get("stage_name") or "").strip()[:200],
        "union_status":  (data.get("union") or "non-union")[:32],
        "headshot_url":  (data.get("headshot_url") or "").strip()[:500],
        "reel_url":      (data.get("reel_url") or "").strip()[:500],
        "agent_contact": (data.get("agent_contact") or "").strip()[:500],
        "bio":           (data.get("bio") or "").strip()[:2000],
    }
    docs["actor_profile"] = prof
    sb.table("profiles").update({"documents": docs}).eq("id", current_user.id).execute()
    return jsonify({"ok": True})


@app.route("/api/toggle-notify", methods=["POST"])
@login_required
def api_toggle_notify():
    """Toggle documents.notify_new_roles on the profile."""
    sb = get_sb()
    r = sb.table("profiles").select("documents").eq("id", current_user.id).limit(1).execute()
    docs = _load_docs(r.data[0]) if r.data else {}
    new_val = not bool(docs.get("notify_new_roles"))
    docs["notify_new_roles"] = new_val
    sb.table("profiles").update({"documents": docs}).eq("id", current_user.id).execute()
    return jsonify({"notify_new_roles": new_val})


@app.route("/api/submit-takes", methods=["POST"])
@login_required
def api_submit_takes():
    """Record an actor's submission — appended to profiles.documents.submissions."""
    from datetime import datetime, timezone
    data = request.get_json(silent=True) or {}
    entry = {
        "favored":       int(data.get("favored") or 0),
        "role":          (data.get("role") or "")[:120],
        "project":       (data.get("project") or "")[:200],
        "submitted_at":  datetime.now(timezone.utc).isoformat(),
    }
    sb = get_sb()
    r = sb.table("profiles").select("documents").eq("id", current_user.id).limit(1).execute()
    docs = _load_docs(r.data[0]) if r.data else {}
    docs.setdefault("submissions", []).insert(0, entry)
    sb.table("profiles").update({"documents": docs}).eq("id", current_user.id).execute()
    return jsonify({"ok": True, "favored": entry["favored"]})


@app.route("/api/build-deck", methods=["POST"])
@subscription_required
def api_build_deck():
    """Run the deterministic deck pipeline against a project's saved script.

    Steps (synchronous — the pipeline is fast enough for foreground request):
      1. Load project from DB; verify ownership.
      2. Serialize project.script_text (JSON scenes) to fountain plaintext.
      3. Create per-project working dir at PROJECTS_DIR/<id>/.
      4. Write input.txt + run input_handler_v1.py + single_brain + layout_engine + deck_builder
         via run_pipeline.py.
      5. Move output .pptx + brain JSON into project_assets, mark project.has_deck=1,
         write deck_path.
      6. Return JSON with download URL.
    """
    import subprocess, json as _json
    from pathlib import Path as _P

    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"error": "project_id required"}), 400

    project = get_project(project_id, current_user.id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    script_text = project.get("script_text") or ""
    title = project.get("title") or "Untitled Project"
    fountain = _serialize_scenes_to_fountain(script_text, title=title,
                                             idea_text=project.get("idea_text") or "",
                                             synopsis_text=project.get("synopsis_text") or "")
    if not fountain or not fountain.strip():
        return jsonify({"error": "Project has no script or idea content yet"}), 400

    app_root = _P(__file__).resolve().parent
    proj_dir = app_root / "projects_work" / str(project_id)
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "input.txt").write_text(fountain, encoding="utf-8")

    env = os.environ.copy()
    env["DAI_WORK_DIR"] = str(proj_dir)
    # Genre picker override — user's chosen world short-circuits detect_world
    if project.get("world_override"):
        env["EVOLUM_WORLD_OVERRIDE"] = project["world_override"]
    try:
        r = subprocess.run(
            ["python3", str(app_root / "run_pipeline.py"), "input.txt"],
            cwd=str(proj_dir), env=env, capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Pipeline timed out (5 min)"}), 504
    if r.returncode != 0:
        print(f"⚠️  build-deck pipeline failed: {r.stderr[-500:]}", flush=True)
        return jsonify({"error": "Pipeline failed", "log": r.stderr[-2000:]}), 500

    deck_out_dir = proj_dir / "visuals" / "output"
    pptx_candidates = sorted(deck_out_dir.glob("pitch_deck_v*.pptx"),
                             key=lambda p: int(p.stem.rsplit("_v", 1)[-1])) if deck_out_dir.exists() else []
    if not pptx_candidates:
        deck_out_dir = proj_dir / "output"
        pptx_candidates = sorted(deck_out_dir.glob("pitch_deck_v*.pptx"),
                                 key=lambda p: int(p.stem.rsplit("_v", 1)[-1])) if deck_out_dir.exists() else []
    if not pptx_candidates:
        return jsonify({"error": "Pipeline ran but produced no .pptx"}), 500
    latest_pptx = pptx_candidates[-1]

    deck_rel_path = str(latest_pptx.relative_to(app_root))
    record_asset(project_id, current_user.id, "deck",
                 latest_pptx.name, deck_rel_path, latest_pptx.stat().st_size,
                 "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    brain_path = proj_dir / "approved_brain_output.json"
    if brain_path.exists():
        record_asset(project_id, current_user.id, "brain",
                     "approved_brain_output.json",
                     str(brain_path.relative_to(app_root)),
                     brain_path.stat().st_size, "application/json")

    return jsonify({
        "ok": True,
        "message": f"Deck built — {latest_pptx.name}",
        "download_url": f"/project/{project_id}/asset/deck",
        "log": r.stdout[-2000:],
    })


def _serialize_scenes_to_fountain(script_json, title="", idea_text="", synopsis_text=""):
    """Convert JSON scenes (as stored in project.script_text) into fountain-style
    plaintext that input_handler_v1.py can parse. Falls back to idea+synopsis as
    minimal content when no scenes exist (deterministic engine still runs)."""
    import json as _json
    lines = []
    if title:
        lines.append(title.upper())
        lines.append("")
        lines.append("")
    try:
        scenes = _json.loads(script_json) if script_json else []
        if not isinstance(scenes, list):
            scenes = scenes.get("scenes", []) if isinstance(scenes, dict) else []
    except Exception:
        scenes = []
    if scenes:
        for s in scenes:
            slug = (s.get("slug") or "").strip()
            if slug:
                lines.append(slug)
                lines.append("")
            for b in s.get("blocks", []):
                t = b.get("type")
                if t == "action":
                    lines.append(b.get("text", "").strip())
                    lines.append("")
                elif t == "character":
                    name = (b.get("name") or "").strip().upper()
                    if name:
                        lines.append(name)
                elif t == "paren":
                    text = (b.get("text") or "").strip()
                    if text:
                        if not text.startswith("("):
                            text = "(" + text
                        if not text.endswith(")"):
                            text = text + ")"
                        lines.append(text)
                elif t == "dialogue":
                    lines.append(b.get("text", "").strip())
                    lines.append("")
                elif t == "transition":
                    txt = (b.get("text") or "").strip().upper()
                    if txt:
                        if not txt.endswith(":"):
                            txt = txt + ":"
                        lines.append(txt)
                        lines.append("")
            lines.append("")
        return "\n".join(lines)
    # No scenes — fall back to a minimal synopsis-driven input
    fallback = []
    if title:
        fallback.append(title.upper())
        fallback.append("")
    if idea_text:
        fallback.append("LOGLINE:")
        fallback.append(idea_text.strip())
        fallback.append("")
    if synopsis_text:
        fallback.append("SYNOPSIS:")
        fallback.append(synopsis_text.strip())
        fallback.append("")
    if not fallback:
        return ""
    return "\n".join(fallback)


@app.route("/project/<project_id>/asset/<kind>")
@subscription_required
def project_asset_download(project_id, kind):
    """Serve a project asset (e.g. /project/<id>/asset/deck → latest .pptx).
    Owner-only. For legacy projects with a public deck_url set in Supabase,
    redirect to that URL instead of serving from local disk."""
    from pathlib import Path as _P
    if not user_owns_project(project_id, current_user.id):
        return "Not found", 404
    # First: look for a locally-recorded asset
    a = latest_asset_of_kind(project_id, current_user.id, kind)
    if a and a.get("path"):
        app_root = _P(__file__).resolve().parent
        full = (app_root / a["path"]).resolve()
        if full.exists() and str(full).startswith(str(app_root)):
            return send_file(str(full), as_attachment=True, download_name=a.get("name", full.name))
    # Fall back to the Supabase project's remote URL for legacy assets
    project = get_project(project_id, current_user.id) or {}
    url_field = {
        "deck":         "deck_url",
        "analysis":     "analysis_report_url",
        "audition_prep": "actor_prep_url",
        "booked_role":  "actor_booked_url",
    }.get(kind)
    if url_field and project.get(url_field):
        return redirect(project[url_field])
    return f"No {kind} asset for this project", 404


@app.route("/api/cut-reel", methods=["POST"])
@subscription_required
def api_cut_reel():
    """Build the deterministic sizzle reel HTML for a project.
    Reads the project's brain output + slide_plan, composes a beat-by-beat reel,
    writes it as a self-contained HTML to the project's work dir, persists as
    project_assets row, flips has_sizzle=1."""
    import json as _json
    from pathlib import Path as _P

    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"error": "project_id required"}), 400

    project = get_project(project_id, current_user.id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not project.get("has_deck"):
        return jsonify({"error": "Build the deck first — the reel uses its data"}), 400

    app_root = _P(__file__).resolve().parent
    proj_dir = app_root / "projects_work" / str(project_id)
    brain_path = proj_dir / "approved_brain_output.json"
    slide_plan_path = proj_dir / "slide_plan.json"
    if not brain_path.exists() or not slide_plan_path.exists():
        return jsonify({"error": "Deck artifacts missing — rebuild the deck"}), 500

    try:
        brain = _json.loads(brain_path.read_text(encoding="utf-8"))
        slide_plan = _json.loads(slide_plan_path.read_text(encoding="utf-8"))
    except Exception as e:
        return jsonify({"error": f"Couldn't read deck artifacts: {e}"}), 500

    html = _compose_sizzle_html(project, brain, slide_plan)
    reel_path = proj_dir / "sizzle_reel.html"
    reel_path.write_text(html, encoding="utf-8")

    rel = str(reel_path.relative_to(app_root))
    record_asset(project_id, current_user.id, "sizzle",
                 "sizzle_reel.html", rel, reel_path.stat().st_size, "text/html")
    return jsonify({
        "ok": True,
        "message": f"Sizzle reel composed — {reel_path.name}",
        "view_url": f"/project/{project_id}/sizzle",
    })


def _compose_sizzle_html(project, brain, slide_plan):
    """Compose a deterministic, self-contained HTML sizzle reel from brain + slide_plan.
    Scrollable beat-by-beat layout. No JS dependencies, no external fonts beyond Google,
    no AI calls — pure templating."""
    title = brain.get("title") or project.get("title", "Untitled")
    logline = brain.get("logline") or project.get("idea_text", "")
    synopsis = brain.get("synopsis") or project.get("synopsis_text", "")
    tone = brain.get("tone", "")
    world = brain.get("world", "")
    theme = brain.get("theme", "")
    characters = brain.get("characters", [])
    if isinstance(characters, list) and characters and isinstance(characters[0], dict):
        char_names = [c.get("name", "") for c in characters[:6]]
    else:
        char_names = list(characters)[:6] if isinstance(characters, list) else []
    slides = slide_plan.get("slides", [])

    # Pull a handful of beat slides (skip deck spine titles, prefer image slides)
    beat_slides = []
    for s in slides:
        if s.get("category") == "Deck Spine":
            beat_slides.append({
                "title": s.get("display_title") or s.get("title", ""),
                "body": s.get("display_body") or s.get("body", ""),
                "image": s.get("image_path", "") or s.get("background_image", ""),
            })
    beat_slides = beat_slides[:8]

    # Render
    import html as _h
    def esc(s): return _h.escape(str(s or ""))
    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">""")
    parts.append(f"<title>Sizzle · {esc(title)} — EVOLUM</title>")
    parts.append("""<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,700;1,9..144,400;1,9..144,700&family=DM+Mono:wght@400;500&family=Inter:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#07070f;color:#ede9e0;font-family:'Inter',sans-serif;line-height:1.6;min-height:100vh}
.sz-shell{max-width:980px;margin:0 auto;padding:0 28px}
.sz-hero{min-height:100vh;display:flex;flex-direction:column;justify-content:center;text-align:center;padding:80px 28px;position:relative}
.sz-hero::before{content:'';position:absolute;inset:0;background:radial-gradient(ellipse 70% 50% at 50% 40%,oklch(0.78 0.16 75/0.10),transparent 70%);pointer-events:none}
.sz-eyebrow{font-family:'DM Mono',monospace;font-size:11px;letter-spacing:2.6px;text-transform:uppercase;color:oklch(0.78 0.16 75);margin-bottom:24px;position:relative;z-index:1}
.sz-title{font-family:'Fraunces',serif;font-style:italic;font-size:clamp(56px,10vw,128px);font-weight:700;letter-spacing:-3px;line-height:0.95;color:#f5efe2;margin-bottom:18px;position:relative;z-index:1}
.sz-logline{font-family:'Fraunces',serif;font-style:italic;font-size:clamp(20px,3vw,28px);color:#c3bdb0;max-width:720px;margin:0 auto;line-height:1.4;position:relative;z-index:1}
.sz-stage-rule{height:1px;background:#1e1e2e;margin:0 0 80px}
.sz-beat{padding:80px 0;display:grid;grid-template-columns:1fr;gap:30px}
.sz-beat-eyebrow{font-family:'DM Mono',monospace;font-size:11px;letter-spacing:2.2px;text-transform:uppercase;color:oklch(0.78 0.16 75)}
.sz-beat-title{font-family:'Fraunces',serif;font-style:italic;font-size:clamp(38px,5vw,64px);font-weight:700;letter-spacing:-1.6px;line-height:1;color:#f5efe2}
.sz-beat-body{font-family:'Fraunces',serif;font-size:18px;color:#c3bdb0;max-width:720px;line-height:1.65;font-style:italic}
.sz-meta-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin:60px 0}
.sz-meta-cell{background:#0d0d18;border:1px solid #1e1e2e;padding:18px 20px;clip-path:polygon(0 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%)}
.sz-meta-label{font-family:'DM Mono',monospace;font-size:9px;letter-spacing:1.6px;text-transform:uppercase;color:#6a6778;margin-bottom:6px}
.sz-meta-value{font-family:'Fraunces',serif;font-style:italic;font-size:18px;color:#ede9e0}
.sz-cast{display:flex;flex-wrap:wrap;gap:8px}
.sz-cast-chip{font-family:'DM Mono',monospace;font-size:11px;letter-spacing:0.6px;border:1px solid oklch(0.78 0.16 75/0.32);color:oklch(0.78 0.16 75);padding:5px 12px}
.sz-foot{text-align:center;padding:60px 28px;border-top:1px solid #1e1e2e;color:#6a6778;font-family:'DM Mono',monospace;font-size:10px;letter-spacing:1.6px;text-transform:uppercase}
.sz-foot strong{color:oklch(0.78 0.16 75)}
</style></head><body>""")

    # HERO
    parts.append(f"""<div class="sz-hero">
  <div class="sz-eyebrow">A Sizzle Reel · EVOLUM</div>
  <h1 class="sz-title">{esc(title)}</h1>
  <p class="sz-logline">{esc(logline)}</p>
</div>
<div class="sz-shell"><div class="sz-stage-rule"></div>""")

    # Synopsis
    if synopsis:
        parts.append(f"""<div class="sz-beat">
  <div class="sz-beat-eyebrow">The story</div>
  <h2 class="sz-beat-title">{esc(title)}, briefly.</h2>
  <p class="sz-beat-body">{esc(synopsis)}</p>
</div><div class="sz-stage-rule"></div>""")

    # Beats
    for i, b in enumerate(beat_slides):
        if not b["title"] and not b["body"]:
            continue
        parts.append(f"""<div class="sz-beat">
  <div class="sz-beat-eyebrow">Beat 0{i+1}</div>
  <h2 class="sz-beat-title">{esc(b['title'])}</h2>
  <p class="sz-beat-body">{esc(b['body'])}</p>
</div><div class="sz-stage-rule"></div>""")

    # Meta
    parts.append('<div class="sz-meta-grid">')
    if world:    parts.append(f'<div class="sz-meta-cell"><div class="sz-meta-label">World</div><div class="sz-meta-value">{esc(world)}</div></div>')
    if tone:     parts.append(f'<div class="sz-meta-cell"><div class="sz-meta-label">Tone</div><div class="sz-meta-value">{esc(tone)}</div></div>')
    if theme:    parts.append(f'<div class="sz-meta-cell"><div class="sz-meta-label">Theme</div><div class="sz-meta-value">{esc(theme)}</div></div>')
    if char_names:
        chip_html = "".join(f'<span class="sz-cast-chip">{esc(n)}</span>' for n in char_names if n)
        parts.append(f'<div class="sz-meta-cell"><div class="sz-meta-label">Cast</div><div class="sz-cast">{chip_html}</div></div>')
    parts.append('</div></div>')

    # Foot
    parts.append(f"""<div class="sz-foot">
  Composed by the <strong>EVOLUM</strong> deterministic engine · No AI cloud calls<br>
  <span style="color:#3a3a4a;">Project · {esc(project.get('title',''))} · {esc(project.get('updated_at',''))}</span>
</div></body></html>""")
    return "".join(parts)


@app.route("/sizzle-reel")
@subscription_required
def sizzle_reel_page():
    """Sizzle reel surface. Project-aware: when ?project=X is supplied and the
    project has a deck, the page shows the composed reel preview."""
    project_id = request.args.get("project", type=str)
    project = get_project(project_id, current_user.id) if project_id else None
    return render_template("sizzle-reel.html", project=project)


@app.route("/project/<project_id>/sizzle")
@subscription_required
def project_sizzle_view(project_id):
    """Serve the composed sizzle reel HTML inline (not a download)."""
    from pathlib import Path as _P
    a = latest_asset_of_kind(project_id, current_user.id, "sizzle")
    if not a:
        return "No sizzle reel yet", 404
    app_root = _P(__file__).resolve().parent
    full = (app_root / a["path"]).resolve()
    if not full.exists() or not str(full).startswith(str(app_root)):
        return "Reel missing on disk", 404
    return send_file(str(full), mimetype="text/html")


def _ensure_project_brain(project, app_root):
    """Make sure the project's brain_output exists; if not, run the input_handler +
    single_brain steps to produce it. Returns the brain_data dict, or None if
    there's no script content at all to work with."""
    import subprocess, json as _json
    from pathlib import Path as _P
    proj_dir = app_root / "projects_work" / str(project["id"])
    proj_dir.mkdir(parents=True, exist_ok=True)
    brain_path = proj_dir / "approved_brain_output.json"
    if brain_path.exists():
        try:
            return _json.loads(brain_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Serialize project script + idea into input.txt
    fountain = _serialize_scenes_to_fountain(
        project.get("script_text") or "",
        title=project.get("title") or "Untitled",
        idea_text=project.get("idea_text") or "",
        synopsis_text=project.get("synopsis_text") or "",
    )
    if not fountain or not fountain.strip():
        return None
    (proj_dir / "input.txt").write_text(fountain, encoding="utf-8")
    env = os.environ.copy()
    env["DAI_WORK_DIR"] = str(proj_dir)
    try:
        subprocess.run(
            ["python3", str(app_root / "input_handler_v1.py"), "input.txt"],
            cwd=str(proj_dir), env=env, capture_output=True, timeout=60,
        )
        subprocess.run(
            ["python3", str(app_root / "single_brain_orchestrator_v3.py"), str(proj_dir / "input.txt")],
            cwd=str(proj_dir), env=env, capture_output=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return None
    if not brain_path.exists():
        return None
    try:
        return _json.loads(brain_path.read_text(encoding="utf-8"))
    except Exception:
        return None


@app.route("/api/build-audition-prep", methods=["POST"])
@subscription_required
def api_build_audition_prep():
    """Build deterministic actor prep PDF for a project + character."""
    from pathlib import Path as _P
    from dai_tools import build_actor_prep_pdf

    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    character_name = (data.get("character_name") or "").strip()[:80]
    if not project_id or not character_name:
        return jsonify({"error": "project_id and character_name required"}), 400

    project = get_project(project_id, current_user.id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    app_root = _P(__file__).resolve().parent
    brain_data = _ensure_project_brain(project, app_root)
    if brain_data is None:
        return jsonify({"error": "No script content yet — add an idea or script first"}), 400

    proj_dir = app_root / "projects_work" / str(project_id)
    out_pdf = proj_dir / f"audition_prep_{re.sub(r'[^a-z0-9]+', '_', character_name.lower())}.pdf"
    script_text = (proj_dir / "input.txt").read_text(encoding="utf-8") if (proj_dir / "input.txt").exists() else ""
    try:
        build_actor_prep_pdf(script_text, character_name, out_pdf, brain_data=brain_data)
    except Exception as e:
        return jsonify({"error": f"Audition prep failed: {e}"}), 500
    if not out_pdf.exists():
        return jsonify({"error": "PDF not produced"}), 500

    rel = str(out_pdf.relative_to(app_root))
    record_asset(project_id, current_user.id, "audition_prep",
                 out_pdf.name, rel, out_pdf.stat().st_size, "application/pdf")
    return jsonify({
        "ok": True,
        "message": f"Audition prep ready for {character_name}",
        "download_url": f"/project/{project_id}/asset/audition_prep",
        "view_url": f"/project/{project_id}/asset/audition_prep",
    })


@app.route("/api/build-booked-role", methods=["POST"])
@subscription_required
def api_build_booked_role():
    """Build deterministic booked role analysis PDF."""
    from pathlib import Path as _P
    from dai_tools import build_actor_booked_pdf

    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    character_name = (data.get("character_name") or "").strip()[:80]
    if not project_id or not character_name:
        return jsonify({"error": "project_id and character_name required"}), 400

    project = get_project(project_id, current_user.id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    app_root = _P(__file__).resolve().parent
    brain_data = _ensure_project_brain(project, app_root)
    if brain_data is None:
        return jsonify({"error": "No script content yet — add an idea or script first"}), 400

    proj_dir = app_root / "projects_work" / str(project_id)
    out_pdf = proj_dir / f"booked_role_{re.sub(r'[^a-z0-9]+', '_', character_name.lower())}.pdf"
    script_text = (proj_dir / "input.txt").read_text(encoding="utf-8") if (proj_dir / "input.txt").exists() else ""
    try:
        build_actor_booked_pdf(script_text, character_name, out_pdf, brain_data=brain_data)
    except Exception as e:
        return jsonify({"error": f"Booked role analysis failed: {e}"}), 500
    if not out_pdf.exists():
        return jsonify({"error": "PDF not produced"}), 500

    rel = str(out_pdf.relative_to(app_root))
    record_asset(project_id, current_user.id, "booked_role",
                 out_pdf.name, rel, out_pdf.stat().st_size, "application/pdf")
    return jsonify({
        "ok": True,
        "message": f"Booked role analysis ready for {character_name}",
        "download_url": f"/project/{project_id}/asset/booked_role",
    })


@app.route("/api/build-script-analysis", methods=["POST"])
@subscription_required
def api_build_script_analysis():
    """Build deterministic script analysis PDF + serve the brain output."""
    from pathlib import Path as _P
    from dai_tools import build_simple_analysis_pdf

    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"error": "project_id required"}), 400

    project = get_project(project_id, current_user.id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    app_root = _P(__file__).resolve().parent
    brain_data = _ensure_project_brain(project, app_root)
    if brain_data is None:
        return jsonify({"error": "No script content yet — add an idea or script first"}), 400

    proj_dir = app_root / "projects_work" / str(project_id)
    out_pdf = proj_dir / "script_analysis.pdf"
    try:
        build_simple_analysis_pdf(brain_data, out_pdf)
    except Exception as e:
        return jsonify({"error": f"Analysis failed: {e}"}), 500
    if not out_pdf.exists():
        return jsonify({"error": "PDF not produced"}), 500

    rel = str(out_pdf.relative_to(app_root))
    record_asset(project_id, current_user.id, "analysis",
                 "script_analysis.pdf", rel, out_pdf.stat().st_size, "application/pdf")
    return jsonify({
        "ok": True,
        "message": "Script analysis ready",
        "download_url": f"/project/{project_id}/asset/analysis",
    })


# ===== PROJECT ROUTES =================================================
# Foundation for the connected studio flow (idea → script → deck → sizzle).
# Per-user project ownership enforced on every endpoint.

def _owns_project(conn_or_ignored, project_id, user_id):
    """Legacy signature preserved (still takes 3 args) — routes through the
    Supabase-backed user_owns_project helper regardless of first arg."""
    return user_owns_project(project_id, user_id)


@app.route("/script-editor")
@subscription_required
def script_editor_page():
    """Scene-based screenplay editor. Saves to project documents.script_text."""
    project_id = request.args.get("project", type=str)
    if not project_id:
        return redirect(url_for("filmmaker_workspace"))
    project = get_project(project_id, current_user.id)
    if not project:
        return redirect(url_for("filmmaker_workspace"))
    return render_template("script_editor.html", project=project)


@app.route("/idea")
@subscription_required
def idea_page():
    """Story development surface — collects logline, synopsis, characters, world.
    Requires ?project=<id>. If the project belongs to the user, render the form
    populated with current state."""
    project_id = request.args.get("project", type=str)
    if not project_id:
        return redirect(url_for("filmmaker_workspace"))
    project = get_project(project_id, current_user.id)
    if not project:
        return redirect(url_for("filmmaker_workspace"))
    suggestion = _classifier_suggestion_for_project(project)
    return render_template("idea.html", project=project,
                           suggestion=suggestion, world_display=WORLD_DISPLAY)


@app.route("/new-project", methods=["GET", "POST"])
@subscription_required
def new_project_page():
    """GET renders the new-project form (title-only default, or a file-upload
    variant when ?flow=script). POST creates the project. If a screenplay was
    uploaded, parses it and stores documents.script_text so /script-editor +
    /pitch-deck can read it immediately."""
    from auth import PROJECT_ROLES, ROLE_HOME
    if getattr(current_user, "role", "filmmaker") not in PROJECT_ROLES:
        home = ROLE_HOME.get(getattr(current_user, "role", "filmmaker"), "filmmaker_workspace")
        return redirect(url_for(home))

    # `flow` distinguishes the "bring a script" upload variant from the plain
    # title-only new-project form. Survives across POST via a hidden input.
    flow = (request.form.get("flow") or request.args.get("flow") or "").strip()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()[:200]
        script_text = ""

        # If we're in the script-upload flow, accept EITHER a file OR pasted text.
        if flow == "script":
            paste_text = (request.form.get("script_paste") or "").strip()
            script_file = request.files.get("script")

            if paste_text:
                # User pasted directly — no format detection needed, treat as .txt.
                script_text = paste_text[:2_000_000]
                filename_for_title_fallback = ""
            elif script_file and script_file.filename:
                ext = "." + script_file.filename.rsplit(".", 1)[-1].lower() if "." in script_file.filename else ""
                if ext not in ALLOWED_EXTENSIONS:
                    return render_template("new_project.html", flow=flow,
                        error=f"Unsupported file type ({ext or '?'}). Use .txt / .pdf / .fdx / .docx / .rtf / .fountain — or paste the text directly below.",
                        show_paste_fallback=True), 400
                try:
                    script_text = extract_script_text(script_file) or ""
                except Exception as e:
                    print(f"⚠️  extract_script_text failed on upload: {e}", flush=True)
                    script_text = ""
                if not script_text.strip():
                    return render_template("new_project.html", flow=flow,
                        error="Couldn't read any text from that file. Try pasting the script text directly below instead.",
                        show_paste_fallback=True), 400
                filename_for_title_fallback = script_file.filename
            else:
                return render_template("new_project.html", flow=flow,
                    error="Please choose a screenplay file to upload OR paste the script text below."), 400

            # If title was left blank, extract from the screenplay
            if not title:
                try:
                    import single_brain_orchestrator_v3 as _brain
                    extracted = _brain.extract_title(script_text) or ""
                    title = extracted.strip()[:200]
                except Exception:
                    pass
                if not title:
                    # last-resort fallback: use the filename without extension (if we have one)
                    if filename_for_title_fallback:
                        title = filename_for_title_fallback.rsplit(".", 1)[0][:200]
                    if not title:
                        title = "Untitled Project"

        if not title:
            return render_template("new_project.html", flow=flow,
                error="A project needs a title."), 400

        ptype = getattr(current_user, "role", "filmmaker")
        pid = sb_create_project(current_user.id, title, project_type=ptype)
        if not pid:
            return render_template("new_project.html", flow=flow,
                error="Couldn't create the project. Try again."), 500

        # If we parsed a screenplay, store it on the new project
        if script_text:
            try:
                update_project_fields(pid, current_user.id, {"script_text": script_text})
            except Exception as e:
                print(f"⚠️  saving script_text to new project failed: {e}", flush=True)

        return redirect(url_for("project_page", project_id=pid))

    return render_template("new_project.html", flow=flow)


@app.route("/project/<project_id>/deliverables")
@subscription_required
def project_deliverables(project_id):
    """Per-project deliverables hub. Shows every asset categorized."""
    project = get_project(project_id, current_user.id)
    if not project:
        return redirect(url_for("filmmaker_workspace"))
    assets = project.get("assets", [])
    # Normalize field names to match the template's expected shape
    norm = []
    for a in assets:
        norm.append({
            "asset_kind": a.get("kind", ""),
            "asset_name": a.get("name", ""),
            "size_bytes": a.get("size_bytes", 0),
            "content_type": a.get("content_type", ""),
            "created_at": a.get("created_at", ""),
        })
    grouped = {}
    for a in norm:
        grouped.setdefault(a["asset_kind"], []).append(a)
    return render_template("deliverables.html", project=project, assets=norm, grouped=grouped)


@app.route("/project/<project_id>")
@subscription_required
def project_page(project_id):
    """Per-project workspace surface — lists assets, deck status, links to tools."""
    project = get_project(project_id, current_user.id)
    if not project:
        return redirect(url_for("filmmaker_workspace"))
    raw_assets = project.get("assets", [])
    assets = [{
        "asset_kind": a.get("kind", ""),
        "asset_name": a.get("name", ""),
        "size_bytes": a.get("size_bytes", 0),
        "created_at": a.get("created_at", ""),
    } for a in raw_assets]
    return render_template("project.html", project=project, assets=assets)


@app.route("/api/projects", methods=["GET"])
@subscription_required
def api_projects_list():
    return jsonify({"projects": list_projects_for_user(current_user.id)})


@app.route("/project/<project_id>/sharing")
@subscription_required
def project_sharing(project_id):
    """Owner-only page to configure a project's public sharing:
    public_page_enabled toggle, URL slug, public blurb, filmmaker's Stripe link."""
    project = get_project(project_id, current_user.id)
    if not project:
        return redirect(url_for("filmmaker_workspace"))
    return render_template("project_sharing.html", project=project)


@app.route("/p/<slug>")
def public_project_page(slug):
    """Public shareable project page. No auth required. 404s unless the project
    row has public_page_enabled=true. The filmmaker's `supporter_stripe_link`
    drives the pledge button — EVOLUM never touches the money."""
    project = get_public_project_by_slug(slug)
    if not project:
        return "Not found", 404
    filmmaker_name = get_filmmaker_display_name(project.get("user_id") or "")
    return render_template("public_project.html", project=project, filmmaker_name=filmmaker_name)


@app.route("/api/projects/<project_id>", methods=["GET", "PATCH", "DELETE"])
@subscription_required
def api_project_one(project_id):
    if not user_owns_project(project_id, current_user.id):
        return jsonify({"error": "Not found"}), 404
    if request.method == "GET":
        return jsonify(get_project(project_id, current_user.id) or {})
    if request.method == "DELETE":
        sb_delete_project(project_id, current_user.id)
        return jsonify({"ok": True})
    # PATCH
    data = request.get_json(silent=True) or {}
    allowed_keys = {"title", "status", "idea_text", "synopsis_text",
                    "characters_json", "world_json", "script_text",
                    "public_page_enabled", "public_blurb", "supporter_stripe_link", "slug",
                    "world_override"}
    patch = {k: v for k, v in data.items() if k in allowed_keys}
    if not patch:
        return jsonify({"error": "Nothing to update"}), 400
    project = update_project_fields(project_id, current_user.id, patch)
    return jsonify(project or {})


# ===== PITCH DECK ROUTES START =======================

# ===== UPLOAD OVERRIDE HELPERS START ====================
def apply_upload_text_overrides(project_dir, logline_override="", synopsis_override=""):
    logline_override = (logline_override or "").strip()
    synopsis_override = (synopsis_override or "").strip()

    if not logline_override and not synopsis_override:
        return

    deck_content_candidates = [
        Path(project_dir) / "deck_content.json",
        Path(project_dir) / "pipeline" / "compile" / "deck_content.json",
        Path(project_dir) / "pipeline" / "compile" / "final_compiled_payload.json",
    ]

    for candidate in deck_content_candidates:
        if not candidate.exists():
            continue

        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue

        changed = False

        # Common payload-level keys
        if logline_override:
            for key in ["logline", "project_logline", "one_line_pitch"]:
                if key in data:
                    data[key] = logline_override
                    changed = True

        if synopsis_override:
            for key in ["synopsis", "project_synopsis", "story_overview"]:
                if key in data:
                    data[key] = synopsis_override
                    changed = True

        # Common slide structures
        slide_collections = []
        for key in ["slides", "deck_slides", "slide_plan"]:
            value = data.get(key)
            if isinstance(value, list):
                slide_collections.append(value)

        for slides in slide_collections:
            for slide in slides:
                if not isinstance(slide, dict):
                    continue

                slide_title = str(slide.get("title", "") or "").lower()
                slide_type = str(slide.get("type", "") or "").lower()

                if logline_override and ("logline" in slide_title or "logline" in slide_type):
                    for field in ["title", "subtitle", "body", "content", "text", "copy", "description"]:
                        if field in slide:
                            # preserve title if it's literally "Logline"
                            if field == "title" and str(slide.get(field, "")).strip().lower() == "logline":
                                continue
                            slide[field] = logline_override
                            changed = True
                            break

                if synopsis_override and ("synopsis" in slide_title or "synopsis" in slide_type):
                    for field in ["title", "subtitle", "body", "content", "text", "copy", "description"]:
                        if field in slide:
                            if field == "title" and str(slide.get(field, "")).strip().lower() == "synopsis":
                                continue
                            slide[field] = synopsis_override
                            changed = True
                            break

        if changed:
            candidate.write_text(json.dumps(data, indent=2), encoding="utf-8")
# ===== UPLOAD OVERRIDE HELPERS END ======================

@app.route("/upload", methods=["POST"])
@subscription_required
def upload():
    submitted_logline = (request.form.get("logline") or "").strip()
    submitted_synopsis = (request.form.get("synopsis") or "").strip()
    file = request.files.get("script")

    if not file or file.filename == "":
        return "No file uploaded", 400

    if not allowed_file(file.filename):
        return "Unsupported file type. Please upload a TXT, PDF, FDX, or DOCX file.", 400

    clear_latest_targets()
    set_status("UPLOADED")

    save_path = UPLOAD_DIR / Path(file.filename).name
    file.save(save_path)

    started_at = time.time()
    log_usage("generate_start", filename=file.filename)

    logline = (request.form.get("logline") or "").strip()
    synopsis = (request.form.get("synopsis") or "").strip()
    poster = request.files.get("poster")
    images = request.files.getlist("images")

    visuals_root = BASE_DIR / "visuals" / "user_uploaded"
    poster_dir = visuals_root / "poster"
    current_dir = visuals_root / "current"

    poster_dir.mkdir(parents=True, exist_ok=True)
    current_dir.mkdir(parents=True, exist_ok=True)

    for old_file in poster_dir.iterdir():
        if old_file.is_file():
            old_file.unlink()

    for old_file in current_dir.iterdir():
        if old_file.is_file():
            old_file.unlink()

    if poster and poster.filename:
        poster_path = poster_dir / Path(poster.filename).name
        poster.save(poster_path)

    saved_images = []
    for image in images:
        if image and image.filename:
            image_path = current_dir / Path(image.filename).name
            image.save(image_path)
            saved_images.append(image_path.name)

    upload_context = {
        "script_filename": Path(file.filename).name,
        "logline": logline,
        "synopsis": synopsis,
        "poster_filename": poster.filename if poster and poster.filename else "",
        "image_filenames": saved_images,
    }

    (BASE_DIR / "user_upload_context.json").write_text(
        json.dumps(upload_context, indent=2),
        encoding="utf-8",
    )

    # === ENSURE OVERRIDE FILE EXISTS IN ALL PIPELINE PATHS ===
    try:
        override_data = json.dumps(upload_context, indent=2)
        (BASE_DIR / "user_upload_context.json").write_text(override_data, encoding="utf-8")
        (BASE_DIR / "input").mkdir(exist_ok=True)
        (BASE_DIR / "input" / "user_upload_context.json").write_text(override_data, encoding="utf-8")
        (BASE_DIR / "pipeline").mkdir(exist_ok=True)
        (BASE_DIR / "pipeline" / "user_upload_context.json").write_text(override_data, encoding="utf-8")
        print("✅ Upload overrides written to all known paths")
    except Exception as e:
        print("⚠️ Failed to write override files:", e)


    # Delete previous session's generated images before starting new build
    prev_session_file = BASE_DIR / "current_session_id.txt"
    if prev_session_file.exists():
        try:
            prev_id = prev_session_file.read_text().strip()
            prev_dir = BASE_DIR / "generated_images" / prev_id
            if prev_dir.exists():
                shutil.rmtree(prev_dir)
        except Exception:
            pass

    session_id = uuid.uuid4().hex
    prev_session_file.write_text(session_id)
    build_env = {**os.environ, "EVOLUM_SESSION_ID": session_id}

    try:
        set_status("ANALYZING")
        log_path = BASE_DIR / "pipeline.log"

        with open(log_path, "w", encoding="utf-8") as log_file:
            subprocess.run(
                ["python3", str(BASE_DIR / "run_pipeline.py"), str(save_path)],
                cwd=str(BASE_DIR),
                stdout=log_file,
                stderr=log_file,
                text=True,
                check=True,
                env=build_env,
            )

        set_status("BUILDING")
    except subprocess.CalledProcessError:
        set_status("ERROR")
        return "Engine failed", 500
    finally:
        try:
            save_path.unlink(missing_ok=True)
        except Exception:
            pass

    fresh_pptx = newest_generated_file(".pptx")
    fresh_pdf = newest_generated_file(".pdf")

    if not fresh_pptx or not fresh_pptx.exists():
        set_status("ERROR")
        return "No deck generated", 500

    publish_latest_outputs(fresh_pptx, fresh_pdf)

    if not LATEST_PPTX.exists():
        set_status("ERROR")
        return "Latest deck publish failed", 500

    set_status("COMPLETE")
    elapsed = int(time.time() - started_at)
    log_usage("generate_complete", success=True, filename=file.filename, elapsed=f"{elapsed}s")
    return ("OK", 200)


@app.route("/output-file")
def output_file():
    name = (request.args.get("name") or "").strip()
    if not name:
        abort(404)

    candidate = (OUTPUT_DIR / name).resolve()
    if not ensure_relative_to_base(candidate) or not candidate.exists() or not candidate.is_file():
        abort(404)

    return send_file(candidate, as_attachment=True, conditional=True)

# ===== DEMO ROUTES START =============================
@app.route("/demo", methods=["POST"])
def demo():
    if not DEMO_DECK.exists():
        return "Demo deck not found", 500
    return send_file(DEMO_DECK, as_attachment=False)


@app.route("/download/latest.pptx")
def download_latest_pptx():
    if not LATEST_PPTX.exists():
        abort(404)
    return send_file(LATEST_PPTX, as_attachment=True)


@app.route("/download/latest.pdf")
def download_latest_pdf():
    if not LATEST_PDF.exists():
        abort(404)
    return send_file(LATEST_PDF, as_attachment=True)


# ===== ANALYZE ROUTES START ==========================
@app.route("/analyze-script-pass", methods=["POST"])
@subscription_required
def analyze_script_pass():
    file = request.files.get("script")

    if not file or file.filename == "":
        return jsonify({"error": "No file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file type. Please upload a TXT, PDF, FDX, or DOCX file."}), 400

    temp_path = UPLOAD_DIR / Path(file.filename).name
    file.save(temp_path)

    started_at = time.time()
    log_usage("analyze_start", filename=file.filename)

    try:
        subprocess.run(
            ["python3", str(BASE_DIR / "single_brain_orchestrator_v3.py"), str(temp_path)],
            cwd=str(BASE_DIR),
            check=True,
        )
    except subprocess.CalledProcessError:
        log_usage("analyze_complete", success=False, filename=file.filename, error="analysis_failed")
        return jsonify({"error": "analysis failed"}), 500
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass

    brain_file = BASE_DIR / "approved_brain_output.json"

    if not brain_file.exists():
        return jsonify({"error": "No brain output"}), 500

    with open(brain_file, "r", encoding="utf-8") as f:
        brain = json.load(f)

    characters = brain.get("characters") or []
    lead_character = brain.get("protagonist") or (characters[0] if characters else "-")
    supporting_characters = characters[1:5] if len(characters) > 1 else []

    report_output = {
        "title": safe_text(brain.get("title"), "UNTITLED PROJECT"),
        "tagline": safe_text(brain.get("tagline") or brain.get("logline")),
        "logline": safe_text(brain.get("logline")),
        "synopsis": safe_text(brain.get("synopsis")),
        "lead_character": safe_text(lead_character),
        "supporting_characters": supporting_characters,
        "genre": safe_text(brain.get("world"), "Drama"),
        "tone": safe_text(brain.get("tone")),
        "theme": safe_text(brain.get("theme")),
        "world": safe_text(brain.get("world")),
        "core_conflict": safe_text(brain.get("core_conflict")),
        "story_engine": safe_text(brain.get("story_engine")),
        "reversal": safe_text(brain.get("reversal")),
        "setting": safe_text(brain.get("setting")),
        "time_frame": safe_text(brain.get("time_frame")),
        "commercial_positioning": safe_text(brain.get("commercial_positioning")),
        "audience_profile": brain.get("audience_profile") or [],
        "tone_comparables": brain.get("tone_comparables") or [],
        "comparable_films": brain.get("comparable_films") or [],
        "market_projections": brain.get("market_projections") or {},
        "strength_index": brain.get("strength_index") or {},
        "executive_summary": safe_text(brain.get("executive_summary")),
        "packaging_potential": safe_text(brain.get("packaging_potential")),
        "protagonist_summary": safe_text(brain.get("protagonist_summary")),
        "character_leverage": safe_text(brain.get("character_leverage")),
        "story_insights": [
            f"Top characters identified: {', '.join(characters[:5])}" if characters else "Top characters identified.",
            f"Protagonist detected: {lead_character}",
            f"World detected: {safe_text(brain.get('world'), 'Unknown')}",
        ],
        "character_analysis": {
            "top_characters": [
                {
                    "name": name,
                    "dialogue_count": (brain.get("character_stats") or {}).get(name, {}).get("dialogue_count", 0),
                    "action_count": (brain.get("character_stats") or {}).get(name, {}).get("action_count", 0),
                    "first_seen": (brain.get("character_stats") or {}).get(name, {}).get("first_seen", 0),
                }
                for name in characters[:5]
            ]
        },
    }

    summary_note = safe_text(report_output.get("summary_note"), "")
    if summary_note in {"", "-"}:
        title = safe_text(report_output.get("title"), "This script")
        lead = safe_text(report_output.get("lead_character"), "the lead character")
        genre = safe_text(report_output.get("genre"), "a cinematic story")
        tone = safe_text(report_output.get("tone"), "grounded and emotional")

        summary_note = (
            f"{title} puts {lead} at the center of {genre.lower()}, "
            f"with a tone that feels {tone.lower()}."
        )

    report_output["summary_note"] = summary_note

    LATEST_ANALYSIS_JSON.write_text(
        json.dumps(report_output, indent=2),
        encoding="utf-8",
    )
    build_simple_analysis_pdf(report_output, LATEST_ANALYSIS_PDF)

    return jsonify(
        {
            "summary_note": summary_note,
            "title": report_output.get("title", "UNTITLED PROJECT"),
            "report_json": str(LATEST_ANALYSIS_JSON.name),
            "report_pdf": str(LATEST_ANALYSIS_PDF.name),
        }
    )


@app.route("/analysis-report/latest.json")
def analysis_report_latest_json():
    if not LATEST_ANALYSIS_JSON.exists():
        return jsonify({"error": "No analysis report yet"}), 404

    with open(LATEST_ANALYSIS_JSON, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/analysis-report/latest.pdf")
def analysis_report_latest_pdf():
    if not LATEST_ANALYSIS_PDF.exists():
        abort(404)
    return send_file(LATEST_ANALYSIS_PDF, as_attachment=False)

@app.route("/download/latest_analysis_report.pdf")
def analysis_report_download():
    if not LATEST_ANALYSIS_PDF.exists():
        abort(404)
    return send_file(LATEST_ANALYSIS_PDF, as_attachment=True)


@app.route("/analyzer")
def analyzer():
    analyzer_file = BASE_DIR / "builder" / "deck_builder_output.json"

    if not analyzer_file.exists():
        return jsonify({"error": "No analyzer output yet"}), 404

    with open(analyzer_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return jsonify(data)



# ===== REFINE DECK ROUTES START =======================
@app.route("/latest-slide-plan")
def latest_slide_plan():
    slide_plan_file = find_latest_slide_plan_file()

    if not slide_plan_file or not slide_plan_file.exists():
        return jsonify({
            "error": "No generated slide plan found yet.",
            "slides": [],
            "slide_count": 0,
        }), 404

    try:
        with open(slide_plan_file, "r", encoding="utf-8") as f:
            slide_plan_data = json.load(f)
    except Exception as e:
        return jsonify({"error": f"Could not read latest slide plan: {e}"}), 500

    cache_key = make_slide_payload_cache_key(slide_plan_file)
    if _LATEST_SLIDE_PAYLOAD_CACHE.get("key") == cache_key and _LATEST_SLIDE_PAYLOAD_CACHE.get("payload") is not None:
        payload = dict(_LATEST_SLIDE_PAYLOAD_CACHE["payload"])
    else:
        payload = build_refine_slide_payload(slide_plan_data, slide_plan_file=slide_plan_file)
        payload["source_file"] = str(slide_plan_file.relative_to(BASE_DIR)) if slide_plan_file.is_relative_to(BASE_DIR) else str(slide_plan_file)
        _LATEST_SLIDE_PAYLOAD_CACHE["key"] = cache_key
        _LATEST_SLIDE_PAYLOAD_CACHE["payload"] = dict(payload)
    return jsonify(payload)


@app.route("/project-file")
def project_file():
    raw_path = unquote((request.args.get("path") or "").strip())
    if not raw_path:
        abort(404)
    candidate = (BASE_DIR / raw_path).resolve()
    if not ensure_relative_to_base(candidate) or not candidate.exists() or not candidate.is_file():
        abort(404)
    return send_file(candidate, as_attachment=False, conditional=True)

@app.route("/refine-deck", methods=["POST"])
def refine_deck():
    data = request.get_json(silent=True) or {}
    slides = data.get("slides", [])

    if not slides or not isinstance(slides, list):
        return jsonify({"error": "No slide data provided."}), 400

    try:
        slide_plan_payload = {
            "title": slides[0].get("title", "Refined Deck") if slides else "Refined Deck",
            "slides": [
                {
                    "title": str(slide_data.get("title", "") or "").strip(),
                    "body": str(slide_data.get("body", "") or "").strip(),
                    "layout": str(slide_data.get("layout", "") or "text").strip(),
                    "stage": str(slide_data.get("stage", "") or "refine").strip(),
                    "subtitle": str(slide_data.get("subtitle", "") or "").strip(),
                    "image_path": str(slide_data.get("image_path", "") or "").strip(),
                    "image_name": str(slide_data.get("image_name", "") or "").strip(),
                    "image_url": str(slide_data.get("image_url", "") or "").strip(),
                    "image_source": str(slide_data.get("image_source", "") or "").strip(),
                    "image_options": slide_data.get("image_options", []) if isinstance(slide_data.get("image_options", []), list) else [],
                    "selected_option_id": str(slide_data.get("selected_option_id", "") or "").strip(),
                }
                for slide_data in slides
            ],
            "slide_count": len(slides),
        }

        slide_plan_path = BASE_DIR / "slide_plan.json"
        temp_slide_plan_path = BASE_DIR / "slide_plan.tmp.json"
        temp_slide_plan_path.write_text(json.dumps(slide_plan_payload, indent=2), encoding="utf-8")
        temp_slide_plan_path.replace(slide_plan_path)

        manifest_payload = []
        for i, slide_data in enumerate(slides, start=1):
            manifest_payload.append({
                "slide_number": i,
                "title": str(slide_data.get("title", "") or "").strip(),
                "body": str(slide_data.get("body", "") or "").strip(),
                "layout": str(slide_data.get("layout", "") or "").strip(),
                "stage": str(slide_data.get("stage", "") or "").strip(),
                "image_path": str(slide_data.get("image_path", "") or "").strip(),
                "image_name": str(slide_data.get("image_name", "") or "").strip(),
                "image_url": str(slide_data.get("image_url", "") or "").strip(),
                "image_source": str(slide_data.get("image_source", "") or "").strip(),
                "image_options": slide_data.get("image_options", []) if isinstance(slide_data.get("image_options", []), list) else [],
                "selected_option_id": str(slide_data.get("selected_option_id", "") or "").strip(),
            })

        LATEST_DECK_MANIFEST_JSON.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")

        refine_session_file = BASE_DIR / "current_refine_session_id.txt"
        if refine_session_file.exists():
            try:
                prev_id = refine_session_file.read_text().strip()
                prev_dir = BASE_DIR / "generated_images" / prev_id
                if prev_dir.exists():
                    shutil.rmtree(prev_dir)
            except Exception:
                pass

        refine_session_id = uuid.uuid4().hex
        refine_session_file.write_text(refine_session_id)
        refine_env = {**os.environ, "EVOLUM_SESSION_ID": refine_session_id}
        subprocess.run(
            ["python3", str(BASE_DIR / "deck_builder.py"), str(slide_plan_path)],
            cwd=str(BASE_DIR),
            check=True,
            env=refine_env,
        )

        fresh_pptx = newest_generated_file(".pptx")
        fresh_pdf = newest_generated_file(".pdf")
        publish_latest_outputs(fresh_pptx, fresh_pdf)

        _LATEST_SLIDE_PAYLOAD_CACHE["key"] = None
        _LATEST_SLIDE_PAYLOAD_CACHE["payload"] = None

        return jsonify({
            "message": "Your refined deck has been rebuilt successfully.",
            "deck": fresh_pptx.name if fresh_pptx else LATEST_PPTX.name,
        })

    except Exception as e:
        return jsonify({"error": f"Refine rebuild failed: {e}"}), 500

# ===== REFINE DECK ROUTES END =========================

# ===== ACTOR PREP ROUTES START =======================
@app.route("/actor-prep-pass", methods=["POST"])
@subscription_required
def actor_prep_pass():
    character_name = (request.form.get("character_name") or "").strip()
    pasted_text = (request.form.get("script_text") or "").strip()
    file = request.files.get("script")

    if not character_name:
        return jsonify({"error": "Please enter the role you are preparing."}), 400

    script_text = ""
    source_mode = "paste"

    if file and file.filename:
        source_mode = "upload"
        script_text = extract_script_text(file)

        if not script_text.strip() and not pasted_text:
            return jsonify({
                "error": "The formatted script could not be read cleanly.",
                "needs_paste": True,
                "message": "Please paste the script text to continue."
            }), 422

    if pasted_text:
        script_text = pasted_text
        source_mode = "paste"

    if not script_text.strip():
        return jsonify({"error": "No script text was provided."}), 400

    brain_data = {}
    try:
        brain_file = OUTPUT_DIR / "approved_brain_output.json"
        if brain_file.exists():
            brain_data = json.loads(brain_file.read_text(encoding="utf-8"))
    except Exception:
        pass

    log_usage("actor_prep_start", role=character_name, mode=source_mode)

    try:
        build_actor_prep_pdf(script_text, character_name, LATEST_ACTOR_PREP_PDF, brain_data=brain_data)
    except Exception as e:
        log_usage("actor_prep_complete", success=False, role=character_name, error="actor_prep_failed")
        return jsonify({"error": f"Actor preparation failed: {e}"}), 500

    if not LATEST_ACTOR_PREP_PDF.exists():
        log_usage("actor_prep_complete", success=False, role=character_name, error="actor_pdf_missing")
        return jsonify({"error": "Actor prep PDF was not created."}), 500

    log_usage("actor_prep_complete", success=True, role=character_name)

    return jsonify({
        "summary_note": f"Your actor preparation packet for {character_name} is ready.",
        "report_pdf": str(LATEST_ACTOR_PREP_PDF.name),
    })




@app.route("/actor-booked-pass", methods=["POST"])
@subscription_required
def actor_booked_pass():
    character_name = (request.form.get("character_name") or "").strip()
    pasted_text = (request.form.get("script_text") or "").strip()
    file = request.files.get("script")

    if not character_name:
        return jsonify({"error": "Please enter the role you are preparing."}), 400

    script_text = ""
    source_mode = "paste"

    if file and file.filename:
        source_mode = "upload"
        script_text = extract_script_text(file)

        if not script_text.strip() and not pasted_text:
            return jsonify({
                "error": "The formatted script could not be read cleanly.",
                "needs_paste": True,
                "message": "Please paste the script text to continue."
            }), 422

    if pasted_text:
        script_text = pasted_text
        source_mode = "paste"

    if not script_text.strip():
        return jsonify({"error": "No script text was provided."}), 400

    brain_data = {}
    try:
        brain_file = OUTPUT_DIR / "approved_brain_output.json"
        if brain_file.exists():
            brain_data = json.loads(brain_file.read_text(encoding="utf-8"))
    except Exception:
        pass

    log_usage("actor_booked_start", role=character_name, mode=source_mode)

    try:
        build_actor_booked_pdf(script_text, character_name, LATEST_ACTOR_BOOKED_PDF, brain_data=brain_data)
    except Exception as e:
        log_usage("actor_booked_complete", success=False, role=character_name, error="actor_booked_failed")
        return jsonify({"error": f"Booked role preparation failed: {e}"}), 500

    if not LATEST_ACTOR_BOOKED_PDF.exists():
        log_usage("actor_booked_complete", success=False, role=character_name, error="actor_booked_pdf_missing")
        return jsonify({"error": "Booked role PDF was not created."}), 500

    log_usage("actor_booked_complete", success=True, role=character_name)

    return jsonify({
        "summary_note": f"{character_name.title()} is ready for the set. Your full role preparation packet breaks down every speaking beat, scene by scene, with continuity notes and performance priorities built in.",
        "report_pdf": str(LATEST_ACTOR_BOOKED_PDF.name),
    })


@app.route("/output/latest_actor_booked_report.pdf")
def actor_booked_latest_pdf():
    if not LATEST_ACTOR_BOOKED_PDF.exists():
        abort(404)
    return send_file(LATEST_ACTOR_BOOKED_PDF, as_attachment=False)


@app.route("/download/latest_actor_booked_report.pdf")
def actor_booked_latest_download_pdf():
    if not LATEST_ACTOR_BOOKED_PDF.exists():
        abort(404)
    return send_file(LATEST_ACTOR_BOOKED_PDF, as_attachment=True)


@app.route("/output/latest_actor_prep_report.pdf")
def actor_prep_latest_pdf():
    if not LATEST_ACTOR_PREP_PDF.exists():
        abort(404)
    return send_file(LATEST_ACTOR_PREP_PDF, as_attachment=False)


@app.route("/download/latest_actor_prep_report.pdf")
def actor_prep_latest_download_pdf():
    if not LATEST_ACTOR_PREP_PDF.exists():
        abort(404)
    return send_file(LATEST_ACTOR_PREP_PDF, as_attachment=True)

# ===== ACTOR PREP ROUTES END =========================

# ===== FEEDBACK ROUTE START ==========================
@app.route("/feedback", methods=["POST"])
def submit_feedback():
    data = request.get_json(silent=True) or {}
    feedback_type = data.get("type", "").strip()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"ok": False, "error": "No message"}), 400

    feedback_file = OUTPUT_DIR / "feedback.txt"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] type={feedback_type or 'none'} | name={name or 'anon'} | email={email or 'none'} | {message}\n"

    with open(feedback_file, "a", encoding="utf-8") as f:
        f.write(line)

    return jsonify({"ok": True})
# ===== FEEDBACK ROUTE END ============================

@app.route("/generate-slide-options", methods=["POST"])
def generate_slide_options():
    import urllib.request as _urlreq

    data = request.get_json(silent=True) or {}
    slide_title = (data.get("slide_title") or "").strip()
    slide_body = (data.get("slide_body") or "").strip()
    user_prompt = (data.get("user_prompt") or "").strip()
    slide_number = int(data.get("slide_number") or 1)
    current_image_path = (data.get("current_image_path") or "").strip()
    current_image_url = (data.get("current_image_url") or "").strip()

    fal_key = os.environ.get("FAL_API_KEY", "")
    if not fal_key:
        return jsonify({"error": "Image generation not configured"}), 503

    brain_file = BASE_DIR / "approved_brain_output.json"
    brain = {}
    if brain_file.exists():
        try:
            brain = json.loads(brain_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    from deck_builder import build_image_prompt
    base = build_image_prompt(slide_title, brain)
    if user_prompt:
        base = base.replace(", 16:9 aspect ratio", f", {user_prompt}, 16:9 aspect ratio")

    variations = [
        base.replace(", 16:9 aspect ratio", ", wide establishing shot, epic scale, golden hour light, 16:9 aspect ratio"),
        base.replace(", 16:9 aspect ratio", ", dramatic close-up, intense emotion, shallow depth of field, 16:9 aspect ratio"),
    ]

    regen_dir = BASE_DIR / "generated_images" / "regen"
    regen_dir.mkdir(parents=True, exist_ok=True)

    options = []
    if current_image_path and current_image_path != "__none__":
        options.append({
            "option_id": "selected",
            "label": "Current Pick",
            "image_path": current_image_path,
            "image_url": current_image_url,
            "image_source": "fal_generated",
        })

    labels = ["Wide Shot", "Close-Up"]
    for i, prompt in enumerate(variations):
        safe_title = re.sub(r"[^a-z0-9_]", "_", slide_title.lower())[:30]
        save_path = regen_dir / f"{slide_number:02d}_{safe_title}_opt{i+1}.jpg"
        payload = json.dumps({
            "prompt": prompt,
            "image_size": "landscape_16_9",
            "num_inference_steps": 4,
            "num_images": 1,
            "enable_safety_checker": True,
        }).encode("utf-8")
        req = _urlreq.Request(
            "https://fal.run/fal-ai/flux/schnell",
            data=payload,
            headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with _urlreq.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            image_url = result["images"][0]["url"]
            _urlreq.urlretrieve(image_url, save_path)
            options.append({
                "option_id": f"opt_{i+1}",
                "label": labels[i],
                "image_path": str(save_path),
                "image_url": f"/project-file?path=generated_images/regen/{save_path.name}",
                "image_source": "fal_generated",
            })
        except Exception as e:
            print(f"⚠️ Option {i+1} generation failed: {e}")

    return jsonify({"options": options})


@app.route("/regenerate-slide-image", methods=["POST"])
def regenerate_slide_image():
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    data = request.get_json(silent=True) or {}
    slide_title = (data.get("slide_title") or "").strip()
    slide_body = (data.get("slide_body") or "").strip()
    user_prompt = (data.get("user_prompt") or "").strip()
    slide_number = int(data.get("slide_number") or 1)

    fal_key = os.environ.get("FAL_API_KEY", "")
    if not fal_key:
        return jsonify({"error": "Image generation not configured"}), 503

    brain_file = BASE_DIR / "approved_brain_output.json"
    brain = {}
    if brain_file.exists():
        try:
            brain = json.loads(brain_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    from deck_builder import build_image_prompt
    base_prompt = build_image_prompt(slide_title, brain)
    if user_prompt:
        base_prompt = base_prompt.replace(", 16:9 aspect ratio", f", {user_prompt}, 16:9 aspect ratio")

    payload = json.dumps({
        "prompt": base_prompt,
        "image_size": "landscape_16_9",
        "num_inference_steps": 4,
        "num_images": 1,
        "enable_safety_checker": True,
    }).encode("utf-8")

    req = _urlreq.Request(
        "https://fal.run/fal-ai/flux/schnell",
        data=payload,
        headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _urlreq.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        image_url = result["images"][0]["url"]

        regen_dir = BASE_DIR / "generated_images" / "regen"
        regen_dir.mkdir(parents=True, exist_ok=True)
        safe_title = re.sub(r"[^a-z0-9_]", "_", slide_title.lower())[:40]
        save_path = regen_dir / f"{slide_number:02d}_{safe_title}.jpg"
        _urlreq.urlretrieve(image_url, save_path)

        serve_url = f"/project-file?path=generated_images/regen/{save_path.name}"
        return jsonify({"image_url": serve_url, "image_path": str(save_path)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/contact", methods=["POST"])
def submit_contact():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    message = data.get("message", "").strip()

    if not message:
        return jsonify({"ok": False, "error": "No message"}), 400

    contact_file = OUTPUT_DIR / "contact.txt"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] name={name or 'anon'} | email={email or 'none'} | {message}\n"

    with open(contact_file, "a", encoding="utf-8") as f:
        f.write(line)

    return jsonify({"ok": True})

# ===== STARTUP CLEANUP START =========================
def _clear_stock_images_once():
    visuals_dir = BASE_DIR / "visuals"
    sentinel = visuals_dir / ".stock_cleared"
    if sentinel.exists():
        return
    if not visuals_dir.exists():
        return
    cleared = 0
    for child in visuals_dir.iterdir():
        if child.is_dir() and child.name != "user_uploaded":
            try:
                shutil.rmtree(child)
                cleared += 1
            except Exception as e:
                print(f"⚠️ Could not remove {child.name}: {e}")
    sentinel.touch()
    print(f"🧹 Stock images cleared on startup ({cleared} folders removed)")

_clear_stock_images_once()
# ===== STARTUP CLEANUP END ===========================

# ===== APP RUN START =================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7000))
    app.run(host="0.0.0.0", port=port)


# ===== APP RUN END ===================================
