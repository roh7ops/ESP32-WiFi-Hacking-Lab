#!/usr/bin/env python3
"""Upload src/ vers l'ESP32 via mpremote."""

import subprocess
import sys
from pathlib import Path

ROOT      = Path(__file__).parent.parent
MPREMOTE  = ROOT / ".venv" / "bin" / "mpremote"
PORT      = "/dev/ttyUSB0"
SRC       = ROOT / "src"

# Mapping src/ → ESP32 filesystem
# src/main.py      → :main.py
# src/config.py    → :config.py
# src/lib/foo.py   → :lib/foo.py
DIRS_TO_CREATE = [":lib"]


def mp(*args):
    cmd = [str(MPREMOTE), "connect", PORT] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def ensure_dirs():
    for d in DIRS_TO_CREATE:
        r = mp("exec", f"import os\ntry:\n os.mkdir('{d[1:]}')\nexcept OSError:\n pass")
        if r.returncode != 0:
            print(f"  [!] Impossible de créer {d} : {r.stderr.strip()}")


def upload(local: Path, remote: str) -> bool:
    r = mp("cp", str(local), f":{remote}")
    if r.returncode == 0:
        print(f"  [+] {remote}")
        return True
    print(f"  [x] {remote} — {r.stderr.strip()}")
    return False


def main() -> int:
    print("=" * 42)
    print("  Deploy → ESP32")
    print(f"  Port   : {PORT}")
    print(f"  Source : {SRC.name}/")
    print("=" * 42)

    if not MPREMOTE.exists():
        print(f"[x] mpremote introuvable : {MPREMOTE}")
        return 1

    ensure_dirs()

    success = errors = 0
    for f in sorted(SRC.rglob("*.py")):
        remote = str(f.relative_to(SRC))
        if upload(f, remote):
            success += 1
        else:
            errors += 1

    print("─" * 42)
    print(f"  {success} fichier(s) OK  |  {errors} erreur(s)")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
