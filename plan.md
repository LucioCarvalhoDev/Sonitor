# Sonitor v0.1 — Specs & Implementation Plan

## Context

Sonitor is a fresh project: only `app/collectors/net.py` has any code (and it has
bugs — `datetime.utc(...)`, `MetricResult.new(...)`, missing `return`).
The README sketched an ambitious CLI (print + routine lifecycle + scheduling +
sys/net/VoIP metrics) but contained ~10 internal contradictions around folder
layout, CLI shape, file format, and metric naming. This document locks the v0.1
design, identifies what needs to change, and stages the work. VoIP metrics and
auto-scheduling are deferred to v0.2.

## Decisions

| Topic              | Choice                                              |
| ------------------ | --------------------------------------------------- |
| CLI metric syntax  | Repeated `--metric` flag                            |
| Routine file       | TOML body, `.sonitor` extension                     |
| Scheduler          | `Scheduler` interface — cron impl + in-process impl |
| v0.1 scope         | `print` + routine lifecycle (no enable/disable yet) |
| VoIP / Asterisk    | Deferred to v0.2                                    |

### Defaults (not explicitly discussed)

- **Folder layout:** keep existing `app/collectors/`, `app/scheduler/` (drop the
  `schedullers` typo and `app/monitor/` from the original README).
- **Canonical metric names:** `sys-df`, `sys-top`, `sys-iostat`, `net-ping`,
  `net-tracert`. Drop the drift (`net-traceroute`, `io-df`, `asterisk-channels`).
- **Snapshot text format:** `--- {ts} - {human} - Iteration N ---` followed by
  `sonitor$ <cmd>\n<stdout>` blocks (matches original README log example).
- **Log rotation:** line-based, default 1000 lines, newest preserved.
- **Storage paths:** `storage/routines/<uuid>.sonitor`, `storage/logs/<uuid>.log`.
  No `local/` directory in v0.1 (status/locks land with `enable/disable` in v0.2).
- **Python deps:** stdlib only. If staying on 3.10 (current `.venv`), add `tomli`
  + `tomli-w`. If bumping to 3.11+, use stdlib `tomllib` (read) + a writer.

## v0.1 CLI surface

```
sonitor print   --metric <name> [args...] [--metric <name> [args...]]... [--output PATH]
sonitor routine create <period> [--alias NAME] [--log-size N] --metric ...
sonitor routine list
sonitor routine run    <uuid|alias>
sonitor routine reset  <uuid|alias>
```

Deferred to v0.2: `routine enable`, `routine disable`, VoIP metrics, lock files,
status ini.

## Routine file format (TOML, `.sonitor` extension)

```toml
[sonitor]
version       = "0.1"
spawn_command = "routine create 12h --metric sys-df --metric sys-uptime"
alias         = ""

[routine]
created_at  = 2026-05-18T00:00:00Z
last_run_at = 2026-05-18T00:00:00Z
state       = "idle"          # idle | running
period      = "12h"

[[routine.metrics]]
name = "sys-df"

[[routine.metrics]]
name = "net-ping"
args = ["8.8.8.8", "1.1.1.1"]

[log]
max_lines = 1000
```

## Module layout

```
sonitor.py                    # thin entrypoint -> app.cli.main()
app/
  __init__.py
  cli.py                      # argparse wiring; subcommand dispatch
  settings.py                 # paths + env loading
  collectors/
    __init__.py               # registry: name -> Metric class
    base.py                   # Metric, MetricResult, Snapshot
    net.py                    # PingMetric, TracertMetric
    sys.py                    # DfMetric, TopMetric, IostatMetric
  routines/
    __init__.py
    model.py                  # Routine dataclass + TOML load/dump
    store.py                  # list / read / write under storage/routines/
    runner.py                 # run a routine once; append + rotate log
  scheduler/
    __init__.py
    base.py                   # Scheduler protocol
    cron.py                   # CronScheduler (stub for v0.2)
    inproc.py                 # InProcessScheduler (stub for v0.2)
  enums/
    env_variables.py          # renamed from env-variables.py (hyphen breaks import)
```

