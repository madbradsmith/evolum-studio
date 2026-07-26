# SINGLE BRAIN ORCHESTRATOR — AI-NATIVE VERSION
# Character stat counting is mechanical. All story analysis via Claude Sonnet.

import sys
import json
import os
import re
from pathlib import Path
from pypdf import PdfReader

APP_DIR = Path(__file__).resolve().parent
OUT = Path(__file__).parent / "approved_brain_output.json"

SCENE_PREFIXES = ("INT.", "EXT.", "INT/", "EXT/")
NON_CHARACTER_PHRASES = {
    "OPENING CREDITS", "END CREDITS", "TITLE CARD",
    "FADE TO BLACK", "FADE IN", "FADE OUT", "FADE UP", "FADE UP ON",
    "CUT TO", "CUT TO:", "TIME CUT", "TIME CUT:",
    "SMASH CUT TO", "SMASH CUT TO:", "DISSOLVE TO", "DISSOLVE TO:",
    "MATCH CUT TO", "MATCH CUT TO:", "BACK TO SCENE", "BACK TO PRESENT",
    "THE END", "BLACK", "END", "SUPER", "INSERT", "INTERCUT",
    "CONTINUED", "MONTAGE", "END MONTAGE", "SERIES OF SHOTS",
    "LATER", "MOMENTS LATER", "ANGLE ON", "CLOSE ON", "WIDE ON",
    "FLASHBACK", "FLASH ON", "FLASH OFF", "SUBTITLE APPEARS BELOW"
}
BAD_TOKENS = {
    "INT", "EXT", "CUT", "FADE", "UP", "ON", "TIME", "FLASH",
    "ANGLE", "WIDE", "CLOSE", "SCENE", "PRESENT"
}
SUSPICIOUS_SINGLE_WORDS = {
    "VIDEO", "TRUNK", "ROOM", "CAR", "DOOR", "HOUSE", "STREET", "WINDOW", "PHONE", "RADIO", "TV",
    "TELEVISION", "HALLWAY", "KITCHEN", "BEDROOM", "BATHROOM", "OFFICE", "DESK", "TABLE", "CHAIR",
    "GARAGE", "PORCH", "ALLEY", "ROAD", "FREEWAY", "AIRPORT", "STATION", "PLANE", "TRAIN", "BUS",
    "MOTEL", "HOTEL", "STORE", "SHOP", "BAR", "CLUB", "YARD", "PARKING", "LOT", "ROOF", "BASEMENT",
    "ATTIC", "ELEVATOR", "STAIRS", "TRUCK", "VAN", "SUV", "COUCH", "BED", "SOFA", "CAMERA",
    "SCREEN", "MONITOR", "FILE", "BOX", "BAG", "SUITCASE", "MAP", "EXCHANGE", "SESSION", "GROCERY"
}
GENERIC_ROLE_WORDS = {
    "MAN", "WOMAN", "GUY", "GIRL", "BOY", "CUSTOMER", "DRIVER", "PASSENGER", "CASHIER",
    "CLERK", "COP", "OFFICER", "WAITER", "WAITRESS", "BARTENDER", "HOST", "HOSTESS",
    "VOICE", "ANNOUNCER", "DISPATCH", "OPERATOR"
}
PRONOUN_WORDS = {
    "I", "ME", "MY", "MINE", "MYSELF",
    "YOU", "YOUR", "YOURS", "YOURSELF", "YOURSELVES",
    "HE", "HIM", "HIS", "HIMSELF",
    "SHE", "HER", "HERS", "HERSELF",
    "IT", "ITS", "ITSELF",
    "WE", "US", "OUR", "OURS", "OURSELVES",
    "THEY", "THEM", "THEIR", "THEIRS", "THEMSELVES"
}
SHOT_PREFIXES = {"CU", "ECU", "WS", "MS", "MLS", "MCU", "POV", "OS", "O.S.", "V.O.", "VO", "ANGLE", "ON", "UNDER", "OVER", "MEDIUM", "CLOSE", "WIDE"}


