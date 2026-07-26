from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import simpleSplit, ImageReader
from reportlab.pdfgen import canvas

# ── PATH CONSTANTS ────────────────────────────────────────────────────────────

_BASE_DIR = Path(__file__).resolve().parent
_OUTPUT_DIR = _BASE_DIR / "visuals" / "output"  # persistent disk mount
_LATEST_PPTX = _OUTPUT_DIR / "latest.pptx"
_LATEST_PDF = _OUTPUT_DIR / "latest.pdf"


# ── DECK UTILITY HELPERS ──────────────────────────────────────────────────────

def normalize_project_relative_path(raw_path: str) -> str:
    cleaned = str(raw_path or "").strip().replace("\\", "/")
    if not cleaned:
        return ""
    prefixes = [
        str(_BASE_DIR).replace("\\", "/").rstrip("/") + "/",
        "/opt/render/project/src/",
        "opt/render/project/src/",
    ]
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned.lstrip("/")


def project_file_url_for_path(raw_path: str) -> str:
    rel = normalize_project_relative_path(raw_path)
    if not rel:
        return ""
    return "/project-file?path=" + quote(rel)


def normalize_manifest_image_options(options) -> list:
    normalized = []
    if not isinstance(options, list):
        return normalized
    for item in options:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        entry["image_path"] = normalize_project_relative_path(entry.get("image_path", "") or "")
        if not entry.get("image_url"):
            entry["image_url"] = project_file_url_for_path(entry.get("image_path", "") or "")
        normalized.append(entry)
    return normalized