## Critical files

- `sonitor.py` — entrypoint (currently empty).
- `app/cli.py` — **new**. `argparse` with subparsers; `--metric` is `action='append'`
  with `nargs='+'` so `--metric net-ping 8.8.8.8 1.1.1.1` lands as one list per flag.
- `app/collectors/base.py` — **new**. Move `Metric`, `MetricResult`, `Snapshot`
  out of `net.py`. Fix:
  - `datetime.now(timezone.utc)` (current code: `datetime.utc(...)`)
  - `MetricResult(...)` (current code: `MetricResult.new(...)`)
  - missing `return` in `Metric.collect`
  - `Snapshot.started_at = datetime.now(...).timestamp()` — current code assigns
    the bound method, not its call
- `app/collectors/net.py` — **rewrite**: `PingMetric` + new `TracertMetric`,
  importing from `base`.
- `app/collectors/sys.py` — **new**: `DfMetric`, `TopMetric`, `IostatMetric`.
- `app/collectors/__init__.py` — **new**: name → class registry consumed by both
  CLI and routine runner.
- `app/routines/{model,store,runner}.py` — **new**, see layout.
- `app/scheduler/{base,cron,inproc}.py` — **new**, interface + stubs that raise
  `NotImplementedError`. Real impls land in v0.2.
- `app/settings.py` — **fill in**: `STORAGE_DIR`, `ROUTINES_DIR`, `LOGS_DIR`, and
  a small `parse_env_file` (no `python-dotenv` dependency).
- `app/enums/env-variables.py` — **rename** to `env_variables.py`.
- `README.md` — rewrite the inconsistent sections to match the above.

## Implementation order

1. Fix module names + drop `__init__.py` into every package so imports work.
2. `collectors/base.py` (with bug fixes) + `collectors/__init__.py` registry.
3. `collectors/sys.py` and rewritten `collectors/net.py` — start with `sys-df`
   and `net-ping` to validate the abstraction end-to-end.
4. `app/cli.py` with just `print`; verify end-to-end.
5. `routines/model.py` + `store.py` (TOML round-trip).
6. `routines/runner.py` (run one routine, append + rotate log).
7. CLI `routine` subcommands: `create`, `list`, `run`, `reset`.
8. `scheduler/` interface + stubs.
9. Rewrite README to match shipped reality.

## Verification

Manual end-to-end (no test framework in v0.1 — small surface; `pytest` lands in
v0.2 with the scheduler impls):

```bash
# Single-shot collection
python3 sonitor.py print --metric sys-df
python3 sonitor.py print --metric net-ping 8.8.8.8 1.1.1.1
python3 sonitor.py print --metric sys-df --metric net-ping 8.8.8.8 --output /tmp/snap.txt
test -s /tmp/snap.txt

# Routine lifecycle
python3 sonitor.py routine create 5m --alias smoke --metric sys-df --metric net-ping 8.8.8.8
python3 sonitor.py routine list                         # shows alias=smoke, period=5m
python3 sonitor.py routine run smoke                    # writes to storage/logs/<uuid>.log
python3 sonitor.py routine run smoke                    # second iteration appended
python3 sonitor.py routine reset smoke                  # log truncated

# Rotation: create with --log-size 3, run 5x, expect only last 3 iteration blocks
python3 sonitor.py routine create 1m --alias rot --log-size 3 --metric sys-df
for i in 1 2 3 4 5; do python3 sonitor.py routine run rot; done
grep -c '^--- ' storage/logs/*rot*.log   # expect 3
```

Spot-check the `.sonitor` file by hand to confirm TOML round-trip stays
human-editable.

## Out of scope (v0.2+)

- `routine enable` / `disable` and the actual `Scheduler` implementations.
- `local/status.ini` and `local/locks/<uuid>.lock` for concurrent-run guarding.
- VoIP metrics (`voip-channelstats`, `voip-endpoints`) — need an Asterisk host
  to validate.
- `pytest` suite.
- Structured JSON output mode.