def normalize(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


_METADATA_PREFIXES = (
    "tone:", "genre:", "written by:", "draft:", "revision:", "format:",
    "written:", "author:", "contact:", "by:", "wga:", "registered:",
    "fade in:", "fade out:", "copyright:", "©", "all rights",
)

def extract_title(text: str) -> str:
    candidates = []
    for line in text.splitlines():
        stripped = line.strip().replace("﻿", "")
        if not stripped:
            continue
        lower = stripped.lower()
        if any(lower.startswith(p) for p in _METADATA_PREFIXES):
            continue
        # Skip lines that look like metadata (contain colon near the start)
        if ":" in stripped[:20] and len(stripped) < 60:
            continue
        candidates.append(stripped)
        if len(candidates) >= 8:
            break

    # Prefer a short all-caps line (classic screenplay title format)
    for c in candidates:
        if c == c.upper() and 2 < len(c) < 80 and not c.startswith("EXT.") and not c.startswith("INT."):
            return c.title()

    # Otherwise take the first non-metadata candidate
    if candidates:
        return candidates[0]
    return "Untitled"


def is_scene_heading(line: str) -> bool:
    return line.upper().startswith(SCENE_PREFIXES)


def clean_name(name: str) -> str:
    name = re.sub(r"\(.*?\)", "", name).strip()
    name = name.rstrip(":")
    name = re.sub(r"[.]+$", "", name).strip()
    name = re.sub(r"\s{2,}", " ", name)
    return name


def is_caps_candidate(line: str) -> bool:
    if not line or line != line.upper():
        return False
    line = normalize(line)
    if len(line) < 2 or len(line) > 40:
        return False
    if any(ch.isdigit() for ch in line):
        return False
    if "+" in line:
        return False
    if line.count("(") > 1 or line.count(")") > 1:
        return False
    return bool(re.fullmatch(r"[A-Z .'/\-():!?&]+", line))


def is_valid_character_name(name: str) -> bool:
    if not name:
        return False
    name = clean_name(name).strip()
    if not name:
        return False
    if any(ch.isdigit() for ch in name):
        return False
    if "+" in name:
        return False
    if len(name) < 2:
        return False
    if name in NON_CHARACTER_PHRASES:
        return False
    if name in GENERIC_ROLE_WORDS or name in PRONOUN_WORDS:
        return False
    if len(name.split()) > 3:
        return False
    if len(re.findall(r"[A-Z]", name)) < 2:
        return False
    if re.search(r"[^A-Z '\-.]", name):
        return False
    return True


def salvage_candidate(upper: str):
    tokens = upper.split()
    if not tokens or upper in NON_CHARACTER_PHRASES:
        return None
    if tokens[0] in {"A", "AN", "THE"}:
        return None
    if len(tokens) == 2 and tokens[0] in SHOT_PREFIXES:
        return tokens[1]
    if len(tokens) == 3 and tokens[1] == "AND":
        return [tokens[0], tokens[2]]
    return upper


def looks_like_dialogue_follow(lines, i: int) -> int:
    for j in range(i + 1, min(i + 5, len(lines))):
        nxt = normalize(lines[j])
        if not nxt:
            continue
        if is_scene_heading(nxt):
            return 0
        if nxt == nxt.upper():
            return 0
        return 1
    return 0


def analyze_dialogue_characters(text: str):
    lines = text.splitlines()
    counts, first_seen, dialogue_support = {}, {}, {}
    for i, raw in enumerate(lines):
        line = normalize(raw)
        if not line or i < 6 or is_scene_heading(line) or not is_caps_candidate(line):
            continue
        cleaned = clean_name(line).upper()
        salvaged = salvage_candidate(cleaned)
        if salvaged is None:
            continue
        candidates = salvaged if isinstance(salvaged, list) else [salvaged]
        for c in candidates:
            c = clean_name(c).upper()
            if not c or c in NON_CHARACTER_PHRASES or len(c.split()) > 3:
                continue
            if any(tok in BAD_TOKENS for tok in c.split()):
                continue
            if len(c.split()) == 1 and c in SUSPICIOUS_SINGLE_WORDS:
                continue
            if c in GENERIC_ROLE_WORDS or c in PRONOUN_WORDS:
                continue
            if not is_valid_character_name(c):
                continue
            counts[c] = counts.get(c, 0) + 1
            if c not in first_seen:
                first_seen[c] = i
            dialogue_support[c] = dialogue_support.get(c, 0) + looks_like_dialogue_follow(lines, i)
    return counts, first_seen, dialogue_support


def is_likely_action_line(line: str) -> bool:
    if not line:
        return False
    if is_scene_heading(line):
        return False
    if line == line.upper():
        return False
    if line.endswith(":"):
        return False
    return True


def extract_action_names(text: str):
    lines = text.splitlines()
    action_counts = {}
    action_first_seen = {}
    for i, raw in enumerate(lines):
        line = normalize(raw)
        if not is_likely_action_line(line):
            continue
        names = re.findall(r"\b([A-Z][a-z]{2,})\b", line)
        for name in names:
            upper = name.upper()
            if upper in GENERIC_ROLE_WORDS or upper in BAD_TOKENS or upper in SUSPICIOUS_SINGLE_WORDS:
                continue
            if upper in PRONOUN_WORDS or upper in {"THE", "A", "AN"}:
                continue
            action_counts[upper] = action_counts.get(upper, 0) + 1
            if upper not in action_first_seen:
                action_first_seen[upper] = i
        full_names = re.findall(r"\b([A-Z][a-z]{2,}\s+[A-Z][a-z]{2,})\b", line)
        for full in full_names:
            upper = full.upper()
            if any(tok in GENERIC_ROLE_WORDS or tok in PRONOUN_WORDS for tok in upper.split()):
                continue
            action_counts[upper] = action_counts.get(upper, 0) + 1
            if upper not in action_first_seen:
                action_first_seen[upper] = i
    return action_counts, action_first_seen


def merge_character_signals(dialogue_counts, dialogue_first, dialogue_support, action_counts, action_first):
    all_names = set(dialogue_counts) | set(action_counts)
    scored = []

    for name in all_names:
        d = dialogue_counts.get(name, 0)
        a = action_counts.get(name, 0)
        first = min(dialogue_first.get(name, 99999), action_first.get(name, 99999))
        score = 0
        score += d * 2
        score += dialogue_support.get(name, 0) * 3
        score += a * 4
        if first < 80:
            score += 4
        elif first < 160:
            score += 2
        if d > 0 and a > 0:
            score += 4
        if a >= 3:
            score += 5
        if d == 1 and a == 0:
            score -= 2
        scored.append((name, score, d, a, first))

    scored.sort(key=lambda x: (-x[1], x[4], x[0]))

    ordered = []
    seen = set()
    for name, score, d, a, first in scored:
        if name in seen:
            continue
        tokens = name.split()
        drop = False
        if len(tokens) == 1:
            for other, _, od, oa, _ in scored:
                if other == name:
                    continue
                other_tokens = other.split()
                if len(other_tokens) > 1 and tokens[0] in other_tokens and (od + oa) >= (d + a):
                    drop = True
                    break
        if not drop:
            seen.add(name)
            ordered.append(name)

    stats = {
        name: {
            "dialogue_count": dialogue_counts.get(name, 0),
            "action_count": action_counts.get(name, 0),
            "first_seen": min(dialogue_first.get(name, 99999), action_first.get(name, 99999)),
        }
        for name in ordered
    }
    return ordered[:8], stats


# ─── AI-NATIVE STORY ANALYSIS ────────────────────────────────────────────────

def _world_category(world: str) -> str:
    """Map Claude's free-form world description to a visual/layout category."""
    w = world.lower()
    # Espionage / covert ops — check before generic thriller
    if any(t in w for t in ["espionage", "spy", "covert", "assassin", "secret agent", "operative", "cia", "cia operative", "intel agency"]):
        return "action_espionage"
    # Contained single-location urban thrillers
    if any(t in w for t in ["rideshare", "cab driver", "contained urban", "urban thriller", "single night", "one location"]):
        return "contained_urban"
    # Courtroom / legal drama — check before generic legal/romance overlap
    if any(t in w for t in ["courtroom", "trial", "tribunal", "military court", "court martial", "prosecution", "verdict"]):
        return "legal_courtroom"
    # Fantasy / satire / medieval — check before other comedy
    if any(t in w for t in ["fantasy", "medieval", "kingdom", "wizard", "dragon", "satire", "storybook", "fairy tale", "mythical"]):
        return "fantasy_satire"
    # Romantic comedy — explicit signals first
    if any(t in w for t in ["romantic comedy", "rom-com", "rom com", "love story", "love interest", "meet cute"]):
        return "romantic_comedy"
    # Legal + romantic overlap (law school rom-com etc.)
    if any(t in w for t in ["legal", "law school", "law firm"]) and any(t in w for t in ["comedy", "romance", "romantic", "relationship"]):
        return "romantic_comedy"
    # Romance without legal qualifier
    if any(t in w for t in ["romance", "romantic", "sorority", "wedding comedy", "relationship comedy"]):
        return "romantic_comedy"
    # Remaining legal/courtroom (no romantic element)
    if any(t in w for t in ["legal", "law", "attorney", "lawyer", "courtroom"]):
        return "legal_courtroom"
    # Nightlife / social comedy
    if any(t in w for t in ["nightlife", "club scene", "party", "nightclub", "velvet rope", "social comedy"]):
        return "nightlife_comedy"
    # Sports
    if any(t in w for t in ["sports", "basketball", "football", "soccer", "baseball", "athlete", "coach", "championship"]):
        return "sports_drama"
    # Crime / heist / underworld
    if any(t in w for t in ["crime", "heist", "gangster", "cartel", "mob", "drug", "underworld", "organized crime"]):
        return "crime_drama"
    # Generic thriller / suspense
    if any(t in w for t in ["thriller", "suspense", "psychological thriller", "paranoia"]):
        return "thriller"
    return "drama"


_ANALYSIS_SYSTEM = """You are a Hollywood screenplay analyst. Read the screenplay and return a story map as a single raw JSON object.

CRITICAL RULES:
- Return ONLY the JSON — no markdown, no code fences, no extra text.
- Every string value must be CONCISE — under 20 words unless explicitly noted.
- Lists must have at most the number of items shown in the example.
- The entire JSON response must fit in 3500 tokens. Be tight.

{
  "title": "title as written in the screenplay",
  "world": "specific genre + world in 6-10 words (e.g. 'warm law-school romantic comedy', 'slow-burn Appalachian crime thriller')",
  "tone": "3-5 tone words, comma-separated",
  "setting": "where this story takes place, 10 words max",
  "time_frame": "time span of the story, 6 words max",
  "logline": "A short demo logline. Replace this sample slate with your own projects.",
  "tagline": "marketing hook, under 10 words",
  "synopsis": "what happens and what is at stake — 80-100 words total",
  "theme": "A sample theme line.",
  "story_engine": "what drives THIS story forward, 10 words max",
  "core_conflict": "the central tension, 10 words max",
  "reversal": "the key reversal or revelation, 12 words max",
  "protagonist": "protagonist name exactly as in the script",
  "protagonist_summary": "who they are and what drives them, under 20 words",
  "characters": ["top 5 character names exactly as written"],
  "character_arcs": {
    "CHARACTER_NAME": {
      "beginning_state": "8 words max",
      "end_state": "8 words max",
      "transformation": "10 words max"
    }
  },
  "relationship_leverage_map": [
    {"character": "name", "dynamic": "6 words", "function": "8 words"}
  ],
  "act_breakdown": {
    "act_1": {"scene_range": "Scenes 1-28", "summary": "15 words max", "key_beats": ["Scene N: 10 words", "Scene N: 10 words"], "turning_point": "Scene N: 8 words"},
    "act_2": {"scene_range": "Scenes 29-80", "summary": "15 words max", "key_beats": ["Scene N: 10 words", "Scene N: 10 words"], "turning_point": "Scene N: 8 words"},
    "act_3": {"scene_range": "Scenes 81-110", "summary": "15 words max", "key_beats": ["Scene N: 10 words", "Scene N: 10 words"], "turning_point": "Scene N: 8 words"}
  },
  "executive_summary": "producer-facing pitch, 2 sentences max",
  "commercial_positioning": "how this sells today, 15 words max",
  "packaging_potential": "what casting makes this work, 12 words max",
  "character_leverage": "commercial and awards appeal, 12 words max",
  "comparable_films": [
    {"title": "Film Title", "why": "Cross-reference tone + world + budget + story structure — 15 words max on which axes match", "budget_tier": "micro/low/low-mid/mid/mid-to-studio/studio", "box_office": "$XM"},
    {"title": "Film Title", "why": "Not just genre — explain the structural or tonal reason this comp is accurate", "budget_tier": "micro/low/low-mid/mid/mid-to-studio/studio", "box_office": "$XM"},
    {"title": "Film Title", "why": "Prefer last 20 years; include one that shows distribution/awards upside if applicable", "budget_tier": "micro/low/low-mid/mid/mid-to-studio/studio", "box_office": "$XM"}
  ],
  "tone_comparables": ["Film 1", "Film 2", "Film 3"],
  "audience_profile": ["segment 1", "segment 2", "segment 3"],
  "market_projections": {
    "budget_range": "dollar range",
    "distribution_angle": "streaming-first / theatrical / limited",
    "awards_potential": "honest 6-word assessment",
    "audience_reach": "who sees this, 8 words",
    "franchise_potential": "yes/no + 6 words"
  },
  "strength_index": {"concept": 8, "character": 9, "marketability": 7, "originality": 8},
  "strengths": ["strength 1, 8 words", "strength 2, 8 words", "strength 3, 8 words"],
  "development_risks": ["risk 1, 8 words", "risk 2, 8 words", "risk 3, 8 words"],
  "actor_objective": "what the lead must accomplish, 12 words",
  "role_arc_map": ["stage 1", "stage 2", "stage 3", "stage 4", "stage 5"],
  "pressure_ladder": ["beat 1", "beat 2", "beat 3", "beat 4", "beat 5"],
  "emotional_continuity": ["note 1, 10 words", "note 2, 10 words"],
  "playable_tactics": ["tactic 1", "tactic 2", "tactic 3", "tactic 4"],
  "emotional_triggers": ["trigger 1", "trigger 2", "trigger 3"],
  "audition_danger_zones": ["pitfall 1, 8 words", "pitfall 2, 8 words"],
  "reader_chemistry_tips": ["tip 1, 10 words", "tip 2, 10 words"],
  "memorization_beats": ["beat 1, 8 words", "beat 2, 8 words"],
  "costume_behavior_clues": ["clue 1, 8 words", "clue 2, 8 words"],
  "set_ready_checklist": ["item 1, 8 words", "item 2, 8 words", "item 3, 8 words"],
  "visual_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6"],
  "character_voice": {
    "CHARACTER_NAME": "10-12 words: how they actually speak, vocabulary, rhythm, what they avoid",
    "CHARACTER_NAME": "10-12 words: specific to THIS script, not generic actor notes"
  },
  "investor_hooks": [
    "Specific pitchable moment from the actual script — concrete scene or line, under 20 words",
    "Another specific moment — not a genre claim, an actual story beat that makes investors lean in",
    "Third hook if warranted — the reversal, the central image, the line that lands"
  ],
  "exposition_heavy_scenes": [
    {"scene": "Scene N or heading", "issue": "what is being over-explained, under 15 words", "example": "the specific line or exchange that flags it, quoted, under 20 words"},
    {"scene": "Scene N or heading", "issue": "characters recapping events both lived through", "example": "quoted line or exchange"}
  ],
  "on_the_nose_moments": [
    {"scene": "Scene N or heading", "line": "the exact line that states what should be implied", "subtext": "what it should be showing instead, under 10 words"},
    {"scene": "Scene N or heading", "line": "another on-the-nose line", "subtext": "the emotion or truth it telegraphs too directly"}
  ]
}"""


def _write_brain_tokens(usage) -> None:
    _work = os.environ.get("DAI_WORK_DIR", "")
    _f = Path(_work) / "pipeline_tokens.json" if _work else APP_DIR / "pipeline_tokens.json"
    try:
        existing = json.loads(_f.read_text(encoding="utf-8")) if _f.exists() else {}
    except Exception:
        existing = {}
    existing["brain"] = {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "model": "claude-haiku-4-5-20251001",
    }
    try:
        _f.write_text(json.dumps(existing), encoding="utf-8")
    except Exception:
        pass


def analyze_script_with_claude(text: str, title: str, char_stats: dict) -> dict:
    """Single Claude Haiku call — generates all story fields from the actual screenplay."""
    api_key = None  # API removed — engine is fully deterministic
    if not api_key:
        return _fallback_story_map(text, title, list(char_stats.keys()), char_stats)
    try:
        import anthropic
    except ImportError:
        return _fallback_story_map(text, title, list(char_stats.keys()), char_stats)

    char_hint = ", ".join(list(char_stats.keys())[:12])
    # Cap screenplay at 120K chars (~30K tokens) to keep API time under Gunicorn timeout
    script_body = text[:120_000] if len(text) > 120_000 else text
    user_msg = (
        f"Title (from first line): {title}\n"
        f"Mechanically-detected character candidates (hints only — correct as needed): {char_hint}\n\n"
        f"FULL SCREENPLAY:\n{script_body}"
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=[{"type": "text", "text": _ANALYSIS_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = next((b.text for b in message.content if hasattr(b, "text")), "")
        if not raw:
            print("⚠️  Claude analysis: empty response — using fallback")
            return _fallback_story_map(text, title, list(char_stats.keys()), char_stats)
        _write_brain_tokens(message.usage)
        # Strip code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned.rstrip())
        # If Haiku wrapped the JSON in prose, extract the outermost {...} block
        if not cleaned.startswith("{"):
            m = re.search(r"\{[\s\S]*\}", cleaned)
            if m:
                cleaned = m.group(0)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as je:
            print(f"⚠️  Claude JSON parse failed ({je}) — raw[:200]: {raw[:200]}")
            return _fallback_story_map(text, title, list(char_stats.keys()), char_stats)
    except Exception as e:
        print(f"⚠️  Claude analysis failed: {e}")
        return _fallback_story_map(text, title, list(char_stats.keys()), char_stats)


# ─── SCENE SEGMENTATION + PRESENCE MAP (Phase 2) ─────────────────────────
# Ported from FINAL_OUTPUT_ENFORCER. Split screenplay into scenes, score each
# scene's intensity + emotional temperature, track which characters appear
# where. Feeds real act_breakdown (scene ranges + turning points) and
# character_arcs work in later phases.

FILLER_WORDS = {
    "A", "AN", "THE", "AND", "OR", "BUT", "IF", "SO", "AS", "AT", "BY", "FOR", "FROM",
    "IN", "INTO", "OF", "OFF", "ON", "ONTO", "OUT", "OVER", "TO", "UP", "WITH"
}


def normalize_character_key(name: str) -> str:
    return clean_name(name).upper()


def detect_character_mentions_in_line(line: str, characters: list) -> set:
    found = set()
    padded = f" {line.upper()} "
    for name in characters:
        key = normalize_character_key(name)
        if not key:
            continue
        tokens = [re.escape(tok) for tok in key.split() if tok and tok not in FILLER_WORDS]
        if not tokens:
            continue
        pattern = r"\b" + r"\s+".join(tokens) + r"\b"
        if re.search(pattern, padded):
            found.add(key)
    return found


def split_into_scenes(text: str) -> list:
    """Break screenplay into scene records at every INT./EXT. heading."""
    lines = text.splitlines()
    scenes = []
    current = None
    for idx, raw in enumerate(lines, start=1):
        line = normalize(raw)
        if is_scene_heading(line):
            if current:
                scenes.append(current)
            current = {
                "scene_number": len(scenes) + 1,
                "heading": line,
                "start_line": idx,
                "lines": [],
            }
            continue
        if current is None:
            current = {
                "scene_number": 1,
                "heading": "PRE-SCENE / FRONT MATTER",
                "start_line": 1,
                "lines": [],
            }
        current["lines"].append({"line_number": idx, "text": line})
    if current:
        scenes.append(current)
    for scene in scenes:
        non_blank = [item["text"] for item in scene["lines"] if item["text"]]
        scene["line_count"] = len(non_blank)
    return scenes


def infer_scene_type(scene_heading: str, scene_lines: list) -> str:
    heading = (scene_heading or "").upper()
    block = " ".join(scene_lines[:12]).lower()
    if any(token in heading for token in ["COURT", "TRIAL", "HEARING", "CHAMBER"]):
        return "institutional"
    if any(token in heading for token in ["CAR", "SUV", "TRUCK", "VAN", "UBER", "LYFT"]):
        return "vehicle"
    if any(token in heading for token in ["HOME", "HOUSE", "APARTMENT", "KITCHEN", "BEDROOM"]):
        return "domestic"
    if any(token in heading for token in ["STREET", "ALLEY", "ROAD", "PARKING", "LOT"]):
        return "street"
    if any(token in heading for token in ["CLUB", "BAR", "PARTY"]):
        return "social"
    if any(token in heading for token in ["CASTLE", "THRONE", "KINGDOM"]):
        return "royal"
    if any(token in block for token in ["argues", "fight", "gun", "threat", "panic", "pressure"]):
        return "conflict"
    if any(token in block for token in ["laugh", "joke", "awkward", "comic"]):
        return "comic"
    return "dramatic"


def score_scene_intensity(scene_heading: str, scene_lines: list) -> int:
    """Score scene 1-10 by intensity keyword hits + exclamations + heading tokens."""
    text = " ".join(scene_lines).lower()
    score = 1
    intensity_terms = [
        "gun", "blood", "fight", "panic", "run", "scream", "threat", "police", "sirens",
        "explosion", "bomb", "chase", "cry", "breaks down", "confession", "trial", "verdict",
        "accuse", "arrest", "attack", "yell", "slams", "storms"
    ]
    for term in intensity_terms:
        if term in text:
            score += 1
    if "!" in " ".join(scene_lines):
        score += 1
    if any(token in scene_heading.upper() for token in ["NIGHT", "ALLEY", "INTERROGATION", "COURTROOM"]):
        score += 1
    return max(1, min(score, 10))


def infer_emotional_temperature(scene_lines: list) -> str:
    text = " ".join(scene_lines).lower()
    if any(term in text for term in ["panic", "cry", "breaks down", "terrified", "desperate", "shaking"]):
        return "raw"
    if any(term in text for term in ["threat", "gun", "police", "pressure", "chase", "suspicion"]):
        return "tense"
    if any(term in text for term in ["laugh", "joke", "awkward", "funny"]):
        return "comic"
    if any(term in text for term in ["kiss", "touch", "love", "warm", "smile"]):
        return "warm"
    if any(term in text for term in ["argues", "fight", "accuses", "storms out"]):
        return "volatile"
    return "controlled"


def build_scene_presence_map(text: str, characters: list, character_stats: dict) -> tuple:
    """For every scene: which characters appear, who speaks, scene type + intensity + temperature.
    Returns (scene_records list, presence_totals dict keyed by character)."""
    scenes = split_into_scenes(text)
    character_keys = [normalize_character_key(c) for c in characters]
    ranking = {normalize_character_key(name): idx + 1 for idx, name in enumerate(characters)}
    presence_totals = {
        key: {
            "scene_count": 0, "speaking_scenes": 0, "mentioned_scenes": 0,
            "act_buckets": set(), "scenes": [],
        }
        for key in character_keys
    }
    total_scene_count = max(1, len(scenes))
    for scene in scenes:
        lines = [item["text"] for item in scene["lines"] if item["text"]]
        speakers = set()
        mentions = set()
        for line in lines:
            if is_caps_candidate(line):
                cleaned = normalize_character_key(line)
                if cleaned in character_keys:
                    speakers.add(cleaned)
                    mentions.add(cleaned)
                    continue
            mentions.update(detect_character_mentions_in_line(line, characters))
        present = set(speakers) | set(mentions)
        weighted_present = sorted(
            present,
            key=lambda name: (
                name not in speakers,
                ranking.get(name, 999),
                character_stats.get(name, {}).get("first_seen", 99999),
                name,
            ),
        )
        act_idx = min(3, int(((scene["scene_number"] - 1) / total_scene_count) * 3) + 1)
        scene_record = {
            "scene_number": scene["scene_number"],
            "heading": scene["heading"],
            "scene_type": infer_scene_type(scene["heading"], lines),
            "conflict_intensity": score_scene_intensity(scene["heading"], lines),
            "emotional_temperature": infer_emotional_temperature(lines),
            "characters_present": weighted_present,
            "speaking_characters": sorted(speakers),
            "line_count": scene.get("line_count", len(lines)),
            "start_line": scene.get("start_line"),
        }
        scene["record"] = scene_record
        for name in present:
            bucket = presence_totals.setdefault(name, {
                "scene_count": 0, "speaking_scenes": 0, "mentioned_scenes": 0,
                "act_buckets": set(), "scenes": [],
            })
            bucket["scene_count"] += 1
            bucket["mentioned_scenes"] += 1
            if name in speakers:
                bucket["speaking_scenes"] += 1
            bucket["act_buckets"].add(act_idx)
            bucket["scenes"].append(scene["scene_number"])
    scene_records = [scene["record"] for scene in scenes]
    for name, bucket in presence_totals.items():
        bucket["act_presence"] = len(bucket.pop("act_buckets", set()))
        bucket["scenes"] = sorted(bucket["scenes"])
    return scene_records, presence_totals


def build_character_rankings(characters: list, character_stats: dict, scene_presence_totals: dict, protagonist: str) -> list:
    """Trust-score per character (0-100) via weighted signal aggregation:
    dialogue×3, action×4, scene×5, speaking×4, act_presence×6, first-seen bonus, protagonist bonus."""
    protagonist_key = normalize_character_key(protagonist)
    rankings = []
    for idx, name in enumerate(characters, start=1):
        key = normalize_character_key(name)
        stats = character_stats.get(key, character_stats.get(name, {}))
        presence = scene_presence_totals.get(key, {})
        dialogue = stats.get("dialogue_count", 0)
        action = stats.get("action_count", 0)
        first_seen = stats.get("first_seen", 99999)
        scene_count = presence.get("scene_count", 0)
        speaking_scenes = presence.get("speaking_scenes", 0)
        act_presence = presence.get("act_presence", 0)

        trust_score = 40
        trust_score += min(dialogue * 3, 24)
        trust_score += min(action * 4, 24)
        trust_score += min(scene_count * 5, 25)
        trust_score += min(speaking_scenes * 4, 20)
        trust_score += act_presence * 6
        if first_seen < 80:
            trust_score += 6
        elif first_seen < 160:
            trust_score += 3
        if idx == 1 or key == protagonist_key:
            trust_score += 10
        trust_score = max(0, min(100, trust_score))
        confidence = "high" if trust_score >= 85 else ("medium" if trust_score >= 65 else "low")

        rankings.append({
            "rank": 0,
            "name": key,
            "dialogue_count": dialogue,
            "action_count": action,
            "scene_count": scene_count,
            "speaking_scenes": speaking_scenes,
            "act_presence": act_presence,
            "first_seen": first_seen,
            "trust_score": trust_score,
            "confidence": confidence,
            "is_protagonist": key == protagonist_key,
        })
    rankings.sort(key=lambda item: (-item["trust_score"], item["first_seen"], item["name"]))
    for rank, item in enumerate(rankings, start=1):
        item["rank"] = rank
    return rankings


def build_relationship_matrix(characters: list, scene_presence_map: list, protagonist: str) -> list:
    """For each non-protagonist character: co-scenes with protagonist, speaking overlap,
    high-intensity co-scene count. Classifies dynamic as obstacle / ally / pressure source / complication."""
    protagonist_key = normalize_character_key(protagonist)
    totals = {normalize_character_key(name): {"co_scenes": 0, "speaking_overlap": 0, "high_intensity_overlap": 0} for name in characters}

    for scene in scene_presence_map:
        present = set(scene.get("characters_present", []))
        speakers = set(scene.get("speaking_characters", []))
        if protagonist_key not in present:
            continue
        for name in list(totals.keys()):
            if name == protagonist_key:
                continue
            if name in present:
                totals[name]["co_scenes"] += 1
                if name in speakers and protagonist_key in speakers:
                    totals[name]["speaking_overlap"] += 1
                if scene.get("conflict_intensity", 1) >= 7:
                    totals[name]["high_intensity_overlap"] += 1

    relationships = []
    for name, data in totals.items():
        if name == protagonist_key or data["co_scenes"] == 0:
            continue
        if data["high_intensity_overlap"] >= 2:
            dynamic = "obstacle"
        elif data["speaking_overlap"] >= 3 and data["co_scenes"] >= 3:
            dynamic = "ally"
        elif data["co_scenes"] >= 2 and data["speaking_overlap"] <= 1:
            dynamic = "pressure source"
        else:
            dynamic = "complication"
        leverage_score = min(100, 45 + data["co_scenes"] * 10 + data["speaking_overlap"] * 8 + data["high_intensity_overlap"] * 10)
        relationships.append({
            "from": protagonist_key,
            "to": name,
            "dynamic": dynamic,
            "co_scene_count": data["co_scenes"],
            "speaking_overlap": data["speaking_overlap"],
            "high_intensity_overlap": data["high_intensity_overlap"],
            "leverage_score": leverage_score,
        })
    relationships.sort(key=lambda item: (-item["leverage_score"], item["to"]))
    return relationships


def build_actor_prep_signal_map(characters: list, scene_presence_map: list) -> dict:
    """Per top-5 character: up to 12 scene beat records (heading, type, intensity, temp, speaking).
    This is what lets actor prep reports read scene-specific instead of generic."""
    result = {}
    for name in characters[:5]:
        key = normalize_character_key(name)
        beats = []
        for scene in scene_presence_map:
            if key not in scene.get("characters_present", []):
                continue
            beats.append({
                "scene_number": scene["scene_number"],
                "heading": scene["heading"],
                "scene_type": scene["scene_type"],
                "conflict_intensity": scene["conflict_intensity"],
                "emotional_temperature": scene["emotional_temperature"],
                "speaking": key in scene.get("speaking_characters", []),
            })
        result[key] = beats[:12]
    return result


def build_confidence_layer(characters: list, character_rankings: list, scene_presence_map: list) -> dict:
    """Per-character trust reasoning + overall pipeline confidence."""
    ranking_map = {item["name"]: item for item in character_rankings}
    character_confidence = {}
    for name in characters:
        key = normalize_character_key(name)
        info = ranking_map.get(key, {})
        reasons = []
        if info.get("dialogue_count", 0) > 0:
            reasons.append("has dialogue signal")
        if info.get("action_count", 0) > 0:
            reasons.append("has action-line signal")
        if info.get("scene_count", 0) >= 2:
            reasons.append("appears across multiple scenes")
        if info.get("act_presence", 0) >= 2:
            reasons.append("spans multiple act buckets")
        character_confidence[key] = {
            "level": info.get("confidence", "low"),
            "trust_score": info.get("trust_score", 0),
            "reasons": reasons or ["limited evidence"],
        }
    scene_count = len(scene_presence_map)
    overall = "high" if scene_count >= 8 else "medium" if scene_count >= 3 else "low"
    return {
        "overall": overall,
        "character_confidence": character_confidence,
        "scene_parser": {"scene_count": scene_count, "level": overall},
    }


def build_relationship_leverage_map_for_templates(relationship_matrix: list) -> list:
    """Reshape relationship_matrix into the {character, dynamic, function} shape templates expect."""
    dyn_to_function = {
        "obstacle": "antagonistic force",
        "ally": "collaborative partner",
        "pressure source": "external stakeholder",
        "complication": "catalyst",
    }
    return [
        {
            "character": r["to"],
            "dynamic": r["dynamic"],
            "function": dyn_to_function.get(r["dynamic"], "supporting force"),
        }
        for r in relationship_matrix[:5]
    ]


def build_strengths_and_risks_from_confidence(confidence_layer: dict, character_rankings: list) -> tuple:
    """Derive strengths + development_risks from the confidence layer's per-character reasons."""
    strengths = []
    risks = []
    high_conf_chars = [r for r in character_rankings if r["confidence"] == "high"]
    if len(high_conf_chars) >= 2:
        strengths.append(f"Strong ensemble: {len(high_conf_chars)} characters land with high confidence.")
    if high_conf_chars and high_conf_chars[0]["is_protagonist"]:
        strengths.append(f"Protagonist carries the script — {high_conf_chars[0]['dialogue_count']}+ dialogue signals, spans {high_conf_chars[0]['act_presence']} acts.")
    if confidence_layer.get("scene_parser", {}).get("scene_count", 0) >= 8:
        strengths.append("Scene structure reads cleanly — clear INT./EXT. headings and enough scenes for structural analysis.")

    low_conf_chars = [r for r in character_rankings if r["confidence"] == "low" and not r["is_protagonist"]]
    if len(low_conf_chars) >= 5:
        risks.append("Multiple secondary characters lack scene-presence signal — may indicate under-developed roles.")
    single_act_chars = [r for r in character_rankings if r["act_presence"] == 1 and r["scene_count"] >= 2]
    if len(single_act_chars) >= 3:
        risks.append("Several characters live in a single act — consider spreading through-lines across the story.")
    if confidence_layer.get("scene_parser", {}).get("scene_count", 0) < 3:
        risks.append("Very few INT./EXT. scene headings detected — script may need clearer structural formatting.")
    return strengths, risks


def build_act_breakdown_from_scenes(scene_records: list) -> dict:
    """Real act_breakdown: scene ranges, high-intensity turning points, key beats.
    Replaces the flat '{summary: Setup, key_beats: [], turning_point: ""}' stubs.
    Truly script-derived — no per-world template leakage (Phase 1 bug pattern doesn't apply)."""
    if not scene_records:
        return {
            "act_1": {"summary": "Setup", "scene_range": "", "key_beats": [], "turning_point": ""},
            "act_2": {"summary": "Confrontation", "scene_range": "", "key_beats": [], "turning_point": ""},
            "act_3": {"summary": "Resolution", "scene_range": "", "key_beats": [], "turning_point": ""},
        }
    total = len(scene_records)
    act_end = [total // 3, 2 * total // 3, total]
    acts = [[], [], []]
    for scene in scene_records:
        num = scene["scene_number"]
        idx = 0 if num <= act_end[0] else 1 if num <= act_end[1] else 2
        acts[idx].append(scene)
    labels = ["Setup", "Confrontation", "Resolution"]
    out = {}
    for i, act_scenes in enumerate(acts):
        if not act_scenes:
            out[f"act_{i+1}"] = {"summary": labels[i], "scene_range": "", "key_beats": [], "turning_point": ""}
            continue
        first_num = act_scenes[0]["scene_number"]
        last_num = act_scenes[-1]["scene_number"]
        turning = max(act_scenes, key=lambda s: s["conflict_intensity"])
        others = sorted(
            [s for s in act_scenes if s["scene_number"] != turning["scene_number"]],
            key=lambda s: -s["conflict_intensity"],
        )[:3]
        out[f"act_{i+1}"] = {
            "summary": labels[i],
            "scene_range": f"Scenes {first_num}-{last_num}",
            "key_beats": [f"Scene {s['scene_number']}: {s['heading'][:70]}" for s in others],
            "turning_point": f"Scene {turning['scene_number']}: {turning['heading'][:80]}",
        }
    return out


# ─── DETERMINISTIC STORY-ANALYSIS GENERATORS ─────────────────────────────
# Ported from single_brain_orchestrator_v8_2b_FINAL_OUTPUT_ENFORCER.py.
# These are the deterministic replacements for the flat Mad-Libs strings the
# fallback used to return. Every generator is world-branched: detect_world()
# classifies the screenplay into a 7-bucket world, then downstream generators
# compose narrative shaped for that world.

def detect_world(text: str) -> str:
    """Classify the screenplay into a world/genre bucket using multi-signal scoring
    with negative-signal weighting. Load-bearing — every downstream generator
    branches on the world.

    User override takes precedence: if EVOLUM_WORLD_OVERRIDE env var is set to
    a valid world string, we short-circuit and return it. The genre picker UI
    surfaces this override — user picks, we trust the user.

    Otherwise runs the deterministic multi-bucket classifier: (1) requires
    multiple hits before classifying, (2) uses negative signals so a script
    with "castle" doesn't get flagged espionage just because it also has
    "chase", (3) has buckets for crime_family/horror/psychological_thriller/
    sci_fi_action/sci_fi_horror/animation_family that the old 7-bucket set
    was missing.
    """
    override = os.environ.get("EVOLUM_WORLD_OVERRIDE", "").strip()
    if override:
        return override

    t = text.lower()

    # Each bucket: (positive signals, negative signals, min score to classify)
    genre_signals = {
        "feature / action espionage thriller": (
            ["spy", "espionage", "cia", "kgb", "mi6", "mossad", "agent", "operative",
             "covert", "undercover", "assassin", "terrorist", "mission", "intel",
             "surveillance", "secret service", "nuclear", "harrier", "helicopter"],
            # Negative — if these strongly present, likely NOT espionage
            ["consigliere", "godfather", "family business", "kingdom", "castle",
             "throne", "spaceship", "xenomorph", "alien species", "toy",
             "courtroom", "verdict", "jury"],
            3  # need 3 espionage-specific hits
        ),
        "feature / contained urban thriller": (
            ["rideshare", "uber", "lyft", "fare", "pickup", "dropoff", "backseat",
             "cabbie", "taxi", "cab driver"],
            [],
            2
        ),
        "feature / legal / courtroom drama": (
            ["courtroom", "trial", "judge", "jury", "verdict", "witness stand",
             "cross-examination", "defense counsel", "prosecution", "objection",
             "hearing", "your honor", "counsel", "sworn testimony"],
            ["kingdom", "castle", "throne", "dragon", "wizard"],
            3
        ),
        "feature / fantasy satire comedy": (
            ["court jester", "jester", "kingdom", "castle", "king", "queen",
             "princess", "prince", "throne", "medieval", "peasant", "royal court",
             "the crown", "duchy"],
            ["spaceship", "robot", "cyborg", "nuclear", "cartel"],
            3
        ),
        "feature / fantasy adventure": (
            ["dragon", "wizard", "elf", "dwarf", "hobbit", "orc", "quest",
             "sword and sorcery", "the ring", "middle earth", "sorcerer",
             "the fellowship", "mordor", "gandalf",
             # Oz-specific — Wizard of Oz IS fantasy adventure
             "witch", "yellow brick", "munchkin", "emerald city",
             "over the rainbow", "flying monkeys", "the wizard", "toto",
             # Broader fantasy adventure
             "enchanted", "the beast", "prophecy", "the chosen one"],
            ["courtroom", "verdict", "spaceship", "modern city",
             "consigliere", "detective"],
            2
        ),
        "feature / nightlife comedy": (
            ["nightclub", "dance floor", "vip", "bouncer", "promoter",
             "velvet rope", "hookup", "night out", "bottle service"],
            [],
            2
        ),
        "feature / sports drama": (
            ["basketball", "football team", "baseball", "soccer", "coach",
             "locker room", "championship", "playoffs", "practice", "training camp",
             "the field", "the court", "the game", "quarterback", "wide receiver",
             "the season", "rookie"],
            ["cartel", "kingdom", "spaceship"],
            3
        ),
        "feature / crime drama": (
            ["cartel", "drug deal", "smuggle", "detective", "police station",
             "homicide", "heist", "robbery", "bookie", "the mob", "hitman",
             "witness protection"],
            ["kingdom", "castle", "spaceship", "consigliere", "godfather"],
            2
        ),
        "feature / crime family": (
            ["consigliere", "godfather", "capo", "made man", "the family",
             "family business", "don ", "sit down", "goomba", "wise guy",
             "underboss", "mafia", "cosa nostra"],
            [],
            2
        ),
        "feature / horror": (
            ["stabbed", "throat slit", "possessed", "haunted", "demon",
             "exorcism", "the killer", "slasher", "torture", "corpse",
             "graveyard", "cemetery", "ritual sacrifice",
             # Shining-specific + broader horror
             "redrum", "room 237", "the hotel", "the caretaker",
             "the twins", "the shining", "the axe", "the maze",
             "chainsaw", "the mask", "final girl", "jump scare"],
            ["cartel", "courtroom", "spaceship", "royal court"],
            2  # lowered from 3 — horror often concentrates keywords
        ),
        "feature / psychological thriller": (
            ["obsession", "paranoia", "unreliable", "hallucination", "manipulation",
             "gaslighting", "the mother", "the doctor", "the therapist", "delusion",
             "the patient", "psychosis"],
            [],
            3
        ),
        "feature / sci-fi action": (
            # Only distinctive sci-fi terms — dropped "the future", "the machine",
            # "laser", "plasma" because they misfire on non-sci-fi scripts (Oz had
            # a "wizard machine", Godfather has "in the future", etc.)
            ["terminator", "cyborg", "skynet", "artificial intelligence",
             "resistance fighter", "the resistance", "cyberdyne", "hunter killer",
             "time-travel", "phaser", "warp drive", "the mothership",
             "the android"],
            ["consigliere", "castle", "peasant", "witch", "kingdom"],
            2
        ),
        "feature / sci-fi horror": (
            ["xenomorph", "alien creature", "the alien", "the ship", "airlock",
             "cryo pod", "space station", "the crew", "chest burst", "acid blood",
             "the pod bay", "space horror"],
            [],
            2
        ),
        "feature / animation family": (
            ["toy", "toys come to life", "cartoon", "animated", "the toys",
             "buzz lightyear", "woody", "andy's room", "mr. potato head",
             "talking animal", "pixar"],
            [],
            2
        ),
    }

    # Use word-boundary regex, not substring matching. Otherwise "cia" hits
    # "specifically", "elf" hits "self", "orc" hits "force", "the ring" hits
    # "the ringing" — every genre bucket lights up on every script.
    def _kw_hit(keyword: str, hay: str) -> bool:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        return re.search(pattern, hay) is not None

    scores = {}
    for genre, (positives, negatives, _min) in genre_signals.items():
        pos_hits = sum(1 for s in positives if _kw_hit(s, t))
        neg_hits = sum(1 for s in negatives if _kw_hit(s, t))
        scores[genre] = pos_hits - (neg_hits * 2)

    # Only accept a classification if it meets its own min hit threshold AND
    # is at least 2 hits above the next-best bucket (avoids near-tie flukes).
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if not ranked:
        return "feature / drama"
    best_genre, best_score = ranked[0]
    runner_up_score = ranked[1][1] if len(ranked) > 1 else 0
    min_hits = genre_signals[best_genre][2]

    if best_score >= min_hits and best_score >= runner_up_score + 1:
        return best_genre
    return "feature / drama"


def classify_world_with_confidence(text: str) -> dict:
    """Richer classifier output for the genre picker UI:
    returns {'world': ..., 'confidence': 0-100, 'alternatives': [(world, score, delta)]}.

    Confidence math: (best_score - runner_up_score) / max(best_score, min_hits) × 100,
    clamped 0-100. Zero confidence when we can't beat the min threshold at all.
    Alternatives = top 3 non-winning buckets that met their min threshold or
    scored at least half of it."""
    t = text.lower()

    def _kw_hit(keyword: str, hay: str) -> bool:
        return re.search(r"\b" + re.escape(keyword) + r"\b", hay) is not None

    # Rebuild the buckets locally (same shape as detect_world). Kept in sync
    # manually with the tuple in detect_world — every edit there needs one here.
    genre_signals = {
        "feature / action espionage thriller": (
            ["spy","espionage","cia","kgb","mi6","mossad","agent","operative","covert","undercover","assassin","terrorist","mission","intel","surveillance","secret service","nuclear","harrier","helicopter"],
            ["consigliere","godfather","family business","kingdom","castle","throne","spaceship","xenomorph","alien species","toy","courtroom","verdict","jury"], 3),
        "feature / contained urban thriller": (
            ["rideshare","uber","lyft","fare","pickup","dropoff","backseat","cabbie","taxi","cab driver"], [], 2),
        "feature / legal / courtroom drama": (
            ["courtroom","trial","judge","jury","verdict","witness stand","cross-examination","defense counsel","prosecution","objection","hearing","your honor","counsel","sworn testimony"],
            ["kingdom","castle","throne","dragon","wizard"], 3),
        "feature / fantasy satire comedy": (
            ["court jester","jester","kingdom","castle","king","queen","princess","prince","throne","medieval","peasant","royal court","the crown","duchy"],
            ["spaceship","robot","cyborg","nuclear","cartel"], 3),
        "feature / fantasy adventure": (
            ["dragon","wizard","elf","dwarf","hobbit","orc","quest","sword and sorcery","the ring","middle earth","sorcerer","the fellowship","mordor","gandalf","witch","yellow brick","munchkin","emerald city","over the rainbow","flying monkeys","the wizard","toto","enchanted","the beast","prophecy","the chosen one"],
            ["courtroom","verdict","spaceship","modern city","consigliere","detective"], 2),
        "feature / nightlife comedy": (
            ["nightclub","dance floor","vip","bouncer","promoter","velvet rope","hookup","night out","bottle service"], [], 2),
        "feature / sports drama": (
            ["basketball","football team","baseball","soccer","coach","locker room","championship","playoffs","practice","training camp","the field","the court","the game","quarterback","wide receiver","the season","rookie"],
            ["cartel","kingdom","spaceship"], 3),
        "feature / crime drama": (
            ["cartel","drug deal","smuggle","detective","police station","homicide","heist","robbery","bookie","the mob","hitman","witness protection"],
            ["kingdom","castle","spaceship","consigliere","godfather"], 2),
        "feature / crime family": (
            ["consigliere","godfather","capo","made man","the family","family business","don ","sit down","goomba","wise guy","underboss","mafia","cosa nostra"], [], 2),
        "feature / horror": (
            ["stabbed","throat slit","possessed","haunted","demon","exorcism","the killer","slasher","torture","corpse","graveyard","cemetery","ritual sacrifice","redrum","room 237","the hotel","the caretaker","the twins","the shining","the axe","the maze","chainsaw","the mask","final girl","jump scare"],
            ["cartel","courtroom","spaceship","royal court"], 2),
        "feature / psychological thriller": (
            ["obsession","paranoia","unreliable","hallucination","manipulation","gaslighting","the mother","the doctor","the therapist","delusion","the patient","psychosis"], [], 3),
        "feature / sci-fi action": (
            ["terminator","cyborg","skynet","artificial intelligence","resistance fighter","the resistance","cyberdyne","hunter killer","time-travel","phaser","warp drive","the mothership","the android"],
            ["consigliere","castle","peasant","witch","kingdom"], 2),
        "feature / sci-fi horror": (
            ["xenomorph","alien creature","the alien","the ship","airlock","cryo pod","space station","the crew","chest burst","acid blood","the pod bay","space horror"], [], 2),
        "feature / animation family": (
            ["toy","toys come to life","cartoon","animated","the toys","buzz lightyear","woody","andy's room","mr. potato head","talking animal","pixar"], [], 2),
    }

    scores = {}
    for genre, (positives, negatives, min_hits) in genre_signals.items():
        pos = sum(1 for s in positives if _kw_hit(s, t))
        neg = sum(1 for s in negatives if _kw_hit(s, t))
        scores[genre] = {"score": pos - (neg * 2), "min_hits": min_hits}

    ranked = sorted(scores.items(), key=lambda kv: -kv[1]["score"])
    best_genre, best_meta = ranked[0]
    runner_up_score = ranked[1][1]["score"] if len(ranked) > 1 else 0

    # Confidence: lead over runner-up divided by min threshold, capped 0-100
    lead = best_meta["score"] - runner_up_score
    denom = max(best_meta["min_hits"], 1)
    confidence = max(0, min(100, int((lead / denom) * 100))) if best_meta["score"] >= best_meta["min_hits"] else 0

    world = best_genre if (best_meta["score"] >= best_meta["min_hits"] and lead >= 1) else "feature / drama"

    # Alternatives: top-3 non-winners that scored at least half their min_hits
    alternatives = []
    for name, meta in ranked[1:6]:
        threshold_frac = max(1, meta["min_hits"] // 2)
        if meta["score"] >= threshold_frac:
            alternatives.append({
                "world": name,
                "score": meta["score"],
                "delta_from_top": best_meta["score"] - meta["score"],
            })
        if len(alternatives) >= 3:
            break

    return {"world": world, "confidence": confidence, "alternatives": alternatives}


def infer_time_frame(text: str) -> str:
    world = detect_world(text)
    t = text.lower()
    if any(phrase in t for phrase in ["single night", "one night", "through the night", "overnight"]):
        return "single night"
    if any(phrase in t for phrase in ["single day", "one day", "same day"]):
        return "single day"
    if world == "feature / action espionage thriller":
        return "compressed high-stakes timeframe"
    if world == "feature / contained urban thriller":
        return "single night"
    if world == "feature / legal / courtroom drama":
        return "contained escalating legal battle"
    if world == "feature / fantasy satire comedy":
        return "contained escalating journey"
    if world == "feature / nightlife comedy":
        return "single night"
    if world == "feature / sports drama":
        return "contained competitive season"
    return "contained timeframe"


def infer_setting(text: str, world: str) -> str:
    if world == "feature / action espionage thriller":
        return "across domestic spaces, covert locations, and escalating action set pieces"
    if world == "feature / contained urban thriller":
        return "inside a rideshare car and across a city at night"
    if world == "feature / legal / courtroom drama":
        return "across courtrooms, military offices, holding rooms, and institutional pressure spaces"
    if world == "feature / fantasy satire comedy":
        return "across castles, ceremonial chambers, village spaces, and a heightened kingdom full of absurd rules"
    if world == "feature / nightlife comedy":
        return "across clubs, streets, parties, and chaotic social spaces over one long night"
    if world == "feature / sports drama":
        return "across locker rooms, courts, homes, and emotionally charged spaces around the game"
    if world == "feature / crime drama":
        return "across dangerous interiors, streets, and pressure-filled underworld spaces"
    return "a contained dramatic environment"


def infer_tone(text: str, world: str) -> str:
    if world == "feature / action espionage thriller":
        return "propulsive, high-stakes, witty, cinematic"
    if world == "feature / contained urban thriller":
        return "tense, paranoid, urban, nocturnal"
    if world == "feature / legal / courtroom drama":
        return "tense, procedural, sharp, morally charged"
    if world == "feature / fantasy satire comedy":
        return "playful, witty, satirical, adventurous"
    if world == "feature / nightlife comedy":
        return "chaotic, funny, awkward, energetic"
    if world == "feature / sports drama":
        return "grounded, competitive, emotional, aspirational"
    if world == "feature / crime drama":
        return "tense, grounded, dangerous, dramatic"
    return "grounded, dramatic, character-driven"


def infer_story_engine(text: str, protagonist: str) -> str:
    """Structural: what drives THIS world's stories. Never a specific film's plot."""
    world = detect_world(text)
    p = protagonist.title()
    if world == "feature / action espionage thriller":
        return (f"{p} operates in a world where identity is a tool and every truth carries a cost — "
                f"and each choice narrows the space between the life they perform and the life they actually live.")
    if world == "feature / contained urban thriller":
        return (f"{p} navigates a compressed environment where interpretation becomes action, "
                f"and the pressure of a single stretch of time forces incomplete information into consequential choices.")
    if world == "feature / legal / courtroom drama":
        return (f"{p} works inside a system where truth is procedural, weight is institutional, and every "
                f"choice tests the distance between what serves the case and what serves the person.")
    if world == "feature / fantasy satire comedy":
        return (f"{p} moves through a world where image outranks wisdom and survival depends on reading absurd "
                f"power dynamics correctly — wit becoming both defense and weapon.")
    if world == "feature / fantasy adventure":
        return (f"{p} is drawn into a journey with mythic scale, where the outcome of one path reshapes the fate "
                f"of many and every choice tests a different form of courage.")
    if world == "feature / nightlife comedy":
        return (f"{p} chases a version of the night — validation, connection, escape — that keeps slipping just out "
                f"of reach, and each attempt to catch it creates the next complication.")
    if world == "feature / sports drama":
        return (f"{p} carries the collision of personal ambition, external expectation, and physical cost, "
                f"forced to define who they are through what they're willing to endure and what they refuse to give up.")
    if world == "feature / crime drama":
        return (f"{p} exists in a world where survival requires moral compromise and every gain has a shadow, "
                f"pushing them toward choices that reveal what kind of person they've become.")
    if world == "feature / crime family":
        return (f"{p} operates inside a world where loyalty defines value and blood defines authority — where "
                f"the pressure of the family reshapes who they can be, and every promotion is also a sentence.")
    if world == "feature / horror":
        return (f"{p} exists in a space where safety is a fragile assumption and dread accumulates faster than it "
                f"can be named — forced to choose what they'll surrender and what they'll fight for before the choice is taken.")
    if world == "feature / psychological thriller":
        return (f"{p} moves through a world where reality itself becomes unstable — perception, memory, and trust "
                f"begin fracturing, forcing them to decide what to believe when the evidence turns against itself.")
    if world == "feature / sci-fi action":
        return (f"{p} navigates a world where technology has outpaced ethics — every advantage cuts both ways, and "
                f"the mission's stated shape is not the shape it takes.")
    if world == "feature / sci-fi horror":
        return (f"{p} occupies a contained hostile environment where the danger is intelligent and the space is not — "
                f"pushing every human dynamic to failure under a threat that doesn't negotiate.")
    if world == "feature / animation family":
        return (f"{p} inhabits a world where wonder is native and every problem is solvable by imagination, courage, "
                f"or the right friend arriving at the right moment — until something bigger than them threatens to decide otherwise.")
    return (f"{p} is pulled into a situation where incomplete information and rising pressure force "
            f"increasingly risky choices — pushing the story toward a reversal that redefines what was at stake.")


def infer_core_conflict(text: str, protagonist: str) -> str:
    """Structural conflict statement — what any protagonist in this world faces."""
    world = detect_world(text)
    p = protagonist.title()
    if world == "feature / action espionage thriller":
        return (f"{p} must protect what they cannot show and reveal what they've spent years concealing, "
                f"as the boundary between professional identity and personal cost collapses.")
    if world == "feature / contained urban thriller":
        return (f"{p}'s reading of the situation begins to shape what the situation actually becomes, "
                f"forcing them to act on judgment they may not fully own.")
    if world == "feature / legal / courtroom drama":
        return (f"{p} must decide whether to serve the truth or serve the case, as institutional pressure "
                f"tries to close the space where those two could ever be the same.")
    if world == "feature / fantasy satire comedy":
        return (f"{p} must navigate a system that punishes wisdom and rewards spectacle, without losing "
                f"the part of themselves that could actually make a difference.")
    if world == "feature / fantasy adventure":
        return (f"{p} must carry a purpose larger than any one person's strength, as the journey exposes what "
                f"they can offer and what they must ask others to become.")
    if world == "feature / nightlife comedy":
        return (f"{p} must reckon with the difference between what they think they want and what they actually need, "
                f"before the night's mistakes stop being reversible.")
    if world == "feature / sports drama":
        return (f"{p} must define themselves through the collision of internal drive and external pressure, "
                f"deciding what performance costs and what it can never give back.")
    if world == "feature / crime drama":
        return (f"{p} must navigate a world where every advantage comes with a price and every alliance "
                f"contains its own exit, deciding what they'll trade for the life they think they're building.")
    if world == "feature / crime family":
        return (f"{p} must reconcile loyalty and ambition inside a hierarchy that rewards both — and destroys "
                f"those who choose the wrong version of either.")
    if world == "feature / horror":
        return (f"{p} must find the edge of what they'll accept and where they'll draw a line, in a space "
                f"that keeps redrawing what safety and courage even mean.")
    if world == "feature / psychological thriller":
        return (f"{p} must sort what's real from what's projected, as the source of the threat becomes "
                f"increasingly indistinguishable from the source of their own perception.")
    if world == "feature / sci-fi action":
        return (f"{p} must decide whose future they're building and what cost they will personally carry, "
                f"as the mission's stakes exceed any single person's authority to answer.")
    if world == "feature / sci-fi horror":
        return (f"{p} must choose who they'll save and what they'll surrender, as an intelligent threat "
                f"forces every trust and every plan to prove itself under pressure.")
    if world == "feature / animation family":
        return (f"{p} must find their courage in a world that keeps testing whether they've earned it, "
                f"discovering that what they need was often already with them.")
    return f"{p} must navigate mounting pressure with incomplete understanding of what's actually at stake."


def infer_reversal(text: str) -> str:
    """Structural reversal — the shape of the turn in this world's stories."""
    world = detect_world(text)
    if world == "feature / action espionage thriller":
        return "What was kept hidden to protect becomes the very thing that endangers, and the mission's real target is closer than assumed."
    if world == "feature / contained urban thriller":
        return "The situation the protagonist thought they were reading was reading them, and their interpretation was itself the danger."
    if world == "feature / legal / courtroom drama":
        return "The deeper truth was never about the case — it was about what the system prefers to bury and what it requires to be defended."
    if world == "feature / fantasy satire comedy":
        return "The clever survival strategies that worked against the system reveal a new problem: what does the protagonist owe the system when they finally have leverage?"
    if world == "feature / fantasy adventure":
        return "The victory the protagonist thought they were pursuing becomes secondary to the cost of who they had to become to earn it."
    if world == "feature / nightlife comedy":
        return "The person the protagonist was chasing was themselves — and what they were escaping was the thing they most needed to face."
    if world == "feature / sports drama":
        return "What looked like a straight path to achievement reveals a deeper reckoning with what the protagonist was actually chasing."
    if world == "feature / crime drama":
        return "The life the protagonist thought they were building begins to look like the life that was building them."
    if world == "feature / crime family":
        return "The loyalty that protected the protagonist reveals itself as the leash that keeps them from becoming who they might have been."
    if world == "feature / horror":
        return "What the protagonist was running from was inside the space they trusted, and what protected them was smaller than they thought."
    if world == "feature / psychological thriller":
        return "The source of what the protagonist most feared was closer to them — and more entangled with their own mind — than they were ready to accept."
    if world == "feature / sci-fi action":
        return "The technology or mission the protagonist thought they were serving was serving something else, and the choice of what to save was never simply operational."
    if world == "feature / sci-fi horror":
        return "The intelligence they faced was not the alien one — it was the human decisions that let it in."
    if world == "feature / animation family":
        return "The help the protagonist was seeking from outside was already inside them, and the person they needed to trust was themselves."
    return "The truth of the situation is different from what the protagonist first assumed — and what they must do about it is different from what they set out to do."


def build_logline_from_story_map(story_map: dict) -> str:
    """Structural logline template — protagonist + world dynamic + stakes shape."""
    world = story_map.get("world", "feature / drama")
    p = (story_map.get("protagonist") or "Protagonist").title()
    if world == "feature / action espionage thriller":
        return (f"When the space between {p}'s two lives collapses, they must protect what they've spent "
                f"years concealing — before the cost of the mission becomes personal.")
    if world == "feature / contained urban thriller":
        return (f"Over the course of one compressed stretch, {p} must interpret escalating pressure without "
                f"the information to be sure — while their reading of the situation reshapes what it becomes.")
    if world == "feature / legal / courtroom drama":
        return (f"When a case forces {p} to choose between what serves the system and what serves the truth, "
                f"they must decide what kind of professional — and person — they're willing to be.")
    if world == "feature / fantasy satire comedy":
        return (f"Thrust into a system where image outranks wisdom, {p} must navigate absurd power without "
                f"losing the part of themselves that could actually change it.")
    if world == "feature / fantasy adventure":
        return (f"Pulled into a journey with stakes beyond their own life, {p} must find a courage they didn't "
                f"know they had — and discover what carrying a purpose actually costs.")
    if world == "feature / nightlife comedy":
        return (f"Over one long night, {p} chases the version of themselves they think they should be — and "
                f"comes face to face with the version they've been avoiding.")
    if world == "feature / sports drama":
        return (f"Under the weight of expectation, personal history, and physical cost, {p} must define who they "
                f"are through what they can endure — and what they refuse to give up.")
    if world == "feature / crime drama":
        return (f"In a world where every advantage carries a shadow, {p} must reckon with the price of the life "
                f"they thought they were building — and what they've become in the building of it.")
    if world == "feature / crime family":
        return (f"Bound by loyalty inside a system that rewards ambition and punishes betrayal, {p} must find "
                f"the shape of who they can be inside the family — and what it will cost either way.")
    if world == "feature / horror":
        return (f"When the space {p} trusted turns against them, they must find the edge of what they'll fight for "
                f"before the choice is no longer theirs to make.")
    if world == "feature / psychological thriller":
        return (f"As the ground of {p}'s reality begins to shift, they must decide what to believe when even the "
                f"evidence — and their own perception — cannot be trusted.")
    if world == "feature / sci-fi action":
        return (f"Caught inside a system where technology has outpaced its makers, {p} must choose whose future they're "
                f"building — and what they're willing to give to build it.")
    if world == "feature / sci-fi horror":
        return (f"Contained with an intelligent threat and diminishing space to escape, {p} must decide what — and "
                f"who — is worth saving as every assumption fails.")
    if world == "feature / animation family":
        return (f"When their world tilts in a way they can't handle alone, {p} must find the courage, the friends, "
                f"and the truth about themselves that will let them set it right.")
    return (f"When mounting pressure begins to reveal what {p} was really carrying, they must find "
            f"a way through — and a version of themselves they can live with once they do.")


def build_synopsis_from_story_map(story_map: dict) -> str:
    """Structural synopsis — the archetypal shape of stories in this world.
    Uses protagonist name + character archetypes; never bakes in specific plot details."""
    world = story_map.get("world", "feature / drama")
    p = (story_map.get("protagonist") or "the protagonist").title()
    chars = [c.title() for c in (story_map.get("characters") or [])[1:4]]
    support = f" Along the way, {', '.join(chars)} sharpen the pressure and shape the stakes." if chars else ""

    if world == "feature / action espionage thriller":
        return (f"{p} lives inside a world where competence is measured in survival and identity is a constant "
                f"negotiation. As pressure mounts and the boundaries between their professional life and their "
                f"personal one begin to collapse, every choice sharpens the cost of what they've been carrying.{support}\n\n"
                f"What was controllable becomes urgent. What was hidden becomes exposed. And {p} moves toward a "
                f"defining confrontation where the price of secrecy — and the cost of the truth — must finally be reckoned with.")

    if world == "feature / contained urban thriller":
        return (f"Across a single compressed stretch of time, {p} moves through escalating pressure with only partial "
                f"information about what they're actually inside of. Each choice reshapes what the situation becomes, "
                f"and their interpretation of the people around them begins to matter as much as what those people are actually doing.{support}\n\n"
                f"What was noise sharpens into pattern. What was suspicion drives action. And {p} confronts the "
                f"consequence of reading a situation they never fully understood.")

    if world == "feature / legal / courtroom drama":
        return (f"{p} operates inside a system where truth is procedural and power is institutional. A case that "
                f"begins routinely opens into something larger — testing the distance between what the record will "
                f"admit and what the protagonist knows to be true.{support}\n\n"
                f"As institutional pressure closes in, {p} must decide whether to protect the position they've built "
                f"or risk it for something the system prefers to bury. What begins as a defense becomes a test of "
                f"courage, precision, and identity.")

    if world == "feature / fantasy satire comedy":
        return (f"{p} lands inside a world where spectacle outranks wisdom, image outranks substance, and survival "
                f"depends on reading power dynamics that don't quite make sense. What starts as a game of clever "
                f"deflection reveals deeper fractures — and deeper leverage — beneath every ridiculous performance.{support}\n\n"
                f"As the chaos escalates, wit becomes both shield and weapon. {p} must learn to survive the "
                f"spectacle without being consumed by it — and to decide what they'll do with the leverage they've earned.")

    if world == "feature / fantasy adventure":
        return (f"{p} is pulled from a familiar life into a journey whose stakes reach beyond any one person. The "
                f"purpose they carry tests forms of courage they didn't know they had, and the world they move through "
                f"is populated by allies who complicate as often as they help.{support}\n\n"
                f"What begins as a quest becomes a test of who {p} is when the responsibility becomes personal. "
                f"The victory they were chasing gives way to a reckoning with what they had to become to earn it.")

    if world == "feature / nightlife comedy":
        return (f"Over one long night, {p} chases connection, validation, and the version of themselves they think "
                f"they're supposed to be. Each escalation makes the night bigger, the mistakes louder, and the "
                f"distance between what they want and what they actually need harder to ignore.{support}\n\n"
                f"By the time the night reaches its edge, {p} is face to face with the person they've been avoiding "
                f"— and the choice about whether they can live with that version, or whether they'll finally do something about it.")

    if world == "feature / sports drama":
        return (f"{p} sits at the collision of personal ambition, external expectation, and the physical and emotional "
                f"cost of performance. What begins as a familiar pursuit sharpens into something more demanding — "
                f"forcing them to navigate what they're carrying beyond the game itself.{support}\n\n"
                f"As the stakes escalate, the pressure becomes personal. Every decision shapes what {p} is willing to "
                f"pay — and what they refuse to give up. What emerges is not just performance but identity: "
                f"the version of themselves they can live with, on and off the field.")

    if world == "feature / crime drama":
        return (f"{p} exists in a world where every advantage carries a shadow and every alliance contains its own exit. "
                f"What begins as opportunity — or necessity — reveals its cost slowly, then all at once, forcing "
                f"{p} to reckon with the shape of the life they're building.{support}\n\n"
                f"The choice each moment presents becomes narrower. And the version of themselves that emerges is one "
                f"they'll have to live with — long after the immediate stakes are settled.")

    if world == "feature / crime family":
        return (f"{p} lives inside a hierarchy where loyalty and ambition sit inches from each other, and where every "
                f"promotion is also a sentence. Family is the source of identity, protection, and pressure — and every "
                f"choice inside it recalibrates who {p} can be and who they can trust.{support}\n\n"
                f"As the pressure inside the family reshapes everyone's position, {p} must decide what they're willing "
                f"to protect and what they'll allow to define them. The cost of loyalty and the cost of ambition begin "
                f"to look the same.")

    if world == "feature / horror":
        return (f"{p} moves through a space that stops being safe. Dread accumulates faster than it can be named, "
                f"and the assumptions that used to define their life — trust, sanctuary, understanding — begin to fail.{support}\n\n"
                f"As the pressure sharpens, {p} must decide what they'll surrender and what they'll fight for. "
                f"What emerges is a version of them that survives what they didn't know could threaten them — "
                f"and a truth about who they are that they can no longer look away from.")

    if world == "feature / psychological thriller":
        return (f"{p} moves through a world where reality itself begins to shift. Perception, memory, and trust "
                f"start to fracture, and the evidence they can gather about their situation increasingly contradicts "
                f"itself. What is real, what is projection, and what is manipulation become impossible to fully separate.{support}\n\n"
                f"As the pressure closes in, {p} must decide what to believe when the source of the threat is "
                f"indistinguishable from the source of their own perception — and act on judgment they cannot fully verify.")

    if world == "feature / sci-fi action":
        return (f"{p} operates inside a system where technology has outpaced its makers and every advantage cuts both "
                f"ways. What begins as a mission with a defined objective opens into a larger question about who is "
                f"actually being served — and who is being made expendable in the process.{support}\n\n"
                f"As the stakes rise beyond any single person's authority to resolve, {p} must decide whose future they "
                f"are building — and what they will personally carry to build it.")

    if world == "feature / sci-fi horror":
        return (f"{p} occupies a contained environment where the danger is intelligent and the space is not. "
                f"Every human dynamic — trust, plan, hierarchy — is pushed to failure under a threat that does not "
                f"negotiate and does not tire.{support}\n\n"
                f"As every assumption fails and the space to escape narrows, {p} must decide who and what is worth "
                f"saving. What emerges is a portrait of who they are when there is no more time to be anyone else.")

    if world == "feature / animation family":
        return (f"{p} lives in a world where wonder is native and connection is currency. When their world tilts in a "
                f"way they can't handle alone, they must find the courage, the friends, and the truth about themselves "
                f"that will let them set it right.{support}\n\n"
                f"What begins as a problem to solve becomes a story about who they become in the solving. And what "
                f"they discover is that the help they were looking for was often already with them.")

    return (f"As pressure mounts around {p}, incomplete information and rising tension force increasingly risky "
            f"choices. What first appears to be one kind of situation gradually reveals itself to be something more "
            f"complicated — pushing the story toward a reversal that redefines what {p} thought they understood.{support}\n\n"
            f"By the time the pressure resolves, the question is no longer just about the outcome — it's about who "
            f"{p} became on the way to it, and what they will carry forward from what they had to face.")


def infer_protagonist_summary(story_map: dict) -> str:
    """Structural protagonist summary keyed on world archetype, not specific plot."""
    p = (story_map.get("protagonist") or "Protagonist").title()
    world = story_map.get("world", "")
    if world == "feature / action espionage thriller":
        return f"{p} is a capable operator whose professional life demands secrecy — and whose personal life keeps asking to be protected from what that secrecy costs."
    if world == "feature / contained urban thriller":
        return f"{p} carries the weight of a situation they only partially understand, forced to act on interpretation while the stakes keep sharpening around them."
    if world == "feature / legal / courtroom drama":
        return f"{p} is a professional trained inside a system that rewards precision — now tested by a situation where precision alone will not answer the deeper question."
    if world == "feature / fantasy satire comedy":
        return f"{p} is a sharp observer navigating absurd power dynamics with wit, instinct, and growing awareness of how the system actually works."
    if world == "feature / fantasy adventure":
        return f"{p} carries a purpose larger than themselves, testing what kind of courage and what kind of trust they can actually offer to a task with mythic weight."
    if world == "feature / nightlife comedy":
        return f"{p} is chasing a version of the night that keeps escaping them — and, in the chasing, running into every part of themselves they've been avoiding."
    if world == "feature / sports drama":
        return f"{p} is a competitor carrying more than their game — the internal drive and the external expectation both testing what they are willing to be defined by."
    if world == "feature / crime drama":
        return f"{p} is navigating a world where every choice has a shadow, forced to weigh survival against the shape of the life they're building."
    if world == "feature / crime family":
        return f"{p} operates inside a hierarchy that defines them as much as they define themselves — reckoning with the loyalty they owe, the ambition they carry, and the cost of both."
    if world == "feature / horror":
        return f"{p} is being asked to find courage inside a space that keeps stripping away the assumptions that made courage feel possible."
    if world == "feature / psychological thriller":
        return f"{p} is a lead whose relationship to reality itself becomes a variable — forced to sort perception from projection while the pressure keeps sharpening."
    if world == "feature / sci-fi action":
        return f"{p} operates inside a system where technology has outpaced ethics, and where their capability is being used to answer questions larger than they can control."
    if world == "feature / sci-fi horror":
        return f"{p} is a competent operator inside a contained environment where competence alone will not be enough — forced to sort what they can trust from what they cannot."
    if world == "feature / animation family":
        return f"{p} is small in a world that is large, and discovering that the courage, the friends, and the truth they need are more accessible than they first appear."
    return f"{p} is the central engine of the story — carrying the emotional pressure, the forward momentum, and the decisive choice that will define what the film is actually about."


def infer_theme(story_map: dict) -> str:
    """Structural theme — the archetypal question this world's stories answer."""
    world = story_map.get("world", "")
    if world == "feature / action espionage thriller":
        return "The cost of concealment collides with the cost of exposure, and identity is forged in the space between."
    if world == "feature / contained urban thriller":
        return "Interpretation shapes reality, and the pressure of a compressed situation reveals who the protagonist becomes when the information is incomplete."
    if world == "feature / legal / courtroom drama":
        return "Truth and system are not the same thing, and integrity has a price the record does not always show."
    if world == "feature / fantasy satire comedy":
        return "Wit is leverage inside an absurd hierarchy — and what the protagonist does with the leverage tests who they actually are."
    if world == "feature / fantasy adventure":
        return "Purpose reveals character, and the cost of carrying something larger than yourself is measured in what you become in the carrying of it."
    if world == "feature / nightlife comedy":
        return "The chase for validation is a mask for the reckoning with self, and the night's mistakes are the last resistance against seeing yourself clearly."
    if world == "feature / sports drama":
        return "Performance is identity under pressure, and the version of the protagonist that emerges is defined by what they refuse to give up."
    if world == "feature / crime drama":
        return "Every advantage carries a shadow, and the life the protagonist builds ends up building them in return."
    if world == "feature / crime family":
        return "Loyalty and ambition rhyme inside a family — and their cost is the same cost, paid in different currencies."
    if world == "feature / horror":
        return "Safety is a fragile assumption, and courage is what remains when the assumptions fail."
    if world == "feature / psychological thriller":
        return "Perception is a variable, and the source of the threat is often closer to the source of the self than the protagonist can afford to admit."
    if world == "feature / sci-fi action":
        return "Technology outpaces ethics, and the question of whose future is being built is never simply an operational one."
    if world == "feature / sci-fi horror":
        return "Intelligence does not require humanity, and human decisions are often what let the threat in."
    if world == "feature / animation family":
        return "Courage, friendship, and the truth about yourself are the tools that answer the world's biggest problems — and they're closer than they feel."
    return "Pressure reveals character, and the story tests what remains when certainty gives way to consequence."


# ─── FALLBACK STORY MAP (now runs the deterministic generators) ──────────

# ─── PHASE 5 — SANITY + FINAL OUTPUT ENFORCER PASSES ─────────────────────
# Defensive scrubbers that catch placeholder-token leakage in output
# (e.g. literal "Protagonist" / "World" / "False must" appearing in
# user-facing text). Also writes the deck_export_payload aliases that
# deck_builder.py + report_renderer.py read for slide + report rendering.

SANITY_BLOCKLIST = {
    "FALSE", "TRUE", "WHAT", "WHO", "WHY", "WHEN", "WHERE", "WORLD", "PROTAGONIST", "THIS", "ANOTHER", "PLACEHOLDER",
    "CHARACTER", "CHARACTERS", "TITLE", "SYNOPSIS", "LOGLINE", "STORY", "SUMMARY",
    "HOOK", "CONFLICT", "STAKES", "TONE", "THEME", "REVERSAL", "SETTING", "ACT", "SCENE"
}
INTERNAL_TITLE_MARKERS = {
    "SINGLE BRAIN ORCHESTRATOR", "COMBINED STORY MAP", "IMAGE PLAN", "AUTHORITY PASS",
    "PROMETHEUS", "TRUST PASS", "SANITY PASS", "VERSION", "FULL REPLACEMENT", "APP/", "V8.", "V7"
}
PLACEHOLDER_PATTERNS = [
    r"\bWhat,\s*Protagonist,\s*World\b",
    r"\b(Protagonist|Character|World|Title|Synopsis|Logline)\b",
]


def is_sanity_blocked_name(name: str) -> bool:
    upper = clean_name(name).upper()
    if not upper:
        return True
    if upper in SANITY_BLOCKLIST:
        return True
    if upper.startswith(("INT", "EXT", "CUT", "FADE")):
        return True
    return False


def sanitize_display_title(title: str, world: str) -> str:
    clean = normalize(title).strip('# ').strip()
    upper = clean.upper()
    if not clean:
        clean = ''
    bad = (not clean) or any(token in upper for token in INTERNAL_TITLE_MARKERS) or len(clean) > 90
    if bad:
        fallback = {
            "feature / fantasy satire comedy": "Untitled Fantasy Project",
            "feature / action espionage thriller": "Untitled Espionage Thriller",
            "feature / contained urban thriller": "Untitled Urban Thriller",
            "feature / legal / courtroom drama": "Untitled Courtroom Drama",
            "feature / nightlife comedy": "Untitled Comedy",
            "feature / sports drama": "Untitled Sports Drama",
        }
        return fallback.get(world, "Untitled Project")
    return clean


def choose_clean_protagonist(characters: list, character_rankings: list, stats: dict, current: str) -> str:
    if current and not is_sanity_blocked_name(current):
        if current.upper() not in {"FALSE", "TRUE"}:
            return current
    for item in character_rankings:
        name = item.get('name', '')
        if not name or is_sanity_blocked_name(name) or name.upper() in {"FALSE", "TRUE"}:
            continue
        trust = item.get('trust_score', 0)
        scenes = item.get('scene_count', 0)
        dialogue = stats.get(name, {}).get('dialogue_count', 0)
        if trust >= 50 or scenes >= 2 or dialogue >= 4:
            return name
    for name in characters:
        if not is_sanity_blocked_name(name) and name.upper() not in {"FALSE", "TRUE"}:
            return name
    return "Protagonist"


def sanitize_audience_text(value: str, story_map: dict) -> str:
    if not isinstance(value, str):
        return value
    cleaned = value
    protagonist = story_map.get('protagonist', 'the protagonist')
    world = story_map.get('world', 'the world of the story')
    replacements = {
        'What, Protagonist, World': '',
        'False must': f'{protagonist} must' if protagonist and protagonist != 'False' else 'The protagonist must',
        'False is ': f'{protagonist} is ' if protagonist and protagonist != 'False' else 'The protagonist is ',
        'False has ': f'{protagonist} has ' if protagonist and protagonist != 'False' else 'The protagonist has ',
        'False toward': f'{protagonist} toward' if protagonist and protagonist != 'False' else 'the protagonist toward',
        'feature / ': '',
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    if protagonist and protagonist != 'Protagonist':
        cleaned = re.sub(r'\bProtagonist\b', protagonist, cleaned)
    cleaned = re.sub(r'\bWorld\b(?![- ]branched)', world, cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    cleaned = cleaned.replace(' ,', ',').replace(' .', '.')
    return cleaned.strip()


def apply_sanity_pass(story_map: dict) -> dict:
    """Cleans title, protagonist name, and any leaked placeholder tokens
    in audience-facing text fields. Runs after Phase 1-4 build story_map."""
    story_map['title'] = sanitize_display_title(story_map.get('title', ''), story_map.get('world', ''))
    protagonist = choose_clean_protagonist(
        story_map.get('characters', []),
        story_map.get('character_rankings', []),
        story_map.get('character_stats', {}),
        story_map.get('protagonist', 'Protagonist'),
    )
    story_map['protagonist'] = protagonist
    story_map['protagonist_profile'] = {'name': protagonist, 'summary': story_map.get('protagonist_summary', '')}
    for key in ['protagonist_summary', 'theme', 'story_engine', 'core_conflict', 'reversal', 'logline',
                'synopsis', 'executive_summary', 'actor_objective', 'commercial_positioning',
                'packaging_potential', 'character_leverage']:
        if key in story_map:
            story_map[key] = sanitize_audience_text(story_map[key], story_map)
    if isinstance(story_map.get('tone_comparables'), list):
        story_map['tone_comparables'] = [sanitize_audience_text(x, story_map) for x in story_map['tone_comparables']]
    story_map['sanity_pass_summary'] = {
        'status': 'active',
        'final_protagonist': story_map.get('protagonist'),
        'final_title': story_map.get('title'),
        'audience_facing_cleanup_applied': True,
    }
    return story_map


def build_deck_export_payload(story_map: dict) -> dict:
    """Writes the flat downstream-friendly aliases deck_builder.py + report_renderer.py read."""
    title = sanitize_display_title(story_map.get('title', ''), story_map.get('world', ''))
    protagonist = choose_clean_protagonist(
        story_map.get('characters', []),
        story_map.get('character_rankings', []),
        story_map.get('character_stats', {}),
        story_map.get('protagonist', 'Protagonist'),
    )
    if protagonist.upper() in {"FALSE", "TRUE"}:
        protagonist = "Protagonist"
    working = dict(story_map)
    working['title'] = title
    working['protagonist'] = protagonist
    logline = sanitize_audience_text(story_map.get('logline', ''), working)
    synopsis = sanitize_audience_text(story_map.get('synopsis', ''), working)
    core_conflict = sanitize_audience_text(story_map.get('core_conflict', ''), working)
    story_engine = sanitize_audience_text(story_map.get('story_engine', ''), working)
    why_this_movie = sanitize_audience_text(story_map.get('executive_summary', '') or story_engine, working)
    return {
        'title': title, 'project_title': title, 'deck_title': title,
        'protagonist': protagonist, 'deck_protagonist': protagonist,
        'logline': logline, 'hook': logline,
        'synopsis': synopsis, 'synopsis_2': synopsis,
        'core_conflict': core_conflict, 'conflict': core_conflict, 'stakes': core_conflict,
        'world': sanitize_audience_text(story_map.get('world', ''), working),
        'tone': sanitize_audience_text(story_map.get('tone', ''), working),
        'story_engine': story_engine,
        'reversal': sanitize_audience_text(story_map.get('reversal', ''), working),
        'why_this_movie': why_this_movie,
    }


def apply_final_output_enforcer(story_map: dict) -> dict:
    """Writes deck_export_payload + downstream-friendly aliases into story_map."""
    payload = build_deck_export_payload(story_map)
    story_map['title'] = payload['title']
    story_map['protagonist'] = payload['protagonist']
    story_map['logline'] = payload['logline']
    story_map['synopsis'] = payload['synopsis']
    story_map['deck_export_payload'] = payload
    # downstream-friendly aliases (read by deck_builder + report_renderer)
    story_map['project_title'] = payload['title']
    story_map['deck_title'] = payload['title']
    story_map['final_title'] = payload['title']
    story_map['display_title'] = payload['title']
    story_map['deck_protagonist'] = payload['protagonist']
    story_map['final_protagonist'] = payload['protagonist']
    story_map['hook'] = payload['hook']
    story_map['synopsis_2'] = payload['synopsis_2']
    story_map['conflict'] = payload['conflict']
    story_map['stakes'] = payload['stakes']
    story_map['why_this_movie'] = payload['why_this_movie']
    story_map['final_output_enforcer_summary'] = {
        "status": "active",
        "final_title": payload["title"],
        "final_protagonist": payload["protagonist"],
        "final_logline": payload["logline"],
        "audience_payload_written": True,
        "export_aliases_written": True,
    }
    return story_map


# ─── PHASE 4 — WORLD-LOOKUP FILLS ─────────────────────────────────────────
# Ported from FINAL_OUTPUT_ENFORCER. World-branched generators for the
# fields that feed actor prep + script analysis reports. Same leakage
# pattern as Phase 1 — templates carry world-typed language rather than
# script-specific plot details, but "The Understudy's fantasy tactics for
# any fantasy script" still applies. Flagged in project_bug_world_generator_leakage
# memory for real-upgrade pass.

def infer_commercial_positioning(story_map: dict) -> str:
    world = story_map.get("world", "")
    primary_mode = ((story_map.get("presentation_modes") or {}).get("primary_mode") or "")
    if world == "feature / contained urban thriller":
        return "Contained commercial thriller with strong low-to-mid budget pitch value and trailer-ready tension."
    if world == "feature / fantasy satire comedy":
        return "Broad-appeal fantasy satire with strong family/comedy packaging potential and visual franchise upside."
    if world == "feature / legal / courtroom drama":
        return "Prestige-leaning legal drama with serious performance, awards, and streamer positioning potential."
    if world == "feature / nightlife comedy":
        return "Commercial nightlife comedy built for fast pacing, ensemble energy, and social-chaos marketability."
    if world == "feature / sports drama":
        return "Emotionally accessible sports drama with inspirational crossover and talent-driven packaging appeal."
    if primary_mode == "tension_pressure":
        return "Commercial tension-driven project with contained scale and strong word-of-mouth premise value."
    if primary_mode == "prestige_authority":
        return "Prestige-forward dramatic package with strong performer appeal and premium streamer potential."
    if primary_mode == "spectacle_play":
        return "Visual, accessible concept with strong packaging upside for broad audiences."
    return "Commercially viable story package with clear pitch angles across concept, character, and tone."


def infer_audience_profile(story_map: dict) -> list:
    world = story_map.get("world", "")
    tone = story_map.get("tone", "")
    profiles = []
    if "thriller" in world:
        profiles += ["Thriller audiences", "Urban suspense viewers", "Contained-premise fans"]
    if "fantasy" in world or "adventure" in tone:
        profiles += ["Fantasy audiences", "Family-friendly comedy viewers", "Adventure-forward viewers"]
    if "courtroom" in world or "legal" in world:
        profiles += ["Prestige drama audiences", "Legal/procedural viewers", "Performance-driven film fans"]
    if "comedy" in world:
        profiles += ["Comedy audiences", "Streaming-first viewers"]
    if "sports" in world:
        profiles += ["Sports drama audiences", "Inspirational drama viewers"]
    if not profiles:
        profiles = ["General film audiences", "Character-driven story viewers", "Streaming platform audiences"]
    seen = []
    for p in profiles:
        if p not in seen:
            seen.append(p)
    return seen[:5]


def infer_strength_index(story_map: dict) -> dict:
    world = story_map.get("world", "")
    characters = story_map.get("characters", [])
    tone = story_map.get("tone", "")
    concept, character, marketability, originality = 7, 7, 7, 7
    if "thriller" in world:
        concept += 2; marketability += 2
    if "fantasy" in world or "satire" in world:
        originality += 2; concept += 1
    if "courtroom" in world or "legal" in world:
        character += 1; marketability += 1
    if len(characters) >= 4:
        character += 1
    if "playful" in tone or "witty" in tone:
        originality += 1
    if "contained" in world:
        marketability += 1
    return {
        "concept": max(1, min(10, concept)),
        "character": max(1, min(10, character)),
        "marketability": max(1, min(10, marketability)),
        "originality": max(1, min(10, originality)),
    }


def infer_packaging_potential(story_map: dict) -> str:
    world = story_map.get("world", "")
    protagonist = story_map.get("protagonist", "Lead")
    if "fantasy" in world:
        return f"Strong packaging upside through distinctive world, comedic ensemble, and a breakout lead role for {protagonist}."
    if "thriller" in world:
        return f"Packaging works best around a strong lead performance, contained tension, and a marketable trailer hook anchored by {protagonist}."
    if "courtroom" in world or "legal" in world:
        return f"Packaging works through prestige casting, performance credibility, and premium streamer positioning around {protagonist}."
    return f"Packaging potential is strongest when the project is sold through lead identity, tone clarity, and a concise market hook built around {protagonist}."


def infer_character_leverage(story_map: dict) -> str:
    protagonist = story_map.get("protagonist", "Lead")
    characters = [c for c in story_map.get("characters", []) if c != protagonist]
    if characters:
        return f"{protagonist} is the primary leverage point, with support strength coming from {', '.join(characters[:3])} as contrast, pressure, or energy multipliers."
    return f"{protagonist} is the clear leverage point and should carry the package, marketing, and audience entry path."


def infer_tone_comparables(story_map: dict) -> list:
    world = story_map.get("world", "")
    tone = story_map.get("tone", "")
    if "fantasy satire comedy" in world:
        return ["The Princess Bride", "Shrek", "Galavant"]
    if "contained urban thriller" in world:
        return ["Collateral", "Nightcrawler", "Phone Booth"]
    if "legal / courtroom drama" in world:
        return ["A Few Good Men", "Michael Clayton", "The Firm"]
    if "nightlife comedy" in world:
        return ["After Hours", "Superbad", "Booksmart"]
    if "sports drama" in world:
        return ["Creed", "Remember the Titans", "Friday Night Lights"]
    if "playful" in tone:
        return ["Knives Out", "Jojo Rabbit", "The Grand Budapest Hotel"]
    return ["Prisoners", "Little Miss Sunshine", "Argo"]


def infer_executive_summary(story_map: dict) -> str:
    title = story_map.get("title", "This project")
    protagonist = story_map.get("protagonist", "the lead")
    world = story_map.get("world", "feature drama")
    tone = story_map.get("tone", "")
    conflict = story_map.get("core_conflict", "")
    return f"{title} is a {world} built around {protagonist}, with a tone that plays {tone}. The commercial hook comes from a clear central engine: {conflict}"


def infer_actor_objective(story_map: dict) -> str:
    protagonist = story_map.get("protagonist", "the character")
    world = story_map.get("world", "")
    if "thriller" in world:
        return "Stay in control long enough to survive the pressure without revealing fear too early."
    if "fantasy" in world:
        return "Hold ground inside absurd power dynamics while using wit and instinct to stay one step ahead."
    if "legal" in world or "courtroom" in world:
        return "Press for truth and leverage without losing authority, credibility, or emotional precision."
    return f"Move the scene forward with clear intention while protecting what {protagonist} most wants from exposure or collapse."


def infer_playable_tactics(story_map: dict) -> list:
    world = story_map.get("world", "")
    tactics = ["Deflect", "Pressure", "Reframe", "Hold control"]
    if "fantasy" in world or "comedy" in world:
        tactics = ["Charm", "Deflect", "Pressure", "Observe", "Pivot"]
    if "thriller" in world:
        tactics = ["Probe", "Control", "Withhold", "Redirect", "Corner"]
    if "legal" in world:
        tactics = ["Corner", "Press", "Frame", "Challenge", "Hold authority"]
    return tactics[:5]


def infer_emotional_triggers(story_map: dict) -> list:
    world = story_map.get("world", "")
    if "fantasy" in world:
        return ["Humiliation", "Status shifts", "Public spectacle", "Unexpected danger"]
    if "thriller" in world:
        return ["Suspicion", "Loss of control", "Time pressure", "Misread intentions"]
    if "legal" in world:
        return ["Institutional pressure", "Exposure of truth", "Loss of credibility", "Moral confrontation"]
    return ["Rejection", "Pressure", "Exposure", "Uncertainty"]


def infer_audition_danger_zones(story_map: dict) -> list:
    world = story_map.get("world", "")
    zones = ["Overplaying intention", "Pushing emotion too early", "Ignoring listening beats"]
    if "comedy" in world or "fantasy" in world:
        zones.append("Playing the joke instead of the objective")
    if "thriller" in world:
        zones.append("Telegraphing fear instead of letting pressure build")
    if "legal" in world:
        zones.append("Mistaking authority for volume")
    return zones[:5]


def infer_reader_chemistry_tips(story_map: dict) -> list:
    return [
        "Pick fixed eyelines for each off-camera character.",
        "Let interruptions feel live rather than pre-timed.",
        "Use the reader to sharpen pressure changes, not flatten them.",
        "Stay responsive to pace shifts instead of locking one rhythm."
    ]


def infer_memorization_beats(story_map: dict) -> list:
    return ["Opening power move", "First pressure turn", "Status shift or reveal", "Control reset", "Exit beat / last impression"]


def infer_role_arc_map(story_map: dict) -> list:
    world = story_map.get("world", "")
    if "fantasy" in world:
        return ["outsider observation", "strategic adaptation", "increased political awareness", "active role in chaos", "earned authority"]
    if "thriller" in world:
        return ["uncertainty", "pressure escalation", "misread danger", "forced decision", "clarity through consequence"]
    if "legal" in world:
        return ["controlled distance", "institutional pressure", "moral confrontation", "truth pursuit", "earned conviction"]
    return ["setup", "pressure", "adaptation", "reversal", "resolution"]


def infer_pressure_ladder(story_map: dict) -> list:
    world = story_map.get("world", "")
    if "thriller" in world:
        return ["unease", "suspicion", "containment pressure", "escalation", "breaking point"]
    if "fantasy" in world:
        return ["social absurdity", "status pressure", "court risk", "public chaos", "high-stakes confrontation"]
    if "legal" in world:
        return ["professional tension", "institutional resistance", "truth pressure", "public exposure", "high-cost choice"]
    return ["low pressure", "rising tension", "complication", "peak pressure", "release"]


def infer_emotional_continuity(story_map: dict) -> list:
    return [
        "Track where confidence cracks, even if behavior stays controlled.",
        "Let pressure affect pace before it affects volume.",
        "Carry unresolved tension into the next scene rather than resetting to neutral.",
        "Protect consistency of listening behavior across takes and scenes."
    ]


def infer_costume_behavior_clues(story_map: dict) -> list:
    world = story_map.get("world", "")
    if "fantasy" in world:
        return ["Carry status in posture before dialogue.", "Let movement reflect court awareness and survival instinct."]
    if "thriller" in world:
        return ["Wardrobe should support fatigue, caution, or pressure.", "Behavior should stay alert even in stillness."]
    if "legal" in world:
        return ["Clothing and posture should signal discipline.", "Small behavioral control beats matter more than broad gestures."]
    return ["Costume should support role clarity.", "Behavior should align with status, confidence, and pressure level."]


def infer_set_ready_checklist(story_map: dict) -> list:
    return [
        "Know the scene's pressure level before you play it.",
        "Track what your character wants from each interaction.",
        "Mark where status rises, slips, or resets.",
        "Keep body language and listening behavior consistent across takes.",
        "Protect continuity more than novelty."
    ]


def _rank_real_characters(candidates: list, character_stats: dict, top_n: int = 8) -> list:
    """Filter the raw caps-candidate list down to the top-N REAL characters —
    those with meaningful dialogue AND action signal. Mirrors the ranking in
    merge_character_signals so Phase 2/3 outputs aren't polluted by noise like
    THE, MORE, SCRIPT that mechanical extraction happens to catch."""
    scored = []
    for name in candidates:
        stats = character_stats.get(name, {})
        d = stats.get("dialogue_count", 0)
        a = stats.get("action_count", 0)
        first = stats.get("first_seen", 99999)
        # Real characters have SOME signal on at least one axis, ideally both
        if d == 0 and a == 0:
            continue
        # Filter obvious non-character words even if they scored
        if name in NON_CHARACTER_PHRASES or name in BAD_TOKENS or name in SUSPICIOUS_SINGLE_WORDS:
            continue
        if name in GENERIC_ROLE_WORDS or name in PRONOUN_WORDS:
            continue
        score = d * 2 + a * 4
        if d > 0 and a > 0:
            score += 8  # bonus for real character signature (both dialogue + action)
        if first < 80:
            score += 6
        elif first < 160:
            score += 3
        scored.append((name, score, first))
    scored.sort(key=lambda x: (-x[1], x[2]))
    return [c[0] for c in scored[:top_n]]


def _fallback_story_map(text: str, title: str, characters: list, character_stats: dict = None) -> dict:
    """Deterministic story-analysis path. Runs when no API key is present.
    Uses the ported world-branched generators instead of flat template strings —
    outputs are real deterministic craft, not Mad-Libs."""
    character_stats = character_stats or {}

    # Filter raw candidates to top-8 REAL characters before anything downstream
    # touches them. Prevents polluted rankings / relationship maps.
    real_characters = _rank_real_characters(characters, character_stats, top_n=8)
    if not real_characters:
        real_characters = characters[:6]  # thin-signal fallback
    characters = real_characters  # override for the rest of the function

    protagonist = characters[0].title() if characters else "Protagonist"
    chars = [c.title() for c in characters[:6]]

    # Detect world first — every downstream generator branches on it
    world = detect_world(text)

    # Phase 2 — scene segmentation + presence map. Everything below reads
    # from the actual script structure, not per-world templates.
    try:
        scene_records, presence_totals = build_scene_presence_map(text, characters, character_stats)
    except Exception as _e:
        print(f"⚠️  scene presence map failed: {_e}")
        scene_records, presence_totals = [], {}

    # Phase 3 — character intelligence (rankings, relationships, actor prep).
    # All script-derived. Safe from the world-template leakage bug.
    try:
        character_rankings = build_character_rankings(characters, character_stats, presence_totals, protagonist)
        relationship_matrix = build_relationship_matrix(characters, scene_records, protagonist)
        actor_prep_signal_map = build_actor_prep_signal_map(characters, scene_records)
        confidence_layer = build_confidence_layer(characters, character_rankings, scene_records)
        rel_map_for_templates = build_relationship_leverage_map_for_templates(relationship_matrix)
        phase3_strengths, phase3_risks = build_strengths_and_risks_from_confidence(confidence_layer, character_rankings)
    except Exception as _e:
        print(f"⚠️  Phase 3 character intelligence failed: {_e}")
        character_rankings = []
        relationship_matrix = []
        actor_prep_signal_map = {}
        confidence_layer = {}
        rel_map_for_templates = []
        phase3_strengths, phase3_risks = [], []

    story_map = {
        "title": title,
        "world": world,
        "protagonist": protagonist,
        "characters": chars,
        "character_arcs": {},  # Phase 4 wires per-char arc narratives from scene beats
        "relationship_leverage_map": rel_map_for_templates,
        "act_breakdown": build_act_breakdown_from_scenes(scene_records),
        "scene_presence_map": scene_records,
        "scene_presence_totals": presence_totals,
        "character_rankings": character_rankings,
        "relationship_matrix": relationship_matrix,
        "actor_prep_signal_map": actor_prep_signal_map,
        "confidence_layer": confidence_layer,
        "executive_summary": f"{title} is a drama built around {protagonist}.",
        "commercial_positioning": "Character-driven story with clear pitch angles.",
        "packaging_potential": "Depends on a strong central performance.",
        "character_leverage": "The protagonist's journey drives commercial appeal.",
        "comparable_films": [],
        "tone_comparables": [],
        "audience_profile": ["General film audiences", "Character-driven story viewers"],
        "market_projections": {
            "budget_range": "",
            "distribution_angle": "",
            "awards_potential": "",
            "audience_reach": "",
            "franchise_potential": "",
        },
        "strength_index": {"concept": 7, "character": 7, "marketability": 6, "originality": 7},
        "strengths": phase3_strengths,
        "development_risks": phase3_risks,
        "character_stats": {c: {"dialogue_count": 0, "action_count": 0, "first_seen": 99999} for c in chars},
        "actor_objective": f"Move the scene forward with clear intention while protecting what {protagonist} most wants.",
        "role_arc_map": ["setup", "pressure", "adaptation", "reversal", "resolution"],
        "pressure_ladder": ["low pressure", "rising tension", "complication", "peak pressure", "release"],
        "emotional_continuity": ["Track where confidence cracks.", "Let pressure affect pace before volume."],
        "playable_tactics": ["Deflect", "Pressure", "Reframe", "Hold", "Pivot"],
        "emotional_triggers": ["Rejection", "Pressure", "Exposure", "Uncertainty"],
        "audition_danger_zones": ["Overplaying intention", "Pushing emotion too early", "Ignoring listening beats"],
        "reader_chemistry_tips": ["Pick fixed eyelines.", "Let interruptions feel live.", "Stay responsive to pace shifts."],
        "memorization_beats": ["Opening beat", "First pressure turn", "Status shift", "Control reset", "Exit beat"],
        "costume_behavior_clues": ["Costume supports role clarity.", "Behavior aligns with status and pressure level."],
        "set_ready_checklist": ["Know the objective.", "Understand the relationship stakes.", "Prepare the physical life of the character."],
        "visual_keywords": ["cinematic", "dramatic", "grounded", "pressure", "environment"],
        "tagline": "Some things can't be undone.",  # Phase 1 does not yet upgrade tagline
    }

    # Phase 1 deterministic upgrades — replace flat template strings with
    # world-branched narrative craft from FINAL_OUTPUT_ENFORCER.
    # Ordering matters: generators that need story_map["world"]/["protagonist"]/["characters"]
    # run first; generators that read core_conflict/reversal (theme) run last.
    story_map["tone"] = infer_tone(text, world)
    story_map["setting"] = infer_setting(text, world)
    story_map["time_frame"] = infer_time_frame(text)
    story_map["story_engine"] = infer_story_engine(text, protagonist)
    story_map["core_conflict"] = infer_core_conflict(text, protagonist)
    story_map["reversal"] = infer_reversal(text)
    story_map["logline"] = build_logline_from_story_map(story_map)
    story_map["synopsis"] = build_synopsis_from_story_map(story_map)
    story_map["protagonist_summary"] = infer_protagonist_summary(story_map)
    story_map["theme"] = infer_theme(story_map)
    story_map["protagonist_profile"] = {"name": protagonist, "summary": story_map["protagonist_summary"]}

    # Phase 4 — world-lookup fills for the remaining Mad-Libs template fields.
    # These read world/protagonist/characters/tone from story_map (all set above).
    story_map["commercial_positioning"] = infer_commercial_positioning(story_map)
    story_map["audience_profile"] = infer_audience_profile(story_map)
    story_map["strength_index"] = infer_strength_index(story_map)
    story_map["packaging_potential"] = infer_packaging_potential(story_map)
    story_map["character_leverage"] = infer_character_leverage(story_map)
    story_map["tone_comparables"] = infer_tone_comparables(story_map)
    story_map["executive_summary"] = infer_executive_summary(story_map)
    story_map["actor_objective"] = infer_actor_objective(story_map)
    story_map["playable_tactics"] = infer_playable_tactics(story_map)
    story_map["emotional_triggers"] = infer_emotional_triggers(story_map)
    story_map["audition_danger_zones"] = infer_audition_danger_zones(story_map)
    story_map["reader_chemistry_tips"] = infer_reader_chemistry_tips(story_map)
    story_map["memorization_beats"] = infer_memorization_beats(story_map)
    story_map["role_arc_map"] = infer_role_arc_map(story_map)
    story_map["pressure_ladder"] = infer_pressure_ladder(story_map)
    story_map["emotional_continuity"] = infer_emotional_continuity(story_map)
    story_map["costume_behavior_clues"] = infer_costume_behavior_clues(story_map)
    story_map["set_ready_checklist"] = infer_set_ready_checklist(story_map)

    # Phase 5 — sanity + final output enforcer passes.
    # Defensive: scrubs placeholder token leaks, writes downstream aliases.
    story_map["character_stats"] = character_stats  # needed by choose_clean_protagonist
    story_map = apply_sanity_pass(story_map)
    story_map = apply_final_output_enforcer(story_map)

    return story_map


def build_story_map(text: str) -> dict:
    # Step 1: Mechanical extraction — character stat counting only
    title = extract_title(text)
    dialogue_counts, dialogue_first, dialogue_support = analyze_dialogue_characters(text)
    action_counts, action_first = extract_action_names(text)
    characters_ranked, character_stats = merge_character_signals(
        dialogue_counts, dialogue_first, dialogue_support, action_counts, action_first
    )

    # Step 2: Claude reads the full screenplay and generates everything
    print("🧠 Sending screenplay to Claude for analysis...")
    story_map = analyze_script_with_claude(text, title, character_stats)

    # Step 3: Merge mechanical stats into Claude's character list
    claude_characters = story_map.get("characters") or characters_ranked[:6]
    merged_stats = {}
    for c in claude_characters:
        upper_c = c.upper()
        if upper_c in character_stats:
            merged_stats[c] = character_stats[upper_c]
        else:
            matched = next(
                (k for k in character_stats if k in upper_c or upper_c in k), None
            )
            merged_stats[c] = character_stats.get(
                matched, {"dialogue_count": 0, "action_count": 0, "first_seen": 99999}
            )
    story_map["character_stats"] = merged_stats

    # Ensure protagonist_profile exists
    protagonist = story_map.get("protagonist", "")
    if protagonist and "protagonist_profile" not in story_map:
        story_map["protagonist_profile"] = {
            "name": protagonist,
            "summary": story_map.get("protagonist_summary", ""),
        }

    # Layout fields computed from Claude's world + tone strings
    story_map["presentation_modes"] = infer_presentation_scores(story_map)
    story_map["presentation_controls"] = infer_presentation_controls(story_map)
    story_map["layout_strategy"] = infer_layout_strategy(story_map)
    story_map["slide_blueprint"] = infer_slide_blueprint(story_map)
    story_map["document_layouts"] = infer_document_layouts(story_map)

    return story_map


# ─── LAYOUT / PRESENTATION ───────────────────────────────────────────────────

def infer_document_layouts(story_map: dict) -> dict:
    cat = _world_category(story_map.get("world", ""))
    primary_mode = ((story_map.get("presentation_modes") or {}).get("primary_mode") or "character_heart")
    strategy = story_map.get("layout_strategy") or {}

    analysis_style = "clean_cinematic_report"
    actor_style = "character_workbook_dark"
    audition_style = "fast_turnaround_brief"
    booked_style = "deep_role_dossier"
    chart_style = "gold_on_dark"

    if cat == "legal_courtroom" or primary_mode == "prestige_authority":
        analysis_style = "prestige_report"
        actor_style = "institutional_character_brief"
        audition_style = "measured_authority_sides"
        booked_style = "prestige_role_bible"
        chart_style = "formal_gold_grid"
    elif cat in ("contained_urban", "thriller", "action_espionage") or primary_mode == "tension_pressure":
        analysis_style = "thriller_intelligence_report"
        actor_style = "pressure_character_brief"
        audition_style = "urgent_sides_brief"
        booked_style = "contained_thriller_role_map"
        chart_style = "signal_on_dark"
    elif cat == "fantasy_satire" or primary_mode == "spectacle_play":
        analysis_style = "storybook_analysis_report"
        actor_style = "playful_character_brief"
        audition_style = "characterful_sides_brief"
        booked_style = "fantasy_role_bible"
        chart_style = "ornate_gold_cards"
    elif primary_mode == "character_heart":
        analysis_style = "human_story_report"
        actor_style = "relationship_character_brief"
        audition_style = "intimate_sides_brief"
        booked_style = "emotional_role_bible"
        chart_style = "warm_neutral_report"

    return {
        "analysis_report": {
            "layout_family": analysis_style,
            "cover_style": strategy.get("headline_style", "statement"),
            "chart_style": chart_style,
            "section_density": strategy.get("text_density", "medium"),
        },
        "actor_prep_report": {
            "layout_family": actor_style,
            "beat_style": "scene_playable_cards",
            "callout_style": chart_style,
            "section_density": "medium_high",
        },
        "audition_analyzer": {
            "layout_family": audition_style,
            "delivery_mode": "quickpack",
            "section_density": "fast_read",
            "callout_style": chart_style,
        },
        "booked_role_analyzer": {
            "layout_family": booked_style,
            "delivery_mode": "deep_prep",
            "section_density": "expanded",
            "callout_style": chart_style,
        },
    }


def infer_presentation_scores(story_map: dict) -> dict:
    world = (story_map.get("world") or "").lower()
    tone = (story_map.get("tone") or "").lower()
    story_engine = (story_map.get("story_engine") or "").lower()
    conflict = (story_map.get("core_conflict") or "").lower()
    synopsis = (story_map.get("synopsis") or "").lower()
    reversal = (story_map.get("reversal") or "").lower()
    text_blob = " ".join([world, tone, story_engine, conflict, synopsis, reversal])

    scores = {
        "prestige_authority": 10,
        "tension_pressure": 10,
        "character_heart": 10,
        "spectacle_play": 10,
    }

    prestige_terms = [
        "courtroom", "legal", "military", "institution", "authority", "verdict",
        "hierarchy", "command", "political", "corporate", "prestige", "procedural",
        "under oath", "truth", "moral", "discipline"
    ]
    tension_terms = [
        "thriller", "pressure", "danger", "fear", "suspicion", "escalate", "paranoid",
        "crime", "buried", "risk", "threat", "urgent", "nocturnal", "claustrophobic",
        "chase", "survive", "consequence", "trap"
    ]
    heart_terms = [
        "family", "identity", "relationship", "emotional", "heart", "redemption",
        "human", "vulnerability", "love", "grief", "friendship", "belonging",
        "personal", "career or", "what kind of", "who they are"
    ]
    spectacle_terms = [
        "fantasy", "comedy", "satire", "adventure", "kingdom", "pageantry", "world",
        "spectacle", "playful", "witty", "absurd", "chaos", "storybook", "epic",
        "theatrical", "action", "big", "cinematic"
    ]

    for term in prestige_terms:
        if term in text_blob:
            scores["prestige_authority"] += 7
    for term in tension_terms:
        if term in text_blob:
            scores["tension_pressure"] += 7
    for term in heart_terms:
        if term in text_blob:
            scores["character_heart"] += 6
    for term in spectacle_terms:
        if term in text_blob:
            scores["spectacle_play"] += 7

    cat = _world_category(world)
    if cat == "legal_courtroom":
        scores["prestige_authority"] += 30
        scores["tension_pressure"] += 10
    elif cat == "action_espionage":
        scores["tension_pressure"] += 28
        scores["spectacle_play"] += 8
    elif cat == "contained_urban":
        scores["tension_pressure"] += 28
        scores["character_heart"] += 6
    elif cat == "fantasy_satire":
        scores["spectacle_play"] += 30
        scores["character_heart"] += 8
    elif cat == "nightlife_comedy":
        scores["spectacle_play"] += 24
        scores["character_heart"] += 8
    elif cat == "sports_drama":
        scores["character_heart"] += 18
        scores["prestige_authority"] += 6
        scores["tension_pressure"] += 8
    elif cat == "romantic_comedy":
        scores["character_heart"] += 22
        scores["spectacle_play"] += 8

    if any(t in tone for t in ["playful", "witty", "satirical", "heightened", "chaotic"]):
        scores["spectacle_play"] += 16
    if any(t in tone for t in ["tense", "sharp", "paranoid", "volatile", "claustrophobic"]):
        scores["tension_pressure"] += 16
    if any(t in tone for t in ["morally charged", "procedural", "restrained", "focused"]):
        scores["prestige_authority"] += 14
    if any(t in tone for t in ["emotional", "warm", "human", "grounded"]):
        scores["character_heart"] += 14

    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    primary_mode = ordered[0][0]
    secondary_mode = ordered[1][0]

    return {
        "presentation_scores": scores,
        "primary_mode": primary_mode,
        "secondary_mode": secondary_mode,
    }


def infer_presentation_controls(story_map: dict) -> dict:
    modes = story_map.get("presentation_modes") or {}
    primary = modes.get("primary_mode", "character_heart")
    secondary = modes.get("secondary_mode", "tension_pressure")

    controls = {
        "layout_energy": "medium",
        "discipline_level": "medium",
        "image_dominance": "medium_high",
        "rhythm_bias": "balanced",
    }

    if primary == "prestige_authority":
        controls.update({"layout_energy": "measured", "discipline_level": "high", "image_dominance": "medium", "rhythm_bias": "disciplined"})
    elif primary == "tension_pressure":
        controls.update({"layout_energy": "high", "discipline_level": "medium_high", "image_dominance": "high", "rhythm_bias": "tight"})
    elif primary == "character_heart":
        controls.update({"layout_energy": "medium", "discipline_level": "medium", "image_dominance": "medium", "rhythm_bias": "intimate"})
    elif primary == "spectacle_play":
        controls.update({"layout_energy": "high", "discipline_level": "medium_low", "image_dominance": "high", "rhythm_bias": "elastic"})

    if secondary == "character_heart" and controls["discipline_level"] in {"medium_high", "high"}:
        controls["discipline_level"] = "medium"
    if secondary == "prestige_authority" and primary == "spectacle_play":
        controls["discipline_level"] = "medium"
    if secondary == "spectacle_play" and primary == "tension_pressure":
        controls["layout_energy"] = "high"

    return controls


def infer_layout_strategy(story_map: dict) -> dict:
    cat = _world_category(story_map.get("world", ""))
    tone = (story_map.get("tone") or "").lower()
    synopsis = (story_map.get("synopsis") or "").lower()

    layout_style = "cinematic_grounded"
    text_density = "medium"
    image_priority = "high"
    pacing = "measured"
    visual_energy = "controlled"
    slide_rhythm = "balanced"
    headline_style = "statement"
    composition_bias = "image_forward"

    if cat == "action_espionage":
        layout_style = "cinematic_high_tension"
        text_density = "low"
        image_priority = "very_high"
        pacing = "fast"
        visual_energy = "volatile"
        slide_rhythm = "punchy"
        headline_style = "hook"
        composition_bias = "full_bleed"
    elif cat == "contained_urban":
        layout_style = "contained_nocturnal"
        text_density = "low"
        image_priority = "very_high"
        pacing = "tight"
        visual_energy = "claustrophobic"
        slide_rhythm = "minimal"
        headline_style = "hook"
        composition_bias = "full_bleed"
    elif cat == "legal_courtroom":
        layout_style = "institutional_cinematic"
        text_density = "medium"
        image_priority = "high"
        pacing = "measured"
        visual_energy = "restrained_intense"
        slide_rhythm = "balanced"
        headline_style = "argument"
        composition_bias = "split_text_image"
    elif cat == "fantasy_satire":
        layout_style = "storybook_satirical"
        text_density = "medium"
        image_priority = "high"
        pacing = "playful"
        visual_energy = "heightened"
        slide_rhythm = "varied"
        headline_style = "characterful"
        composition_bias = "illustrative"
    elif cat == "romantic_comedy":
        layout_style = "romantic_cinematic"
        text_density = "medium"
        image_priority = "high"
        pacing = "warm"
        visual_energy = "emotional"
        slide_rhythm = "flowing"
        headline_style = "characterful"
        composition_bias = "image_forward"
    elif cat == "nightlife_comedy":
        layout_style = "neon_social_chaos"
        text_density = "low"
        image_priority = "very_high"
        pacing = "fast"
        visual_energy = "chaotic"
        slide_rhythm = "punchy"
        headline_style = "hook"
        composition_bias = "full_bleed"
    elif cat == "sports_drama":
        layout_style = "athletic_prestige"
        text_density = "medium"
        image_priority = "high"
        pacing = "driving"
        visual_energy = "focused"
        slide_rhythm = "balanced"
        headline_style = "statement"
        composition_bias = "hero_image"
    elif cat == "crime_drama":
        layout_style = "urban_crime_cinematic"
        text_density = "medium"
        image_priority = "high"
        pacing = "measured"
        visual_energy = "tense"
        slide_rhythm = "balanced"
        headline_style = "hook"
        composition_bias = "full_bleed"
    elif cat == "thriller":
        layout_style = "cinematic_suspense"
        text_density = "low"
        image_priority = "very_high"
        pacing = "tight"
        visual_energy = "volatile"
        slide_rhythm = "punchy"
        headline_style = "hook"
        composition_bias = "full_bleed"

    if "morally charged" in tone or "procedural" in tone:
        text_density = "medium_high"
        slide_rhythm = "disciplined"
    if "playful" in tone or "satirical" in tone:
        slide_rhythm = "elastic"
    if "chaotic" in tone or "energetic" in tone:
        pacing = "fast"
    if "nocturnal" in tone or "paranoid" in tone:
        composition_bias = "full_bleed"
    if len(synopsis.split()) > 85 and text_density == "low":
        text_density = "medium"

    return {
        "layout_style": layout_style,
        "text_density": text_density,
        "image_priority": image_priority,
        "pacing": pacing,
        "visual_energy": visual_energy,
        "slide_rhythm": slide_rhythm,
        "headline_style": headline_style,
        "composition_bias": composition_bias,
    }


def infer_slide_blueprint(story_map: dict) -> dict:
    cat = _world_category(story_map.get("world", ""))
    strategy = story_map.get("layout_strategy") or {}

    slide_count = 12
    if strategy.get("image_priority") == "very_high":
        slide_count = 14
    if cat == "legal_courtroom":
        slide_count = 13
    if cat == "fantasy_satire":
        slide_count = 14

    opening_style = "title_then_hook"
    headline_style = strategy.get("headline_style", "statement")
    if headline_style == "argument":
        opening_style = "title_then_premise"
    if headline_style == "characterful":
        opening_style = "title_then_world"

    return {
        "recommended_slide_count": slide_count,
        "opening_style": opening_style,
        "mid_deck_focus": strategy.get("composition_bias", "image_forward"),
        "closing_style": "punchline_with_heart" if cat == "nightlife_comedy" else "statement",
    }


# ─── IMAGE TERM FUNCTIONS ────────────────────────────────────────────────────

def base_image_terms(story_map: dict) -> list[str]:
    cat = _world_category(story_map.get("world", ""))
    visual_keywords = story_map.get("visual_keywords") or []
    terms = []

    if cat == "action_espionage":
        terms.extend(["covert", "surveillance", "domestic_tension", "high_stakes", "cinematic"])
    elif cat == "contained_urban":
        terms.extend(["urban", "night", "car", "tension", "isolation"])
    elif cat == "legal_courtroom":
        terms.extend(["courtroom", "institution", "authority", "moral_pressure"])
    elif cat == "fantasy_satire":
        terms.extend(["kingdom", "pageantry", "satire", "fantasy", "court_chaos"])
    elif cat == "romantic_comedy":
        terms.extend(["romance", "connection", "warmth", "social_world", "emotional_honesty"])
    elif cat == "nightlife_comedy":
        terms.extend(["nightlife", "social_chaos", "party", "awkwardness", "city_night"])
    elif cat == "sports_drama":
        terms.extend(["sports", "court", "locker_room", "pressure", "competition"])
    elif cat == "crime_drama":
        terms.extend(["urban", "danger", "night", "street", "pressure"])
    elif cat == "thriller":
        terms.extend(["tension", "shadow", "isolation", "urban", "pressure"])
    else:
        terms.extend(["grounded", "dramatic", "environment"])

    terms.extend([k for k in visual_keywords[:4] if k not in terms])
    return terms


def slide_visual_terms(slide_name: str, story_map: dict) -> list[str]:
    cat = _world_category(story_map.get("world", ""))
    protagonist = slugify(story_map.get("protagonist", ""))
    tone_terms = [slugify(t) for t in (story_map.get("tone") or "").split(",") if t.strip()]
    base_terms = base_image_terms(story_map)

    mapping = {
        "Title": ["establishing", "cinematic", "world"],
        "Logline": ["wide", "establishing", "mood"],
        "Synopsis": ["pressure", "environment", "story_world"],
        "Protagonist": ["isolation", "implied_presence", protagonist],
        "Antagonist": ["pressure", "rival_energy", "confrontation_space"],
        "Supporting Characters": ["group_dynamic", "world_detail", "relationship_space"],
        "Theme": ["symbolic", "atmosphere", "identity"],
        "Tone": ["mood", "texture", "lighting"],
        "World": ["environment", "place", "lived_in"],
        "Conflict Engine": ["tension", "separation", "friction"],
        "Stakes": ["scale", "emptiness", "consequence"],
        "Why This Film": ["cinematic", "elevated", "statement"],
        "Audience": ["relatable_world", "emotion", "aspiration"],
        "Visual Style": ["visual_texture", "lighting", "composition"],
        "Comparables": ["premium", "cinematic", "recognizable_lane"],
        "Market Position": ["commercial", "elevated", "broad_appeal"],
        "Director Vision": ["intimate", "framing", "movement"],
        "Casting Ideas": ["presence", "silhouette", "human_energy"],
        "Production Scope": ["contained", "practical", "real_world"],
        "Closing Statement": ["emotional_finality", "impact", "resonance"],
    }

    cat_slide_terms = {
        "action_espionage": {
            "world_base": ["surveillance", "night_operation", "hidden_identity"],
            "character": ["split_life", "domestic_cover", "covert_pressure"],
            "theme": ["explosive_reveal", "family_risk", "high_stakes"],
        },
        "contained_urban": {
            "world_base": ["streetlights", "car_interior", "night"],
            "character": ["windshield", "rearview", "implied_presence"],
            "theme": ["pressure", "isolation", "urban"],
        },
        "legal_courtroom": {
            "world_base": ["courtroom_wide", "military_formality", "institutional_space"],
            "character": ["witness_stand", "interrogation_room", "command_pressure"],
            "theme": ["truth_under_oath", "moral_weight", "verdict_energy"],
        },
        "fantasy_satire": {
            "world_base": ["castle_wide", "ceremonial_absurdity", "storybook_scale"],
            "character": ["throne_room", "comic_intrigue", "royal_misrule"],
            "theme": ["satirical_pageantry", "kingdom_chaos", "comic_resolution"],
        },
        "romantic_comedy": {
            "world_base": ["warm_interior", "social_setting", "romance_connection"],
            "character": ["intimate_moment", "social_pressure", "friendship_bond"],
            "theme": ["love_realization", "emotional_honesty", "comic_warmth"],
        },
        "nightlife_comedy": {
            "world_base": ["club_exterior", "velvet_rope", "city_lights"],
            "character": ["dancefloor", "awkward_party", "social_pressure"],
            "theme": ["afterparty_fallout", "neon_regret", "comic_release"],
        },
        "sports_drama": {
            "world_base": ["empty_court", "arena", "night"],
            "character": ["locker_room", "hallway", "quiet_pressure"],
            "theme": ["scoreboard", "gym", "after_hours"],
        },
        "crime_drama": {
            "world_base": ["street_night", "urban_grit", "danger_interior"],
            "character": ["confrontation", "underworld_space", "tension"],
            "theme": ["consequence", "moral_cost", "street_truth"],
        },
    }

    terms = []
    terms.extend(base_terms)
    terms.extend(tone_terms[:3])
    terms.extend(mapping.get(slide_name, ["cinematic", "environment"]))

    cat_terms = cat_slide_terms.get(cat, {})
    if slide_name in {"Title", "Logline", "World"}:
        terms.extend(cat_terms.get("world_base", []))
    elif slide_name in {"Protagonist", "Antagonist", "Supporting Characters", "Conflict Engine", "Stakes"}:
        terms.extend(cat_terms.get("character", []))
    elif slide_name in {"Theme", "Closing Statement"}:
        terms.extend(cat_terms.get("theme", []))

    seen = set()
    ordered = []
    for t in terms:
        if not t:
            continue
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


def score_terms_for_slide(slide_name: str, story_map: dict) -> dict:
    cat = _world_category(story_map.get("world", ""))
    primary_mode = story_map.get("presentation_modes", {}).get("primary_mode", "")
    secondary_mode = story_map.get("presentation_modes", {}).get("secondary_mode", "")
    protagonist = slugify(story_map.get("protagonist", ""))
    weights: dict[str, int] = {}

    def bump(term: str, points: int):
        if not term:
            return
        weights[term] = weights.get(term, 0) + points

    slide_weights = {
        "Title": [("establishing", 18), ("cinematic", 16), ("world", 14)],
        "Logline": [("mood", 15), ("wide", 14), ("establishing", 12)],
        "Synopsis": [("story_world", 16), ("pressure", 14), ("environment", 12)],
        "Protagonist": [(protagonist, 20), ("implied_presence", 16), ("isolation", 14)],
        "Antagonist": [("rival_energy", 16), ("confrontation_space", 14), ("pressure", 10)],
        "Supporting Characters": [("group_dynamic", 16), ("relationship_space", 14), ("world_detail", 10)],
        "Theme": [("symbolic", 18), ("identity", 14), ("atmosphere", 12)],
        "Tone": [("mood", 18), ("lighting", 14), ("texture", 12)],
        "World": [("place", 16), ("environment", 16), ("lived_in", 12)],
        "Conflict Engine": [("tension", 18), ("friction", 14), ("separation", 12)],
        "Stakes": [("consequence", 18), ("scale", 14), ("emptiness", 10)],
        "Why This Film": [("statement", 16), ("elevated", 14), ("cinematic", 12)],
        "Audience": [("emotion", 16), ("relatable_world", 12), ("aspiration", 10)],
        "Visual Style": [("composition", 16), ("lighting", 14), ("visual_texture", 12)],
        "Comparables": [("premium", 14), ("cinematic", 12), ("recognizable_lane", 10)],
        "Market Position": [("commercial", 14), ("broad_appeal", 12), ("elevated", 10)],
        "Director Vision": [("framing", 16), ("movement", 12), ("intimate", 10)],
        "Casting Ideas": [("presence", 14), ("silhouette", 12), ("human_energy", 10)],
        "Production Scope": [("practical", 14), ("contained", 12), ("real_world", 10)],
        "Closing Statement": [("impact", 16), ("resonance", 14), ("emotional_finality", 12)],
    }
    for term, pts in slide_weights.get(slide_name, []):
        bump(term, pts)

    cat_world_map = {
        "action_espionage": {
            "base": [("surveillance", 14), ("night_operation", 12), ("hidden_identity", 10)],
            "character": [("split_life", 14), ("covert_pressure", 12), ("domestic_cover", 10)],
            "theme": [("family_risk", 12), ("explosive_reveal", 10), ("high_stakes", 10)],
        },
        "contained_urban": {
            "base": [("streetlights", 16), ("car_interior", 14), ("night", 12)],
            "character": [("rearview", 14), ("windshield", 12), ("implied_presence", 10)],
            "theme": [("pressure", 10), ("isolation", 10), ("urban", 8)],
        },
        "legal_courtroom": {
            "base": [("courtroom_wide", 16), ("institutional_space", 14), ("military_formality", 10)],
            "character": [("witness_stand", 14), ("command_pressure", 12), ("interrogation_room", 10)],
            "theme": [("truth_under_oath", 12), ("moral_weight", 10), ("verdict_energy", 10)],
        },
        "fantasy_satire": {
            "base": [("castle_wide", 16), ("storybook_scale", 14), ("ceremonial_absurdity", 10)],
            "character": [("throne_room", 14), ("comic_intrigue", 12), ("royal_misrule", 10)],
            "theme": [("satirical_pageantry", 12), ("kingdom_chaos", 10), ("comic_resolution", 10)],
        },
        "romantic_comedy": {
            "base": [("romance_connection", 16), ("warm_interior", 14), ("social_setting", 10)],
            "character": [("intimate_moment", 14), ("social_pressure", 12), ("friendship_bond", 10)],
            "theme": [("love_realization", 12), ("emotional_honesty", 10), ("comic_warmth", 10)],
        },
        "nightlife_comedy": {
            "base": [("club_exterior", 14), ("velvet_rope", 12), ("city_lights", 10)],
            "character": [("awkward_party", 14), ("social_pressure", 12), ("dancefloor", 10)],
            "theme": [("afterparty_fallout", 12), ("neon_regret", 10), ("comic_release", 10)],
        },
        "sports_drama": {
            "base": [("arena", 14), ("empty_court", 12), ("night", 8)],
            "character": [("locker_room", 14), ("quiet_pressure", 12), ("hallway", 10)],
            "theme": [("scoreboard", 12), ("after_hours", 10), ("gym", 8)],
        },
        "crime_drama": {
            "base": [("street_night", 14), ("urban_grit", 12), ("danger_interior", 10)],
            "character": [("confrontation", 14), ("tension", 12), ("underworld", 10)],
            "theme": [("consequence", 12), ("moral_cost", 10), ("street_truth", 8)],
        },
    }

    category = "base"
    if slide_name in {"Protagonist", "Antagonist", "Supporting Characters", "Conflict Engine", "Stakes"}:
        category = "character"
    elif slide_name in {"Theme", "Tone", "Why This Film", "Closing Statement"}:
        category = "theme"

    for term, pts in cat_world_map.get(cat, {}).get(category, []):
        bump(term, pts)

    mode_weights = {
        "prestige_authority": [("premium", 12), ("authority", 10), ("disciplined", 8)],
        "tension_pressure": [("tension", 12), ("pressure", 10), ("isolation", 8)],
        "character_heart": [("emotion", 12), ("human_energy", 10), ("intimate", 8)],
        "spectacle_play": [("spectacle", 12), ("pageantry", 10), ("playful", 8)],
    }
    for term, pts in mode_weights.get(primary_mode, []):
        bump(term, pts)
    for term, pts in mode_weights.get(secondary_mode, []):
        bump(term, max(4, pts // 2))

    return weights


def infer_file_strategy(slide_name: str, story_map: dict) -> dict:
    composition = story_map.get("layout_strategy", {}).get("composition_bias", "balanced")
    if slide_name in {"Title", "World", "Visual Style", "Closing Statement"}:
        return {"subject_preference": "environment_first", "framing": "wide", "people_density": "low_to_medium", "swap_ready": True}
    if slide_name in {"Protagonist", "Antagonist", "Supporting Characters", "Conflict Engine", "Stakes"}:
        return {"subject_preference": "character_presence", "framing": "medium", "people_density": "medium", "swap_ready": True}
    if slide_name in {"Tone", "Theme", "Why This Film", "Audience", "Comparables"}:
        return {"subject_preference": "mood_symbolic", "framing": "flexible", "people_density": "low", "swap_ready": True}
    return {"subject_preference": composition, "framing": "flexible", "people_density": "medium", "swap_ready": True}


def build_image_plan(story_map: dict) -> list[dict]:
    slide_names = [
        "Title", "Logline", "Synopsis", "Protagonist", "Antagonist",
        "Supporting Characters", "Theme", "Tone", "World", "Conflict Engine",
        "Stakes", "Why This Film", "Audience", "Visual Style", "Comparables",
        "Market Position", "Director Vision", "Casting Ideas", "Production Scope",
        "Closing Statement",
    ]
    plan = []
    for idx, slide_name in enumerate(slide_names, start=1):
        terms = slide_visual_terms(slide_name, story_map)
        plan.append({
            "slide_number": idx,
            "slide_title": slide_name,
            "image_query": " ".join(terms[:4]),
            "image_tags": terms,
            "image_score": 1.0,
            "preferred_folders": [],
            "visual_family": None,
            "file_strategy": infer_file_strategy(slide_name, story_map),
            "image_options": [],
        })
    return plan


def main():
    if len(sys.argv) < 2:
        print("❌ No input provided")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    ext = input_path.suffix.lower()
    if ext == ".pdf":
        try:
            reader = PdfReader(input_path)
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception:
            text = ""
    elif ext in (".docx", ".doc"):
        try:
            import docx as _docx
            doc = _docx.Document(str(input_path))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            text = input_path.read_text(errors="ignore")
    else:
        text = input_path.read_text(errors="ignore")
    story_map = build_story_map(text)

    print(f"🎬 Title: {story_map['title']}")
    print(f"🔥 Characters: {story_map['characters']}")
    print(f"🎯 Protagonist: {story_map['protagonist']}")
    print(f"🌍 World: {story_map['world']}")
    print(f"🎭 Tone: {story_map['tone']}")
    print(f"🪞 Theme: {story_map['theme']}")
    print(f"🧠 Story Engine: {story_map['story_engine']}")
    print(f"⚔️ Core Conflict: {story_map['core_conflict']}")
    print(f"🔄 Reversal: {story_map['reversal']}")
    print(f"🧾 Logline: {story_map['logline']}")
    print(f"📚 Synopsis: {story_map['synopsis']}")
    print(f"🎛️ Presentation Modes: {json.dumps(story_map['presentation_modes'], indent=2)}")
    print(f"🧱 Layout Strategy: {json.dumps(story_map['layout_strategy'], indent=2)}")

    _dai_work_dir = os.environ.get("DAI_WORK_DIR", "")
    out_path = Path(_dai_work_dir) / "approved_brain_output.json" if _dai_work_dir else OUT
    if _dai_work_dir:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(story_map, indent=2))


if __name__ == "__main__":
    main()
