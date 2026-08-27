#!/usr/bin/env python3
"""fabric-worker.py — compute-side worker for the hub↔compute data pipeline.

Polling loop (compute-initiated — hub never SSHes out):
  1. GET  hub /api/jobs/claim   → next pending typed job (or None)
  2. run  the job locally (subprocess, typed: bash/python, explicit cwd,
         timeout, output captured)
  3. POST hub /api/jobs/result  → exit code + stdout/stderr

Job types:
  bash    — run cmd via shell
  python  — run cmd as python3 -u -c '<cmd>'

Env:
  FABRIC_URL         (default http://hub.local:8888)
  FABRIC_TOKEN_FILE  (default ~/.config/fabric-token)
  FABRIC_WORKER      (worker name; default hostname)
  FABRIC_INTERVAL    (poll seconds; default 30)
"""
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

URL = os.environ.get("FABRIC_URL", "http://hub.local:8888").rstrip("/")
TOKEN_FILE = Path(os.environ.get("FABRIC_TOKEN_FILE", "~/.config/fabric-token")).expanduser()
WORKER = os.environ.get("FABRIC_WORKER", os.uname().nodename)
INTERVAL = int(os.environ.get("FABRIC_INTERVAL", "30"))


def log(msg):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] fabric: {msg}", file=sys.stderr, flush=True)


def token() -> str:
    return TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""


def http(method, path, payload=None, timeout=30):
    body = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(URL + path, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def claim():
    return http("POST", "/api/jobs/claim", {"token": token(), "worker": WORKER}).get("job")


def post_result(job_id, exit_code, stdout, stderr):
    http("POST", "/api/jobs/result", {
        "token": token(), "id": job_id,
        "exit": exit_code, "stdout": stdout, "stderr": stderr,
    }, timeout=30)


def run_job(job):
    typ = job.get("type", "bash")
    cmd = job.get("cmd", "")
    cwd = os.path.expanduser(job.get("cwd") or "~")
    timeout = int(job.get("timeout", 300))
    log(f"job {job['id']} [{typ}] cwd={cwd} timeout={timeout}s: {cmd[:80]}")
    if typ == "python":
        argv = [sys.executable, "-u", "-c", cmd]
    else:
        argv = ["/bin/bash", "-c", cmd]
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        stdout, stderr, code = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, code = "", f"timeout after {timeout}s", 124
    except Exception as e:
        stdout, stderr, code = "", f"{type(e).__name__}: {e}", 1
    post_result(job["id"], code, stdout, stderr)
    log(f"job {job['id']} -> exit={code} stdout={len(stdout)}B stderr={len(stderr)}B")


def once():
    job = claim()
    if not job:
        log("no pending jobs")
        return False
    run_job(job)
    return True


def loop():
    log(f"fabric worker '{WORKER}' polling {URL} every {INTERVAL}s")
    while True:
        try:
            once()
        except Exception as e:
            log(f"poll error: {type(e).__name__}: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        sys.exit(0 if once() else 0)
    loop()
