"""
engine/report_renderer.py — HTML report renderer using Claude Design layout templates.
Reads data-slot HTML layout files, picks a random variant per page type,
injects AI data into slots, and returns a complete self-contained HTML page.
"""
from __future__ import annotations

import copy
import random
import re
from html import escape as esc
from pathlib import Path
from typing import Any

from lxml import etree
from lxml import html as lhtml

LAYOUTS_DIR = Path(__file__).parent / "static" / "layouts"

# (page_type_prefix, [variant_classes A→D])
_ACTOR_PREP_PAGES = [
    ("cov", ["cov-a", "cov-b", "cov-c", "cov-d"]),
    ("pb",  ["pb-a",  "pb-b",  "pb-c",  "pb-d"]),
    ("at",  ["at-a",  "at-b",  "at-c",  "at-d"]),
]

_SCRIPT_ANALYSIS_PAGES = [
    ("cov", ["cov-a", "cov-b", "cov-c", "cov-d"]),
    ("sa",  ["sa-a",  "sa-b",  "sa-c",  "sa-d"]),
    ("ci",  ["ci-a",  "ci-b",  "ci-c",  "ci-d"]),
    ("mk",  ["mk-a",  "mk-b",  "mk-c",  "mk-d"]),
    ("ag",  ["ag-a",  "ag-b",  "ag-c",  "ag-d"]),
    ("ai",  ["ai-a",  "ai-b",  "ai-c",  "ai-d"]),
    ("am",  ["am-a",  "am-b",  "am-c",  "am-d"]),
]

_ACTOR_BOOKED_PAGES = [
    ("cov", ["cov-a", "cov-b", "cov-c", "cov-d"]),
    ("ri",  ["ri-a",  "ri-b",  "ri-c",  "ri-d"]),
    ("dna", ["dna-a", "dna-b", "dna-c", "dna-d"]),
    ("bfm", ["bfm-a", "bfm-b", "bfm-c", "bfm-d"]),
]


# ── Layout file parsing ───────────────────────────────────────────────────────

def _parse_layout_file(path: Path) -> tuple[str, dict[str, Any]]:
    """Return (css_string, {variant_class: lxml_element})."""
    content = path.read_text(encoding="utf-8")
    doc = lhtml.fromstring(content)

    styles = doc.xpath("//style/text()")
    css = styles[0] if styles else ""

    pages: dict[str, Any] = {}
    for div in doc.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " page ")]'):
        classes = (div.get("class") or "").split()
        if "page" in classes:
            for cls in classes:
                if cls != "page":
                    pages[cls] = div

    return css, pages


# ── Slot injection ────────────────────────────────────────────────────────────

def _clear(el) -> None:
    el.text = None
    for child in list(el):
        el.remove(child)


def _fill_one_slot(el, slot_name: str, value: Any) -> None:
    if value is None:
        return
    _clear(el)

    if isinstance(value, list):
        items = [str(x).strip() for x in value if str(x).strip()]
        if not items:
            return
        if el.tag == "ul":
            for item in items:
                li = etree.SubElement(el, "li")
                li.text = item
        else:
            ul = etree.SubElement(el, "ul")
            ul.set("class", "bullet-list")
            for item in items:
                li = etree.SubElement(ul, "li")
                li.text = item

    elif slot_name.endswith("_img") and value:
        img = etree.SubElement(el, "img")
        img.set("src", str(value))
        img.set("style", "width:100%;height:100%;object-fit:cover;display:block")
        img.set("loading", "lazy")
        img.set("alt", "")

    else:
        el.text = str(value)


def _fill_slots(el, data: dict) -> None:
    for slotted in el.xpath(".//*[@data-slot]"):
        slot_name = slotted.get("data-slot")
        if slot_name in data:
            _fill_one_slot(slotted, slot_name, data[slot_name])


def _serialize(el) -> str:
    return lhtml.tostring(el, encoding="unicode", method="html")


# ── Page assembly ─────────────────────────────────────────────────────────────

def _assemble(css: str, page_htmls: list[str], title: str, back_url: str = "/") -> str:
    pages = "\n".join(page_htmls)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<style>