def newest_generated_file(ext: str, uid: str = ""):
    excluded = {_LATEST_PPTX.name, _LATEST_PDF.name}
    uid_prefix = f"{uid}_" if uid else ""
    pattern = f"{uid_prefix}pitch_deck_v*{ext}"
    files = [p for p in _OUTPUT_DIR.glob(pattern) if p.name not in excluded]
    if not files and uid:
        # fallback: any pitch_deck file (handles builds before uid was threaded through)
        files = [p for p in _OUTPUT_DIR.glob(f"pitch_deck_v*{ext}") if p.name not in excluded]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _next_labeled_pptx(label: str):
    """Return the most recently written pitch_deck_{label}_v*.pptx file."""
    files = list(_OUTPUT_DIR.glob(f"pitch_deck_{label}_v*.pptx"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def publish_latest_outputs(pptx_source, pdf_source) -> None:
    if pptx_source and pptx_source.exists():
        shutil.copy2(pptx_source, _LATEST_PPTX)
    if pdf_source and pdf_source.exists():
        shutil.copy2(pdf_source, _LATEST_PDF)


def rebuild_refined_deck(slides: list, latest_manifest_path=None, label: str = "", user_id: str = "") -> dict:
    """Build a new deck from refined slide data. Returns {'deck': name} or {'error': msg}."""
    if not slides or not isinstance(slides, list):
        return {"error": "No slide data provided."}

    try:
        slide_plan_payload = {
            "title": slides[0].get("title", "Refined Deck") if slides else "Refined Deck",
            "slides": [
                {
                    "title": str(s.get("title", "") or "").strip(),
                    "body": str(s.get("body", "") or "").strip(),
                    "layout": str(s.get("layout", "") or "text").strip(),
                    "stage": str(s.get("stage", "") or "refine").strip(),
                    "subtitle": str(s.get("subtitle", "") or "").strip(),
                    "image_path": normalize_project_relative_path(s.get("image_path", "") or ""),
                    "image_name": str(s.get("image_name", "") or "").strip(),
                    "image_url": str(s.get("image_url", "") or "").strip(),
                    "image_source": str(s.get("image_source", "") or "").strip(),
                    "image_options": normalize_manifest_image_options(s.get("image_options", [])),
                    "selected_option_id": str(s.get("selected_option_id", "") or "").strip(),
                    "person_name": str(s.get("person_name", "") or "").strip(),
                    "person_role": str(s.get("person_role", "") or "").strip(),
                    "person_credits_line": str(s.get("person_credits_line", "") or "").strip(),
                    "person_photo_url": str(s.get("person_photo_url", "") or "").strip(),
                }
                for s in slides
            ],
            "slide_count": len(slides),
        }

        slide_plan_path = _BASE_DIR / "slide_plan.json"
        temp_path = _BASE_DIR / "slide_plan.tmp.json"
        temp_path.write_text(json.dumps(slide_plan_payload, indent=2), encoding="utf-8")
        temp_path.replace(slide_plan_path)

        manifest_payload = [
            {
                "slide_number": i,
                "title": str(s.get("title", "") or "").strip(),
                "body": str(s.get("body", "") or "").strip(),
                "layout": str(s.get("layout", "") or "").strip(),
                "stage": str(s.get("stage", "") or "").strip(),
                "image_path": normalize_project_relative_path(s.get("image_path", "") or ""),
                "image_name": str(s.get("image_name", "") or "").strip(),
                "image_url": str(s.get("image_url", "") or "").strip(),
                "image_source": str(s.get("image_source", "") or "").strip(),
                "image_options": normalize_manifest_image_options(s.get("image_options", [])),
                "selected_option_id": str(s.get("selected_option_id", "") or "").strip(),
                "person_name": str(s.get("person_name", "") or "").strip(),
                "person_role": str(s.get("person_role", "") or "").strip(),
                "person_credits_line": str(s.get("person_credits_line", "") or "").strip(),
                "person_photo_url": str(s.get("person_photo_url", "") or "").strip(),
            }
            for i, s in enumerate(slides, start=1)
        ]

        if latest_manifest_path:
            manifest_out = Path(latest_manifest_path)
        elif user_id:
            prefix = f"{user_id}_"
            name = f"{prefix}latest_deck_manifest_{label}.json" if label else f"{prefix}latest_deck_manifest.json"
            manifest_out = _OUTPUT_DIR / name
        else:
            manifest_out = _OUTPUT_DIR / "latest_deck_manifest.json"
        manifest_out.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")

        cmd = ["python3", str(_BASE_DIR / "deck_builder.py"), str(slide_plan_path)]
        if label:
            cmd += ["--label", label]
        if user_id:
            cmd += ["--uid", user_id]
        env = os.environ.copy()
        if user_id:
            env["EVOLUM_SESSION_ID"] = user_id
        subprocess.run(cmd, cwd=str(_BASE_DIR), env=env, check=True)

        fresh_pptx = newest_generated_file(".pptx") if not label else _next_labeled_pptx(label)
        fresh_pdf = newest_generated_file(".pdf") if not label else None
        publish_latest_outputs(fresh_pptx, fresh_pdf)

        return {"deck": fresh_pptx.name if fresh_pptx else _LATEST_PPTX.name}

    except Exception as e:
        return {"error": f"Refine rebuild failed: {e}"}


# ── SHARED DATA STRUCTURES ────────────────────────────────────────────────────

@dataclass
class BeatEntry:
    reference: str
    scene_heading: str
    cue_line: str
    dialogue: str
    beat: str
    subtext: str
    playable_note: str
    category: str = "TACTICAL"


# ── AI HELPERS (OPTIONAL / SAFE FALLBACKS) ───────────────────────────────────

def _call_text_ai(system_prompt: str, user_prompt: str, max_tokens: int = 350) -> str:
    """Best-effort text AI helper using Claude Haiku."""
    api_key = None  # API removed — deterministic engine only
    if not api_key:
        return ""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return (resp.content[0].text or "").strip()
    except Exception:
        return ""


def _methodology_lines() -> List[str]:
    return [
        "Uploaded script or sides supplied by the user.",
        "Developum AI extraction and scene/character parsing.",
        "Manifest / brain-derived story fields already available in the system.",
        "AI editorial assistance for concise summaries, framing, and report language when available.",
        "Public market-reference metadata only when already supplied to the system.",
    ]


# ── SHARED SCRIPT PARSING UTILITIES ──────────────────────────────────────────

def normalize_character_name(name: str) -> str:
    name = (name or "").strip().upper()
    name = re.sub(r"\s+", " ", name)
    return name


def _clean_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\x0c", "\n")
    text = text.replace("\ufffe", " ")
    # common transfer / OCR junk
    text = re.sub(r'\d{4,}\s*-\s*\w+ \d{1,2},\s*\d{4}\s*\d{1,2}:\d{2}\s*[AP]M\s*-?\s*', '', text)
    text = re.sub(r'([A-Z]{2,6}-){3,}[A-Z]{2,6}', '', text)
    text = re.sub(r'\b(TYPE|FILTER|LENGTH|RESOURCES|CONTENTS)\b(?=\s|$)', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def _is_scene_heading(line: str) -> bool:
    s = line.strip().upper()
    # Strip leading scene numbers like "1.", "4A.", "12B." before checking
    s = re.sub(r'^\d+[A-Z]?\.\s*', '', s)
    return (s.startswith("INT.") or s.startswith("EXT.") or
            s.startswith("INT ") or s.startswith("EXT ") or
            s.startswith("INT/EXT") or s.startswith("I/E "))


def _is_parenthetical(line: str) -> bool:
    s = line.strip()
    return s.startswith("(") and s.endswith(")")


def _looks_like_character_cue(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 40 or _is_scene_heading(s) or s.startswith("("):
        return False
    letters = [ch for ch in s if ch.isalpha()]
    if not letters:
        return False
    upper_ratio = sum(1 for ch in letters if ch.isupper()) / max(1, len(letters))
    return upper_ratio > 0.85


def _normalize_cue(line: str) -> str:
    s = line.strip().upper()
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _estimate_page_no(global_line_index: int, lines_per_page: int = 55) -> int:
    return max(1, (global_line_index // lines_per_page) + 1)


def _infer_beat(dialogue: str, scene_heading: str) -> Tuple[str, str, str, str]:
    """Returns (beat_name, subtext, playable_note, category)."""
    lower = dialogue.strip().lower()

    # --- EMOTIONAL beats ---
    if any(k in lower for k in ["i'm sorry", "i am sorry", "forgive", "i never told", "truth is",
                                  "i have to tell", "i need you to know", "i lied", "the truth is",
                                  "i should have", "i was afraid", "i was wrong"]):
        return (
            "Reveal Something True",
            "The character is dropping a guard they've been holding the whole scene.",
            "Let the vulnerability come from the body, not just the words.",
            "EMOTIONAL",
        )
    if any(k in lower for k in ["please", "i need you", "i need this", "help me", "you have to",
                                  "you've got to", "i'm begging", "don't leave", "don't go",
                                  "i can't do this without"]):
        return (
            "Make a Plea",
            "The character is asking from a place of genuine need, not strategy.",
            "Earn this beat. The ask only lands when the stakes are completely visible.",
            "EMOTIONAL",
        )
    if any(k in lower for k in ["it's okay", "it'll be", "i'm here", "you're safe", "don't worry",
                                  "i've got you", "everything's going to be", "nothing's going to happen",
                                  "i'll take care", "you're going to be fine"]):
        return (
            "Offer Comfort",
            "The character is softening — choosing connection over self-protection.",
            "Let the care be specific. Generic comfort is just noise. Find the real thing they're soothing.",
            "EMOTIONAL",
        )
    if any(k in lower for k in ["i am", "i know who i am", "this is who", "i've always been",
                                  "i believe", "i stand by", "my whole life", "i was born",
                                  "this is what i do", "i'm not that", "i'm a", "that's who i am"]):
        return (
            "Assert Identity",
            "The character is claiming who they are — often under pressure to be something else.",
            "Don't perform it. Let the certainty land like a fact, not a speech.",
            "EMOTIONAL",
        )

    # --- RELATIONAL beats ---
    if any(k in lower for k in ["what if", "hear me out", "let's say", "suppose",
                                  "what would it take", "i'll give you", "how about",
                                  "deal", "i can offer", "let's make a deal", "i propose"]):
        return (
            "Negotiate",
            "The character is in problem-solving mode — offering terms, testing possibilities.",
            "Stay two steps ahead. Every offer has something held back.",
            "RELATIONAL",
        )
    if any(k in lower for k in ["that's not true", "you're wrong", "i don't believe",
                                  "that's a lie", "you never", "that's ridiculous",
                                  "that's not what", "you said", "you told me"]):
        return (
            "Challenge",
            "The character is pushing back and forcing the other person to justify themselves.",
            "Make it feel like a real refusal, not a reaction. The character chose this.",
            "RELATIONAL",
        )

    # --- CONCEALMENT beats ---
    if any(k in lower for k in ["nothing", "nothing's wrong", "never happened", "forget it",
                                  "nobody needs to know", "doesn't matter", "i don't know what you're talking",
                                  "you imagined", "you're confused", "that never", "drop it",
                                  "leave it alone", "it's nothing", "i don't want to talk about"]):
        return (
            "Protect a Secret",
            "The character is concealing something — from the other person or from themselves.",
            "Play what's being hidden, not the deflection. The audience should feel the weight behind the nothing.",
            "CONCEALMENT",
        )

    # --- TACTICAL beats ---
    if any(k in lower for k in ["be careful", "watch yourself", "you don't want to",
                                  "last chance", "i'm warning you", "don't make me",
                                  "you'll regret", "think about what you're doing",
                                  "i suggest you", "tread carefully"]):
        return (
            "Deliver a Warning",
            "The character is making consequences clear without fully committing to them yet.",
            "Keep it quiet. The most effective warnings land like facts, not threats.",
            "TACTICAL",
        )
    if any(k in lower for k in ["kill", "hurt you", "destroy", "finish you", "end this",
                                  "going to get you", "going to make you", "you'll pay",
                                  "punishment", "i'll make sure", "you're dead", "bash your"]):
        return (
            "Express Threat",
            "The character has crossed from warning into open aggression.",
            "Don't rush to volume. The menace lives in the specificity, not the size.",
            "TACTICAL",
        )
    if any(k in lower for k in ["who", "what", "where", "why", "how", "tell me",
                                  "i need to know", "what happened", "where were you",
                                  "explain", "what do you mean"]):
        return (
            "Pressure for Information",
            "The character is trying to get clarity while still keeping leverage.",
            "Ask like it matters. Curiosity is not enough here.",
            "TACTICAL",
        )
    if any(k in lower for k in ["calm down", "sit down", "listen", "hold on", "wait",
                                  "easy", "relax", "everybody", "settle", "take a breath",
                                  "let me finish", "let me explain"]):
        return (
            "Control the Room",
            "The character is slowing the chaos down and forcing the scene back under control.",
            "Use calm authority. The power is in the certainty, not the volume.",
            "TACTICAL",
        )
    if any(k in lower for k in ["don't", "do not", "can't", "cannot", "won't", "stop",
                                  "not going to", "never again", "that's enough", "enough"]):
        return (
            "Set a Boundary",
            "The character is drawing a line and making the other person feel the limit.",
            "Keep it clear and definite. This beat lands when the line feels real.",
            "TACTICAL",
        )
    if scene_heading and any(k in scene_heading.upper() for k in
                              ["OFFICE", "INTERROGATION", "BAR", "LOUNGE", "MEETING"]):
        return (
            "Apply Pressure",
            "The character is reading the other person and leaning in for leverage.",
            "Push with intelligence. Let the pressure come from focus, not force.",
            "TACTICAL",
        )

    # --- OBSERVATIONAL beats ---
    if any(k in lower for k in ["that means", "which means", "those are", "this is",
                                  "that's a", "it looks like", "notice", "clearly",
                                  "something's", "this means", "if.*is happening",
                                  "connect", "map", "symbol", "route", "coup", "planted",
                                  "that has to be", "that must be", "that would be",
                                  "is moving", "is looking for", "are looking for",
                                  "you know about", "so the entire", "the entire"]):
        return (
            "Read the Situation",
            "The character is processing information and forming a picture. Their intelligence is the weapon here.",
            "Let the thinking show. The audience should feel them assembling the truth in real time.",
            "OBSERVATIONAL",
        )
    if any(k in lower for k in ["i know", "i run", "i've seen", "i've heard", "i've been",
                                  "you should know", "here's what", "here's the thing",
                                  "two things", "one thing", "the thing is",
                                  "in this castle", "in this place", "around here",
                                  "dozens", "hundreds", "everyone knows", "nobody knows",
                                  "happens every", "every year", "days away", "two days",
                                  "we bring", "bring news", "stay with the"]):
        return (
            "Share Intelligence",
            "The character has information the other person needs. They control the room through what they know.",
            "Don't over-explain. Drop the intel with the confidence of someone who's been watching for a long time.",
            "OBSERVATIONAL",
        )
    if any(k in lower for k in ["didn't you", "isn't it", "wasn't it", "aren't you",
                                  "i think", "probably", "i'd guess", "my guess",
                                  "look at it this way", "congratulations", "at least",
                                  "you're now", "welcome to", "interesting", "fascinating",
                                  "look festive", "look busy", "carry something"]):
        return (
            "Test and Probe",
            "The character is reading the other person — using wit or indirect questions to surface a reaction.",
            "Stay light. The probe only works if the other person doesn't feel it coming.",
            "RELATIONAL",
        )
    if any(k in lower for k in ["just stay", "just keep", "just move", "time to go",
                                  "we have been", "they are gaining", "they are chasing",
                                  "we've been discovered", "run", "move fast", "better move",
                                  "stay on the", "just carry", "bolt", "go go", "get out",
                                  "left!", "right!", "down!", "up!", "jump!", "now!"]):
        return (
            "Navigate Danger",
            "The character is executing under pressure — managing an escape, a pursuit, or a critical real-time decision.",
            "These beats are instinct, not strategy. Stay in the body. Thought slows the scene down.",
            "TACTICAL",
        )

    # --- TRANSITIONAL beats ---
    if any(k in lower for k in ["good", "okay", "alright", "cool", "fine", "right",
                                  "understood", "got it", "move on", "let's move", "fair enough"]):
        return (
            "Reset and Move Forward",
            "The character absorbs the moment and redirects the energy instead of sitting in it.",
            "Treat it like a pivot, not relief.",
            "TRANSITIONAL",
        )

    return (
        "Hold Authority",
        "The character is managing the scene from a position of control.",
        "Stay grounded and specific. Quiet command usually wins this beat.",
        "TACTICAL",
    )


def extract_beats(script_text: str, character_name: str) -> List[BeatEntry]:
    script_text = _clean_text(script_text)
    lines = script_text.split("\n")
    target = normalize_character_name(character_name)

    beats: List[BeatEntry] = []
    current_scene = "SCENE NOT DETECTED"

    i = 0
    global_line_index = 0
    while i < len(lines):
        line = lines[i].strip()

        if _is_scene_heading(line):
            current_scene = line

        if _looks_like_character_cue(line):
            cue = _normalize_cue(line)
            if cue == target:
                page_no = _estimate_page_no(global_line_index)
                j = i + 1
                dialogue_lines: List[str] = []

                while j < len(lines):
                    nxt = lines[j].strip()
                    if not nxt:
                        if dialogue_lines:
                            break
                        j += 1
                        continue
                    if _is_scene_heading(nxt) or (_looks_like_character_cue(nxt) and not _is_parenthetical(nxt)):
                        break
                    if not _is_parenthetical(nxt):
                        dialogue_lines.append(nxt)
                    j += 1

                dialogue = " ".join(dialogue_lines).strip()
                dialogue = re.sub(r'\s{2,}', ' ', dialogue)
                if dialogue:
                    beat, subtext, playable, category = _infer_beat(dialogue, current_scene)
                    beats.append(
                        BeatEntry(
                            reference=f"Page {page_no}",
                            scene_heading=current_scene,
                            cue_line=line,
                            dialogue=dialogue,
                            beat=beat,
                            subtext=subtext,
                            playable_note=playable,
                            category=category,
                        )
                    )
                i = max(i + 1, j)
                global_line_index = i
                continue

        i += 1
        global_line_index += 1

    return beats


# ── FRIENDLIER CUSTOMER-FACING LANGUAGE ──────────────────────────────────────

_FRIENDLY_BEAT_TITLES: Dict[str, List[str]] = {
    "Reveal Something True":   ["Drop the Guard", "Let It Out", "Tell the Truth"],
    "Make a Plea":             ["Ask from Need", "Reach Out", "The Real Ask"],
    "Offer Comfort":           ["Steady the Other", "Hold Space", "Be Present"],
    "Assert Identity":         ["Stand Your Ground", "Claim Your Space", "This Is Who I Am"],
    "Negotiate":               ["Find the Deal", "Make the Offer", "Work the Room"],
    "Challenge":               ["Push Back", "Refuse the Reality", "Hold the Line"],
    "Protect a Secret":        ["Cover the Ground", "Deflect and Hold", "Nothing to See"],
    "Deliver a Warning":       ["Make It Clear", "Last Warning", "State the Consequence"],
    "Express Threat":          ["Show the Edge", "Let Them Feel It", "Full Menace"],
    "Pressure for Information":["Push for Answers", "Get the Truth", "Lean In for Clarity"],
    "Control the Room":        ["Take Control", "Steady the Room", "Own the Moment"],
    "Set a Boundary":          ["Draw the Line", "Hold Your Ground", "Make the Limit Clear"],
    "Apply Pressure":          ["Turn Up the Pressure", "Lean In", "Press the Point"],
    "Read the Situation":      ["Piece It Together", "See What's There", "Work the Picture"],
    "Share Intelligence":      ["Drop the Intel", "Show What You Know", "Brief the Room"],
    "Test and Probe":          ["Read the Reaction", "Feel Them Out", "Try the Line"],
    "Navigate Danger":         ["Execute Now", "Make the Move", "Stay in Motion"],
    "Reset and Move Forward":  ["Shift the Energy", "Reset and Move On", "Pivot Cleanly"],
    "Hold Authority":          ["Stay in Command", "Lead Quietly", "Keep Control"],
}


def _friendly_beat_title(beat: str, index: int) -> str:
    options = _FRIENDLY_BEAT_TITLES.get(beat, [beat])
    return options[(index - 1) % len(options)]


_GROUP_COACHING: Dict[str, str] = {
    "Reveal Something True":    "This is the role's most exposed beat. What gets revealed here should visibly cost the character. Find the moment the guard actually drops — it's in the body, not the words.",
    "Make a Plea":              "The character is operating without armor. Earn the need. If the stakes aren't visible before the ask, the plea reads as manipulation, not desperation.",
    "Offer Comfort":            "The character is choosing someone else over their own self-protection. Play what they're giving up to give this. That's where the scene lives.",
    "Assert Identity":          "These beats are declarations under pressure. Don't let them become speeches. The certainty should land like a closed door, not an open argument.",
    "Negotiate":                "The character is always thinking two moves ahead. Every offer conceals what they're actually protecting. Find the thing they won't give, and play from there.",
    "Challenge":                "The character refuses to accept the other person's version of reality. Anchor the refusal — this was a choice, not a reaction.",
    "Protect a Secret":         "The most textured beats in the role. Play what's underneath the deflection — the weight of what can't be said is what the audience reads. Let it be effortful.",
    "Deliver a Warning":        "The most effective warnings are stated like facts. Strip the emotion out. The consequence is real — say it like something that's already decided.",
    "Express Threat":           "Don't go to volume. The menace lives in specificity. The character knows exactly what they're capable of and wants the other person to feel that certainty.",
    "Pressure for Information": "The character isn't just asking — they're tracking what the other person gives away with each answer. Play the listening as much as the questioning.",
    "Control the Room":         "Calm is the weapon here. The character is slowing the scene down on purpose. Every steady breath is an assertion of power.",
    "Set a Boundary":           "Play the clarity, not the anger. The line is already drawn. The beat is making the other person feel where it is.",
    "Apply Pressure":           "The character is leaning in with a read on the other person. Intelligence drives this beat, not force. Let the pressure be precise.",
    "Read the Situation":       "The character is assembling a picture in real time. Intelligence is the weapon. Let the audience watch the pieces connect.",
    "Share Intelligence":       "The character controls through what they know. Each detail shared is a deliberate choice about what to reveal and when.",
    "Test and Probe":           "This beat is a read. The character is listening for something in the response. The probe only works if it doesn't feel like one.",
    "Navigate Danger":          "These are instinct beats. The character acts before they think. Stay in the body — deliberation kills the urgency of these scenes.",
    "Reset and Move Forward":   "This is a pivot beat. The character absorbs what just happened and redirects — it should feel like a choice, not a collapse.",
    "Hold Authority":           "The baseline state of this role. The danger is flatness — keep it textured. Authority that never wavers reads as bored, not powerful.",
}
_DEFAULT_GROUP_COACHING = "Protect the role's internal logic on these beats. Find the specific thing the character wants in each scene and let that drive the line."


def group_beats_by_type(beats: List[BeatEntry]) -> List[dict]:
    """Groups beats by type. Returns list ordered by frequency, each entry has coaching + up to 3 sample beats."""
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for b in beats:
        groups[b.beat].append(b)

    result = []
    for beat_type, group in sorted(groups.items(), key=lambda x: -len(x[1])):
        pages = sorted(set(b.reference for b in group), key=lambda r: int(re.sub(r'\D', '', r) or 0))
        samples = group[:3]
        result.append({
            "beat_type": beat_type,
            "label": _friendly_beat_title(beat_type, 1),
            "coaching": _GROUP_COACHING.get(beat_type, _DEFAULT_GROUP_COACHING),
            "count": len(group),
            "pages": pages,
            "samples": samples,
        })
    return result


# ── SHARED PDF DRAWING UTILITIES ──────────────────────────────────────────────

def _split_lines(pdf: canvas.Canvas, text: str, font_name: str, font_size: int, max_width: int) -> List[str]:
    return simpleSplit(text or "", font_name, font_size, max_width)


def _draw_lines(pdf: canvas.Canvas, lines: List[str], x: float, y: float, leading: int, font_name: str, font_size: int, color=colors.white) -> float:
    pdf.setFont(font_name, font_size)
    pdf.setFillColor(color)
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def _footer(pdf: canvas.Canvas, width: float, page_no: int) -> None:
    pdf.setStrokeColor(colors.HexColor("#2b2b2b"))
    pdf.line(42, 28, width - 42, 28)
    pdf.setFillColor(colors.HexColor("#8f8f8f"))
    pdf.setFont("Helvetica", 8)
    pdf.drawString(42, 16, "Powered by Developum AI Engine")
    pdf.drawRightString(width - 42, 16, f"Page {page_no}")


def _new_page(pdf: canvas.Canvas, width: float, height: float, page_no: int, bg_color) -> float:
    _footer(pdf, width, page_no)
    pdf.showPage()
    pdf.setFillColor(bg_color)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    return height - 56


def _ensure_space(pdf: canvas.Canvas, width: float, height: float, y: float, needed: float, page_no: int, bg_color) -> Tuple[float, int]:
    if y - needed < 48:
        y = _new_page(pdf, width, height, page_no, bg_color)
        page_no += 1
        pdf.setFillColor(colors.white)
    return y, page_no


def _safe(val, fallback: str = "") -> str:
    if val is None:
        return fallback
    if isinstance(val, list):
        return ", ".join(str(v) for v in val if str(v).strip())
    return str(val).strip() or fallback


def _clean_characters(chars: List) -> List[str]:
    bad = {"TYPE", "FILTER", "LENGTH", "RESOURCES", "CONTENTS"}
    out = []
    for c in chars or []:
        s = str(c).strip()
        if not s or s.upper() in bad:
            continue
        if len(s) > 40:
            continue
        out.append(s)
    return out


class _PDFCtx:
    def __init__(self, pdf: canvas.Canvas, width: float, height: float, left: float,
                 usable_width: float, charcoal, gold, blue, white, muted, soft, panel):
        self.pdf = pdf
        self.width = width
        self.height = height
        self.left = left
        self.uw = usable_width
        self.charcoal = charcoal
        self.gold = gold
        self.blue = blue
        self.white = white
        self.muted = muted
        self.soft = soft
        self.panel = panel
        self.y = height - 56
        self.page_no = 2

    def new_page(self):
        self.y = _new_page(self.pdf, self.width, self.height, self.page_no, self.charcoal)
        self.page_no += 1
        self.pdf.setFillColor(self.white)

    def section_header(self, title: str, subtitle: str = ""):
        self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, self.y, 44, self.page_no, self.charcoal)
        self.pdf.setFillColor(self.gold)
        self.pdf.setFont("Helvetica-Bold", 15)
        self.pdf.drawString(self.left, self.y, title)
        self.y -= 18
        if subtitle:
            self.y = _draw_lines(self.pdf,
                                 _split_lines(self.pdf, subtitle, "Helvetica", 10, self.uw),
                                 self.left, self.y, 12, "Helvetica", 10, self.soft)
            self.y -= 6

    def text_block(self, text: str, color=None, font_name: str = "Helvetica", font_size: int = 11, leading: int = 14, inset: int = 0):
        color = color if color is not None else self.muted
        lines = _split_lines(self.pdf, text, font_name, font_size, self.uw - inset)
        self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, self.y,
                                             max(40, len(lines) * leading + 10), self.page_no, self.charcoal)
        self.y = _draw_lines(self.pdf, lines, self.left + inset, self.y, leading, font_name, font_size, color)

    def bullet_list(self, items: List[str], bullet_color=None):
        bc = bullet_color or self.blue
        for item in items:
            lines = _split_lines(self.pdf, item, "Helvetica", 10, self.uw - 26)
            self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, self.y,
                                                 len(lines) * 13 + 14, self.page_no, self.charcoal)
            self.pdf.setFillColor(bc)
            self.pdf.setFont("Helvetica-Bold", 12)
            self.pdf.drawString(self.left, self.y, "•")
            self.y = _draw_lines(self.pdf, lines, self.left + 14, self.y, 13, "Helvetica", 10, self.muted)
            self.y -= 3

    def chip_row(self, items: List[str], chip_color=None):
        color = chip_color or self.blue
        x = self.left
        y = self.y
        max_h = 22
        for item in items:
            label = str(item).strip()
            if not label:
                continue
            w = min(max(54, 8 + len(label) * 5.6), self.uw)
            if x + w > self.left + self.uw:
                x = self.left
                y -= max_h + 6
                self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, y, max_h + 10, self.page_no, self.charcoal)
            self.pdf.setFillColor(self.panel)
            self.pdf.roundRect(x, y - 16, w, max_h, 8, stroke=0, fill=1)
            self.pdf.setStrokeColor(color)
            self.pdf.roundRect(x, y - 16, w, max_h, 8, stroke=1, fill=0)
            self.pdf.setFillColor(color)
            self.pdf.setFont("Helvetica-Bold", 9)
            self.pdf.drawString(x + 8, y - 4, label[:26])
            x += w + 6
        self.y = y - max_h - 8

    def info_row(self, label: str, value: str):
        lines = simpleSplit(str(value or "-"), "Helvetica", 10.5, self.uw - 120)
        self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, self.y,
                                             len(lines) * 14 + 10, self.page_no, self.charcoal)
        self.pdf.setFillColor(self.white)
        self.pdf.setFont("Helvetica-Bold", 10.5)
        self.pdf.drawString(self.left, self.y, label)
        self.pdf.setFillColor(self.muted)
        self.pdf.setFont("Helvetica", 10.5)
        yy = self.y
        for line in lines:
            self.pdf.drawString(self.left + 120, yy, line)
            yy -= 14
        self.y = yy - 4

    def methodology_box(self):
        lines: List[str] = []
        for item in _methodology_lines():
            lines.extend(_split_lines(self.pdf, item, "Helvetica", 9, self.uw - 26))
        box_h = max(84, len(lines) * 11 + 34)
        self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, self.y, box_h + 10, self.page_no, self.charcoal)
        self.pdf.setFillColor(self.panel)
        self.pdf.roundRect(self.left, self.y - box_h + 10, self.uw, box_h, 12, stroke=0, fill=1)
        self.pdf.setFillColor(self.gold)
        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawString(self.left + 14, self.y - 10, "Sources & Methodology")
        yy = self.y - 28
        for item in _methodology_lines():
            self.pdf.setFillColor(self.gold)
            self.pdf.setFont("Helvetica-Bold", 10)
            self.pdf.drawString(self.left + 14, yy, "•")
            block = _split_lines(self.pdf, item, "Helvetica", 9, self.uw - 34)
            yy = _draw_lines(self.pdf, block, self.left + 28, yy, 11, "Helvetica", 9, self.muted)
            yy -= 2
        self.y -= box_h + 10

    def act_breakdown_cards(self, act_breakdown: dict):
        """Render 3-column act breakdown cards."""
        if not act_breakdown or not isinstance(act_breakdown, dict):
            return
        self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, self.y, 175, self.page_no, self.charcoal)
        card_w = (self.uw - 20) / 3
        card_h = 158
        acts = [
            ("ACT ONE", act_breakdown.get("act_1") or {}),
            ("ACT TWO", act_breakdown.get("act_2") or {}),
            ("ACT THREE", act_breakdown.get("act_3") or {}),
        ]
        for i, (label, act) in enumerate(acts):
            x = self.left + i * (card_w + 10)
            y = self.y
            self.pdf.setFillColor(self.panel)
            self.pdf.roundRect(x, y - card_h, card_w, card_h, 10, stroke=0, fill=1)
            self.pdf.setFillColor(self.gold)
            self.pdf.roundRect(x, y - card_h, 4, card_h, 2, stroke=0, fill=1)
            self.pdf.setFillColor(self.gold)
            self.pdf.setFont("Helvetica-Bold", 9)
            self.pdf.drawString(x + 14, y - 16, label)
            yy = y - 30
            summary = _safe(act.get("summary"))
            if summary:
                lines = _split_lines(self.pdf, summary, "Helvetica-Bold", 9, card_w - 26)
                for line in lines[:3]:
                    self.pdf.setFillColor(self.white)
                    self.pdf.setFont("Helvetica-Bold", 9)
                    self.pdf.drawString(x + 14, yy, line)
                    yy -= 11
                yy -= 6
            for beat in (act.get("key_beats") or [])[:3]:
                beat_str = str(beat).strip()
                if not beat_str:
                    continue
                beat_lines = _split_lines(self.pdf, beat_str, "Helvetica", 8, card_w - 36)
                self.pdf.setFillColor(self.gold)
                self.pdf.setFont("Helvetica-Bold", 9)
                self.pdf.drawString(x + 14, yy, "·")
                for bl in beat_lines[:2]:
                    self.pdf.setFillColor(self.muted)
                    self.pdf.setFont("Helvetica", 8)
                    self.pdf.drawString(x + 24, yy, bl)
                    yy -= 10
            tp = _safe(act.get("turning_point"))
            if tp and yy > y - card_h + 20:
                yy -= 4
                self.pdf.setFillColor(self.gold)
                self.pdf.setFont("Helvetica-Bold", 8)
                self.pdf.drawString(x + 14, yy, "↪")
                tp_lines = _split_lines(self.pdf, tp, "Helvetica", 8, card_w - 36)
                for tl in tp_lines[:2]:
                    self.pdf.setFillColor(self.soft)
                    self.pdf.setFont("Helvetica", 8)
                    self.pdf.drawString(x + 26, yy, tl)
                    yy -= 10
        self.y -= card_h + 16

    def character_arc_rows(self, character_arcs: dict):
        """Render character arcs as beginning → transformation → end rows."""
        if not character_arcs or not isinstance(character_arcs, dict):
            return
        for char_name, arc in list(character_arcs.items())[:6]:
            if not isinstance(arc, dict):
                continue
            beginning = _safe(arc.get("beginning_state"))
            transformation = _safe(arc.get("transformation"))
            end = _safe(arc.get("end_state"))
            parts = [p for p in [beginning, transformation, end] if p]
            if not parts:
                continue
            arc_line = "  →  ".join(parts)
            arc_lines = _split_lines(self.pdf, arc_line, "Helvetica", 9.5, self.uw - 14)
            needed = 16 + len(arc_lines) * 12 + 8
            self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, self.y, needed, self.page_no, self.charcoal)
            self.pdf.setFillColor(self.gold)
            self.pdf.setFont("Helvetica-Bold", 9.5)
            self.pdf.drawString(self.left, self.y, char_name.upper())
            self.y -= 13
            self.y = _draw_lines(self.pdf, arc_lines, self.left + 10, self.y, 12, "Helvetica", 9.5, self.muted)
            self.y -= 8

    def comp_table(self, comparable_details: List[str]):
        """Render comparable films as a clean per-line table."""
        if not comparable_details:
            return
        for item in comparable_details:
            item_lines = _split_lines(self.pdf, item, "Helvetica", 10, self.uw - 20)
            needed = len(item_lines) * 14 + 10
            self.y, self.page_no = _ensure_space(self.pdf, self.width, self.height, self.y, needed, self.page_no, self.charcoal)
            self.pdf.setFillColor(self.panel)
            self.pdf.roundRect(self.left, self.y - needed + 6, self.uw, needed, 6, stroke=0, fill=1)
            self.pdf.setFillColor(self.gold)
            self.pdf.roundRect(self.left, self.y - needed + 6, 4, needed, 2, stroke=0, fill=1)
            yy = self.y - 6
            for line in item_lines:
                self.pdf.setFillColor(self.white)
                self.pdf.setFont("Helvetica", 10)
                self.pdf.drawString(self.left + 14, yy, line)
                yy -= 14
            self.y -= needed + 5


