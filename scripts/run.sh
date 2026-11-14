#!/usr/bin/env bash
# Ejecuta Texas CAS Manager desde el repositorio (usa .venv si existe).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m texas_cas_manager "$@"
