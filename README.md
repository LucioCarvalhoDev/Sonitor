# Sonitor

Sonitor is a lightweight CLI tool for collecting and logging server metrics from
Linux systems and networks. VoIP / Asterisk PBX metrics are planned for v0.2.

It is designed around two modes:

- **`print`** — single-shot snapshot to stdout or a file. **(implemented)**
- **`routine`** — persist a named set of metrics with a period, run on demand, and
  schedule recurring execution through a pluggable `Scheduler` (cron). **(implemented)**

> **Status:** both `print` and the full `routine` lifecycle
> (`create/list/run/reset/enable/disable`) work end-to-end. The cron scheduler is
> the first `Scheduler` implementation; an in-process scheduler is stubbed behind
> the same interface.

## Usage

```
sonitor.py print --metric <name> [args...] [--metric <name> [args...]]... [--output PATH]
```

Metrics are declared with the `--metric` flag, followed by the metric name and any
arguments that metric accepts. The flag may be repeated to combine metrics in a
single snapshot.

### `print`

- `--metric <name> [args...]` — repeat for each metric.
- `--output <path>` — write the snapshot to a file instead of stdout.

### Available metrics

| Name             | Command run        | Arguments        |
| ---------------- | ------------------ | ---------------- |
| `sys-storage`    | `df`               | —                |
| `sys-uptime`     | `uptime`           | —                |
| `sys-top`        | `top -bn1`         | —                |
| `net-ping`       | `ping <addr> -c 4` | `<address>`      |
| `net-dns`        | `nslookup <addr>`  | `<address>`      |
| `net-public-ip`  | `curl -4 -s ifconfig.me` | —          |

## Examples

```bash
# Single metric to stdout
python3 sonitor.py print --metric sys-storage

# Network metric with an argument
python3 sonitor.py print --metric net-ping 8.8.8.8

# Combine several metrics in one snapshot
python3 sonitor.py print --metric sys-uptime --metric sys-top --metric net-ping 8.8.8.8

# Write the snapshot to a file
python3 sonitor.py print --metric sys-storage --metric net-dns google.com --output ./snap.txt
```

## `routine`

A routine is a named, persisted set of metrics with a recurrence period. It is
stored as a TOML `.sonitor` file under `storage/routines/<uuid>.sonitor` and logs
each run (a `Snapshot` block) to `storage/logs/<uuid>.log`, rotated to the last
`--log-size` iteration blocks.

```
sonitor.py routine create <period> [--name NAME] [--annotation TEXT] [--log-size N] --metric <name> [args...]...
sonitor.py routine list [--scheduler cron|inproc]
sonitor.py routine run        <uuid|name>
sonitor.py routine reset      <uuid|name>
sonitor.py routine reschedule <uuid|name> <period> [--scheduler cron|inproc]
sonitor.py routine enable  <uuid|name> [--scheduler cron|inproc]
sonitor.py routine disable <uuid|name> [--scheduler cron|inproc]
sonitor.py routine delete  <uuid|name> [--scheduler cron|inproc]
sonitor.py routine purge   <uuid|name> [--scheduler cron|inproc]
```

`<period>` is an integer with a `s|m|h|d` suffix (`30s`, `5m`, `12h`, `1d`).
`--name` is a friendly handle that must be **unique** across routines (creation
fails if it already exists); `--annotation` stores a free-text note in the
`.sonitor` file. A routine can always be referenced by its uuid as well.

```bash
# Create a routine and reference it by name
python3 sonitor.py routine create 5m --name smoke --annotation "nightly disk check" --metric sys-storage --metric net-ping 8.8.8.8
python3 sonitor.py routine run smoke              # run once, append to its log
python3 sonitor.py routine list

# Schedule / unschedule recurring execution (cron installs into your crontab)
python3 sonitor.py routine enable smoke
python3 sonitor.py routine disable smoke

# Change the period (re-applies the cron schedule if the routine is enabled)
python3 sonitor.py routine reschedule smoke 1m

# Remove a routine (both unschedule it first to avoid a dangling cron entry)
python3 sonitor.py routine delete smoke           # remove the .sonitor file, keep the log
python3 sonitor.py routine purge smoke            # remove the .sonitor file and the log
```

### Scheduling