# ── LIGHT SYNTHESIS HELPERS ───────────────────────────────────────────────────

def _fallback_audition_snapshot(character_name: str, beats: List[BeatEntry]) -> str:
    top = beats[0].beat if beats else "Hold Authority"
    return (
        f"{character_name.title()} reads as a role carried by pressure, control, and quick decisions. "
        f"Across the current sides, the material most often asks for '{top}'. "
        f"The strongest audition choice is usually specific, contained, and alive in the listening."
    )


def _fallback_booked_snapshot(character_name: str, beats: List[BeatEntry]) -> str:
    top = beats[0].beat if beats else "Hold Authority"
    scene_count = len(list(dict.fromkeys([b.scene_heading for b in beats if b.scene_heading])))
    return (
        f"{character_name.title()} currently reads like a role shaped by control, timing, and scene pressure. "
        f"The present extraction finds {len(beats)} speaking beats across {scene_count or 1} scene(s), with the role most often living inside '{top}'. "
        f"The job in booked-mode is continuity: keep the core behavior stable while allowing pressure to change pace, patience, and openness."
    )


def _fallback_exec_summary(title: str, genre: str, tone: str, logline: str) -> str:
    return (
        f"{title.title()} currently presents as {genre or 'a feature screenplay'} with a tone that leans {tone or 'grounded and commercial'}. "
        f"At its best, the material works because the central pressure line is easy to understand and the story engine is clear. "
        f"The clearest commercial hook remains: {logline or 'the protagonist is forced into a high-pressure situation that escalates toward a reversal.'}"
    )


def _smart_summary(mode: str, title: str, character_name: str, logline: str, synopsis: str, beats: List[BeatEntry], extra: str = "") -> str:
    if mode == "audition":
        user = (
            f"Write a 90-word actor-facing audition snapshot for the role {character_name}. "
            f"Conversational, concise, helpful for a novice actor. No fluff. "
            f"Use this context: logline={logline}; synopsis={synopsis}; top beats={[b.beat for b in beats[:5]]}; extra={extra}."
        )
        out = _call_text_ai(
            "You write concise, conversational actor prep copy for audition packets. Avoid robotic labels. Do not mention AI.",
            user,
            max_tokens=180,
        )
        return out or _fallback_audition_snapshot(character_name, beats)
    if mode == "booked":
        user = (
            f"Write a 110-word booked-role overview for the role {character_name}. "
            f"Conversational but professional. Focus on continuity, pressure, and role behavior. "
            f"Use: logline={logline}; synopsis={synopsis}; beats={[b.beat for b in beats[:8]]}; extra={extra}."
        )
        out = _call_text_ai(
            "You write clear, practical actor continuity notes. Avoid jargon overload. Do not mention AI.",
            user,
            max_tokens=220,
        )
        return out or _fallback_booked_snapshot(character_name, beats)
    user = (
        f"Write a 110-word executive summary for the screenplay {title}. Professional, concise, market-aware, novice-friendly. "
        f"Use only this info: genre={extra}; logline={logline}; synopsis={synopsis}."
    )
    out = _call_text_ai(
        "You write concise, professional script analysis summaries for development reports. No hype. No fluff. Do not mention AI.",
        user,
        max_tokens=220,
    )
    return out or _fallback_exec_summary(title, extra, "", logline)


def _unique_scenes(beats: List[BeatEntry]) -> List[str]:
    return list(dict.fromkeys([b.scene_heading for b in beats if b.scene_heading]))


# ── ACTOR V2 DYNAMIC INTELLIGENCE + IMAGE HELPERS ────────────────────────────

def _as_list(value, fallback: Optional[List[str]] = None) -> List[str]:
    if value is None:
        return fallback or []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                joined = " — ".join(str(v).strip() for v in item.values() if str(v).strip())
                if joined:
                    out.append(joined)
            else:
                s = str(item).strip()
                if s:
                    out.append(s)
        return out or (fallback or [])
    s = str(value).strip()
    if not s:
        return fallback or []
    parts = [x.strip(" •-\n\t") for x in re.split(r"\n+|;|\|", s) if x.strip(" •-\n\t")]
    return parts or [s]


def _project_title(brain_data: Dict) -> str:
    for key in ["title", "project_title", "script_title", "name"]:
        v = _safe(brain_data.get(key))
        if v:
            return v
    return "Untitled"


def _world_value(brain_data: Dict) -> str:
    return _safe(brain_data.get("world") or brain_data.get("genre") or brain_data.get("setting"), "Script world")


def _character_mentions_from_script(script_text: str, character_name: str) -> str:
    """When 0 beats found, extract all lines that mention the character by name."""
    target = character_name.upper()
    lines = script_text.split("\n")
    mentions = []
    for line in lines:
        upper = line.strip().upper()
        if target in upper and line.strip():
            mentions.append(line.strip()[:200])
        if len(mentions) >= 30:
            break
    return "\n".join(mentions)


