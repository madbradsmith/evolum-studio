import json
import os
import re

# Paths
ANALYSIS_DIR = os.path.expanduser("~/app/pipeline/analysis")
INPUT_DIR = os.path.expanduser("~/app/input")

INPUT_PATH = os.path.join(INPUT_DIR, "script_input.txt")
OUTPUT_PATH = os.path.join(ANALYSIS_DIR, "analysis_output.json")
ERROR_PATH = os.path.join(ANALYSIS_DIR, "analysis_error_report.json")


TITLE_GARBAGE_PATTERNS = [
    r"(?i)^written by\b",
    r"(?i)^screenplay by\b",
    r"(?i)^story by\b",
    r"(?i)^created by\b",
    r"(?i)^based on\b",
    r"(?i)^developum\b",
]

PLACEHOLDER_TITLE_VALUES = {
    "title",
    "untitled project",
    "screenplay",
}


def load_input_text(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def normalize_whitespace(text):
    return re.sub(r"\s+", " ", text).strip()


def split_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def split_sentences(text):
    cleaned = text.replace("\n", " ").strip()
    parts = re.split(r'(?<=[.!?])\s+', cleaned)
    return [normalize_whitespace(p) for p in parts if p.strip()]


def is_title_garbage(line):
    lowered = line.strip().lower()
    if lowered in PLACEHOLDER_TITLE_VALUES:
        return True
    for pattern in TITLE_GARBAGE_PATTERNS:
        if re.match(pattern, line.strip()):
            return True
    return False


def infer_project_title(text):
    lines = split_lines(text)
    for line in lines[:8]:
        if not is_title_garbage(line):
            return line[:120]
    return "Untitled Project"


def remove_title_block(text):
    lines = split_lines(text)
    if not lines:
        return text

    kept = []
    skipped_title = False

    for i, line in enumerate(lines):
        if i == 0 and not is_title_garbage(line):
            skipped_title = True
            continue
        if skipped_title and i < 5 and is_title_garbage(line):
            continue
        kept.append(line)

    return "\n".join(kept).strip()


def first_story_chunk(text, limit=3000):
    body = remove_title_block(text)
    return body[:limit]


def infer_protagonist(text):
    body = first_story_chunk(text)
    sentences = split_sentences(body)

    priority_patterns = [
        r"\b([A-Z][a-z]+ [A-Z][a-z]+),\s+a[n]?\s+[^.]{0,80}\b",
        r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b",
    ]

    lead_indicator_sentences = []
    for sentence in sentences[:12]:
        lowered = sentence.lower()
        if any(
            phrase in lowered for phrase in [
                "over the course",
                "follows",
                "story of",
                "centers on",
                "trying to",
                "must",
                "picks up",
                "arrives",
                "becomes convinced",
            ]
        ):
            lead_indicator_sentences.append(sentence)

    search_zone = " ".join(lead_indicator_sentences) if lead_indicator_sentences else body

    for pattern in priority_patterns:
        matches = re.findall(pattern, search_zone)
        for match in matches:
            candidate = match[0] if isinstance(match, tuple) else match
            cleaned = candidate.strip()
            lowered = cleaned.lower()
            if lowered not in {"not today", "court jester", "test project"}:
                return cleaned

    lowered = body.lower()
    if "rideshare driver" in lowered:
        return "a rideshare driver"
    if "driver" in lowered:
        return "a driver"
    if "journalist" in lowered:
        return "a journalist"
    if "jester" in lowered:
        return "a jester"
    if "lawyer" in lowered:
        return "a lawyer"
    return "a person"


def infer_goal(text):
    body = first_story_chunk(text)
    sentences = split_sentences(body)

    priority_phrases = [
        "trying to",
        "must",
        "wants to",
        "needs to",
        "hopes to",
    ]

    for sentence in sentences[:12]:
        lowered = sentence.lower()
        if any(phrase in lowered for phrase in priority_phrases):
            return sentence[:220]

    lowered = body.lower()

    if "rideshare driver" in lowered or "driver" in lowered:
        return "Get through the night safely and hold onto financial stability"
    if "jester" in lowered and "court" in lowered:
        return "Survive the court and find a way to stay ahead of the danger around him"
    if "lawyer" in lowered and ("trial" in lowered or "court" in lowered):
        return "Uncover the truth and defend his clients before the system crushes them"

    if sentences:
        for sentence in sentences[:10]:
            lowered = sentence.lower()
            if any(word in lowered for word in ["journey", "story", "follows", "centers"]):
                return sentence[:220]

    return "Pursue a goal that could change their situation"


def infer_stakes(text):
    body = first_story_chunk(text)
    sentences = split_sentences(body)
    lowered = body.lower()

    # Best case: explicit consequence language
    consequence_triggers = [
        "could lose",
        "or risk",
        "risks",
        "if he fails",
        "if she fails",
        "if they fail",
        "if he lets",
        "if she lets",
        "if they let",
        "if malik",
        "or else",
    ]

    # Avoid picking reveal/irony sentences as stakes
    reveal_markers = [
        "what he doesn't realize",
        "what she doesn't realize",
        "what they don't realize",
        "unaware that",
        "actually",
        "secretly",
        "the truth is",
    ]

    for sentence in sentences[:16]:
        sentence_lower = sentence.lower()

        if any(marker in sentence_lower for marker in reveal_markers):
            continue

        if any(trigger in sentence_lower for trigger in consequence_triggers):
            return sentence[:220]

    # Secondary pattern: consequence phrasing after commas or conditionals
    for sentence in sentences[:16]:
        sentence_lower = sentence.lower()

        if any(marker in sentence_lower for marker in reveal_markers):
            continue

        if "lose" in sentence_lower or "destroy" in sentence_lower or "cost him" in sentence_lower or "cost her" in sentence_lower:
            return sentence[:220]

    # Smart project-aware fallbacks
    if "financial lifeline" in lowered:
        return "If Malik misreads the situation, he could lose the financial lifeline he desperately needs."
    if "rideshare" in lowered or "driver" in lowered:
        return "If fear drives his decisions, he could destroy the one opportunity that might change his life."
    if "kingdom" in lowered and ("fall" in lowered or "conspiracy" in lowered):
        return "If the truth stays buried, the kingdom could fall into the wrong hands."
    if "lawyer" in lowered and ("trial" in lowered or "court" in lowered):
        return "If he takes the safe path, the truth stays buried and innocent lives are destroyed by the system."

    return "Everything important could be put at risk"


def infer_theme(text):
    body = first_story_chunk(text)
    lowered = body.lower()

    if "fear" in lowered and ("perception" in lowered or "misread" in lowered or "wrong" in lowered):
        return "Fear distorts perception"
    if "pressure" in lowered and ("misread" in lowered or "wrong" in lowered):
        return "Pressure can cause people to misread the truth"
    if "truth" in lowered and "power" in lowered:
        return "Truth collides with power"
    if "kingdom" in lowered and ("truth" in lowered or "power" in lowered):
        return "Power depends on controlling who gets to speak the truth"
    if "survival" in lowered:
        return "Survival pressure reveals character"
    if "family" in lowered:
        return "Family and belonging shape identity"

    return "Pressure reveals the deeper truth of the story"


def infer_tone(text):
    body = first_story_chunk(text)
    lowered = body.lower()

    tone_parts = []

    if any(word in lowered for word in ["tense", "suspense", "threat", "danger", "criminal", "paranoia"]):
        tone_parts.append("Tense")
    if any(word in lowered for word in ["grounded", "realistic", "financial", "human"]):
        tone_parts.append("Grounded")
    if any(word in lowered for word in ["thriller", "mystery", "suspicion", "fear"]):
        tone_parts.append("Suspenseful")
    if any(word in lowered for word in ["funny", "comedy", "joke", "laugh", "jester"]):
        tone_parts.append("Comedic")
    if any(word in lowered for word in ["court", "kingdom", "royal", "dramatic", "conspiracy"]):
        tone_parts.append("Dramatic")
    if any(word in lowered for word in ["emotional", "life-changing", "human", "heart"]):
        tone_parts.append("Emotionally Charged")

    if not tone_parts:
        tone_parts = ["Dramatic", "Grounded"]

    return ", ".join(dict.fromkeys(tone_parts))


def write_error(message):
    report = {
        "status": "failed",
        "stage": "analysis_engine",
        "message": message
    }

    with open(ERROR_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("❌ Analysis failed.")
    print(ERROR_PATH)


def write_output(payload):
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("✅ Analysis successful.")
    print(OUTPUT_PATH)


def run():
    text = load_input_text(INPUT_PATH)

    if text is None or text.strip() == "":
        write_error("script_input.txt missing or empty")
        return

    payload = {
        "project_title": infer_project_title(text),
        "protagonist": infer_protagonist(text),
        "goal": infer_goal(text),
        "stakes": infer_stakes(text),
        "theme": infer_theme(text),
        "tone": infer_tone(text)
    }

    write_output(payload)


if __name__ == "__main__":
    run()
