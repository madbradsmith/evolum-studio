#!BETA version v1.5 - BUILD 1.2
import os
import sys
import json
import subprocess
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
_DAI_UID = os.environ.get("DAI_USER_ID", "")
_DAI_WORK_DIR = os.environ.get("DAI_WORK_DIR", "")
STATUS_FILE = APP_DIR / (f"pipeline_status_{_DAI_UID}.json" if _DAI_UID else "status.json")


def _work_path(filename: str) -> str:
    """Return the DAI_WORK_DIR path for a file when it exists there, else APP_DIR path."""
    if _DAI_WORK_DIR:
        p = Path(_DAI_WORK_DIR) / filename
        if p.exists():
            return str(p)
    return str(APP_DIR / filename)


def write_status(step, progress, message, start_time, state="running"):
    elapsed = int(time.time() - start_time)
    payload = {
        "state": state,
        "step": step,
        "progress": progress,
        "message": message,
        "elapsed_seconds": elapsed
    }
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run(cmd, step_key, progress, message, start_time):
    write_status(step_key, progress, message, start_time, state="running")
    print("\n" + "=" * 40)
    print(cmd)
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        write_status(step_key, progress, f"Failed during: {message}", start_time, state="error")
        print("❌ Step failed")
        sys.exit(1)


def find_latest_pptx():
    files = []

    output_dir = APP_DIR / "output"
    if output_dir.exists():
        files += list(output_dir.glob("pitch_deck_v*.pptx"))

    exports_dir = APP_DIR / "exports"
    if exports_dir.exists():
        files += list(exports_dir.glob("pitch_deck_v*.pptx"))

    files += list(APP_DIR.glob("pitch_deck_v*.pptx"))

    files = [f for f in files if f.is_file()]
    if not files:
        return None

    return max(files, key=lambda f: f.stat().st_mtime)


def main(input_file):
    start_time = time.time()

    write_status("start", 1, "Starting pipeline...", start_time, state="running")
    print("🚀 Starting full pipeline")
    print(f"📄 Script input: {input_file}")
    print(f"📁 Working directory: {APP_DIR}")

    run(
        f'python3 "{APP_DIR}/input_handler_v1.py" "{input_file}"',
        "input_handler",
        15,
        "Parsing screenplay...",
        start_time
    )

    _cache_hit_file = Path(_DAI_WORK_DIR) / "brain_cache_hit.txt" if _DAI_WORK_DIR else None
    _brain_cache_dir = os.environ.get("DAI_BRAIN_CACHE_DIR", "")
    _script_hash = os.environ.get("DAI_SCRIPT_HASH", "")

    if _cache_hit_file and _cache_hit_file.exists():
        write_status("brain", 35, "Story analysis loaded from cache...", start_time, state="running")
        print("🧠 Brain cache HIT — skipping Claude call")
    else:
        run(
            f'python3 "{APP_DIR}/single_brain_orchestrator_v3.py" "{_work_path("input.txt")}"',
            "brain",
            35,
            "Generating story analysis...",
            start_time
        )
        # Save brain output to cache for future runs of this script
        if _brain_cache_dir and _script_hash:
            try:
                _brain_out = Path(_work_path("approved_brain_output.json"))
                if _brain_out.exists():
                    import shutil as _sc
                    _sc.copy2(_brain_out, Path(_brain_cache_dir) / f"{_script_hash}.json")
                    print(f"🧠 Brain output cached for hash {_script_hash[:12]}")
            except Exception as e:
                print(f"⚠️ Brain cache save failed: {e}")

    _ctx_uid = os.environ.get("DAI_USER_ID", "")
    _work_ctx = Path(_DAI_WORK_DIR) / "user_upload_context.json" if _DAI_WORK_DIR else None
    if _work_ctx and _work_ctx.exists():
        upload_context_path = _work_ctx
    else:
        _ctx_name = f"user_upload_context_{_ctx_uid}.json" if _ctx_uid else "user_upload_context.json"
        upload_context_path = APP_DIR / _ctx_name
        if not upload_context_path.exists():
            upload_context_path = APP_DIR / "user_upload_context.json"
    approved_path = Path(_work_path("approved_brain_output.json"))

    if upload_context_path.exists() and approved_path.exists():
        try:
            with open(upload_context_path, "r", encoding="utf-8") as f:
                user_context = json.load(f)

            with open(approved_path, "r", encoding="utf-8") as f:
                approved = json.load(f)

            user_logline = (user_context.get("logline") or "").strip()
            user_synopsis = (user_context.get("synopsis") or "").strip()

            if user_logline:
                approved["logline"] = user_logline

            if user_synopsis:
                approved["synopsis"] = user_synopsis

            with open(approved_path, "w", encoding="utf-8") as f:
                json.dump(approved, f, indent=2)
        except Exception as e:
            print(f"⚠️ Could not merge user upload context: {e}")

    run(
        f'python3 "{APP_DIR}/layout_engine.py" "{_work_path("approved_brain_output.json")}"',
        "layout",
        55,
        "Building slide plan...",
        start_time
    )

    _uid = os.environ.get("DAI_USER_ID", "")
    _uid_flag = f" --uid {_uid}" if _uid else ""
    if _uid:
        os.environ["EVOLUM_SESSION_ID"] = _uid

    run(
        f'python3 "{APP_DIR}/deck_builder.py" "{_work_path("slide_plan.json")}"{_uid_flag}',
        "deck_builder_full",
        72,
        "Building full pitch deck...",
        start_time
    )

    find_latest_pptx()

    write_status("complete", 100, "Complete", start_time, state="complete")
    print("\n🎉 Pipeline complete — pitch deck built")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ No input file provided")
        sys.exit(1)

    main(sys.argv[1])
