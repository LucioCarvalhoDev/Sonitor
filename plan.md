# Sonitor — Specs & Implementation Plan

## Context

Sonitor collects and logs server metrics from Linux systems and networks. The
project started from an ambitious README sketch (print + routine lifecycle +
scheduling + sys/net/VoIP metrics) that had internal contradictions around folder
layout, CLI shape, file format, and metric naming.

During implementation the code converged on an abstraction that **differs from the
original sketch** and is the one we keep going forward:

- `Metric` / `Collector` / `CollectorRepository` (in `app/collectors/`)
- a separate `ShellExecutor` (in `app/execution/`)
- a `Snapshot` formatter

This document records the locked decisions, what already shipped (Phase A), and
what remains (Phase B). VoIP / Asterisk metrics and auto-scheduling are deferred to
v0.2.

## Decisions

| Topic              | Choice                                                        |
| ------------------ | ------------------------------------------------------------ |
| Architecture       | Keep `Collector` / `CollectorRepository` / `ShellExecutor`   |
| CLI metric syntax  | Repeated `--metric` flag (`append` + `nargs='+'`)            |
| Routine file       | TOML body, `.sonitor` extension                              |
| TOML on Python 3.10| `tomli` (read) + `tomli-w` (write) — no stdlib `tomllib`     |
| Scheduler          | `Scheduler` interface — cron impl shipped; in-process stubbed|
| Delivery           | Incremental — `print` first (Phase A), routines next (Phase B)|
| VoIP / Asterisk    | Deferred to v0.2                                             |

### Conventions

- **Metric names** (implemented): `sys-storage`, `sys-uptime`, `sys-top`,
  `net-ping`, `net-dns`, `net-public-ip`.
- **Snapshot text format:** `--- {utc-ts} - {utc-human} - Iteration N ---`
  followed by `sonitor$ <cmd>\n<stdout>` blocks.
- **Storage paths:** `storage/routines/<uuid>.sonitor`, `storage/logs/<uuid>.log`
  (base dir from `STORAGE_FOLDER`, default `./storage`).
- **Packages:** explicit `__init__.py` in every package (no namespace-package
  reliance).

## Module layout (current)

```
sonitor.py                 # thin entrypoint -> app.cli.main()
app/
  cli.py                   # argparse wiring; `print` subcommand
  settings.py              # .env parsing + STORAGE_DIR/ROUTINES_DIR/LOGS_DIR
  collectors/
    __init__.py            # CollectorRepository (full name -> Metric class)
    generic.py             # Metric, MetricResult, Collector, Snapshot
    net.py                 # PingMetric, DnsMetric, PublicIPMetric, NetCollector
    sys.py                 # UptimeMetric, StorageMetric, TopMetric, SystemCollector
  execution/
    shell_executor.py      # ShellExecutor
  scheduler/               # (v0.2) base + cron + inproc
  enums/
    env_variables.py       # EnvVariable enum
tests/
  unit/                    # (Phase B)
storage/
  routines/<uuid>.sonitor  # (Phase B)
  logs/<uuid>.log          # (Phase B)
```

## Phase A — `print` end-to-end ✅ (shipped)

Implemented and verified end-to-end:

- Added the missing `__init__.py` across `app/` and `tests/` packages.
- Fixed collector bugs: `TopMetric` self-recursion + `top -bn1`,
  `UptimeMetric.__init__` signature, `DnsMetric` argument handling,
  `MetricResult` default-argument annotations, `ShellExecutor` type hints.
- Added `Snapshot` (header + `sonitor$` blocks) reused by `print` and, later,
  routines.
- New `app/cli.py`: `argparse` with the `print` subcommand
  (`--metric` as `append` + `nargs='+'`, plus `--output`), friendly error +
  non-zero exit on unknown metrics.
- `sonitor.py` reduced to a thin entrypoint.
- Filled `app/settings.py` (`.env` parser, storage paths) and
  `app/enums/env_variables.py`.

### Phase A verification (manual)

