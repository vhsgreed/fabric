# fabric

Typed job queue + data-sync pipeline for a hub↔compute two-machine fleet.

One always-on machine (the **hub**) hosts the job queue over HTTP. Worker
machines (e.g. a GPU box that sleeps when idle) **claim** jobs by polling the
hub — no SSH in the loop, no inbound connections to workers, works through
Wake-on-LAN outages because workers only need outbound HTTP when they're up.

- `fabric.py` — hub-side CLI: enqueue jobs, list/results, rsync data sync
- `fabric-worker.py` — worker daemon: poll → claim → run → report

Job types: `bash` (shell one-liner/script) and `python` (`python3 -u -c`).
Every job carries explicit cwd, timeout and priority. Output (stdout/stderr,
64 KB caps enforced by the server) is posted back and stored with the job.

## Server-side API (endpoints)

The queue API is ~80 lines you embed in any HTTP server (the reference
implementation lives in our dashboard; see `server.py` routes):

```
POST /api/jobs/enqueue   {token, type, cmd, cwd, timeout, priority, note}
POST /api/jobs/claim     {token, worker}   → next pending job (marks claimed)
POST /api/jobs/result    {token, id, exit, stdout, stderr}
GET  /api/jobs                             → all jobs (for list/results)
```

Auth: shared unit token in the JSON body. Jobs persist to a JSONL file
(crash-safe append) behind a `threading.Lock`.

## Hub CLI

```bash
export FABRIC_URL=http://127.0.0.1:8888
export FABRIC_TOKEN_FILE=~/.openclaw/workspace/dashboard/unit-token

fabric.py enqueue "python3 -c 'import platform; print(platform.node())'" \
        --type bash --cwd "~" --timeout 60 --note "hello"
fabric.py list --tail 10
fabric.py results --tail 3
fabric.py sync --push data benchmarks   # rsync dirs hub → compute
fabric.py sync --pull rsi/data          # rsync results back
```

Env: `FABRIC_URL`, `FABRIC_TOKEN_FILE`, `COMPUTE_HOST` (rsync target),
`FABRIC_SYNC_DIRS` (default sync set).

## Worker daemon

```bash
export FABRIC_URL=http://hub.local:8888
export FABRIC_TOKEN_FILE=~/.config/fabric-token
python3 fabric-worker.py            # poll every 30s
python3 fabric-worker.py --once     # single claim+run cycle
```

Env: `FABRIC_URL`, `FABRIC_TOKEN_FILE`, `FABRIC_WORKER` (name in claims),
`FABRIC_INTERVAL` (poll seconds).

Run it under a user systemd service with `Restart=on-failure`.

## Design notes

- **Push model:** workers initiate everything. The hub never SSHes out. If a
  worker is asleep (WOL / idle-shutdown), jobs simply wait as `pending`.
- **Typed jobs, explicit everything:** no shell-guessing — type, cwd, timeout
  and priority travel with the job; output is capped (64 KB) server-side.
- **Crash-safe queue:** JSONL append + fsync-style discipline; the server
  rewrites the file on each mutation while holding the lock.
- **Data sync is separate from compute:** rsync `--push`/`--pull` moves whole
  directories so jobs can be pure compute and I/O stays out of the queue.

## Status

Alpha. battle-tested on a 2-machine fleet (hub: laptop; compute: 16-core GPU
box with idle-shutdown) — live-tested enqueue → claim → run → result with
both bash and python jobs, plus bidirectional rsync. API surface may still
change; pin before relying on it.

MIT license. Part of the [vhsgreed](https://github.com/vhsgreed) tooling.
