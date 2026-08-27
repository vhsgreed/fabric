#!/usr/bin/env bash
# CI: syntax-check both scripts (stdlib-only, no deps to install)
set -euo pipefail
python3 -m py_compile fabric.py fabric-worker.py
python3 fabric.py --help >/dev/null
python3 fabric-worker.py --help >/dev/null 2>&1 || python3 -c "import ast; ast.parse(open('fabric-worker.py').read())"
echo "CI OK"
