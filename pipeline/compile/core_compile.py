import json
import os

# File paths
BASE_DIR = os.path.expanduser("~/app/pipeline")

ANALYSIS_PATH = os.path.join(BASE_DIR, "analysis", "analysis_output.json")
PACKAGING_PATH = os.path.join(BASE_DIR, "packaging", "packaging_output.json")

OUTPUT_PATH = os.path.join(BASE_DIR, "compile", "core_compiled_payload.json")
ERROR_PATH = os.path.join(BASE_DIR, "compile", "core_compile_error_report.json")

# Required fields
REQUIRED_ANALYSIS_FIELDS = [
    "project_title",
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

def validate(analysis, packaging):
    missing = []
    invalid = []

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

    # Development notes deeper check
    dev_notes = packaging.get("development_notes", {})
    for sub in ["whats_working", "what_could_be_stronger"]:
        val = dev_notes.get(sub)
        if val is None:
            missing.append(f"packaging.development_notes.{sub}")
        elif is_invalid(val):
            invalid.append({
                "field": f"packaging.development_notes.{sub}",
                "reason": "invalid_value"
            })

    return missing, invalid

def write_error(missing, invalid):
    report = {
        "status": "failed",
        "stage": "core_compile",
        "missing_fields": missing,
        "invalid_fields": invalid,
        "message": "Core compile halted due to missing or invalid fields."
    }

    with open(ERROR_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print("❌ Compile failed. Error report written.")
    print(ERROR_PATH)

def write_output(analysis, packaging):
    payload = {
        "project_title": analysis.get("project_title"),
        "analysis": analysis,
        "packaging": packaging
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    print("✅ Compile successful.")
    print(OUTPUT_PATH)

def run():
    analysis = load_json(ANALYSIS_PATH)
    packaging = load_json(PACKAGING_PATH)

    if analysis is None or packaging is None:
        write_error(
            ["analysis_output.json or packaging_output.json missing"],
            []
        )
        return

    missing, invalid = validate(analysis, packaging)

    if missing or invalid:
        write_error(missing, invalid)
        return

    write_output(analysis, packaging)

if __name__ == "__main__":
    run()
