"""Run a verification command with a durable, timestamped invocation log."""
import datetime
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise SystemExit("Usage: python tools/run_logged.py -- COMMAND [ARG ...]")
    (ROOT / "artifacts").mkdir(exist_ok=True)
    with (ROOT / "artifacts/sol-run.log").open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] {shlex.join(command)}\n")
        log.flush()
        process = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        for line in process.stdout:
            log.write(line)
            print(line, end="", flush=True)
        code = process.wait()
        log.write(f"[exit={code}]\n")
        return code


if __name__ == "__main__":
    raise SystemExit(main())