def _actor_ai_json(character_name: str, title: str, mode: str, brain_data: Dict, beats: List[BeatEntry], script_text: str = "") -> Dict:
    """Returns actor-specific copy blocks. Uses API when available; otherwise strong local fallbacks."""
    logline = _safe(brain_data.get("logline"))
    synopsis = _safe(brain_data.get("synopsis"))[:1800]
    top_dialogue = [f"{b.scene_heading}: {b.dialogue[:160]}" for b in beats[:8]]
    # When 0 beats, use script mentions so Haiku can still generate character-specific content
    if not beats and script_text:
        mentions = _character_mentions_from_script(script_text, character_name)
        if mentions:
            top_dialogue = [f"Script mentions of {character_name}:\n{mentions[:1200]}"]
    system = (
        "You create premium, practical actor preparation reports from screenplay data. "
        "Be specific to the role and script. Do not use generic filler. Do not mention AI. "
        "Return ONLY valid JSON."
    )
    user = f"""
Create concise actor-report copy for {character_name} in {title}.
Mode: {mode}
Logline: {logline}
Synopsis: {synopsis}
Detected beat types: {[b.beat for b in beats[:12]]}
Sample dialogue beats: {top_dialogue}
Return JSON with these keys:
summary: string, 60-90 words
casting_read: list of 4 specific bullets
playable_tactics: list of 4 specific bullets
emotional_triggers: list of 4 specific bullets
danger_zones: list of 4 specific bullets
memorization_beats: list of 4 specific bullets
reader_chemistry: list of 4 specific bullets
look_presence: list of 4 specific bullets
booked_continuity: list of 5 specific bullets
scene_priorities: list of 6 specific bullets
"""
    raw = _call_text_ai(system, user, max_tokens=850)
    if raw:
        try:
            import json
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
                cleaned = re.sub(r"```$", "", cleaned).strip()
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    beat_types = list({b.beat for b in beats[:12]}) or ["Present"]
    sample_lines = [b.dialogue[:80] for b in beats[:4]] or ["No dialogue detected."]
    return {
        "summary": f"{character_name} in {title or 'this project'}. {len(beats)} beats detected across {len({b.scene_heading for b in beats})} scenes. Review the beat breakdown for specific playable moments.",
        "casting_read":       [f"Play {bt}" for bt in beat_types[:4]] or ["Lead with objective", "Stay present", "Trust the silence", "Let the scene breathe"],
        "playable_tactics":   ["Lead with objective, not emotion", "Let silence carry subtext", "Protect listening over performing", "One physical life throughout"],
        "emotional_triggers": [d[:80] for d in sample_lines[:4]] or ["See script for specific triggers"],
        "danger_zones":       ["Over-explaining the emotion", "Playing the result instead of the want", "Losing physical consistency", "Rushing past the silence"],
        "memorization_beats": [f"Page {b.reference}: {b.dialogue[:60]}" for b in beats[:6]] or ["No beats detected"],
        "reader_chemistry":   ["Commit to the want, not the feeling", "Give the reader something to react to", "Find the humor in the tension", "Let them finish your thought"],
        "look_presence":      ["One physical choice, held consistently", "Let the body carry the weight before the words do", "Economy of movement under pressure", "Stay rooted, not rigid"],
        "booked_continuity":  [f"Track how {bt} evolves across scenes" for bt in beat_types[:5]] or ["Track core identity across all scenes"],
        "scene_priorities":   [f"{b.scene_heading}: {b.beat}" for b in beats[:6]] or ["No scene data detected"],
    }


# ─── POSTER LIBRARY LOOKUP FOR REPORT COVERS ─────────────────────────────
# Maps brain's `world` string → poster library genre slug (from the FAL-
# generated asset library at /static/asset_library/posters). Used for actor
# prep, actor booked, and script analysis report covers.
_REPORT_WORLD_TO_POSTER_GENRE = {
    "feature / action espionage thriller": "action_espionage",
    "feature / contained urban thriller":  "contained_urban",
    "feature / legal / courtroom drama":   "legal_courtroom",
    "feature / fantasy satire comedy":     "fantasy_satire",
    "feature / fantasy adventure":         "fantasy_satire",  # library has no adventure variant yet
    "feature / nightlife comedy":          "nightlife_comedy",
    "feature / sports drama":              "sports_drama",
    "feature / crime drama":               "crime_drama",
    "feature / crime family":              "crime_drama",     # library reuse
    "feature / horror":                    "crime_drama",     # library reuse (dark visual)
    "feature / psychological thriller":    "contained_urban", # library reuse
    "feature / sci-fi action":             "action_espionage",# library reuse
    "feature / sci-fi horror":             "contained_urban", # library reuse
    "feature / animation family":          "drama",           # library reuse (paper tone)
    "feature / drama":                     "drama",
}

_POSTER_LIBRARY_DIR = Path("/opt/evolum/static/asset_library/posters")
_POSTER_MANIFEST = Path("/opt/evolum/static/asset_library/posters_manifest.json")
_POSTER_MANIFEST_CACHE = {"loaded": False, "posters": []}


def _load_poster_manifest() -> list:
    if _POSTER_MANIFEST_CACHE["loaded"]:
        return _POSTER_MANIFEST_CACHE["posters"]
    _POSTER_MANIFEST_CACHE["loaded"] = True
    if _POSTER_MANIFEST.exists():
        try:
            data = json.loads(_POSTER_MANIFEST.read_text())
            _POSTER_MANIFEST_CACHE["posters"] = data.get("posters", [])
        except Exception:
            pass
    return _POSTER_MANIFEST_CACHE["posters"]


def _pick_poster_from_library(world: str, seed_key: str = "") -> Optional[Path]:
    """Return a local file path to a genre-appropriate poster from the FAL
    library, or None if no library or no match. `seed_key` (e.g. project title
    + character) makes selection deterministic per report — same key returns
    the same poster across regenerations."""
    posters = _load_poster_manifest()
    if not posters:
        return None
    genre = _REPORT_WORLD_TO_POSTER_GENRE.get(world or "", "drama")
    matching = [p for p in posters if p.get("genre") == genre]
    if not matching:
        matching = [p for p in posters if p.get("genre") == "drama"] or posters
    if not matching:
        return None
    # Deterministic pick keyed on seed_key
    idx = int(hash(seed_key or "default") % len(matching)) if seed_key else 0
    entry = matching[idx]
    # `path` in the manifest is a URL-style path starting with /static/... —
    # translate to the local filesystem path.
    web_path = str(entry.get("path", "")).strip()
    if web_path.startswith("/static/asset_library/posters/"):
        local = _POSTER_LIBRARY_DIR / Path(web_path).name
        if local.exists() and local.is_file() and local.stat().st_size > 1000:
            return local
    return None


def _find_actor_report_image(brain_data: Dict, mode: str, character_name: str, title: str) -> Optional[Path]:
    """Cover image for a report: brain's image_plan first, else the FAL-generated
    poster library keyed on world."""
    # 1. Explicit path from brain image_plan only
    for item in brain_data.get("image_plan") or []:
        if isinstance(item, dict):
            for key in ["local_path", "image_path", "path", "selected_image_path"]:
                val = str(item.get(key) or "").strip()
                if val and not val.startswith("http"):
                    p = Path(val)
                    if p.exists() and p.is_file() and p.stat().st_size > 1000:
                        return p

    # 2. Poster library — deterministic pick keyed on world + title + character
    world = _world_value(brain_data)
    seed_key = f"{world}|{title}|{character_name}|{mode}"
    poster_path = _pick_poster_from_library(world, seed_key)
    if poster_path:
        return poster_path

    # 3. FAL generation — cached per report so it never regenerates unnecessarily
    fal_key = None  # FAL removed — visuals/ library is the only image source
    if not fal_key:
        return None
    try:
        import urllib.request
        import fal_client  # type: ignore
        out_dir = _BASE_DIR / "visuals" / "output" / "report_images"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", f"{title}_{character_name}_{mode}").strip("_").lower()[:80]
        out_path = out_dir / f"{safe_name}.png"
        if out_path.exists() and out_path.stat().st_size > 1000:
            return out_path
        world = _world_value(brain_data)
        tone = _safe(brain_data.get("tone"), "cinematic, grounded")
        if mode == "analysis":
            prompt = (
                f"Cinematic cover image for a screenplay called '{title}'. "
                f"World: {world}. Tone: {tone}. "
                f"Film production still, atmospheric, evocative, no text, no logos, no watermarks, "
                f"shallow depth of field, premium streaming drama look, 16:9."
            )
        else:
            prompt = (
                f"Cinematic actor prep image for character {character_name} in '{title}'. "
                f"World: {world}. Tone: {tone}. "
                f"Professional film still, dramatic but tasteful, no text, no logos, no watermarks, "
                f"shallow depth of field, premium streaming drama look, 16:9."
            )
        result = fal_client.subscribe(
            os.getenv("FAL_IMAGE_MODEL", "fal-ai/flux/dev"),
            arguments={"prompt": prompt, "image_size": "landscape_16_9", "num_images": 1},
        )
        url = None
        images = result.get("images") if isinstance(result, dict) else None
        if images and isinstance(images, list):
            first = images[0]
            if isinstance(first, dict):
                url = first.get("url")
        if url:
            urllib.request.urlretrieve(url, out_path)
            return out_path if out_path.exists() else None
    except Exception:
        return None
    return None


def _draw_cover_image(pdf: canvas.Canvas, image_path: Optional[Path], x: float, y: float, w: float, h: float, stroke_color) -> bool:
    """Draws the cover image box. Returns True if drawn, False if no image."""
    if not (image_path and image_path.exists()):
        return False
    pdf.setFillColor(colors.HexColor("#0b0b0b"))
    pdf.roundRect(x, y, w, h, 14, stroke=0, fill=1)
    try:
        pdf.drawImage(ImageReader(str(image_path)), x, y, width=w, height=h, preserveAspectRatio=True, anchor="c", mask="auto")
    except Exception:
        pass
    pdf.setStrokeColor(stroke_color)
    pdf.roundRect(x, y, w, h, 14, stroke=1, fill=0)
    return True


def _draw_card(pdf: canvas.Canvas, x: float, y: float, w: float, h: float, title: str, lines: List[str], gold, panel, white, muted) -> None:
    pdf.setFillColor(panel)
    pdf.roundRect(x, y - h, w, h, 12, stroke=0, fill=1)
    pdf.setFillColor(gold)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(x + 12, y - 18, title.upper()[:34])
    yy = y - 38
    for item in lines[:6]:
        chunks = simpleSplit(str(item), "Helvetica", 9, w - 34)
        if yy - len(chunks)*11 < y - h + 10:
            break
        pdf.setFillColor(gold)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(x + 12, yy, "•")
        yy = _draw_lines(pdf, chunks, x + 24, yy, 11, "Helvetica", 9, muted)
        yy -= 3


def _page_bg(pdf: canvas.Canvas, width: float, height: float, charcoal, gold):
    pdf.setFillColor(charcoal)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    pdf.setFillColor(gold)
    pdf.rect(0, height - 6, width, 6, stroke=0, fill=1)


def _draw_tag_pill(pdf: canvas.Canvas, text: str, x: float, y: float, gold, panel) -> float:
    """Draws a pill tag. Returns x position after the pill."""
    tw = len(text) * 5.4 + 18
    pdf.setFillColor(panel)
    pdf.roundRect(x, y - 14, tw, 17, 6, stroke=0, fill=1)
    pdf.setFillColor(gold)
    pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(x + 9, y - 7, text.upper()[:30])
    return x + tw + 7


def _draw_beat_map(pdf: canvas.Canvas, groups: list, x: float, y: float, w: float,
                   gold, panel, white, muted) -> float:
    """Draws beat frequency bar chart + 2 signature moment cards. Returns final y."""
    if not groups:
        return y
    max_count = max(g["count"] for g in groups)
    bar_bg = colors.HexColor("#1e2226")
    label_w = 174
    bar_total = w - label_w - 62
    row_h = 28

    for g in groups[:9]:
        filled = max(int((g["count"] / max_count) * bar_total), 6)
        page_range = (f"p.{g['pages'][0]}–{g['pages'][-1]}" if len(g["pages"]) > 1
                      else (f"p.{g['pages'][0]}" if g["pages"] else ""))
        bx = x + label_w

        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(x, y - 11, g["beat_type"].upper()[:26])

        pdf.setFillColor(bar_bg)
        pdf.roundRect(bx, y - 18, bar_total, 12, 4, stroke=0, fill=1)
        pdf.setFillColor(gold)
        pdf.roundRect(bx, y - 18, filled, 12, 4, stroke=0, fill=1)

        pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(bx + bar_total + 7, y - 11, str(g["count"]))
        pdf.setFillColor(muted); pdf.setFont("Helvetica", 7)
        pdf.drawString(bx + bar_total + 26, y - 11, page_range)

        y -= row_h

    sig = [g for g in groups if g.get("samples")][:2]
    if sig:
        y -= 10
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(x, y - 4, "SIGNATURE MOMENTS")
        y -= 18
        sg_w = (w - 12) / len(sig)
        for si, sg in enumerate(sig):
            s = sg["samples"][0]
            sx = x + si * (sg_w + 12)
            scene = s.scene_heading if s.scene_heading and s.scene_heading != "SCENE NOT DETECTED" else s.reference
            quote = f'"{s.dialogue[:110]}"'
            pdf.setFillColor(panel)
            pdf.roundRect(sx, y - 58, sg_w, 58, 8, stroke=0, fill=1)
            pdf.setFillColor(gold)
            pdf.roundRect(sx, y - 58, 3, 58, 2, stroke=0, fill=1)
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 7)
            pdf.drawString(sx + 10, y - 13, sg["beat_type"].upper()[:30])
            pdf.setFillColor(muted); pdf.setFont("Helvetica", 7)
            pdf.drawString(sx + 10, y - 24, scene[:40])
            q_lines = simpleSplit(quote, "Helvetica", 7, sg_w - 18)
            _draw_lines(pdf, q_lines[:3], sx + 10, y - 36, 10, "Helvetica", 7, colors.HexColor("#aaaaaa"))
        y -= 66
    return y


