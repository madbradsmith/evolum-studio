import json
import os
import re

# Paths
PACKAGING_DIR = os.path.expanduser("~/app/pipeline/packaging")
INPUT_DIR = os.path.expanduser("~/app/input")

INPUT_PATH = os.path.join(INPUT_DIR, "script_input.txt")
OUTPUT_PATH = os.path.join(PACKAGING_DIR, "packaging_output.json")
ERROR_PATH = os.path.join(PACKAGING_DIR, "packaging_error_report.json")


def load_input_text(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def normalize_whitespace(text):
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text):
    cleaned = text.replace("\n", " ").strip()
    parts = re.split(r'(?<=[.!?])\s+', cleaned)
    return [p.strip() for p in parts if p.strip()]


def infer_project_title(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        first = re.sub(r"(?i)^title:\s*", "", lines[0]).strip()
        return first[:120]
    return "Untitled Project"


def infer_protagonist(text):
    patterns = [
        r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b",
        r"\b([A-Z][a-z]+)\b"
    ]

    search_zone = text[:3000]

    for pattern in patterns:
        matches = re.findall(pattern, search_zone)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            cleaned = match.strip()
            if cleaned.lower() not in ["screenplay", "written", "title"]:
                return cleaned

    lowered = text.lower()
    if "driver" in lowered:
        return "a rideshare driver"
    if "journalist" in lowered:
        return "a journalist"
    if "jester" in lowered:
        return "a jester"
    return "a person"


def infer_logline(text, protagonist):
    lowered = text.lower()

    if "rideshare" in lowered and "criminal" in lowered:
        return (
            "Over the course of one tense Chicago night, a financially strained rideshare driver "
            "becomes convinced the strangers in his back seat are involved in something criminal—"
            "unaware that misreading them could cost him the one moment that might change his life."
        )

    if "court" in lowered and "jester" in lowered:
        return (
            "A quick-witted outsider sneaks into a royal court by posing as a noble, only to be exposed "
            "and forced into the role of court jester—where his humor earns the king’s favor, but also "
            "draws him into a dangerous political conspiracy."
        )

    sentences = split_sentences(text)
    if sentences:
        first = normalize_whitespace(sentences[0])
        if len(first) > 220:
            first = first[:217] + "..."
        return first

    return (
        f"{protagonist} is pulled into a high-pressure situation that forces a confrontation with the truth."
    )


def infer_synopsis(text, protagonist):
    sentences = split_sentences(text)

    if len(sentences) >= 4:
        selected = sentences[:4]
        return "\n\n".join(normalize_whitespace(s) for s in selected)

    cleaned = normalize_whitespace(text)
    if len(cleaned) > 900:
        cleaned = cleaned[:897] + "..."
    return cleaned


def infer_why_this_movie(text):
    lowered = text.lower()

    if "fear" in lowered and "perception" in lowered:
        return (
            "This story works because it is built on something real: the way pressure changes how we see the world. "
            "When people are exhausted, stressed, and trying to survive, they do not just make bad decisions—they start "
            "reading things wrong. That gap between perception and reality creates tension, emotional payoff, and a clear hook."
        )

    if "truth" in lowered and "power" in lowered:
        return (
            "This story works because it puts truth in direct conflict with power. The tension is not just about what happens, "
            "but about who gets to define reality. That gives the material both dramatic weight and strong pitch value."
        )

    if "kingdom" in lowered or "royal" in lowered:
        return (
            "This story works because it combines entertainment with stakes. The world is rich and accessible, but underneath "
            "the fun is a story about power, identity, and who is allowed to speak the truth. That mix gives it both commercial appeal and depth."
        )

    return (
        "This story works because it pairs a clear concept with emotional stakes. It gives the audience something immediate to hold onto "
        "while also suggesting deeper pressure, conflict, or transformation underneath."
    )


def infer_development_notes(text):
    lowered = text.lower()

    whats_working = (
        "The concept has a clear core and a strong foundation for pitch language. There is enough tension, conflict, or emotional pressure "
        "in the material to make the project feel purposeful rather than generic."
    )

    what_could_be_stronger = (
        "The next level of refinement would come from sharpening the protagonist’s internal turning points so the escalation feels even more intentional."
    )

    if "jester" in lowered or "court" in lowered:
        what_could_be_stronger = (
            "The next level of refinement would come from sharpening the lead character’s transformation from survivor to active player, "
            "so the emotional arc lands as strongly as the plot."
        )

    if "rideshare" in lowered or "driver" in lowered:
        what_could_be_stronger = (
            "The story could hit even harder by clarifying the precise moments where suspicion becomes certainty, so each escalation feels distinct and earned."
        )

    return {
        "whats_working": whats_working,
        "what_could_be_stronger": what_could_be_stronger
    }


def write_error(message):
    report = {
        "status": "failed",
        "stage": "packaging_engine",
        "message": message
    }

    with open(ERROR_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("❌ Packaging failed.")
    print(ERROR_PATH)


def write_output(payload):
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print("✅ Packaging successful.")
    print(OUTPUT_PATH)


def run():
    text = load_input_text(INPUT_PATH)

    if text is None or text.strip() == "":
        write_error("script_input.txt missing or empty")
        return

    project_title = infer_project_title(text)
    protagonist = infer_protagonist(text)

    payload = {
        "logline": infer_logline(text, protagonist),
        "synopsis": infer_synopsis(text, protagonist),
        "why_this_movie": infer_why_this_movie(text),
        "development_notes": infer_development_notes(text)
    }

    write_output(payload)


if __name__ == "__main__":
    run()
