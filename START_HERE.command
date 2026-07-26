#!/usr/bin/env bash
# Evolum Studio — one-command start.
# Mac: double-click this file. Linux: ./START_HERE.command
# Windows: use START_HERE.bat instead.

cd "$(dirname "$0")" || exit 1

say()  { printf '  %s\n' "$1"; }
fail() { printf '\n  %s\n\n' "$1"; read -r -p "  Press Enter to close." _ 2>/dev/null; exit 1; }

printf '\n  Evolum Studio — starting up\n  ---------------------------\n\n'

# ── 1. Python ───────────────────────────────────────────────────────────
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -z "$PY" ] && fail "Python 3.9 or newer is required.
  Get it from https://www.python.org/downloads/ then run this again."
say "[1/4] Python found: $($PY --version 2>&1)"

# ── 2. Environment ──────────────────────────────────────────────────────
# Preferred: a private venv. If the system is missing python3-venv (common on
# Debian/Ubuntu), fall back to a user-level install instead of dying.
RUNPY=""
if [ -x venv/bin/python ]; then
  RUNPY="venv/bin/python"
  say "[2/4] Environment already set up."
elif "$PY" -m venv venv >/dev/null 2>&1 && [ -x venv/bin/python ]; then
  RUNPY="venv/bin/python"
  say "[2/4] Created a private Python environment."
else
  rm -rf venv
  RUNPY="$PY"
  say "[2/4] No venv support on this system — installing to your user account"
  say "      instead. (To use a clean environment later:"
  say "       sudo apt install python3-venv  — then delete this folder and rerun.)"
fi

# ── 3. Dependencies ─────────────────────────────────────────────────────
say "[3/4] Installing dependencies — first run takes a minute..."
if [ "$RUNPY" = "$PY" ]; then
  PIP_FLAGS="--user"
else
  PIP_FLAGS=""
fi
if ! "$RUNPY" -m pip install --quiet --disable-pip-version-check $PIP_FLAGS -r requirements.txt 2>/tmp/evolum_pip_err.$$; then
  printf '\n'
  say "Dependency install failed. The error was:"
  printf '\n'
  sed 's/^/      /' /tmp/evolum_pip_err.$$ | tail -12
  rm -f /tmp/evolum_pip_err.$$
  fail "Nothing was broken — this just didn't finish.
  Most common cause is no internet connection."
fi
rm -f /tmp/evolum_pip_err.$$

# ── 4. Config ───────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  "$RUNPY" - <<'PY'
import secrets, pathlib
p = pathlib.Path('.env')
p.write_text(p.read_text().replace(
    'SECRET_KEY=replace-with-a-long-random-string',
    'SECRET_KEY=' + secrets.token_urlsafe(48)))
PY
  say "[4/4] Created .env with a fresh random SECRET_KEY."
else
  say "[4/4] Using your existing .env"
fi

printf '\n  Ready. Opening http://localhost:7000\n  Press Ctrl+C in this window to stop.\n\n'

( sleep 2
  command -v open     >/dev/null 2>&1 && open     http://localhost:7000 && exit
  command -v xdg-open >/dev/null 2>&1 && xdg-open http://localhost:7000
) >/dev/null 2>&1 &

exec "$RUNPY" app.py