def _render_scene_intensity_arc_png(scene_presence_map: list) -> Optional[Path]:
    """Line chart of conflict_intensity across scene numbers.
    Shows the pressure arc of the screenplay at a glance."""
    if not scene_presence_map:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return None
    scene_nums = []
    intensities = []
    for s in scene_presence_map:
        if not isinstance(s, dict):
            continue
        try:
            scene_nums.append(int(s.get("scene_number") or 0))
            intensities.append(float(s.get("conflict_intensity") or 0))
        except (TypeError, ValueError):
            continue
    if len(scene_nums) < 2:
        return None

    charcoal_hex, panel_hex = "#111111", "#1b1f23"
    gold_hex, white_hex, muted_hex, ring_hex = "#f0c15d", "#ffffff", "#8f8f8f", "#2a2f34"

    fig, ax = plt.subplots(figsize=(7.6, 3.0))
    fig.patch.set_facecolor(charcoal_hex)
    ax.set_facecolor(panel_hex)

    # Divide into 3 acts by scene number quantiles (matching brain's logic)
    total = max(scene_nums)
    act1_end = total / 3.0
    act2_end = 2 * total / 3.0
    ax.axvspan(0.5, act1_end, alpha=0.06, color=gold_hex)
    ax.axvspan(act2_end, total + 0.5, alpha=0.06, color=gold_hex)

    # Area fill + line
    ax.fill_between(scene_nums, intensities, 0, color=gold_hex, alpha=0.22)
    ax.plot(scene_nums, intensities, color=gold_hex, linewidth=2, marker="o", markersize=3.5, markerfacecolor=gold_hex)

    # Act markers
    for x, label in [(act1_end, "END ACT I"), (act2_end, "END ACT II")]:
        ax.axvline(x, color=muted_hex, linestyle="--", linewidth=0.7, alpha=0.75)
        ax.text(x, 10.6, label, color=muted_hex, fontsize=7, ha="center", fontweight="bold")

    ax.set_ylim(0, 11)
    ax.set_xlim(0.5, total + 0.5)
    ax.set_yticks([2, 4, 6, 8, 10])
    ax.set_yticklabels(["2", "4", "6", "8", "10"], color=muted_hex, fontsize=8)
    ax.set_xlabel("Scene #", color=muted_hex, fontsize=9)
    ax.set_ylabel("Intensity", color=muted_hex, fontsize=9)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(ring_hex)
    ax.tick_params(colors=muted_hex)
    ax.grid(True, color=ring_hex, alpha=0.4, linestyle="-", linewidth=0.4)
    ax.set_axisbelow(True)

    import tempfile
    fd, tmp_str = tempfile.mkstemp(suffix=".png", prefix="evolum_arc_")
    os.close(fd)
    tmp_path = Path(tmp_str)
    fig.savefig(str(tmp_path), dpi=150, bbox_inches="tight", facecolor=charcoal_hex)
    plt.close(fig)
    return tmp_path if tmp_path.exists() else None


def _render_character_bars_png(character_rankings: list, max_chars: int = 6) -> Optional[Path]:
    """Horizontal bar chart of top-N characters' trust_score. Fast read of
    ensemble balance — is this a solo lead film, or a 4-hander?"""
    if not character_rankings:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    top = [r for r in character_rankings[:max_chars] if isinstance(r, dict) and r.get("name")]
    if len(top) < 2:
        return None
    top.reverse()  # matplotlib horizontal bars stack bottom-up
    names = [str(r.get("name") or "").title()[:24] for r in top]
    scores = [max(0, min(100, int(r.get("trust_score") or 0))) for r in top]

    charcoal_hex, panel_hex = "#111111", "#1b1f23"
    gold_hex, gold_soft, white_hex, muted_hex, ring_hex = "#f0c15d", "#c9a04f", "#ffffff", "#8f8f8f", "#2a2f34"

    fig, ax = plt.subplots(figsize=(7.6, max(2.2, 0.5 * len(top) + 0.6)))
    fig.patch.set_facecolor(charcoal_hex)
    ax.set_facecolor(panel_hex)

    ax.barh(names, scores, color=gold_hex, height=0.6, edgecolor=gold_soft, linewidth=0.5)
    for i, s in enumerate(scores):
        ax.text(s + 1.5, i, f"{s}", color=gold_hex, fontsize=9, fontweight="bold", va="center")

    ax.set_xlim(0, 108)
    ax.set_xticks([25, 50, 75, 100])
    ax.set_xticklabels(["25", "50", "75", "100"], color=muted_hex, fontsize=8)
    ax.tick_params(colors=muted_hex)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(ring_hex)
    for label in ax.get_yticklabels():
        label.set_color(white_hex); label.set_fontweight("bold"); label.set_fontsize(10)
    ax.set_xlabel("Trust score  (dialogue · action · scene presence)", color=muted_hex, fontsize=8)
    ax.grid(True, axis="x", color=ring_hex, alpha=0.4, linestyle="-", linewidth=0.4)
    ax.set_axisbelow(True)

    import tempfile
    fd, tmp_str = tempfile.mkstemp(suffix=".png", prefix="evolum_bars_")
    os.close(fd)
    tmp_path = Path(tmp_str)
    fig.savefig(str(tmp_path), dpi=150, bbox_inches="tight", facecolor=charcoal_hex)
    plt.close(fig)
    return tmp_path if tmp_path.exists() else None


def _render_strength_radar_png(strength_dict: dict) -> Optional[Path]:
    """Render an evolum-styled radar chart of strength_index scores as a
    temporary PNG. Returns the path, or None if matplotlib is unavailable
    or all scores are missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return None
    labels = ["Concept", "Character", "Market", "Originality"]
    keys = ["concept", "character", "marketability", "originality"]
    values = []
    for k in keys:
        try:
            values.append(min(max(float(strength_dict.get(k, 0) or 0), 0), 10))
        except (TypeError, ValueError):
            values.append(0)
    if not any(values):
        return None
    values_loop = values + values[:1]
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles_loop = angles + angles[:1]

    charcoal_hex, panel_hex = "#111111", "#1b1f23"
    gold_hex, white_hex, ring_hex = "#f0c15d", "#ffffff", "#2a2f34"

    fig, ax = plt.subplots(figsize=(4.4, 4.4), subplot_kw={"projection": "polar"})
    fig.patch.set_facecolor(charcoal_hex)
    ax.set_facecolor(panel_hex)
    for r in (2, 4, 6, 8, 10):
        ax.plot(angles_loop, [r] * len(angles_loop), color=ring_hex, linewidth=0.5, alpha=0.75)
    ax.plot(angles_loop, values_loop, color=gold_hex, linewidth=2.2)
    ax.fill(angles_loop, values_loop, color=gold_hex, alpha=0.22)
    for a, v in zip(angles, values):
        ax.plot(a, v, "o", color=gold_hex, markersize=6)
    ax.set_ylim(0, 10.0)
    ax.set_yticks([])
    ax.set_xticks(angles)
    # Stack label + score so nothing overlaps
    combined = [f"{lbl}\n{int(round(v))}" for lbl, v in zip(labels, values)]
    ax.set_xticklabels(combined, color=white_hex, fontsize=11, fontweight="bold")
    # Colorize the score line differently by rewrapping ticks: matplotlib doesn't
    # do per-line color easily, so we leave the whole label in white and pop the
    # value dots at r=v with gold to carry the color story.
    ax.spines["polar"].set_color(ring_hex)
    ax.tick_params(pad=14)
    import tempfile
    fd, tmp_str = tempfile.mkstemp(suffix=".png", prefix="evolum_radar_")
    os.close(fd)
    tmp_path = Path(tmp_str)
    fig.savefig(str(tmp_path), dpi=150, bbox_inches="tight", facecolor=charcoal_hex)
    plt.close(fig)
    return tmp_path if tmp_path.exists() else None


def _draw_strength_bars(pdf: canvas.Canvas, strength_dict: dict, x: float, y: float, w: float,
                        gold, panel, white, muted) -> float:
    """Draws 1-10 score bars for strength_index fields. Returns final y."""
    score_map = [
        ("Concept",     strength_dict.get("concept")),
        ("Character",   strength_dict.get("character")),
        ("Market",      strength_dict.get("marketability")),
        ("Originality", strength_dict.get("originality")),
    ]
    valid = []
    for lbl, val in score_map:
        try:
            valid.append((lbl, min(max(float(val), 0), 10)))
        except (TypeError, ValueError):
            pass
    if not valid:
        return y
    bar_bg = colors.HexColor("#1e2226")
    label_w = 112
    bar_total = w - label_w - 58
    row_h = 28
    for label, score in valid:
        filled = max(int((score / 10) * bar_total), 6)
        bx = x + label_w
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(x, y - 11, label.upper())
        pdf.setFillColor(bar_bg); pdf.roundRect(bx, y - 18, bar_total, 12, 4, stroke=0, fill=1)
        pdf.setFillColor(gold); pdf.roundRect(bx, y - 18, filled, 12, 4, stroke=0, fill=1)
        pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(bx + bar_total + 8, y - 11, f"{score:.0f}/10")
        y -= row_h
    return y


# ── MODE 1: AUDITION QUICKPACK ───────────────────────────────────────────────

def build_actor_prep_pdf(script_text: str, character_name: str, output_path: str | Path, brain_data: Optional[Dict] = None) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    beats = extract_beats(script_text, character_name)
    brain_data = brain_data or {}

    pdf = canvas.Canvas(str(output_path), pagesize=LETTER)
    pdf.setTitle(f"{character_name.title()} — Actor Prep V2")
    width, height = LETTER
    left, right = 42, width - 42
    usable_width = right - left

    charcoal = colors.HexColor("#111111")
    panel = colors.HexColor("#1b1f23")
    gold = colors.HexColor("#f0c15d")
    white = colors.white
    muted = colors.HexColor("#d8d8d8")

    title = _project_title(brain_data)
    tone = _safe(brain_data.get("tone"), "Performance-driven")
    world = _world_value(brain_data)
    intelligence = _actor_ai_json(character_name, title, "audition", brain_data, beats, script_text)
    image_path = _find_actor_report_image(brain_data, "actor_prep", character_name, title)

    emotional_continuity_prep = [str(x).strip() for x in (brain_data.get("emotional_continuity") or []) if str(x).strip()]
    costume_clues_prep = [str(x).strip() for x in (brain_data.get("costume_behavior_clues") or []) if str(x).strip()]
    relationship_map_prep = brain_data.get("relationship_leverage_map") or []
    role_arc_map_prep = brain_data.get("role_arc_map") or []
    pressure_ladder_prep = brain_data.get("pressure_ladder") or []
    set_ready_prep = _as_list(brain_data.get("set_ready_checklist"), [
        "Know the scene pressure level before the first take.",
        "Track what changed from the previous scene.",
        "Protect body language and listening continuity.",
        "Mark where status rises, slips, or resets.",
        "Keep novelty second to continuity.",
    ])
    character_arcs_prep = brain_data.get("character_arcs") or {}

    # When 0 beats, brain_data fields are script-wide — generate character-specific via AI
    if not beats and script_text:
        mentions = _character_mentions_from_script(script_text, character_name)
        if mentions:
            char_sys = (
                "You generate specific, practical actor preparation data from screenplay context. "
                "Be specific to this character. Do not use generic filler. Return only valid JSON."
            )
            char_prompt = f"""
Character: {character_name} in {title}
Script mentions of this character:
{mentions[:1400]}

