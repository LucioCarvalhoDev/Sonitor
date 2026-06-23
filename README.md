# Sonitor

Sonitor is a lightweight CLI tool for collecting and logging server metrics from
Linux systems and networks. VoIP / Asterisk PBX metrics are planned for v0.2.

## Setup

After cloning, run the setup script to create the virtualenv, install
dependencies, and seed a local `.env` (idempotent — safe to re-run):

```bash
./scripts/init.sh            # runtime + dev deps (includes pytest)
./scripts/init.sh --no-dev   # runtime deps only
```

sonitor requires **Python 3.10+**. To bootstrap with a specific interpreter:
`PYTHON=python3.11 ./scripts/init.sh`. For servers stuck on old/legacy Python,
see [Agentless collection](#agentless-collection-remote-hosts) — run sonitor
from a modern host and collect over SSH.

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
| `voip-channels-count` | `asterisk -rx "core show channels count"` | — |
| `voip-channels`  | `asterisk -rx "pjsip show channels"`      | — |
| `voip-channelstatus` | `asterisk -rx "pjsip show channelstats"` | — |
| `voip-sip`       | `sngrep <args>`    | `"<sngrep args>"` |

> **VoIP metrics** assume an Asterisk PBX with the **PJSIP** channel driver and,
> for `voip-sip`, the `sngrep` tool. The `voip-sip` argument string is passed
> through to `sngrep` verbatim — quote it as a single argument and use a
> non-interactive form, e.g. `voip-sip "-N -q -O /tmp/capture.pcap"`.

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

## Agentless collection (remote hosts)

By default every metric runs on the local host. With `--target` the metric
commands run on a remote host over **SSH** instead, so sonitor can run from one
modern machine while the monitored servers need **no Python at all** — only a
shell and the tools each metric calls (`df`, `asterisk`, `sngrep`, …). This is
the recommended way to monitor boxes stuck on old/legacy Python.

```
--target NAME | [USER@]HOST[:PORT]   # registered target name, or an ad-hoc spec
--identity PATH                      # ssh -i private key (requires --target)
--ssh-option KEY=VALUE               # extra ssh -o option, repeatable
```

SSH runs with `BatchMode=yes` and `ConnectTimeout=10` so unattended (cron) runs
never block on a prompt and fail fast when a host is unreachable. Each remote
command is prefixed with a standard `PATH` (including `/usr/sbin` and `/sbin`) so
system tools like `asterisk` and `tcpdump` resolve under the non-interactive SSH
shell, which otherwise has a minimal `PATH` and ignores the user's dotfiles. Set
up key auth to the target first (or use `remote setup` below). `--target` works on both
`print` and `routine create`; a routine stores its resolved target in the
`.sonitor` file, so scheduled runs hit the same host.

```bash
# One-shot snapshot of a remote Asterisk PBX (ad-hoc spec)
python3 sonitor.py print --target root@pbx.example.com \
  --metric voip-channels-count --metric voip-channelstats

# Persist a routine that collects from the PBX every 5 minutes
python3 sonitor.py routine create 5m --name pbx --target root@10.0.0.5:2222 \
  --ssh-option StrictHostKeyChecking=accept-new \
  --metric voip-channels-count --metric voip-sip "-N -q -O /tmp/cap.pcap"
```

### Inspecting a command (`debug metric`)

`debug metric` prints the command layers for a metric **without running anything**
— handy when a remote command misbehaves. With `--target` it shows the bare metric
command, the PATH-prefixed command the remote shell runs, and the full ssh wrapper:

```bash
python3 sonitor.py debug metric --target pbx01 voip-contacts 2020@
# metric command : asterisk -rx "pjsip show contacts" | grep 2020@
# remote command : PATH="/usr/local/sbin:...:/sbin:$PATH" asterisk -rx "pjsip show contacts" | grep 2020@
# ssh wrapper    : ssh -o BatchMode=yes -o ConnectTimeout=10 sonitor@pbx01 '...'
```

Put `--target` before the metric name; everything after the metric name is
forwarded to it as arguments (so dashed args like `voip-sip -N -q` work as-is).
Without `--target` only the bare metric command is shown (it would run locally).

### Onboarding a target (`remote setup`)

`remote setup` automates key-based access in one interactive step: it generates a
dedicated keypair **on this host** (the private key never leaves it), connects to
the target once with the privileged credentials you give it (SSH prompts for the
password on your terminal), and on the target it creates a locked-down `sonitor`
user, installs the **public** key, and wires up metric privileges (adds it to the
`asterisk` group and gives `sngrep` `cap_net_raw`). The target is then registered
under a name you can pass to `--target`.

```
sonitor remote setup [USER@]HOST[:PORT] --name NAME [--no-privileges] [--force]
sonitor remote list
sonitor remote rename CURRENT NEW
sonitor remote forget NAME [--keep-key]
sonitor remote teardown (NAME | [USER@]HOST[:PORT]) [--bootstrap-user USER] [--no-privileges]
sonitor remote purge NAME [--bootstrap-user USER] [--no-privileges] [--keep-key]
```

```bash
# Provision once (type the root password when prompted), then use the name
python3 sonitor.py remote setup root@pbx.example.com --name pbx01
python3 sonitor.py remote list
python3 sonitor.py print --target pbx01 --metric sys-top
python3 sonitor.py routine create 5m --target pbx01 --metric voip-channels-count
python3 sonitor.py remote rename pbx01 pbx-prod   # renames the target + its key files
python3 sonitor.py remote forget pbx-prod         # forgets the target + deletes its key (local-only)

# Undo the setup on the server itself (the inverse of `setup`):
python3 sonitor.py remote teardown pbx-prod                  # by name: bootstraps as root@<host>
python3 sonitor.py remote teardown root@pbx.example.com:22   # explicit destination (no registry lookup)
python3 sonitor.py remote purge pbx-prod                     # teardown + forget: host AND local cleanup
```

Keys live under `storage/ssh/id_<uuid>` (0600) and the registry under
`storage/targets/<name>.target` — both inside the git-ignored `storage/`. Key files
are named by UUID, not by target name: the registry entry owns the path reference.
The key has no passphrase (so cron can use it); its protection is filesystem
permissions plus the locked `sonitor` account. `remote rename` is a pure registry
operation — the key file stays put, so routines created before the rename keep
working. `remote forget` deletes the local key and registry entry but leaves the
`sonitor` user on the remote host in place. `remote teardown` is the inverse of
`setup` on the **host side only**, and accepts either a registered name or an
explicit `[user@]host[:port]` destination. With a name it looks the host up in the
registry and bootstraps as `root@<host>` (override with `--bootstrap-user`); with
an explicit destination it connects there verbatim with no registry lookup. Either
way it reconnects with privileged credentials (the locked `sonitor` user can't
remove itself, so SSH prompts for the root password again), runs `userdel -r
sonitor` and reverts the `sngrep` capability (`--no-privileges` keeps the
capability), and leaves the local registration and key in place. `remote purge
NAME` is `teardown` + `forget` in one step: it undoes the host **and** drops the
local registry entry and key (`--keep-key` keeps the key); unlike `teardown` it
only takes a registered name. So `forget` is the local-only cleanup, `teardown` is
the host-only cleanup, and `purge` does both.

#### Host-side manifest (`/home/sonitor`)

The controller keeps the source of truth (`storage/targets/*.target` + the private
key), but `setup` also drops a small **manifest** in the `sonitor` user's home so a
host carries a record of its own provisioning:

```
/home/sonitor/
  README.md      what this user is and how to remove it (for a passing sysadmin)
  version.toml   [provision] version = N — which provisioning version set it up
  hosts.toml     one [[controller]] per operator machine (key fingerprint + label)
  uninstall.sh   self-contained removal script, run as root on the host
```

This addresses three otherwise-invisible situations:

- **Several controllers, one host.** Each `setup` appends the controller's key
  (idempotent) *and* a `[[controller]]` entry in `hosts.toml`, so the host records
  who can reach it. `teardown`/`purge` are still global (`userdel -r` revokes every
  key); when `hosts.toml` lists more than one controller, they print a warning
  naming the others before the destructive step.
- **Provisioning drift.** The project version is centralized in `app/version.py`
  (semantic versioning; print it with `sonitor --version`), and `setup` records it
  in the host's `version.toml`.
  `remote check` reads it back and compares it with the controller's version,
  reporting `ok`, `outdated` (host provisioned by an older release — re-run
  `setup --force`), `unmanaged` (reachable but no manifest, i.e. a legacy setup)
  or `unreachable`:

  ```bash
  python3 sonitor.py remote check pbx01
  # ok: target 'pbx01' is reachable at sonitor@pbx.example.com (provision v0.1.0)
  # outdated: ... was provisioned with v0.1.0, but this sonitor expects v0.2.0.
  #   re-provision with: sonitor remote setup <DEST> --name pbx01 --force
  ```

- **Removing `sonitor` from the host itself.** When you only have the server (no
  controller, no registry), an admin can wipe the account directly — the manifest's
  `README.md` documents exactly this and `uninstall.sh` is the same teardown logic
  `remote teardown` runs:

  ```bash
  sudo sh /home/sonitor/uninstall.sh   # removes the user + home, reverts sngrep cap
  ```

Re-running `setup` (e.g. `--force`) rewrites `version.toml`, `README.md` and
`uninstall.sh` to the current version and adds the controller to `hosts.toml` if it
is not already there, so the manifest tracks the latest provisioning.

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
  `MetricResult`. `RemoteShellExecutor` wraps the command in `ssh` to run it on
  a remote `SshTarget` (agentless); `get_executor(target)` picks local vs remote.
- **`Snapshot`** — aggregates `MetricResult`s into the text block shown above.

When you run `python3 sonitor.py print --metric net-ping 8.8.8.8`, the CLI
(`app/cli.py`) resolves each `--metric` through `CollectorRepository`, executes it
via `ShellExecutor`, and renders the results as a `Snapshot` to stdout or a file.

## Folder structure

```
sonitor.py                 # thin entrypoint -> app.cli.main()
scripts/init.sh            # post-clone setup (venv + deps + .env)
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
    voip.py                # Channels/ChannelStatus/Sip metrics, VoipCollector
  execution/
    __init__.py            # get_executor(target) factory (local vs remote)
    shell_executor.py      # ShellExecutor + RemoteShellExecutor (SSH)
    target.py              # SshTarget ([user@]host[:port] -> ssh wrapper)
  remote/
    model.py               # Target (named SshTarget) + TOML (de)serialize
    store.py               # named-target registry + resolve_spec (name | spec)
    provision.py           # remote setup: keygen, provisioning script, run_setup
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
  targets/<name>.target    # registered SSH targets (remote setup)
  ssh/id_<uuid>            # private key, referenced by the target (0600)
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
- **v0.3** — VoIP / Asterisk (PJSIP) metrics + `sngrep`, agentless collection
  over SSH (`--target`), and `remote setup` to onboard targets (named registry +
  key provisioning). ✅ shipped.
- **Next** — in-process scheduler implementation, structured JSON output.

See `plan.md` for the implementation breakdown.
```
