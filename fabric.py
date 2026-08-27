#!/usr/bin/env python3
"""fabric.py — hub CLI for the hub↔compute unified data pipeline.

Typed job queue + rsync data sync, all compute-initiated where possible
(hub hosts the queue API; compute workers claim jobs; server never SSHes).

Usage:
  fabric.py enqueue "cmd" [--type bash|python] [--cwd DIR] [--timeout N] [--priority N] [--note T]
  fabric.py list [--all|--pending|--done|--error] [--tail N]
  fabric.py results [--tail N]
  fabric.py sync [--push DIR...] [--pull DIR...]   # rsync data dirs hub<->compute
  fabric.py worker-test                               # claim+run one job locally (hub as worker)

Env: FABRIC_URL (default http://127.0.0.1:8888), FABRIC_TOKEN_FILE
     (default <workspace>/dashboard/unit-token), COMPUTE_HOST (default compute.local)

Data sync config: FABRIC_SYNC_DIRS (default "data benchmarks rsi/data") —
space-separated dir names relative to the workspace, synced to
~/fabric/<name> on compute (push) and back (pull).
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

WORKSPACE = Path(os.environ.get("WORKSPACE", os.path.expanduser("~/.openclaw/workspace")))
URL = os.environ.get("FABRIC_URL", "http://127.0.0.1:8888").rstrip("/")
TOKEN_FILE = Path(os.environ.get("FABRIC_TOKEN_FILE", WORKSPACE / "dashboard" / "unit-token"))
COMPUTE = os.environ.get("COMPUTE_HOST", "compute.local")
SYNC_DIRS = os.environ.get("FABRIC_SYNC_DIRS", "data benchmarks rsi/data").split()


def token() -> str:
    return TOKEN_FILE.read_text().strip()


def http(method, path, payload=None, timeout=30):
    body = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(URL + path, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def cmd_enqueue(args):
    job = http("POST", "/api/jobs/enqueue", {
        "token": token(), "type": args.type, "cmd": args.cmd,
        "cwd": args.cwd, "timeout": args.timeout, "priority": args.priority,
        "note": args.note,
    })["job"]
    print(f"enqueued {job['id']} [{job['type']}] prio={job['priority']} "
          f"timeout={job['timeout']}s: {job['cmd'][:60]}")


def cmd_list(args):
    jobs = http("GET", "/api/jobs")
    flt = args.filter
    if flt == "pending":
        jobs = [j for j in jobs if j.get("status") == "pending"]
    elif flt == "done":
        jobs = [j for j in jobs if j.get("status") == "done"]
    elif flt == "error":
        jobs = [j for j in jobs if j.get("status") == "error"]
    jobs = jobs[-args.tail:]
    if not jobs:
        print("no jobs")
        return
    for j in jobs:
        st = j.get("status", "?")
        print(f"{j['id']:<22} {st:<8} [{j.get('type','?')}] "
              f"exit={str(j.get('exit','')):<4} {j.get('cmd','')[:50]}")
        if args.verbose and j.get("stderr"):
            print(f"    stderr: {j['stderr'][:200]}")


def cmd_results(args):
    jobs = [j for j in http("GET", "/api/jobs") if j.get("status") in ("done", "error")]
    jobs = jobs[-args.tail:]
    for j in jobs:
        print(f"=== {j['id']} [{j.get('type')}] exit={j.get('exit')} "
              f"({j.get('finished_at','')})")
        print(f"cmd: {j.get('cmd','')}")
        if j.get("stdout"):
            print(f"stdout: {j['stdout'][:600]}")
        if j.get("stderr"):
            print(f"stderr: {j['stderr'][:300]}")
        print()


def _rsync(direction, name):
    src_dir = WORKSPACE / name
    if not src_dir.exists() and direction == "push":
        print(f"skip {name}: no {src_dir}")
        return 0
    if direction == "push":
        remote = f"{COMPUTE}:~/fabric/{name}/"
        local = f"{src_dir}/"
        subprocess.run(["ssh", COMPUTE, f"mkdir -p ~/fabric/{name}"],
                       timeout=30, capture_output=True)
        cmd = ["rsync", "-az", "--delete", local, remote]
    else:
        remote = f"{COMPUTE}:~/fabric/{name}/"
        local = f"{src_dir}/"
        src_dir.mkdir(parents=True, exist_ok=True)
        cmd = ["rsync", "-az", remote, local]
    print(f"  {'push' if direction=='push' else 'pull'} {name} ...")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        print(f"  rsync {name} FAILED: {p.stderr[-200:]}")
        return 1
    print(f"  {name}: ok")
    return 0


def cmd_sync(args):
    rc = 0
    for d in args.push or []:
        rc |= _rsync("push", d)
    for d in args.pull or []:
        rc |= _rsync("pull", d)
    sys.exit(rc)


def cmd_worker_test(args):
    import importlib.util
    spec = importlib.util.spec_from_file_location("fw", WORKSPACE / "scripts" / "fabric-worker.py")
    fw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fw)
    fw.once()


def main():
    ap = argparse.ArgumentParser(description="fabric — hub↔compute data pipeline CLI")
    sub = ap.add_subparsers(dest="action", required=True)

    p = sub.add_parser("enqueue", help="queue a typed job for compute")
    p.add_argument("cmd")
    p.add_argument("--type", choices=["bash", "python"], default="bash")
    p.add_argument("--cwd", default="~")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--priority", type=int, default=5)
    p.add_argument("--note", default=None)
    p.set_defaults(fn=cmd_enqueue)

    p = sub.add_parser("list", help="list jobs")
    p.add_argument("--filter", choices=["pending", "done", "error", "all"], default="all")
    p.add_argument("--tail", type=int, default=20)
    p.add_argument("--verbose", "-v", action="store_true")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("results", help="show job outputs")
    p.add_argument("--tail", type=int, default=5)
    p.set_defaults(fn=cmd_results)

    p = sub.add_parser("sync", help="rsync data dirs hub<->compute")
    p.add_argument("--push", nargs="*", default=[])
    p.add_argument("--pull", nargs="*", default=[])
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("worker-test", help="claim+run one job as hub worker")
    p.set_defaults(fn=cmd_worker_test)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