Return JSON with these keys (each a list of 3-4 short, specific bullets):
emotional_continuity: emotional thread this character carries across scenes
costume_behavior_clues: physical/costume details that reveal character state
relationship_leverage_map: strings like "Character A and Character B — dynamic — story function"
set_ready_checklist: things the actor must confirm before each take
"""
            raw_char = _call_text_ai(char_sys, char_prompt, max_tokens=600)
            if raw_char:
                try:
                    cleaned_char = raw_char.strip()
                    if cleaned_char.startswith("```"):
                        cleaned_char = re.sub(r"^```(?:json)?", "", cleaned_char).strip()
                        cleaned_char = re.sub(r"```$", "", cleaned_char).strip()
                    char_fields = json.loads(cleaned_char)
                    if isinstance(char_fields, dict):
                        if char_fields.get("emotional_continuity"):
                            emotional_continuity_prep = [str(x) for x in char_fields["emotional_continuity"]]
                        if char_fields.get("costume_behavior_clues"):
                            costume_clues_prep = [str(x) for x in char_fields["costume_behavior_clues"]]
                        if char_fields.get("relationship_leverage_map"):
                            relationship_map_prep = [str(x) for x in char_fields["relationship_leverage_map"]]
                        if char_fields.get("set_ready_checklist"):
                            set_ready_prep = [str(x) for x in char_fields["set_ready_checklist"]]
                except Exception:
                    pass

    # Save JSON for HTML report page
    try:
        json_path = output_path.with_suffix(".json")
        groups = group_beats_by_type(beats)
        json_path.write_text(json.dumps({
            "character_name": character_name,
            "title": title,
            "tone": _safe(brain_data.get("tone"), ""),
            "world": world,
            "genre": _safe(brain_data.get("genre"), ""),
            "beat_count": len(beats),
            "intelligence": intelligence,
            "character_arcs": character_arcs_prep,
            "emotional_continuity": emotional_continuity_prep,
            "costume_behavior_clues": costume_clues_prep,
            "relationship_leverage_map": relationship_map_prep,
            "role_arc_map": role_arc_map_prep,
            "pressure_ladder": pressure_ladder_prep,
            "set_ready_checklist": set_ready_prep,
            "beat_groups": [
                {
                    "beat_type": g["beat_type"],
                    "coaching": g["coaching"],
                    "count": g["count"],
                    "scenes": g["scenes"][:4],
                }
                for g in groups[:10]
            ],
        }, indent=2), encoding="utf-8")
    except Exception:
        pass

    # ── PAGE 1: COVER ─────────────────────────────────────────────────────────
    _page_bg(pdf, width, height, charcoal, gold)
    pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(left, height - 44, "ACTOR PREP REPORT")
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 40)
    pdf.drawString(left, height - 96, character_name.upper()[:22])
    pdf.setFillColor(muted); pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(left, height - 118, title.upper()[:46])
    pdf.setStrokeColor(gold); pdf.setLineWidth(0.5)
    pdf.line(left, height - 138, right, height - 138)

    has_image = _draw_cover_image(pdf, image_path, left, height - 338, usable_width, 186, gold)

    snap = intelligence.get("summary") or ""
    snap_lines = simpleSplit(snap, "Helvetica", 10, usable_width - 32)
    box_h = max(76, len(snap_lines) * 13 + 30)
    sy = height - 352 if has_image else height - 156
    pdf.setFillColor(panel); pdf.roundRect(left, sy - box_h, usable_width, box_h, 10, stroke=0, fill=1)
    pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(left + 12, sy - 13, "ROLE SNAPSHOT")
    _draw_lines(pdf, snap_lines, left + 12, sy - 27, 13, "Helvetica", 10, white)

    pill_y = sy - box_h - 16
    px = left
    for tag in [tone[:22] if tone else None, world[:24] if world else None, f"{len(beats)} Beats · {len(_unique_scenes(beats)) or 1} Scenes"]:
        if tag:
            px = _draw_tag_pill(pdf, tag, px, pill_y, gold, panel)
    _footer(pdf, width, 1); pdf.showPage()

    # ── PAGE 2: THE PLAYBOOK ──────────────────────────────────────────────────
    _page_bg(pdf, width, height, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(left, height - 58, "THE PLAYBOOK")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(left, height - 76, "What to play, what to protect, and what to avoid in the room.")

    col_w = (usable_width - 18) / 2
    row_h = 178
    grid_y = height - 108
    for idx, (label, key) in enumerate([
        ("Casting Read",       "casting_read"),
        ("Danger Zones",       "danger_zones"),
        ("Playable Tactics",   "playable_tactics"),
        ("Emotional Triggers", "emotional_triggers"),
    ]):
        cx = left + (idx % 2) * (col_w + 18)
        cy = grid_y - (idx // 2) * (row_h + 18)
        _draw_card(pdf, cx, cy, col_w, row_h, label, _as_list(intelligence.get(key)), gold, panel, white, muted)
    _footer(pdf, width, 2); pdf.showPage()

    # ── PAGE 3: TAPE ROOM + BEAT FREQUENCY MAP ────────────────────────────────
    _page_bg(pdf, width, height, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(left, height - 58, "TAPE ROOM")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(left, height - 76, "Memorization, reader chemistry, and physical presence.")

    tape_col_w = (usable_width - 24) / 3
    tape_h = 168
    tape_y = height - 100
    for ti, (label, key) in enumerate([
        ("Memorization Beats", "memorization_beats"),
        ("Reader Chemistry",   "reader_chemistry"),
        ("Look / Presence",    "look_presence"),
    ]):
        _draw_card(pdf, left + ti * (tape_col_w + 12), tape_y, tape_col_w, tape_h,
                   label, _as_list(intelligence.get(key)), gold, panel, white, muted)

    bm_top = tape_y - tape_h - 20
    pdf.setStrokeColor(colors.HexColor("#252a2e")); pdf.setLineWidth(0.5)
    pdf.line(left, bm_top + 2, right, bm_top + 2)
    pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(left, bm_top - 12, "BEAT FREQUENCY MAP")
    beat_count_label = f"{len(beats)} detected beats — how often each pattern appears in the script"
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 8)
    pdf.drawString(left, bm_top - 24, beat_count_label)

    if beats:
        groups = group_beats_by_type(beats)
        _draw_beat_map(pdf, groups, left, bm_top - 40, usable_width, gold, panel, white, muted)
    else:
        pdf.setFillColor(muted); pdf.setFont("Helvetica", 9)
        pdf.drawString(left, bm_top - 54, "No beats detected. Confirm the character name matches the script exactly.")
    _footer(pdf, width, 3); pdf.showPage()

    # ── PAGE 4: BEFORE YOU SEND ───────────────────────────────────────────────
    _page_bg(pdf, width, height, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(left, height - 58, "BEFORE YOU SEND")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(left, height - 76, "Five things to lock in before the tape leaves your hands.")

    checklist = [
        ("Lead with the objective",   "Play what the character wants — not how they feel about it. Want drives the scene."),
        ("Protect listening beats",   "The role breathes in the wait. Over-acting lives there. Stay present, not prepared."),
        ("One physical life",         "Choose one body choice and keep it consistent across every take and every page."),
        ("Let pressure change pace",  "Raise the stakes through timing and stillness before you raise your volume."),
        ("Technical check",           "File name, framing, clean audio, upload instructions — confirm before you hit send."),
    ]
    cy = height - 112
    for i, (heading, note) in enumerate(checklist):
        pdf.setFillColor(gold)
        pdf.circle(left + 13, cy - 13, 13, stroke=0, fill=1)
        pdf.setFillColor(charcoal); pdf.setFont("Helvetica-Bold", 13)
        pdf.drawCentredString(left + 13, cy - 18, str(i + 1))
        pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(left + 34, cy - 9, heading)
        note_lines = simpleSplit(note, "Helvetica", 9, usable_width - 50)
        _draw_lines(pdf, note_lines, left + 34, cy - 22, 12, "Helvetica", 9, muted)
        cy -= 52
        if i < len(checklist) - 1:
            pdf.setStrokeColor(colors.HexColor("#1e2226")); pdf.setLineWidth(0.5)
            pdf.line(left + 34, cy + 10, right, cy + 10)

    _footer(pdf, width, 4)
    pdf.save()
    return output_path



# ── MODE 2: BOOKED ROLE PREP ─────────────────────────────────────────────────

_CONTINUITY_NOTES: Dict[str, str] = {
    "Reveal Something True":    "What the character reveals here must carry through every subsequent scene. Track the weight of exposure.",
    "Make a Plea":              "The character is exposed here. Track the moment the need overcomes the defense.",
    "Offer Comfort":            "The role is giving something away. Track the cost so it reads as real, not performed.",
    "Assert Identity":          "This declaration anchors the role. Every later scene should echo back to this moment.",
    "Negotiate":                "The character is thinking ahead. Let each offer cost them something or it feels free.",
    "Challenge":                "The character refuses to accept the other person's reality. Keep the refusal grounded.",
    "Protect a Secret":         "What's being concealed must remain consistent — never let the audience forget it's there.",
    "Deliver a Warning":        "The consequence stated here is a promise. If the character doesn't follow through later, the warning felt hollow.",
    "Express Threat":           "The level of menace established here is the ceiling for every threat that follows.",
    "Pressure for Information": "Track what the character learns here and let that new information change the next beat.",
    "Control the Room":         "This is a control beat. Keep the body and pace consistent so the authority feels earned.",
    "Set a Boundary":           "This is where the line gets drawn. Play the clarity, not the anger.",
    "Apply Pressure":           "The role is leaning in here. The scene changes because the character chooses to press.",
    "Read the Situation":       "Track what the character now knows after this beat. Every subsequent scene inherits this new information.",
    "Share Intelligence":       "Protect what the character chose NOT to share here — that's as important as what they did reveal.",
    "Test and Probe":           "Track what the character learned from the reaction. The probe is only useful if they carry the read forward.",
    "Navigate Danger":          "Physical state continuity matters here — injuries, exhaustion, adrenaline. Track what the body carries out of these scenes.",
    "Reset and Move Forward":   "This beat shifts the energy. Let it feel like a clean redirect, not a full emotional reset.",
    "Hold Authority":           "This is the baseline control state. Keep it textured so it does not flatten.",
}
_DEFAULT_CONTINUITY = "Protect continuity first. Let pressure change pace and patience while core identity stays recognizable."


def build_actor_booked_pdf(script_text: str, character_name: str, output_path: str | Path, brain_data: Optional[Dict] = None) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    beats = extract_beats(script_text, character_name)
    brain_data = brain_data or {}

    pdf = canvas.Canvas(str(output_path), pagesize=LETTER)
    pdf.setTitle(f"{character_name.title()} — Booked Role Report")
    width, height = LETTER
    left, right = 42, width - 42
    usable_width = right - left

    charcoal = colors.HexColor("#111111")
    panel = colors.HexColor("#1b1f23")
    gold = colors.HexColor("#f0c15d")
    white = colors.white
    muted = colors.HexColor("#d8d8d8")
    soft = colors.HexColor("#8f8f8f")

    title = _project_title(brain_data)
    world = _world_value(brain_data)
    tone = _safe(brain_data.get("tone"), "")
    intelligence = _actor_ai_json(character_name, title, "booked", brain_data, beats, script_text)
    image_path = _find_actor_report_image(brain_data, "actor_booked", character_name, title)
    scene_count = len(_unique_scenes(beats)) or 1

    # Pull brain fields for this character
    character_arcs = brain_data.get("character_arcs") or {}
    char_arc = None
    for k, v in character_arcs.items():
        if k.upper() == character_name.upper() and isinstance(v, dict):
            char_arc = v
            break
    emotional_continuity = [str(x).strip() for x in (brain_data.get("emotional_continuity") or []) if str(x).strip()]
    costume_clues = [str(x).strip() for x in (brain_data.get("costume_behavior_clues") or []) if str(x).strip()]
    relationship_map = brain_data.get("relationship_leverage_map") or []
    set_ready = _as_list(brain_data.get("set_ready_checklist"), [
        "Know the scene pressure level before the first take.",
        "Track what changed from the previous scene.",
        "Protect body language and listening continuity.",
        "Mark where status rises, slips, or resets.",
        "Keep novelty second to continuity.",
    ])

    # When 0 beats found, brain_data fields are script-wide (wrong character). Generate character-specific via AI.
    if not beats and script_text:
        mentions = _character_mentions_from_script(script_text, character_name)
        if mentions:
            char_sys = (
                "You generate specific, practical actor preparation data from screenplay context. "
                "Be specific to this character. Do not use generic filler. Return only valid JSON."
            )
            char_prompt = f"""
Character: {character_name} in {title}
Script mentions of this character:
{mentions[:1400]}

