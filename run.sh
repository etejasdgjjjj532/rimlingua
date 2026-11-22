#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
translator_python="${RW_TRANSLATOR_PYTHON:-.venv/bin/python}"
if [[ ! -x "$translator_python" ]]; then
    echo 'Create .venv and install .[dev], or set RW_TRANSLATOR_PYTHON to an absolute Python executable path.' >&2
    exit 1
fi
exec "$translator_python" -m rimworld_translator "$@"
