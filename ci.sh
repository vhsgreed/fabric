#!/usr/bin/env bash
# CI: syntax-check both scripts + exercise the hub CLI parser.
# NOTE: fabric-worker.py has NO argparse — never run it without args in CI
# (it enters the polling loop). Syntax-check it instead.
set -euo pipefail
python3 -m py_compile fabric.py fabric-worker.py
python3 fabric.py --help >/dev/null
python3 fabric.py list --help >/dev/null
python3 -c "import ast; ast.parse(open('fabric-worker.py').read()); print('worker syntax OK')"
echo "CI OK"