Return JSON with these keys (each a list of 3-4 short, specific bullets):
emotional_continuity: emotional thread this character carries across scenes
costume_behavior_clues: physical/costume details that reveal character state
relationship_leverage_map: strings like "Character A and Character B — dynamic — story function"
set_ready_checklist: things the actor must confirm before each take
"""
            raw_char = _call_text_ai(char_sys, char_prompt, max_tokens=600)
            if raw_char:
                try:
                    cleaned_char = raw_char.strip()
                    if cleaned_char.startswith("```"):
                        cleaned_char = re.sub(r"^```(?:json)?", "", cleaned_char).strip()
                        cleaned_char = re.sub(r"```$", "", cleaned_char).strip()
                    char_fields = json.loads(cleaned_char)
                    if isinstance(char_fields, dict):
                        if char_fields.get("emotional_continuity"):
                            emotional_continuity = [str(x) for x in char_fields["emotional_continuity"]]
                        if char_fields.get("costume_behavior_clues"):
                            costume_clues = [str(x) for x in char_fields["costume_behavior_clues"]]
                        if char_fields.get("relationship_leverage_map"):
                            relationship_map = [str(x) for x in char_fields["relationship_leverage_map"]]
                        if char_fields.get("set_ready_checklist"):
                            set_ready = [str(x) for x in char_fields["set_ready_checklist"]]
                except Exception:
                    pass

    # Save JSON for HTML report page
    try:
        json_path = output_path.with_suffix(".json")
        groups = group_beats_by_type(beats)
        json_path.write_text(json.dumps({
            "character_name": character_name,
            "title": title,
            "tone": _safe(brain_data.get("tone"), ""),
            "world": world,
            "beat_count": len(beats),
            "scene_count": scene_count,
            "intelligence": intelligence,
            "character_arcs": character_arcs,
            "emotional_continuity": emotional_continuity,
            "costume_behavior_clues": costume_clues,
            "relationship_leverage_map": relationship_map,
            "beat_groups": [
                {
                    "beat_type": g["beat_type"],
                    "coaching": g["coaching"],
                    "count": g["count"],
                    "pages": g["pages"],
                    "samples": [{"reference": s.reference, "scene_heading": s.scene_heading, "dialogue": s.dialogue[:300]} for s in g["samples"]],
                }
                for g in groups
            ],
            "set_ready_checklist": set_ready,
        }, indent=2), encoding="utf-8")
    except Exception:
        pass

    # ── PAGE 1: COVER ─────────────────────────────────────────────────────────
    _page_bg(pdf, width, height, charcoal, gold)
    pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(left, height - 44, "BOOKED ROLE REPORT")
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 40)
    pdf.drawString(left, height - 96, character_name.upper()[:22])
    pdf.setFillColor(muted); pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(left, height - 118, title.upper()[:46])
    pdf.setStrokeColor(gold); pdf.setLineWidth(0.5)
    pdf.line(left, height - 138, right, height - 138)

    has_image = _draw_cover_image(pdf, image_path, left, height - 338, usable_width, 186, gold)

    snap = intelligence.get("summary") or ""
    snap_lines = simpleSplit(snap, "Helvetica", 10, usable_width - 32)
    box_h = max(76, len(snap_lines) * 13 + 30)
    sy = height - 352 if has_image else height - 156
    pdf.setFillColor(panel); pdf.roundRect(left, sy - box_h, usable_width, box_h, 10, stroke=0, fill=1)
    pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(left + 12, sy - 13, "FULL ROLE SNAPSHOT")
    _draw_lines(pdf, snap_lines, left + 12, sy - 27, 13, "Helvetica", 10, white)

    pill_y = sy - box_h - 16
    px = left
    for tag in [f"{len(beats)} Beats · {scene_count} Scenes", world[:24] if world else None, tone[:22] if tone else None]:
        if tag:
            px = _draw_tag_pill(pdf, tag, px, pill_y, gold, panel)
    _footer(pdf, width, 1); pdf.showPage()

    # ── PAGE 2: ROLE INTELLIGENCE ─────────────────────────────────────────────
    _page_bg(pdf, width, height, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(left, height - 58, "ROLE INTELLIGENCE")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(left, height - 76, "What this role requires you to hold, protect, and deliver across the shoot.")
    col_w = (usable_width - 18) / 2
    row_h = 178
    grid_y = height - 108
    for idx, (label, key) in enumerate([
        ("Booked Continuity",  "booked_continuity"),
        ("Scene Priorities",   "scene_priorities"),
        ("Emotional Triggers", "emotional_triggers"),
        ("Look / Behavior",    "look_presence"),
    ]):
        cx = left + (idx % 2) * (col_w + 18)
        cy = grid_y - (idx // 2) * (row_h + 18)
        _draw_card(pdf, cx, cy, col_w, row_h, label, _as_list(intelligence.get(key)), gold, panel, white, muted)
    _footer(pdf, width, 2); pdf.showPage()

    # ── PAGE 3: CHARACTER DNA ─────────────────────────────────────────────────
    _page_bg(pdf, width, height, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(left, height - 58, "CHARACTER DNA")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(left, height - 76, "The physical and emotional thread to protect from first day to wrap.")
    dna_y = height - 106

    # Character arc panels
    if char_arc:
        arc_parts = [(phase, _safe(char_arc.get(key))) for phase, key in
                     [("BEGINS", "beginning_state"), ("TRANSFORMS", "transformation"), ("ENDS", "end_state")]
                     if _safe(char_arc.get(key))]
        if arc_parts:
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 8)
            pdf.drawString(left, dna_y - 4, f"CHARACTER ARC  ·  {character_name.upper()}")
            dna_y -= 18
            arc_col_w = (usable_width - (len(arc_parts) - 1) * 10) / len(arc_parts)
            for ai, (phase, val) in enumerate(arc_parts):
                ax = left + ai * (arc_col_w + 10)
                pdf.setFillColor(panel); pdf.roundRect(ax, dna_y - 72, arc_col_w, 72, 8, stroke=0, fill=1)
                pdf.setFillColor(gold); pdf.roundRect(ax, dna_y - 72, 3, 72, 2, stroke=0, fill=1)
                pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 7)
                pdf.drawString(ax + 10, dna_y - 14, phase)
                val_lines = simpleSplit(val, "Helvetica", 9, arc_col_w - 18)
                _draw_lines(pdf, val_lines[:5], ax + 10, dna_y - 28, 12, "Helvetica", 9, muted)
            dna_y -= 86

    # Emotional continuity + costume side by side
    cont_cards = [(l, v) for l, v in [("Emotional Continuity", emotional_continuity), ("Costume & Behavior", costume_clues)] if v]
    if cont_cards:
        cc_w = (usable_width - 18) / 2 if len(cont_cards) > 1 else usable_width
        cc_h = 158
        for ci, (cl, cv) in enumerate(cont_cards[:2]):
            _draw_card(pdf, left + ci * (cc_w + 18), dna_y, cc_w, cc_h, cl, cv, gold, panel, white, muted)
        dna_y -= cc_h + 18

    # Relationship map
    rel_lines = []
    for row in relationship_map:
        if isinstance(row, dict):
            parts = [str(row.get(k) or "").strip() for k in ["character", "dynamic", "function"] if str(row.get(k) or "").strip()]
            if parts:
                rel_lines.append(" — ".join(parts[:3]))
    if rel_lines and dna_y > 80:
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(left, dna_y - 6, "RELATIONSHIP LEVERAGE MAP")
        dna_y -= 20
        for rl in rel_lines[:7]:
            rls = simpleSplit(rl, "Helvetica", 9, usable_width - 18)
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 9)
            pdf.drawString(left, dna_y, "•")
            pdf.setFillColor(muted); pdf.setFont("Helvetica", 9)
            for line in rls[:2]:
                pdf.drawString(left + 12, dna_y, line)
                dna_y -= 13
            dna_y -= 3
    _footer(pdf, width, 3); pdf.showPage()

    # ── PAGE 4: BEAT MAP + SET-READY ─────────────────────────────────────────
    _page_bg(pdf, width, height, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(left, height - 58, "BEAT FREQUENCY MAP")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(left, height - 76, f"{len(beats)} beats — how this character operates across every scene in the script.")

    bm_top = height - 106
    if beats:
        groups = group_beats_by_type(beats)
        bm_end = _draw_beat_map(pdf, groups, left, bm_top, usable_width, gold, panel, white, muted)
    else:
        pdf.setFillColor(muted); pdf.setFont("Helvetica", 9)
        pdf.drawString(left, bm_top - 14, "No beats detected. Confirm the character name matches the script exactly.")
        bm_end = bm_top - 40

    # Set-ready checklist below
    sr_y = bm_end - 20
    if set_ready and sr_y > 80:
        pdf.setStrokeColor(colors.HexColor("#252a2e")); pdf.setLineWidth(0.5)
        pdf.line(left, sr_y + 6, right, sr_y + 6)
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(left, sr_y - 8, "SET-READY CHECKLIST")
        pdf.setFillColor(muted); pdf.setFont("Helvetica", 8)
        pdf.drawString(left, sr_y - 20, "Clear these before the first take of every scene.")
        sr_y -= 34
        for item in set_ready[:6]:
            chunks = simpleSplit(str(item), "Helvetica", 9, usable_width - 20)
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(left, sr_y, "✓")
            pdf.setFillColor(muted); pdf.setFont("Helvetica", 9)
            pdf.drawString(left + 14, sr_y, chunks[0] if chunks else "")
            sr_y -= 15

    _footer(pdf, width, 4)
    pdf.save()
    return output_path



# ── MODE 3: SCRIPT ANALYSIS REPORT ───────────────────────────────────────────

def build_simple_analysis_pdf(report_output: dict, out_path: Path):
    W, H = LETTER
    L, R = 42, W - 42
    UW = R - L

    charcoal = colors.HexColor("#111111")
    panel = colors.HexColor("#1a1a1a")
    gold = colors.HexColor("#f0c15d")
    blue = colors.HexColor("#4C88C7")
    white = colors.white
    muted = colors.HexColor("#cfcfcf")
    soft = colors.HexColor("#8f8f8f")

    title = _safe(report_output.get("title"), "UNTITLED PROJECT")
    genre = _safe(report_output.get("genre") or report_output.get("world"))
    tone = _safe(report_output.get("tone"))
    logline = _safe(report_output.get("logline"))
    synopsis = _safe(report_output.get("synopsis"))
    theme = _safe(report_output.get("theme"))
    world = _safe(report_output.get("world"))
    setting = _safe(report_output.get("setting"))
    time_frame = _safe(report_output.get("time_frame"))
    core = _safe(report_output.get("core_conflict"))
    engine = _safe(report_output.get("story_engine"))
    reversal = _safe(report_output.get("reversal"))
    lead = _safe(report_output.get("lead_character") or report_output.get("protagonist"))
    protagonist_sum = _safe(report_output.get("protagonist_summary"))
    char_leverage = _safe(report_output.get("character_leverage"))
    top_chars_raw = (report_output.get("character_analysis") or {}).get("top_characters", [])
    if not top_chars_raw:
        top_chars_raw = report_output.get("characters") or []
    top_chars = _clean_characters(top_chars_raw)

    comparables_raw = report_output.get("tone_comparables") or []
    if not comparables_raw:
        comparables_raw = [c.get("title") for c in (report_output.get("comparable_films") or []) if isinstance(c, dict)]
    comparables = _clean_characters(comparables_raw)

    market_projections = report_output.get("market_projections") or {}
    strength = report_output.get("strength_index") or {}
    commercial = _safe(report_output.get("commercial_positioning"))
    audience = _clean_characters(report_output.get("audience_profile") or [])
    packaging = _safe(report_output.get("packaging_potential"))
    executive_summary = _safe(report_output.get("executive_summary"))
    summary_note = _safe(report_output.get("summary_note"))
    story_insights = report_output.get("story_insights") or []
    rewrite_priorities = report_output.get("rewrite_priorities") or report_output.get("next_draft_priorities") or []
    strengths_list = report_output.get("strengths") or []
    risks_list = report_output.get("risks") or report_output.get("development_risks") or []
    budget_lane = _safe(market_projections.get("budget_range") or market_projections.get("estimated_budget_tier") or report_output.get("budget_lane") or report_output.get("estimated_budget"))
    streamer_fit = _safe(market_projections.get("streamer_fit") or market_projections.get("distribution_angle") or report_output.get("streamer_fit"))
    awards_lane = _safe(market_projections.get("awards_lane") or market_projections.get("awards_potential") or report_output.get("awards_lane"))
    franchise = _safe(market_projections.get("franchise_potential") or report_output.get("franchise_potential"))
    sales_hook = _safe(market_projections.get("sales_hook"))

    actor_objective = _safe(report_output.get("actor_objective"))
    playable_tactics = _clean_characters(report_output.get("playable_tactics") or [])
    emotional_triggers = _clean_characters(report_output.get("emotional_triggers") or [])
    audition_danger_zones = _clean_characters(report_output.get("audition_danger_zones") or [])
    reader_chemistry_tips = [str(x).strip() for x in (report_output.get("reader_chemistry_tips") or []) if str(x).strip()]
    memorization_beats = _clean_characters(report_output.get("memorization_beats") or [])
    role_arc_map = _clean_characters(report_output.get("role_arc_map") or [])
    pressure_ladder = _clean_characters(report_output.get("pressure_ladder") or [])
    emotional_continuity = [str(x).strip() for x in (report_output.get("emotional_continuity") or []) if str(x).strip()]
    costume_behavior_clues = [str(x).strip() for x in (report_output.get("costume_behavior_clues") or []) if str(x).strip()]
    set_ready_checklist = [str(x).strip() for x in (report_output.get("set_ready_checklist") or []) if str(x).strip()]
    relationship_map = report_output.get("relationship_leverage_map") or []
    image_plan = report_output.get("image_plan") or []
    act_breakdown = report_output.get("act_breakdown") or {}
    character_arcs = report_output.get("character_arcs") or {}

    layout_strategy = report_output.get("layout_strategy") or {}
    slide_blueprint = report_output.get("slide_blueprint") or {}
    document_layouts = report_output.get("document_layouts") or {}
    analysis_layout = document_layouts.get("analysis_report") or {}

    if not executive_summary:
        executive_summary = _smart_summary("analysis", title, "", logline, synopsis, [], extra=genre)

    if not strengths_list:
        strengths_list = [s for s in [theme, engine, commercial, packaging, actor_objective] if s][:5]
    if not rewrite_priorities:
        rewrite_priorities = [
            "Clarify the protagonist's pressure line even further.",
            "Make the reversal land with maximum clarity.",
            "Sharpen supporting roles so they do more than serve plot.",
        ]
    if not story_insights:
        story_insights = [
            f"Lead role currently reads strongest through {lead or 'the protagonist'}.",
            "The reversal is doing real structural work and should stay visible in the pitch.",
            "The project feels strongest when the audience is tracking pressure, not exposition.",
        ]

    score_parts = []
    for key, label in [("concept", "Concept"), ("character", "Character"), ("marketability", "Market"), ("originality", "Originality")]:
        val = strength.get(key)
        if val:
            score_parts.append(f"{label}: {val}/10")
    strength_line = "  ·  ".join(score_parts)

    comparable_details = []
    for comp in (report_output.get("comparable_films") or []):
        if isinstance(comp, dict):
            title_part = str(comp.get("title") or "").strip()
            why_part = str(comp.get("why") or "").strip()
            box_part = str(comp.get("box_office") or "").strip()
            pieces = [p for p in [title_part, why_part, box_part] if p]
            if pieces:
                comparable_details.append(" — ".join(pieces[:2]) if len(pieces) < 3 else f"{title_part} — {why_part} ({box_part})")

    relationship_lines = []
    for row in relationship_map:
        if isinstance(row, dict):
            character = str(row.get("character") or "").strip()
            dynamic = str(row.get("dynamic") or "").strip()
            function = str(row.get("function") or "").strip()
            parts = [p for p in [character, dynamic, function] if p]
            if parts:
                relationship_lines.append(" — ".join(parts[:2]) if len(parts) < 3 else f"{character} — {dynamic} — {function}")

    image_summary = []
    for item in image_plan[:5]:
        if isinstance(item, dict):
            slide_title = str(item.get("slide_title") or item.get("slide_number") or "").strip()
            visual_family = str(item.get("visual_family") or "").strip()
            query = str(item.get("image_query") or "").strip()
            parts = [slide_title]
            if visual_family:
                parts.append(visual_family)
            if query:
                parts.append(query[:90] + ("…" if len(query) > 90 else ""))
            image_summary.append(" — ".join([p for p in parts if p]))

    cover_image = _find_actor_report_image(report_output, "analysis", lead or title, title)

    pdf = canvas.Canvas(str(out_path), pagesize=LETTER)
    pdf.setTitle(f"{title} — Script Analysis Report")

    # ── PAGE 1: COVER ─────────────────────────────────────────────────────────
    _page_bg(pdf, W, H, charcoal, gold)
    pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(L, H - 44, "SCRIPT ANALYSIS REPORT")

    # Title — up to 2 lines at 30pt
    t_lines = simpleSplit(title.upper(), "Helvetica-Bold", 30, UW)[:2]
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 30)
    for i, tl in enumerate(t_lines):
        pdf.drawString(L, H - 88 - i * 36, tl)
    title_base = H - 88 - (len(t_lines) - 1) * 36

    meta_str = "  ·  ".join(p for p in [genre, tone, time_frame] if p)
    if meta_str:
        pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
        pdf.drawString(L, title_base - 20, meta_str[:80])
    divider_y = title_base - 38
    pdf.setStrokeColor(gold); pdf.setLineWidth(0.5)
    pdf.line(L, divider_y, R, divider_y)

    # Cover image — full width, prominent
    img_h = 188
    has_image = _draw_cover_image(pdf, cover_image, L, divider_y - 12 - img_h, UW, img_h, gold)

    # Executive snapshot box
    snap_y = (divider_y - 12 - img_h - 14) if has_image else (divider_y - 22)
    snap_lines = simpleSplit(executive_summary or "", "Helvetica", 10, UW - 32)
    snap_box_h = max(76, len(snap_lines) * 13 + 30)
    pdf.setFillColor(panel); pdf.roundRect(L, snap_y - snap_box_h, UW, snap_box_h, 10, stroke=0, fill=1)
    pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 7)
    pdf.drawString(L + 12, snap_y - 13, "EXECUTIVE SNAPSHOT")
    _draw_lines(pdf, snap_lines, L + 12, snap_y - 27, 13, "Helvetica", 10, white)

    pill_y = snap_y - snap_box_h - 16
    px = L
    for tag in [budget_lane[:26] if budget_lane else None,
                streamer_fit[:26] if streamer_fit else None,
                awards_lane[:26] if awards_lane else None]:
        if tag and px < R - 60:
            px = _draw_tag_pill(pdf, tag, px, pill_y, gold, panel)
    _footer(pdf, W, 1); pdf.showPage()

    # ── PAGE 2: STORY FOUNDATION ──────────────────────────────────────────────
    _page_bg(pdf, W, H, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(L, H - 58, "STORY FOUNDATION")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(L, H - 76, "The plain-English engine underneath this project.")
    sy2 = H - 106

    # Logline — hero panel
    if logline:
        lg_lines = simpleSplit(logline, "Helvetica-Bold", 12, UW - 32)
        lg_h = max(64, len(lg_lines) * 16 + 28)
        pdf.setFillColor(panel); pdf.roundRect(L, sy2 - lg_h, UW, lg_h, 10, stroke=0, fill=1)
        pdf.setFillColor(gold); pdf.roundRect(L, sy2 - lg_h, 4, lg_h, 3, stroke=0, fill=1)
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(L + 12, sy2 - 13, "LOGLINE")
        _draw_lines(pdf, lg_lines, L + 12, sy2 - 28, 16, "Helvetica-Bold", 12, white)
        sy2 -= lg_h + 14

    # Synopsis
    if synopsis:
        syn_lines = simpleSplit(synopsis, "Helvetica", 10, UW - 32)[:8]
        syn_h = max(56, len(syn_lines) * 13 + 28)
        pdf.setFillColor(panel); pdf.roundRect(L, sy2 - syn_h, UW, syn_h, 10, stroke=0, fill=1)
        pdf.setFillColor(muted); pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(L + 12, sy2 - 13, "SYNOPSIS")
        _draw_lines(pdf, syn_lines, L + 12, sy2 - 27, 13, "Helvetica", 10, muted)
        sy2 -= syn_h + 16

    # 3-column mini-cards: World | Core Conflict | Story Engine
    mini_data = [(lbl, val) for lbl, val in [
        ("World", world), ("Core Conflict", core or reversal), ("Story Engine", engine)
    ] if val]
    if mini_data:
        mc_n = len(mini_data)
        mc_w = (UW - (mc_n - 1) * 12) / mc_n
        mc_h = 90
        for mi, (ml, mv) in enumerate(mini_data):
            mx = L + mi * (mc_w + 12)
            pdf.setFillColor(panel); pdf.roundRect(mx, sy2 - mc_h, mc_w, mc_h, 8, stroke=0, fill=1)
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 7)
            pdf.drawString(mx + 10, sy2 - 14, ml.upper())
            mv_lines = simpleSplit(mv, "Helvetica", 9, mc_w - 18)
            _draw_lines(pdf, mv_lines[:5], mx + 10, sy2 - 28, 12, "Helvetica", 9, muted)
        sy2 -= mc_h + 16

    # Compact info rows: Lead, Theme, Setting
    for lbl, val in [("Lead Role", protagonist_sum or lead), ("Theme", theme), ("Setting", setting)]:
        if val and sy2 > 80:
            v_lines = simpleSplit(val, "Helvetica", 9, UW - 100)
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 8)
            pdf.drawString(L, sy2, lbl.upper())
            for vi, vl in enumerate(v_lines[:2]):
                pdf.setFillColor(muted); pdf.setFont("Helvetica", 9)
                pdf.drawString(L + 98, sy2 - vi * 13, vl)
            sy2 -= max(15, len(v_lines[:2]) * 13) + 4
    _footer(pdf, W, 2); pdf.showPage()

    # ── PAGE 3: MARKET POSITION ───────────────────────────────────────────────
    _page_bg(pdf, W, H, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(L, H - 58, "MARKET POSITION")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(L, H - 76, "The commercial lane and how this project compares.")
    my = H - 106

    if strength:
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(L, my - 4, "STRENGTH INDEX")
        pdf.setFillColor(muted); pdf.setFont("Helvetica", 8)
        pdf.drawString(L, my - 16, "Deterministic assessment across four market dimensions")
        # Radar on the left, compact bars on the right for detail readout
        radar_path = _render_strength_radar_png(strength)
        radar_size = 200
        if radar_path and radar_path.exists():
            pdf.drawImage(str(radar_path), L, my - 30 - radar_size,
                          width=radar_size, height=radar_size,
                          preserveAspectRatio=True, mask="auto")
            bars_x = L + radar_size + 24
            bars_w = UW - radar_size - 24
            _draw_strength_bars(pdf, strength, bars_x, my - 44, bars_w, gold, panel, white, muted)
            my = my - 30 - radar_size
            try:
                radar_path.unlink()
            except Exception:
                pass
        else:
            my = _draw_strength_bars(pdf, strength, L, my - 32, UW, gold, panel, white, muted)
        my -= 14

    if comparable_details:
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(L, my - 4, "COMPARABLE FILMS")
        my -= 22
        for comp in comparable_details[:5]:
            comp_lines = simpleSplit(comp, "Helvetica", 9, UW - 20)
            ch = max(46, len(comp_lines) * 12 + 20)
            pdf.setFillColor(panel); pdf.roundRect(L, my - ch, UW, ch, 6, stroke=0, fill=1)
            pdf.setFillColor(gold); pdf.roundRect(L, my - ch, 3, ch, 2, stroke=0, fill=1)
            yy = my - 10
            for cl in comp_lines[:4]:
                pdf.setFillColor(white); pdf.setFont("Helvetica", 9)
                pdf.drawString(L + 12, yy, cl)
                yy -= 12
            my -= ch + 8
        my -= 8

    market_rows = [(lbl, val) for lbl, val in [
        ("Budget Lane",  budget_lane), ("Streaming Fit", streamer_fit),
        ("Awards Angle", awards_lane), ("Audience",      ", ".join(audience[:4]) if audience else None),
        ("Commercial",   commercial),  ("Franchise",     franchise),
    ] if val]
    if market_rows and my > 80:
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(L, my - 4, "MARKET DETAILS")
        my -= 22
        for lbl, val in market_rows[:6]:
            if my < 80:
                break
            v_lines = simpleSplit(val, "Helvetica", 9, UW - 110)
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 8)
            pdf.drawString(L, my, lbl.upper())
            pdf.setFillColor(muted); pdf.setFont("Helvetica", 9)
            pdf.drawString(L + 108, my, v_lines[0] if v_lines else "")
            my -= 14
    _footer(pdf, W, 3); pdf.showPage()

    # ── PAGE 4: STRUCTURE + CHARACTER INTELLIGENCE ───────────────────────────
    _page_bg(pdf, W, H, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(L, H - 58, "STRUCTURE + CHARACTERS")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(L, H - 76, "The pressure arc and ensemble balance of the project.")
    ctx4 = _PDFCtx(pdf, W, H, L, UW, charcoal, gold, blue, white, muted, soft, panel)
    ctx4.y = H - 106
    ctx4.page_no = 4

    # Scene-intensity arc — visual pressure curve across the whole script
    scene_presence_map = report_output.get("scene_presence_map") or []
    if scene_presence_map:
        arc_path = _render_scene_intensity_arc_png(scene_presence_map)
        if arc_path and arc_path.exists():
            arc_h = 128
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(L, ctx4.y, "SCENE-BY-SCENE PRESSURE ARC")
            pdf.setFillColor(muted); pdf.setFont("Helvetica", 8)
            pdf.drawString(L, ctx4.y - 12, f"Intensity (1-10) across all {len(scene_presence_map)} detected scenes")
            pdf.drawImage(str(arc_path), L, ctx4.y - 24 - arc_h, width=UW, height=arc_h,
                          preserveAspectRatio=True, mask="auto")
            ctx4.y -= arc_h + 34
            try:
                arc_path.unlink()
            except Exception:
                pass

    # Character bars — top 6 by trust score
    character_rankings = report_output.get("character_rankings") or []
    if character_rankings:
        bars_path = _render_character_bars_png(character_rankings, max_chars=6)
        if bars_path and bars_path.exists():
            bars_h = 148
            pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 10)
            pdf.drawString(L, ctx4.y, "CHARACTER TRUST SCORES")
            pdf.setFillColor(muted); pdf.setFont("Helvetica", 8)
            pdf.drawString(L, ctx4.y - 12, "Weighted signal across dialogue, action, and scene presence")
            pdf.drawImage(str(bars_path), L, ctx4.y - 24 - bars_h, width=UW, height=bars_h,
                          preserveAspectRatio=True, mask="auto")
            ctx4.y -= bars_h + 30
            try:
                bars_path.unlink()
            except Exception:
                pass

    if act_breakdown:
        ctx4.section_header("Act Structure", "How the story is built across its three movements.")
        ctx4.act_breakdown_cards(act_breakdown)
        ctx4.y -= 8

    char_rows = [(lbl, val) for lbl, val in [
        ("Lead role", protagonist_sum or lead), ("Character leverage", char_leverage),
        ("Top characters", ", ".join(top_chars[:8]) if top_chars else None),
    ] if val]
    if char_rows:
        ctx4.section_header("Character Value", "Why the roles matter.")
        for lbl, val in char_rows:
            ctx4.info_row(lbl, val)
        ctx4.y -= 8

    if character_arcs:
        ctx4.section_header("Character Arcs", "Where each key role begins, transforms, and lands.")
        ctx4.character_arc_rows(character_arcs)
        ctx4.y -= 4

    if relationship_lines:
        ctx4.section_header("Relationship Map", "How each key relationship functions in the story.")
        ctx4.bullet_list(relationship_lines[:6], bullet_color=gold)

    # ── PAGE 5: DEVELOPMENT INTELLIGENCE ─────────────────────────────────────
    _footer(pdf, W, ctx4.page_no); pdf.showPage()
    page_no5 = ctx4.page_no + 1
    _page_bg(pdf, W, H, charcoal, gold)
    pdf.setFillColor(white); pdf.setFont("Helvetica-Bold", 28)
    pdf.drawString(L, H - 58, "DEVELOPMENT INTELLIGENCE")
    pdf.setFillColor(muted); pdf.setFont("Helvetica", 10)
    pdf.drawString(L, H - 76, "What is working, what to fix next, and why this project matters.")

    # 2-column: What's Working | Rewrite Priorities
    col_w5 = (UW - 18) / 2
    dev_y = H - 108
    _draw_card(pdf, L, dev_y, col_w5, 178, "What's Working",
               [str(x) for x in strengths_list[:6] if str(x).strip()], gold, panel, white, muted)
    _draw_card(pdf, L + col_w5 + 18, dev_y, col_w5, 178, "Rewrite Priorities",
               [str(x) for x in rewrite_priorities[:6] if str(x).strip()], gold, panel, white, muted)
    dev_y -= 196

    # Story insights full-width card
    si_items = [str(x).strip() for x in story_insights[:5] if str(x).strip()]
    if si_items:
        _draw_card(pdf, L, dev_y, UW, 138, "Why This Project Matters", si_items, gold, panel, white, muted)
        dev_y -= 154

    # Actor intelligence — compact 4-column if data present
    actor_cols = [(lbl, vals) for lbl, vals in [
        ("Playable Tactics",   playable_tactics[:5]),
        ("Emotional Triggers", emotional_triggers[:5]),
        ("Danger Zones",       audition_danger_zones[:5]),
        ("Reader Chemistry",   reader_chemistry_tips[:4]),
    ] if vals]
    if actor_cols and dev_y > 120:
        pdf.setStrokeColor(colors.HexColor("#252a2e")); pdf.setLineWidth(0.5)
        pdf.line(L, dev_y + 6, R, dev_y + 6)
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(L, dev_y - 8, "ACTOR INTELLIGENCE")
        dev_y -= 28
        ac_w = (UW - (len(actor_cols) - 1) * 8) / len(actor_cols)
        ac_h = min(dev_y - 50, 110)
        if ac_h > 60:
            for ai, (al, av) in enumerate(actor_cols):
                _draw_card(pdf, L + ai * (ac_w + 8), dev_y, ac_w, ac_h, al, av, gold, panel, white, muted)
            dev_y -= ac_h + 10

    # Risks (compact)
    if risks_list and dev_y > 80:
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(L, dev_y - 6, "THINGS TO WATCH")
        dev_y -= 20
        for risk in risks_list[:4]:
            if dev_y < 80:
                break
            r_chunk = simpleSplit(str(risk).strip(), "Helvetica", 9, UW - 20)
            pdf.setFillColor(colors.HexColor("#e05252")); pdf.setFont("Helvetica-Bold", 9)
            pdf.drawString(L, dev_y, "!")
            pdf.setFillColor(muted); pdf.setFont("Helvetica", 9)
            pdf.drawString(L + 12, dev_y, r_chunk[0] if r_chunk else "")
            dev_y -= 14

    # Methodology box
    meth_items = _methodology_lines()
    meth_lines_flat = []
    for item in meth_items:
        meth_lines_flat.extend(simpleSplit(item, "Helvetica", 9, UW - 34))
    mbox_h = max(84, len(meth_lines_flat) * 11 + 34)
    if dev_y - mbox_h < 40:
        _footer(pdf, W, page_no5); pdf.showPage(); page_no5 += 1
        _page_bg(pdf, W, H, charcoal, gold)
        dev_y = H - 56
    mbox_y = dev_y - 18
    pdf.setFillColor(panel); pdf.roundRect(L, mbox_y - mbox_h, UW, mbox_h, 12, stroke=0, fill=1)
    pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(L + 14, mbox_y - 14, "Sources & Methodology")
    yy = mbox_y - 30
    for item in meth_items:
        bl = simpleSplit(item, "Helvetica", 9, UW - 34)
        pdf.setFillColor(gold); pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(L + 14, yy, "•")
        yy = _draw_lines(pdf, bl, L + 28, yy, 11, "Helvetica", 9, muted)
        yy -= 2

    _footer(pdf, W, page_no5)
    pdf.save()

#========== DAI DECK PIPELINE ==============
def run_deck_pipeline(script_path=None, project_id=None, user_id=None):
    """
    Main DAI deck lane.
    Central wrapper for deck generation flow.
    Safe first bridge step.
    """

    import subprocess
    import os
    from pathlib import Path

    base_dir = Path(__file__).resolve().parent

    cmd = ["python3", str(base_dir / "run_pipeline.py")]

    env = os.environ.copy()

    if script_path:
        env["DAI_SCRIPT_PATH"] = str(script_path)

    if project_id:
        env["DAI_PROJECT_ID"] = str(project_id)

    if user_id:
        env["DAI_USER_ID"] = str(user_id)

    result = subprocess.run(
        cmd,
        cwd=str(base_dir),
        env=env,
        capture_output=True,
        text=True
    )

    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr
    }

