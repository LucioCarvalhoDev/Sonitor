# Sonitor

Sonitor is a lightweight CLI tool for collecting and logging server metrics from Linux systems, networks, and Asterisk PBX instances.

## Usage

### Flags

## Subcommands

- `log <Metrics>+`: Single execution and prints snapshot to console given metrics;
    - `--output`: Instead of print, saves to output;
    - `--input: <path>`: Path to routine to extract metrics.
- `list-routines`;
- `start <Routine>`: Receives routine alias or uuid and prepare cron;
- `restart <Routine>`: Clear `[Log]` section and procedes to `start`;
- `routine <TimePeriod> <Metrics>+`: Creates a `.sonitor` file based on next arguments.
    - `--log-size <Lines:int=1000>`: When provided makes the total amount of lines of the routine trim at `Lines`, the newest lines are preserved;
    - `--alias <str>`: Give and alias to the routine;
    - `net-ping <Address>+`: My receive list of Address;
    - `net-tracert <Address>+`;
    - `asterisk-stats`: `asterisk -rx "pjsip show channelstats"`;
    - `asterisk-channels`: My receive list of regex patterns to filter;
    - `sys-df`;
    - `sys-iostat <Arguments>`;
    - `sys-htop`.

## Folder Structure

```
app/enums/env_variables
app/monitor/net.py
app/monitor/asterisk.py
app/monitor/sys.py
app/settings.py
app/settings.py
storage/routines/dd-mm-yyyy_<uuid>.sonitor
local/
sonitor.py
.env
.env.sample
```

## Dictionary

- Snapshot: Set of the every metric of a given iteration;
- Routine: An object stored as text (like a .ini file) and includes the given logs and metadata of an sonitor log request;
- `.sonitor`: Extension used in sonitor log files, the file contentes are plain text ini-like;

## Examples

The cli app can be used for both, simple logs to the console or more complex periodic observation. Its usage have the formart `python3 sonitor.py subcommand flags+ metrics*`. There are a few examples:

- `python3 sonitor.py log net-tracert 8.8.8.8` or `python3 sonitor.py log --metric net-tracert 8.8.8.8`

The cli parses "net-tracert 8.8.8.8" as one metric definition, executes treaceroute and prints to console.

- `python3 sonitor.py log --metric sys-df --metric net-ping 1.1.1.1`

The cli parses two metrics definitions, the printed snapshot contains `df` and `ping`.

- `python3 sonitor.py log --output="./file.txt" --metric net-ping 8.8.8.8 domain.site.com`

The cli parses a ping metric to two address, executes and saves the snapshot to given output file.

- `python3 sonitor.py routine 5m --metric sys-top`

The cli parses one metric and creates a `.sonitor` file that will executed every five minutes.

- `python3 sonitor.py routine 5m --metric net-ping 8.8.8.8 domain.site.net --metric net-tracert 212.78.32.113`

The cli parses two metrics and every five minutes log the given metrics on the `.sonitor` generated file.

## Architecture

When a command like `python3 sonitor.py routine 1m --metric asterisk-channels --metric io-df"` is invoked, the cli creates an `.sonitor` file on `storage/routines` with includes static metadate about the commands (like the "net-ping 8.8.8.8" subcommand), variables and, under the "[Log]" section, the logs. Them, the cli creates a crontab entry that calls `python3 sonitor.py start <ROUTINE_PATH>` that, finally, executes the routine and updates the log file.

### Routine file

```
[Sonitor]
version=0.1
id={UUID}
alias=
spawn-command=--routine 12h --metric sys-uptime --metric sys-df"
metrics=["sys-uptime", "sys-df"]
period=12h
created-at={utc-timestamp}
log-size=1000

[Routine]
step=0

[Log]
--- {utc-timestamp} - {utc-human-readable} - Iteration {step + 1} ---

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