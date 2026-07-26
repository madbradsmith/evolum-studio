import json
import os

# Base paths
BASE_DIR = os.path.expanduser("~/app/pipeline")

COMPILED_INPUT_PATH = os.path.join(BASE_DIR, "compile", "core_compiled_payload.json")
DISPATCH_OUTPUT_PATH = os.path.join(BASE_DIR, "dispatch", "post_compile_dispatch_payload.json")
ERROR_PATH = os.path.join(BASE_DIR, "dispatch", "post_compile_dispatch_error_report.json")

# Required compiled fields before dispatch
REQUIRED_TOP_LEVEL = [
    "project_title",
    "analysis",
    "packaging"
]

REQUIRED_ANALYSIS_FIELDS = [
    "protagonist",
    "goal",
    "stakes",
    "theme",
    "tone"
]

REQUIRED_PACKAGING_FIELDS = [
    "logline",
    "synopsis",
    "why_this_movie",
    "development_notes"
]

PLACEHOLDER_VALUES = ["TBD", "N/A", "Unknown", "None", ""]


def is_invalid(value):
    if value is None:
        return True
    if isinstance(value, str):
        if value.strip() == "":
            return True
        if value.strip() in PLACEHOLDER_VALUES:
            return True
    return False


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def validate_payload(payload):
    missing = []
    invalid = []

    # Top-level checks
    for field in REQUIRED_TOP_LEVEL:
        value = payload.get(field)
        if value is None:
            missing.append(field)
        elif is_invalid(value):
            invalid.append({"field": field, "reason": "invalid_value"})

    analysis = payload.get("analysis", {})
    packaging = payload.get("packaging", {})

    # Analysis checks
    for field in REQUIRED_ANALYSIS_FIELDS:
        value = analysis.get(field)
        if value is None:
            missing.append(f"analysis.{field}")
        elif is_invalid(value):
            invalid.append({"field": f"analysis.{field}", "reason": "invalid_value"})

    # Packaging checks
    for field in REQUIRED_PACKAGING_FIELDS:
        value = packaging.get(field)
        if value is None:
            missing.append(f"packaging.{field}")
        elif is_invalid(value):
            invalid.append({"field": f"packaging.{field}", "reason": "invalid_value"})

    # Development notes checks
    dev_notes = packaging.get("development_notes", {})
    for subfield in ["whats_working", "what_could_be_stronger"]:
        value = dev_notes.get(subfield)
        if value is None:
            missing.append(f"packaging.development_notes.{subfield}")
        elif is_invalid(value):
            invalid.append({
                "field": f"packaging.development_notes.{subfield}",
                "reason": "invalid_value"
            })

    return missing, invalid


def build_dispatch_payload(payload):
    analysis = payload["analysis"]
    packaging = payload["packaging"]

    dispatch_payload = {
        "project_title": payload["project_title"],

        "shared_context": {
            "protagonist": analysis.get("protagonist"),
            "goal": analysis.get("goal"),
            "stakes": analysis.get("stakes"),
            "theme": analysis.get("theme"),
            "tone": analysis.get("tone")
        },

        "image_generation_module": {
            "enabled": True,
            "project_title": payload["project_title"],
            "character_focus": analysis.get("protagonist"),
            "tone": analysis.get("tone"),
            "theme": analysis.get("theme"),
            "logline": packaging.get("logline"),
            "synopsis": packaging.get("synopsis")
        },

        "other_modules": {
            "enabled": True,
            "project_title": payload["project_title"],
            "why_this_movie": packaging.get("why_this_movie"),
            "development_notes": packaging.get("development_notes")
        },

        "deck_builder_preview": {
            "enabled": True,
            "project_title": payload["project_title"],
            "logline": packaging.get("logline"),
            "synopsis": packaging.get("synopsis"),
            "why_this_movie": packaging.get("why_this_movie"),
            "development_notes": packaging.get("development_notes"),
            "analysis": analysis
        }
    }

    return dispatch_payload


def write_error(missing, invalid):
    report = {
        "status": "failed",
        "stage": "post_compile_dispatch",
        "missing_fields": missing,
        "invalid_fields": invalid,
        "message": "Post-compile dispatch halted due to missing or invalid compiled payload fields."
    }

    with open(ERROR_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print("❌ Dispatch failed. Error report written.")
    print(ERROR_PATH)


def write_output(dispatch_payload):
    with open(DISPATCH_OUTPUT_PATH, "w") as f:
        json.dump(dispatch_payload, f, indent=2)

    print("✅ Dispatch successful.")
    print(DISPATCH_OUTPUT_PATH)


def run():
    payload = load_json(COMPILED_INPUT_PATH)

    if payload is None:
        write_error(
            ["core_compiled_payload.json missing"],
            []
        )
        return

    missing, invalid = validate_payload(payload)

    if missing or invalid:
        write_error(missing, invalid)
        return

    dispatch_payload = build_dispatch_payload(payload)
    write_output(dispatch_payload)


if __name__ == "__main__":
    run()
