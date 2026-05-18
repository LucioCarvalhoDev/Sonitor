# Sonitor

Sonitor is a lightweight CLI tool for collecting and logging server metrics from
Linux systems, networks, and (in v0.2) Asterisk PBX instances.

It has two modes:

- **`print`** — single-shot snapshot to stdout or a file.
- **`routine`** — persist a named set of metrics with a period; run it on demand
  now, enable/disable scheduled execution in v0.2.

## Usage

```
sonitor.py print   --metric <name> [args...] [--metric <name> [args...]]... [--output PATH]
sonitor.py routine create <period> [--alias NAME] [--log-size N] --metric ...
sonitor.py routine list
sonitor.py routine run    <uuid|alias>
sonitor.py routine reset  <uuid|alias>
```

Metrics are always declared with the `--metric` flag, followed by the metric
name and any positional arguments that metric accepts. The flag may be repeated.

### Subcommands

- `print` — single execution; emits the snapshot to stdout.
  - `--metric <name> [args...]` — repeat for each metric.
  - `--output <path>` — write to a file instead of stdout.
- `routine create <period> --metric ...` — create a `.sonitor` file.
  - `<period>` — e.g. `30s`, `5m`, `12h`, `1d`.
  - `--alias <str>` — human-readable handle (otherwise refer by uuid).
  - `--log-size <N>` — keep the routine's log under N iteration blocks
    (newest preserved). Default `1000`.
- `routine list` — list routines with their alias, period, and state.
- `routine run <uuid|alias>` — run one iteration now.
- `routine reset <uuid|alias>` — clear the log file for a routine.

### Available metrics (v0.1)

- `sys-df` — `df -h`
- `sys-top` — `top -bn1`
- `sys-iostat <interval>` — `iostat <interval> 2`
- `net-ping <address>+` — `ping -c 4 <address>`
- `net-tracert <address>+` — `traceroute <address>`

Deferred to v0.2: `voip-channelstats`, `voip-endpoints <pattern?>`, and the
`routine enable` / `disable` scheduling commands.

## Examples

```bash
# Print a single metric to stdout
python3 sonitor.py print --metric net-tracert 8.8.8.8

# Combine metrics
python3 sonitor.py print --metric sys-df --metric net-ping 1.1.1.1

# Send the snapshot to a file
python3 sonitor.py print --output ./file.txt --metric net-ping 8.8.8.8 domain.site.com

# Persist a routine and run it once
python3 sonitor.py routine create 5m --alias edge --metric sys-top
python3 sonitor.py routine run edge

# Multi-metric routine
python3 sonitor.py routine create 5m \
  --metric net-ping 8.8.8.8 domain.site.net \
  --metric net-tracert 212.78.32.113
```

## Folder structure

```
.env
.env.sample
sonitor.py
plan.md
app/
  __init__.py
  cli.py
  settings.py
  collectors/
    __init__.py        # name -> Metric registry
    base.py            # Metric, MetricResult, Snapshot
    net.py             # PingMetric, TracertMetric
    sys.py             # DfMetric, TopMetric, IostatMetric
  routines/
    model.py           # Routine dataclass + TOML I/O
    store.py           # CRUD under storage/routines/
    runner.py          # run a routine + rotate its log
  scheduler/
    base.py            # Scheduler protocol
    cron.py            # CronScheduler (v0.2)
    inproc.py          # InProcessScheduler (v0.2)
  enums/
    env_variables.py
storage/
  routines/<uuid>.sonitor
  logs/<uuid>.log
```

## Architecture

When the user runs `python3 sonitor.py routine create 1m --metric sys-df`, the
CLI writes a `<uuid>.sonitor` file under `storage/routines/` containing the
spawn command, the routine's metadata, and its metric list (see format below).
`routine run <uuid|alias>` loads that file, executes each metric, formats the
output as a snapshot, and appends it to `storage/logs/<uuid>.log`, trimming the
log to the last `max_lines` iteration blocks.

In v0.2, `routine enable` will register the routine with a configured
`Scheduler` (cron entry on the host, or the in-process scheduler for dev/test);
`routine disable` removes it.

### Routine file (`storage/routines/<uuid>.sonitor`, TOML)

```toml
[sonitor]
version       = "0.1"
spawn_command = "routine create 12h --metric sys-uptime --metric sys-df"
alias         = ""

[routine]
created_at  = 2026-05-18T00:00:00Z
last_run_at = 2026-05-18T00:00:00Z
state       = "idle"           # idle | running
period      = "12h"

[[routine.metrics]]
name = "sys-uptime"

[[routine.metrics]]
name = "sys-df"

[log]
max_lines = 1000
```

### Log file (`storage/logs/<uuid>.log`)

```
--- {utc-timestamp} - {utc-human-readable} - Iteration {step} ---

sonitor$ uptime
09:20:12 up 29 min,  2 users,  load average: 0.01, 0.40, 0.20

sonitor$ df
Filesystem      1K-blocks      Used Available Use% Mounted on
/dev/sdd       1055762868   5547328 996512068   1% /
...

--- {utc-timestamp} - {utc-human-readable} - Iteration {step} ---

sonitor$ uptime
...
```

## Glossary

- **Snapshot** — the set of all metric results for one iteration; serializable
  as the text block shown above.
- **Routine** — an in-memory object backed by a `.sonitor` file under
  `storage/routines/` that defines which metrics to capture, on what period,
  and how large its log may grow.
- **Iteration** — one execution of a routine producing one snapshot.

## Roadmap

- **v0.1** — `print`, routine lifecycle (`create`/`list`/`run`/`reset`),
  sys + net metrics.
- **v0.2** — `routine enable`/`disable` with the `Scheduler` interface
  (cron + in-process impls), VoIP metrics, lock files / status under `local/`,
  `pytest` suite.

See `plan.md` for the implementation breakdown.
