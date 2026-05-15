# Sonitor

Sonitor is a lightweight CLI tool for collecting and logging server metrics from Linux systems, networks, and Asterisk PBX instances.

## Usage

### Flags

## Subcommands

- `print <metrics>+`: Single execution and prints snapshot to console of given metrics;
    - `--output`: Instead of print, saves to output;
- `routine`: Prints subcommand man.
- `routine list`: List all subrotines stored with its status;
- `routine create <Period:str> <flags> <metrics>`: Creates a `.sonitor` file based on next arguments.
    - `--log-size <Lines:int=1000>`: The `[Log]` section is keep under Lines, the newest lines are preserved;
    - `--alias <str>`: Give and alias to the routine;
    - `net-ping <address>+`: My receive list of Address;
    - `net-tracert <address>+`;
    - `voip-channelstats`: `asterisk -rx "pjsip show channelstats"`;
    - `voip-endpoints <pattern?>`: `asterisk -rx "pjsip show endpoints"`, may receive a regex pattern for filtering;
    - `sys-df`;
    - `sys-iostat <int>`;
    - `sys-top`.
- `routine run <uuid|alias>`: Single execution of given routine;
- `routine reset <uuid|alias>`: Clear `[Log]` section of given routine;
- `routine enable <uuid|alias>`: Start repeating execution of given routine;
- `routine disable <uuid|alias>`: Stop repeating execution of given routine;

## Folder Structure

```
.env
.env.sample
app/enums/env_variables
app/monitor/net.py
app/monitor/voip.py
app/monitor/sys.py
app/settings.py
app/schedullers/cron.py
local/status.ini
local/locks/<uuid>.lock
storage/logs/dd-mm-yyyy_<uuid>.log
storage/routines/dd-mm-yyyy_<uuid>.sonitor
sonitor.py
```

## Dictionary

- Snapshot: Set of all metric results of a given iteration, can me transformed to a string output;
- Routine: An in memory object that defines metrics and options (stored on `.sonitor` files) to capture `snapshots` registerd on `.log` files;
- `.sonitor`: Extension used in plain text file that define an routine to generate snapshots;

## Examples

The cli app can be used for both, simple logs to the console or more complex periodic observation. Its usage have the formart `python3 sonitor.py subcommand flags+ metrics*`. There are a few examples:

- `python3 sonitor.py print --metric net-traceroute 8.8.8.8`

The cli parses "net-traceroute 8.8.8.8" as one metric definition, executes treaceroute and prints to console.

- `python3 sonitor.py print --metric sys-df --metric net-ping 1.1.1.1`

The cli parses two metrics definitions, the printed snapshot contains `df` and `ping`.

- `python3 sonitor.py print --output="./file.txt" --metric net-ping 8.8.8.8 domain.site.com`

The cli parses a ping metric to two address, executes and saves the snapshot to given output file.

- `python3 sonitor.py routine 5m --metric sys-top`

The cli parses one metric and creates a `.sonitor` file that will executed every five minutes.

- `python3 sonitor.py routine 5m --metric net-ping 8.8.8.8 domain.site.net --metric net-traceroute 212.78.32.113`

The cli parses two metrics and every five minutes log the given metrics on the `.sonitor` generated file.

## Architecture

When a command like `python3 sonitor.py routine 1m --metric asterisk-channels --metric io-df"` is invoked, the cli creates an `.sonitor` file on `storage/routines` with includes static metadate about the commands (like the "net-ping 8.8.8.8" subcommand) and variables. Them, the cli creates a crontab entry that calls `python3 sonitor.py start <ROUTINE_PATH>` that, finally, executes the routine and updates the log file.

### Routine file

```
sonitor:
 - version: 0.1
 - spawn-command: "--routine 12h --metric sys-uptime --metric sys-df"
 - alias: ~
 - created-at: {utc-timestamp}
 - state: active

routine:
 - last-execution: {utc-timestap}
 - period: 12h
metrics:
 - sys-uptime: ~
 - sys-df: ~

log:
 - size: 1000l
```

### Log File

```/dict/sonitor/storage/log/<uuid>.log
--- {utc-timestamp} - {utc-human-readable} - Iteration {step} ---

sonitor$ uptime
09:20:12 up 29 min,  2 users,  load average: 0.01, 0.40, 0.20

sonitor$ df
Filesystem      1K-blocks      Used Available Use% Mounted on
none              3010168         0   3010168   0% /usr/lib/modules/6.6.87.2-microsoft-standard-WSL2
none              3010168         4   3010164   1% /mnt/wsl
drivers         233551868 119496876 114054992  52% /usr/lib/wsl/drivers
/dev/sdd       1055762868   5547328 996512068   1% /
none              3010168        80   3010088   1% /mnt/wslg
none              3010168         0   3010168   0% /usr/lib/wsl/lib
rootfs            3005128      2720   3002408   1% /init
none              3010168       492   3009676   1% /run

--- {utc-timestamp} - {utc-human-readable} - Iteration {step} ---

sonitor$ uptime
09:20:12 up 29 min,  2 users,  load average: 0.01, 0.40, 0.20

sonitor$ df
Filesystem      1K-blocks      Used Available Use% Mounted on
none              3010168         0   3010168   0% /usr/lib/modules/6.6.87.2-microsoft-standard-WSL2
none              3010168         4   3010164   1% /mnt/wsl
drivers         233551868 119496876 114054992  52% /usr/lib/wsl/drivers
/dev/sdd       1055762868   5547328 996512068   1% /
none              3010168        80   3010088   1% /mnt/wslg
none              3010168         0   3010168   0% /usr/lib/wsl/lib
rootfs            3005128      2720   3002408   1% /init
none              3010168       492   3009676   1% /run
```