html, body {{ margin: 0; padding: 0; }}
body {{ background: #1a1a1a; padding: 40px 20px; }}
{css}
#reportBack {{
  position: fixed; top: 16px; right: 16px; z-index: 9999;
  background: rgba(0,0,0,0.65); border: 1px solid rgba(255,255,255,0.18);
  color: rgba(255,255,255,0.8); font-family: -apple-system, sans-serif;
  font-size: 12px; font-weight: 500; letter-spacing: 0.04em;
  padding: 7px 16px; border-radius: 999px; text-decoration: none;
  backdrop-filter: blur(8px); transition: background .15s;
}}
#reportBack:hover {{ background: rgba(0,0,0,0.88); color: #fff; }}
@media print {{
  #reportBack {{ display: none; }}
  body {{ background: white; padding: 0; }}
}}
</style>
</head>
<body>
<a id="reportBack" href="{esc(back_url)}">← Back</a>
{pages}
</body>
</html>"""


def _select_pages(pages: dict, page_spec: list) -> list[str]:
    """Pick one random variant per page type, fill nothing, return as elements."""
    selected = []
    for _prefix, variants in page_spec:
        available = [v for v in variants if v in pages]
        if not available:
            continue
        variant = random.choice(available)
        selected.append(copy.deepcopy(pages[variant]))
    return selected


# ── Slot data builders ────────────────────────────────────────────────────────

def _rel_map_to_list(rel_map: list) -> list:
    lines = []
    for row in rel_map or []:
        if isinstance(row, dict):
            parts = [str(row.get(k) or "").strip() for k in ("character", "dynamic", "function")]
            line = " — ".join(p for p in parts if p)
            if line:
                lines.append(line)
        elif isinstance(row, str) and row.strip():
            lines.append(row.strip())
    return lines


def _arc_slots(arc_list: list) -> dict:
    """Extract begin/mid/end from a flat arc list."""
    if not arc_list or len(arc_list) < 1:
        return {}
    out = {"arc_begin_name": arc_list[0], "arc_begin_text": arc_list[0]}
    if len(arc_list) >= 2:
        mid = arc_list[len(arc_list) // 2]
        out["arc_mid_name"] = mid
        out["arc_mid_text"] = mid
    if len(arc_list) >= 3:
        out["arc_end_name"] = arc_list[-1]
        out["arc_end_text"] = arc_list[-1]
    return out


def _comps_to_list(comps) -> list:
    if not comps:
        return []
    if isinstance(comps, list):
        return [str(c.get("title", c) if isinstance(c, dict) else c) for c in comps[:5]]
    return [str(comps)]


# ── Public render functions ───────────────────────────────────────────────────

def render_actor_prep_html(data: dict, back_url: str = "/") -> str:
    """
    Build a complete HTML Actor Prep Report from the AI JSON data.
    data: the actor_prep JSON (intelligence, brain_data fields merged).
    """
    layout_path = LAYOUTS_DIR / "actor-prep-layouts.html"
    css, pages = _parse_layout_file(layout_path)

    intel = data.get("intelligence") or {}
    arc_list = data.get("role_arc_map") or []

    slots: dict = {
        "doc_type_label": "ACTOR PREP REPORT",
        "powered_by": "EVOLUM STUDIO",
        "confidential": "CONFIDENTIAL",
        "character_name": (data.get("character_name") or "THE CHARACTER").upper(),
        "title": data.get("title") or "",
        "genre": (data.get("genre") or "").upper(),
        "tone": (data.get("tone") or "").upper(),
        "world": data.get("world") or "",
        "setting": data.get("world") or "",
        "beat_count": f"{data.get('beat_count', 0)} BEATS",
        "intelligence_summary": intel.get("summary") or "",
        "casting_read": intel.get("casting_read") or [],
        "danger_zones": intel.get("danger_zones") or [],
        "playable_tactics": intel.get("playable_tactics") or [],
        "emotional_triggers": intel.get("emotional_triggers") or [],
        "emotional_continuity": data.get("emotional_continuity") or [],
        "costume_behavior_clues": data.get("costume_behavior_clues") or [],
        "role_arc_map": arc_list,
        "pressure_ladder": data.get("pressure_ladder") or [],
        "memorization_beats": data.get("memorization_beats") or [],
        "relationship_leverage_map": _rel_map_to_list(data.get("relationship_leverage_map")),
        "set_ready_checklist": data.get("set_ready_checklist") or [],
        **_arc_slots(arc_list),
    }

    els = _select_pages(pages, _ACTOR_PREP_PAGES)
    for el in els:
        _fill_slots(el, slots)
    serialized = [_serialize(el) for el in els]

    char = data.get("character_name") or "Actor Prep"
    title_str = f"{char} — Actor Prep Report"
    return _assemble(css, serialized, title_str, back_url)


def render_script_analysis_html(data: dict, back_url: str = "/") -> str:
    """
    Build a complete HTML Script Analysis Report from the AI brain JSON data.
    data: the analysis/brain_data JSON.
    """
    layout_path = LAYOUTS_DIR / "script-analysis-layouts.html"
    css, pages = _parse_layout_file(layout_path)

    mkt = data.get("market_projections") or {}
    strength = data.get("strength_index") or 0
    arc_list = data.get("role_arc_map") or []
    comps = _comps_to_list(data.get("comparables"))

    slots: dict = {
        "doc_type_label": "SCRIPT ANALYSIS REPORT",
        "powered_by": "EVOLUM STUDIO · ANALYSIS ENGINE",
        "confidential": "CONFIDENTIAL · COVERAGE",
        "recommendation": "CONSIDER",
        "title": data.get("title") or "Untitled",
        "title_2": data.get("title") or "Untitled",
        "genre": (data.get("genre") or "").upper(),
        "tone": (data.get("tone") or "").upper(),
        "logline": data.get("logline") or "",
        "synopsis": data.get("synopsis") or data.get("summary") or "",
        "theme": data.get("theme") or "",
        "core_conflict": data.get("core_conflict") or "",
        "story_engine": data.get("story_engine") or "",
        "reversal": data.get("reversal") or "",
        "world": data.get("world") or data.get("setting") or "",
        "setting": data.get("setting") or data.get("world") or "",
        "time_frame": data.get("time_frame") or "",
        "executive_summary": data.get("executive_summary") or "",
        "strength_index": str(strength),
        "strength_label": _strength_label(strength),
        "lead_character": data.get("lead_character") or data.get("protagonist") or "",
        "protagonist_summary": data.get("protagonist_summary") or "",
        "character_leverage": data.get("character_leverage") or "",
        "comparables": comps,
        "comparables_inline": ", ".join(comps[:3]),
        "budget_range": mkt.get("budget_range") or data.get("budget_range") or "",
        "streamer_fit": mkt.get("streamer_fit") or "",
        "awards_lane": mkt.get("awards_lane") or "",
        "franchise_potential": mkt.get("franchise_potential") or "",
        "sales_hook": mkt.get("sales_hook") or "",
        "commercial_positioning": data.get("commercial_positioning") or "",
        "audience_profile": data.get("audience_profile") or "",
        "packaging_potential": data.get("packaging_potential") or "",
        "strengths": data.get("strengths") or [],
        "risks": data.get("risks") or [],
        "story_insights": data.get("story_insights") or [],
        "rewrite_priorities": data.get("rewrite_priorities") or [],
        "actor_objective": data.get("actor_objective") or "",
        "playable_tactics": data.get("playable_tactics") or [],
        "emotional_triggers": data.get("emotional_triggers") or [],
        "audition_danger_zones": data.get("audition_danger_zones") or [],
        "reader_chemistry_tips": data.get("reader_chemistry_tips") or [],
        "memorization_beats": data.get("memorization_beats") or [],
        "role_arc_map": arc_list,
        "pressure_ladder": data.get("pressure_ladder") or [],
        "emotional_continuity": data.get("emotional_continuity") or [],
        "costume_behavior_clues": data.get("costume_behavior_clues") or [],
        "set_ready_checklist": data.get("set_ready_checklist") or [],
        "relationship_leverage_map": _rel_map_to_list(data.get("relationship_leverage_map")),
        **_arc_slots(arc_list),
    }

    els = _select_pages(pages, _SCRIPT_ANALYSIS_PAGES)
    for el in els:
        _fill_slots(el, slots)
    serialized = [_serialize(el) for el in els]

    title_str = f"{data.get('title') or 'Script'} — Analysis Report"
    return _assemble(css, serialized, title_str, back_url)


def _strength_label(score: int | str) -> str:
    try:
        n = int(score)
    except (TypeError, ValueError):
        return ""
    if n >= 85:
        return "High commercial · awards viable"
    if n >= 70:
        return "Strong · development ready"
    if n >= 55:
        return "Solid · rewrites recommended"
    return "Developing · significant work needed"


def _booked_arc_slots(character_arcs: dict, character_name: str) -> dict:
    """Extract arc begin/mid/end from character_arcs dict keyed by name."""
    arc = None
    name_upper = (character_name or "").upper()
    for k, v in (character_arcs or {}).items():
        if isinstance(v, dict) and k.upper() == name_upper:
            arc = v
            break
    if not arc:
        # Fall back to first arc if name doesn't match
        for v in (character_arcs or {}).values():
            if isinstance(v, dict):
                arc = v
                break
    if not arc:
        return {}
    return {
        "arc_begin_name": "BEGINS",
        "arc_begin_text": arc.get("begin") or arc.get("start") or "",
        "arc_mid_name": "TRANSFORMS",
        "arc_mid_text": arc.get("transform") or arc.get("mid") or arc.get("middle") or "",
        "arc_end_name": "ENDS",
        "arc_end_text": arc.get("end") or arc.get("resolution") or "",
    }


def _beat_groups_to_list(groups) -> list:
    if not groups:
        return []
    lines = []
    for g in groups:
        if isinstance(g, dict):
            bt = g.get("beat_type", "")
            count = g.get("count", 0)
            coaching = g.get("coaching", "")
            line = f"{bt} ({count}): {coaching}" if coaching else f"{bt} ({count})"
            lines.append(line)
        elif isinstance(g, str) and g.strip():
            lines.append(g.strip())
    return lines


def render_actor_booked_html(data: dict, back_url: str = "/") -> str:
    """Build a complete HTML Actor Booked Report from the AI JSON data."""
    layout_path = LAYOUTS_DIR / "actor-booked-layouts.html"
    css, pages = _parse_layout_file(layout_path)

    intel = data.get("intelligence") or {}
    char_name = data.get("character_name") or "THE CHARACTER"
    beat_count = data.get("beat_count", 0)
    scene_count = data.get("scene_count", 0)

    slots: dict = {
        "doc_type_label": "BOOKED ROLE REPORT",
        "report_date": "PRINCIPAL PHOTOGRAPHY",
        "confidential": "CONFIDENTIAL · EVOLUM STUDIO",
        "role_label": "THE ROLE",
        "page_number": "",
        "character_name": char_name.upper(),
        "title": data.get("title") or "",
        "genre": (data.get("genre") or "").upper(),
        "tone": (data.get("tone") or "").upper(),
        "world": data.get("world") or "",
        "beat_count": f"{beat_count} BEATS",
        "scene_count": f"{scene_count} SCENES",
        "intelligence_summary": intel.get("summary") or "",
        "booked_continuity": intel.get("booked_continuity") or [],
        "scene_priorities": intel.get("scene_priorities") or [],
        "emotional_triggers": intel.get("emotional_triggers") or [],
        "look_presence": intel.get("look_presence") or [],
        "emotional_continuity": data.get("emotional_continuity") or [],
        "costume_behavior_clues": data.get("costume_behavior_clues") or [],
        "relationship_leverage_map": _rel_map_to_list(data.get("relationship_leverage_map")),
        "beat_groups": _beat_groups_to_list(data.get("beat_groups")),
        "set_ready_checklist": data.get("set_ready_checklist") or [],
        **_booked_arc_slots(data.get("character_arcs") or {}, char_name),
    }

    els = _select_pages(pages, _ACTOR_BOOKED_PAGES)
    for el in els:
        _fill_slots(el, slots)
    serialized = [_serialize(el) for el in els]

    title_str = f"{char_name} — Booked Role Report"
    return _assemble(css, serialized, title_str, back_url)