```bash
python3 sonitor.py print --metric sys-storage
python3 sonitor.py print --metric sys-uptime --metric sys-top --metric net-ping 8.8.8.8
python3 sonitor.py print --metric sys-storage --metric net-dns google.com --output /tmp/snap.txt
test -s /tmp/snap.txt && echo OK
python3 sonitor.py print --metric net-foobar; echo "exit=$?"   # friendly error, exit 1
```

## Phase B — routines + scheduler (next)

### B0. Dependencies

- Add `requirements.txt` with `tomli` and `tomli-w` (Python 3.10).

### B1. Routine file format (`storage/routines/<uuid>.sonitor`, TOML)

```toml
[sonitor]
version       = "0.1"
spawn_command = "routine create 12h --metric sys-storage --metric sys-uptime"
alias         = ""

[routine]
created_at  = 2026-05-18T00:00:00Z
last_run_at = 2026-05-18T00:00:00Z
state       = "idle"          # idle | running
period      = "12h"

[[routine.metrics]]
name = "sys-storage"

[[routine.metrics]]
name = "net-ping"
args = ["8.8.8.8", "1.1.1.1"]

[log]
max_lines = 1000
```

### B2. New modules

- `app/routines/model.py` — `Routine` dataclass + TOML load/dump (`tomli` /
  `tomli-w`). Period parser (`30s`, `5m`, `12h`, `1d`).
- `app/routines/store.py` — list / read / write under `ROUTINES_DIR`; resolve by
  `uuid` or `alias`.
- `app/routines/runner.py` — run a routine once: build metrics via
  `CollectorRepository`, execute via `ShellExecutor`, render a `Snapshot`, append
  to `storage/logs/<uuid>.log`, and rotate to the last `max_lines` iteration
  blocks (newest preserved).

### B3. CLI `routine` subcommands

```
sonitor routine create <period> [--alias NAME] [--log-size N] --metric ...
sonitor routine list
sonitor routine run    <uuid|alias>
sonitor routine reset  <uuid|alias>
```

### B4. Scheduler interface (shipped)

- `app/scheduler/base.py` — `Scheduler` ABC (`enable`/`disable`/`is_enabled`/
  `list_enabled`).
- `app/scheduler/cron.py` — `CronScheduler`: `period_to_cron` + manages the user's
  crontab (`# sonitor:<uuid>` marker + entry running `routine run <uuid>`).
  Sub-minute periods are rejected.
- `app/scheduler/inproc.py` — `InprocScheduler` stub (`NotImplementedError`).
- `app/scheduler/__init__.py` — `get_scheduler(name)` factory selecting by
  `DEFAULT_SCHEDULER`.
- CLI `routine enable`/`disable [--scheduler ...]` wired through `get_scheduler`.

### B5. Tests

- `tests/unit/` with `pytest`: `--metric` parsing, TOML round-trip, log rotation.

### Phase B verification (manual)

```bash
python3 sonitor.py routine create 5m --alias smoke --metric sys-storage --metric net-ping 8.8.8.8
python3 sonitor.py routine list                 # shows alias=smoke, period=5m
python3 sonitor.py routine run smoke            # writes storage/logs/<uuid>.log
python3 sonitor.py routine run smoke            # second iteration appended
python3 sonitor.py routine reset smoke          # log cleared

# Rotation: --log-size 3, run 5x, expect only the last 3 iteration blocks
python3 sonitor.py routine create 1m --alias rot --log-size 3 --metric sys-storage
for i in 1 2 3 4 5; do python3 sonitor.py routine run rot; done
grep -c '^--- ' storage/logs/*rot*.log          # expect 3
```

## Out of scope (next)

- In-process `Scheduler` implementation (sub-minute periods).
- `local/status.ini` and `local/locks/<uuid>.lock` for concurrent-run guarding.
- VoIP metrics (`voip-channelstats`, `voip-endpoints`) — need an Asterisk host.
- Structured JSON output mode.
```