`enable`/`disable` delegate to a `Scheduler` selected by `--scheduler` or, by
default, the `DEFAULT_SCHEDULER` setting. The **cron** scheduler manages your
crontab automatically: it adds a `# sonitor:<uuid>` marker plus a cron entry that
runs `sonitor.py routine run <uuid>`, and removes both on `disable`. Cron's
granularity is one minute, so sub-minute periods are rejected by the cron
scheduler. The **inproc** scheduler is stubbed behind the same interface for a
future in-process loop.

`routine list` reports each routine's `STATE` as `enabled`/`disabled` by querying
the scheduler (the crontab, for cron) — the schedule itself is the source of
truth, so the column reflects whether the routine is actually scheduled rather
than a value stored in the `.sonitor` file.

## Snapshot format

A snapshot is the set of all metric results for one iteration, rendered as text:

```
--- {utc-timestamp} - {utc-human-readable} - Iteration {n} ---

sonitor$ uptime
 07:25:02 up 4 days, 22:14,  5 users,  load average: 0.07, 0.17, 0.18

sonitor$ df
Filesystem      1K-blocks      Used Available Use% Mounted on
/dev/sdd       1055762868   5929784 996129612   1% /
...
```

## Architecture

The implemented design is built around collectors, a registry, and a shell
executor:

- **`Metric`** — knows how to build a shell command from its arguments.
- **`Collector`** — groups related metrics under a prefix (`sys`, `net`) and
  exposes them by full name (e.g. `sys-storage`).
- **`CollectorRepository`** — resolves a metric full name (`net-ping`) to its
  `Metric` class.
- **`ShellExecutor`** — runs a metric's command, times it, and returns a
  `MetricResult`.
- **`Snapshot`** — aggregates `MetricResult`s into the text block shown above.

When you run `python3 sonitor.py print --metric net-ping 8.8.8.8`, the CLI
(`app/cli.py`) resolves each `--metric` through `CollectorRepository`, executes it
via `ShellExecutor`, and renders the results as a `Snapshot` to stdout or a file.

## Folder structure

```
sonitor.py                 # thin entrypoint -> app.cli.main()
.env / .env.sample
plan.md
app/
  cli.py                   # argparse wiring; `print` subcommand
  settings.py              # .env parsing + storage paths
  collectors/
    __init__.py            # registry: CollectorRepository (name -> Metric)
    generic.py             # Metric, MetricResult, Collector, Snapshot
    net.py                 # PingMetric, DnsMetric, PublicIPMetric, NetCollector
    sys.py                 # UptimeMetric, StorageMetric, TopMetric, SystemCollector
  execution/
    shell_executor.py      # ShellExecutor
  routines/
    model.py               # Routine dataclass, period parser, TOML (de)serialize
    store.py               # create/list/save/resolve under ROUTINES_DIR
    runner.py              # run a routine once: collect, snapshot, append, rotate
  scheduler/
    base.py                # Scheduler interface (ABC)
    cron.py                # CronScheduler (manages the user's crontab)
    inproc.py              # InprocScheduler (stub)
    __init__.py            # get_scheduler() factory + registry
  enums/
    env_variables.py       # EnvVariable enum
tests/
  unit/                    # pytest: parsing, TOML round-trip, rotation, scheduler
storage/
  routines/<uuid>.sonitor
  logs/<uuid>.log
```

## Configuration

`app/settings.py` reads an optional `.env` (no external dependency). See
`.env.sample`:

- `STORAGE_FOLDER` — base directory for routine files and logs (default
  `./storage`).
- `DEFAULT_SCHEDULER` — scheduler used by `routine enable`/`disable` when
  `--scheduler` is omitted (`cron` | `inproc`, default `cron`).

## Glossary

- **Snapshot** — the set of all metric results for one iteration, serializable as
  the text block shown above.
- **Routine** — a persisted set of metrics captured on a period, backed by a
  `.sonitor` file under `storage/routines/` and logged to `storage/logs/`.
- **Iteration** — one execution producing one snapshot.
- **Scheduler** — interface (`app/scheduler/base.py`) that hooks a routine into a
  recurring mechanism; `CronScheduler` is the first implementation.

## Roadmap

- **v0.1** — `print` with sys + net metrics. ✅ shipped.
- **v0.2** — `routine create/list/run/reset` (TOML `.sonitor` files + rotated
  logs) and `routine enable`/`disable` via a `Scheduler` interface (cron impl;
  in-process stubbed), with a `pytest` suite. ✅ shipped.
- **Next** — in-process scheduler implementation, VoIP / Asterisk metrics,
  structured JSON output.

See `plan.md` for the implementation breakdown.
```
