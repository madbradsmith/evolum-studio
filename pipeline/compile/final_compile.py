import json
import os

# Base paths
BASE_DIR = os.path.expanduser("~/app/pipeline")

DISPATCH_INPUT_PATH = os.path.join(BASE_DIR, "dispatch", "post_compile_dispatch_payload.json")
OUTPUT_PATH = os.path.join(BASE_DIR, "compile", "final_compiled_payload.json")
ERROR_PATH = os.path.join(BASE_DIR, "compile", "final_compile_error_report.json")

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


def validate_dispatch_payload(payload):
    missing = []
    invalid = []

    # Top-level required sections
    for field in ["project_title", "shared_context", "image_generation_module", "other_modules", "deck_builder_preview"]:
        value = payload.get(field)
        if value is None:
            missing.append(field)
        elif is_invalid(value):
            invalid.append({"field": field, "reason": "invalid_value"})

    shared = payload.get("shared_context", {})
    for field in ["protagonist", "goal", "stakes", "theme", "tone"]:
        value = shared.get(field)
        if value is None:
            missing.append(f"shared_context.{field}")
        elif is_invalid(value):
            invalid.append({"field": f"shared_context.{field}", "reason": "invalid_value"})

    deck = payload.get("deck_builder_preview", {})
    for field in ["project_title", "logline", "synopsis", "why_this_movie", "development_notes", "analysis"]:
        value = deck.get(field)
        if value is None:
            missing.append(f"deck_builder_preview.{field}")
        elif is_invalid(value):
            invalid.append({"field": f"deck_builder_preview.{field}", "reason": "invalid_value"})

    dev_notes = deck.get("development_notes", {})
    for subfield in ["whats_working", "what_could_be_stronger"]:
        value = dev_notes.get(subfield)
        if value is None:
            missing.append(f"deck_builder_preview.development_notes.{subfield}")
        elif is_invalid(value):
            invalid.append({
                "field": f"deck_builder_preview.development_notes.{subfield}",
                "reason": "invalid_value"
            })

    analysis = deck.get("analysis", {})
    for field in ["protagonist", "goal", "stakes", "theme", "tone"]:
        value = analysis.get(field)
        if value is None:
            missing.append(f"deck_builder_preview.analysis.{field}")
        elif is_invalid(value):
            invalid.append({
                "field": f"deck_builder_preview.analysis.{field}",
                "reason": "invalid_value"
            })

    return missing, invalid


def build_final_payload(payload):
    shared = payload["shared_context"]
    deck = payload["deck_builder_preview"]
    image_module = payload["image_generation_module"]
    other_modules = payload["other_modules"]

    final_payload = {
        "project_title": payload["project_title"],

        "deck_builder_input": {
            "project_title": deck["project_title"],
            "logline": deck["logline"],
            "synopsis": deck["synopsis"],
            "why_this_movie": deck["why_this_movie"],
            "development_notes": deck["development_notes"],

            "story_core": {
                "protagonist": shared["protagonist"],
                "goal": shared["goal"],
                "stakes": shared["stakes"],
                "theme": shared["theme"],
                "tone": shared["tone"]
            },

            "analysis": deck["analysis"]
        },

        "module_outputs": {
            "image_generation_module": image_module,
            "other_modules": other_modules
        },

        "ready_for_deck_builder": True
    }

    return final_payload


def write_error(missing, invalid):
    report = {
        "status": "failed",
        "stage": "final_compile",
        "missing_fields": missing,
        "invalid_fields": invalid,
        "message": "Final compile halted due to missing or invalid dispatch payload fields."
    }

    with open(ERROR_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print("❌ Final compile failed. Error report written.")
    print(ERROR_PATH)


def write_output(final_payload):
    with open(OUTPUT_PATH, "w") as f:
        json.dump(final_payload, f, indent=2)

    print("✅ Final compile successful.")
    print(OUTPUT_PATH)


def run():
    payload = load_json(DISPATCH_INPUT_PATH)

    if payload is None:
        write_error(
            ["post_compile_dispatch_payload.json missing"],
            []
        )
        return

    missing, invalid = validate_dispatch_payload(payload)

    if missing or invalid:
        write_error(missing, invalid)
        return

    final_payload = build_final_payload(payload)
    write_output(final_payload)


if __name__ == "__main__":
    run()
