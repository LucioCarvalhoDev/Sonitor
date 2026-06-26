import argparse
import sys
from pathlib import Path
from typing import Dict, List

from app.collectors import CollectorRepository, Metric, MetricResult, Snapshot
from app.execution import get_executor
from app.execution.target import SshTarget
from app.remote import audit as remote_audit
from app.remote import provision
from app.remote import store as remote_store
from app.routines import runner, store
from app.routines.model import parse_period
from app.scheduler import get_scheduler
from app.version import __version__


def _build_target(
    target: str | None,
    identity: str | None,
    ssh_options: List[str] | None,
) -> SshTarget | None:
    """Build an SshTarget from CLI flags, or None for local execution.

    ``--target`` accepts a registered target name or a ``[user@]host[:port]``
    spec. ``--identity``/``--ssh-option`` without ``--target`` is a usage error.
    """
    if not target:
        if identity or ssh_options:
            raise ValueError("--identity/--ssh-option require --target")
        return None
    return remote_store.resolve_spec(target, identity, ssh_options)


def build_metrics(metric_specs: List[List[str]]) -> List[Metric]:
    """Turn ``--metric`` specs into resolved Metric instances.

    Each spec is ``[name, arg1, arg2, ...]`` as produced by argparse's
    ``append`` + ``nargs='+'``. Resolution errors (unknown metric) raise
    ``ValueError`` from the repository.
    """
    metrics: List[Metric] = []
    for spec in metric_specs:
        name = spec[0]
        arguments = spec[1:]
        metric_cls = CollectorRepository.resolve(name)
        metrics.append(metric_cls(arguments))
    return metrics


def _metric_flag_arity(name: str) -> Dict[str, int]:
    """Map each of a metric's flag strings to how many values it consumes.

    Read from the metric's ``arg_parser()`` so the splitter knows which dashed
    tokens belong to the metric (and how many values to swallow). Unknown
    metrics (resolution fails) have no known flags, so the splitter stops at
    the first dashed token and ``build_metrics`` later raises the nice error.
    """
    try:
        metric_cls = CollectorRepository.resolve(name)
    except ValueError:
        return {}
    parser = metric_cls.arg_parser()
    if parser is None:
        return {}
    arity: Dict[str, int] = {}
    for action in parser._actions:
        takes_value = 0 if action.nargs == 0 else 1
        for option in action.option_strings:
            arity[option] = takes_value
    return arity


def _extract_metric_groups(argv: List[str]) -> tuple[List[str], List[List[str]]]:
    """Pull each ``--metric NAME [args/flags...]`` group out of ``argv``.

    Runs before argparse so a metric's own dashed flags (e.g. ``sys-top
    --head 5``) are captured instead of being rejected as unknown options. A
    group runs from ``--metric NAME`` until the next ``--metric`` or the next
    dashed token that is *not* one of that metric's flags (a sibling option,
    which stops the group). Returns ``(residual_argv, groups)`` where
    ``residual_argv`` is everything that was not part of a metric group.
    """
    residual: List[str] = []
    groups: List[List[str]] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token != "--metric":
            residual.append(token)
            index += 1
            continue

        index += 1  # consume '--metric'
        if index >= len(argv) or argv[index] == "--metric":
            raise ValueError("--metric requires a metric name")
        name = argv[index]
        index += 1
        group = [name]
        flag_arity = _metric_flag_arity(name)
        while index < len(argv):
            candidate = argv[index]
            if candidate == "--metric":
                break
            if candidate.startswith("-"):
                flag = candidate.split("=", 1)[0]
                if flag not in flag_arity:
                    break  # sibling option -> the metric group ends here
                group.append(candidate)
                index += 1
                # a separate value (not the --flag=value form) is part of the group
                if "=" not in candidate and flag_arity[flag] and index < len(argv) and argv[index] != "--metric":
                    group.append(argv[index])
                    index += 1
                continue
            group.append(candidate)
            index += 1
        groups.append(group)
    return residual, groups


def run_print(
    metric_specs: List[List[str]],
    output: str | None,
    target: SshTarget | None = None,
) -> int:
    metrics = build_metrics(metric_specs)

    executor = get_executor(target)
    results: List[MetricResult] = [executor.collect(metric) for metric in metrics]
    snapshot = Snapshot(results)
    text = snapshot.as_text()

    if output:
        Path(output).write_text(text + "\n")
    else:
        print(text)

    return 0


def run_metric_man(name: str) -> int:
    """Print the documentation (``man``) for a collector or a metric.

    A bare collector name (e.g. ``voip``) prints the collector man; a metric
    full name (e.g. ``voip-contacts``) prints the metric man. Resolution errors
    raise ``ValueError`` from the repository and are reported by ``main``.
    """
    man: str = CollectorRepository.generate_man(name)
    print(man)
    return 0


def run_debug_metric(
    metric_name: str,
    arguments: List[str],
    target: SshTarget | None = None,
) -> int:
    """Show, without running anything, the command layers for a metric.

    Prints the bare metric command and — when ``--target`` is given — the
    PATH-prefixed command the remote shell would run and the full ssh wrapper
    sonitor would invoke locally.
    """
    metric = build_metrics([[metric_name, *arguments]])[0]
    bare = metric.mount_shell_command()

    print(f"metric command : {bare}")
    if target is None:
        print("execution      : local (no --target; runs as-is, no ssh/PATH wrapper)")
        return 0
    print(f"remote command : {target.remote_command(bare)}")
    print(f"ssh wrapper    : {target.wrap(bare)}")
    return 0


def _metric_specs_to_dicts(metric_specs: List[List[str]]) -> List[Dict]:
    """Validate metric specs against the repository and shape them for storage."""
    metric_dicts: List[Dict] = []
    for spec in metric_specs:
        CollectorRepository.resolve(spec[0])  # raises ValueError on unknown metric
        entry: Dict = {"name": spec[0]}
        if len(spec) > 1:
            entry["args"] = spec[1:]
        metric_dicts.append(entry)
    return metric_dicts


def run_routine_create(
    period: str,
    metric_specs: List[List[str]],
    name: str | None,
    annotation: str | None,
    log_size: int | None,
    target_spec: str | None = None,
    identity: str | None = None,
    ssh_options: List[str] | None = None,
    log_to: List[str] | None = None,
) -> int:
    parse_period(period)  # validate early with a friendly error
    metrics = _metric_specs_to_dicts(metric_specs)
    target = _build_target(target_spec, identity, ssh_options)

    parts = ["routine", "create", period]
    if name:
        parts += ["--name", name]
    if annotation:
        parts += ["--annotation", annotation]
    if log_size:
        parts += ["--log-size", str(log_size)]
    for path in log_to or []:
        parts += ["--log-to", path]
    if target_spec:
        parts += ["--target", target_spec]
    if identity:
        parts += ["--identity", identity]
    for option in ssh_options or []:
        parts += ["--ssh-option", option]
    for spec in metric_specs:
        parts += ["--metric", *spec]

    routine = store.create(
        period=period,
        metrics=metrics,
        name=name or "",
        annotation=annotation or "",
        log_size=log_size,
        spawn_command=" ".join(parts),
        target=target,
        log_to=log_to,
    )
    print(f"created routine {routine.uuid}" + (f" (name {routine.name})" if routine.name else ""))
    return 0


def run_routine_list(scheduler_name: str | None = None) -> int:
    routines = store.list_routines()
    if not routines:
        print("no routines")
        return 0

    enabled = set(get_scheduler(scheduler_name).list_enabled())

    print(f"{'UUID':<32}  {'NAME':<12}  {'PERIOD':<7}  {'STATE':<8}  LAST_RUN")
    for routine in routines:
        last_run = routine.last_run_at.strftime("%Y-%m-%d %H:%M:%SZ")
        state = "enabled" if routine.uuid in enabled else "disabled"
        print(
            f"{routine.uuid:<32}  {routine.name or '-':<12}  "
            f"{routine.period:<7}  {state:<8}  {last_run}"
        )
    return 0


def run_routine_show(target: str) -> int:
    routine = store.resolve(target)
    routine_path = store.path_for(routine.uuid)

    print(f"# {routine_path}")
    print(routine_path.read_text().rstrip())
    for log in runner.log_paths(routine):
        print()
        print(f"# {log}")
        log_text = log.read_text().rstrip() if log.exists() else ""
        print(log_text if log_text else "(no log yet)")
    return 0


def run_routine_reschedule(target: str, period: str, scheduler_name: str | None) -> int:
    parse_period(period)  # validate early with a friendly error
    routine = store.resolve(target)
    old_period = routine.period
    routine.period = period
    store.save(routine)

    message = f"rescheduled routine {routine.uuid} from {old_period} to {period}"

    scheduler = get_scheduler(scheduler_name)
    if scheduler.is_enabled(routine):
        scheduler.enable(routine)  # re-apply so the schedule reflects the new period
        message += f"; reapplied {scheduler.name} schedule"

    print(message)
    return 0


def run_routine_run(target: str) -> int:
    routine = store.resolve(target)
    paths = runner.run_once(routine)
    print(f"ran routine {routine.uuid} -> {', '.join(str(path) for path in paths)}")
    return 0


def run_routine_reset(target: str) -> int:
    routine = store.resolve(target)
    runner.reset(routine)
    print(f"reset log for routine {routine.uuid}")
    return 0


def run_routine_delete(target: str, scheduler_name: str | None) -> int:
    routine = store.resolve(target)
    get_scheduler(scheduler_name).disable(routine)  # drop any dangling schedule
    store.delete(routine)
    print(f"deleted routine {routine.uuid}")
    return 0


def run_routine_purge(target: str, scheduler_name: str | None) -> int:
    routine = store.resolve(target)
    get_scheduler(scheduler_name).disable(routine)  # drop any dangling schedule
    for path in runner.log_paths(routine):  # clear: remove the log files
        path.unlink(missing_ok=True)
    store.delete(routine)  # delete: remove the .sonitor
    print(f"purged routine {routine.uuid} (log and .sonitor removed)")
    return 0


def run_routine_enable(target: str, scheduler_name: str | None) -> int:
    routine = store.resolve(target)
    scheduler = get_scheduler(scheduler_name)
    scheduler.enable(routine)
    print(f"enabled routine {routine.uuid} via {scheduler.name} scheduler")
    return 0


def run_routine_disable(target: str, scheduler_name: str | None) -> int:
    routine = store.resolve(target)
    scheduler = get_scheduler(scheduler_name)
    scheduler.disable(routine)
    print(f"disabled routine {routine.uuid} via {scheduler.name} scheduler")
    return 0


def run_remote_setup(destination: str, name: str, no_privileges: bool, force: bool) -> int:
    target = provision.run_setup(destination, name, no_privileges=no_privileges, force=force)
    print(f"registered target '{name}' -> {target.target.destination}")
    print(f"  identity: {target.target.identity_file}")
    print(f"  manifest on host: /home/{provision.REMOTE_USER} (README.md, version.toml, hosts.toml, uninstall.sh)")
    print(f"  try: sonitor print --target {name} --metric sys-uptime")
    return 0


def run_remote_list() -> int:
    targets = remote_store.list_targets()
    if not targets:
        print("no targets")
        return 0

    print(f"{'NAME':<16}  {'DESTINATION':<28}  IDENTITY")
    for entry in targets:
        dest = entry.target.destination + (f":{entry.target.port}" if entry.target.port else "")
        print(f"{entry.name:<16}  {dest:<28}  {entry.target.identity_file or '-'}")
    return 0


def run_remote_forget(name: str, keep_key: bool) -> int:
    entry = remote_store.resolve(name)  # raises ValueError if unknown
    remote_store.delete(name)
    if not keep_key and entry.target.identity_file:
        provision.delete_key_files(entry.target.identity_file)
    print(f"forgot target '{name}'" + ("" if keep_key else " and its key"))
    print(
        "note: the 'sonitor' user on the remote host was left in place — "
        "use 'sonitor remote teardown' to remove it on the host too."
    )
    return 0


def run_remote_teardown(target: str, bootstrap_user: str) -> int:
    entry = provision.run_teardown(target, bootstrap_user=bootstrap_user)
    if entry:
        dest = entry.target.host + (f":{entry.target.port}" if entry.target.port else "")
        print(f"tore down the '{provision.REMOTE_USER}' user on {dest}")
        print(
            f"note: target '{entry.name}' is still registered locally — use 'sonitor remote forget' "
            "to drop it, or 'sonitor remote purge' to tear down and forget in one step."
        )
    else:
        print(f"tore down the '{provision.REMOTE_USER}' user on {target}")
    return 0


def run_remote_purge(name: str, bootstrap_user: str, keep_key: bool) -> int:
    provision.run_purge(name, bootstrap_user=bootstrap_user, keep_key=keep_key)
    tail = "" if keep_key else " and deleted its key"
    print(f"purged target '{name}': removed the '{provision.REMOTE_USER}' user on its host{tail}")
    return 0


def run_remote_check(name: str) -> int:
    result = provision.run_check(name)
    entry = result.entry
    dest = entry.target.destination + (f":{entry.target.port}" if entry.target.port else "")
    if result.status == provision.CHECK_OK:
        print(f"ok: target '{name}' is reachable at {dest} (provision v{result.remote_version})")
        return 0
    if result.status == provision.CHECK_OUTDATED:
        print(
            f"outdated: target '{name}' at {dest} was provisioned with v{result.remote_version}, "
            f"but this sonitor expects v{result.expected_version}.\n"
            f"  re-provision with: sonitor remote setup <DEST> --name {name} --force"
        )
        return 0
    if result.status == provision.CHECK_UNMANAGED:
        print(
            f"unmanaged: target '{name}' is reachable at {dest} but has no manifest "
            "(provisioned by an older sonitor).\n"
            f"  re-provision with: sonitor remote setup <DEST> --name {name} --force"
        )
        return 0
    print(f"error: target '{name}' is unreachable at {dest}: {result.detail}", file=sys.stderr)
    return 1


def run_remote_rename(current: str, new: str) -> int:
    renamed = provision.rename_target(current, new)
    print(f"renamed target '{current}' -> '{new}'")
    print(f"  destination: {renamed.target.destination}")
    print(f"  identity: {renamed.target.identity_file or '-'}")
    return 0


_CHECK_LABELS = {
    provision.CHECK_OK: "ok",
    provision.CHECK_OUTDATED: "OUTDATED",
    provision.CHECK_UNMANAGED: "UNMANAGED",
    provision.CHECK_UNREACHABLE: "UNREACHABLE",
}


def _target_status_line(audit: remote_audit.TargetAudit, checked: bool) -> str:
    """One-line health summary for a target: key-pair integrity, then reachability."""
    if audit.no_identity:
        return "no SSH key on record"

    problems: List[str] = []
    if audit.missing_private:
        problems.append(f"private key missing ({audit.entry.target.identity_file})")
    if audit.missing_public:
        problems.append("public key (.pub) missing")
    if problems:
        return "; ".join(problems)

    if not checked:
        return "key ok (connectivity not checked)"

    check = audit.check
    label = _CHECK_LABELS.get(check.status, check.status)
    if check.status == provision.CHECK_OK:
        return f"ok — reachable, provision v{check.remote_version}"
    if check.status == provision.CHECK_OUTDATED:
        return f"{label} — provisioned v{check.remote_version}, expected v{check.expected_version}"
    if check.status == provision.CHECK_UNMANAGED:
        return f"{label} — reachable but no manifest (legacy provisioning)"
    return f"{label} — {check.detail}"


def run_audit(no_check: bool = False, prune_keys: bool = False) -> int:
    """Audit the local remote registry, SSH keys and routines; optionally prune unused keys."""
    report = remote_audit.run_audit(do_check=not no_check)
    checked = not no_check

    if report.targets:
        print(f"Registered targets ({len(report.targets)}):")
        for audit in report.targets:
            marker = "  " if not audit.has_issue else "! "
            print(f"  {marker}{audit.name:<16}  {_target_status_line(audit, checked)}")
    else:
        print("Registered targets: none")

    if report.unreadable_targets:
        print(f"\nUnreadable target files ({len(report.unreadable_targets)}):")
        for path in report.unreadable_targets:
            print(f"  ! {path}")

    if report.orphan_keys or report.lone_public_keys:
        total = len(report.orphan_keys) + len(report.lone_public_keys)
        print(f"\nUnused SSH keys ({total}):")
        for orphan in report.orphan_keys:
            suffix = " (+ .pub)" if orphan.public else " (no .pub)"
            print(f"  ! {orphan.private.name}{suffix}")
        for public in report.lone_public_keys:
            print(f"  ! {public.name} (orphaned .pub, private key gone)")
        if not prune_keys:
            print("  → delete them with: sonitor audit --prune-keys")

    if report.routine_issues:
        print(f"\nRoutine problems ({len(report.routine_issues)}):")
        for issue in report.routine_issues:
            ref = issue.name or issue.uuid
            print(f"  ! {ref}: {issue.detail}")

    remaining = report.issue_count
    if prune_keys and (report.orphan_keys or report.lone_public_keys):
        removed = remote_audit.prune_orphan_keys(report)
        print(f"\npruned {len(removed)} unused key file group(s).")
        remaining -= len(report.orphan_keys) + len(report.lone_public_keys)

    print()
    if remaining == 0:
        print("audit: clean — no inconsistencies found.")
        return 0
    print(f"audit: {remaining} issue(s) found.")
    return 1


def _add_ssh_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the agentless SSH target flags shared by `print` and `routine create`."""
    parser.add_argument(
        "--target",
        metavar="[USER@]HOST[:PORT]",
        help="Run the metrics on this host over SSH instead of locally (agentless).",
    )
    parser.add_argument(
        "--identity",
        metavar="PATH",
        help="SSH identity (private key) file, passed as ssh -i (requires --target).",
    )
    parser.add_argument(
        "--ssh-option",
        action="append",
        metavar="KEY=VALUE",
        dest="ssh_options",
        help="Extra ssh -o option, e.g. --ssh-option StrictHostKeyChecking=accept-new. Repeatable.",
    )


def _add_all_argument(parser: argparse.ArgumentParser, *, noun: str) -> None:
    """Add the reusable `--all` modifier that targets every stored ``noun``."""
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_targets",
        help=f"Apply to every stored {noun} (mutually exclusive with the positional target).",
    )


def _add_yes_argument(parser: argparse.ArgumentParser) -> None:
    """Add `--yes`, which skips the confirmation prompt for bulk destructive operations."""
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the confirmation prompt for bulk destructive operations (--all).",
    )


def _select_identifiers(
    target: str | None,
    all_targets: bool,
    list_fn,
    id_attr: str,
) -> List[str]:
    """Resolve which identifiers a command acts on: one explicit target, or every stored one."""
    if all_targets:
        if target:
            raise ValueError("--all cannot be combined with an explicit target.")
        return [getattr(item, id_attr) for item in list_fn()]
    if not target:
        raise ValueError("a target is required (or pass --all to apply to every target).")
    return [target]


def _confirm_bulk(verb: str, noun: str, count: int) -> bool:
    answer = input(f"{verb} all {count} {noun}(s)? type 'yes' to proceed: ")
    return answer.strip().lower() == "yes"


def _run_over_targets(
    args: argparse.Namespace,
    *,
    list_fn,
    id_attr: str,
    run_one,
    verb: str,
    noun: str,
    destructive: bool,
) -> int:
    """Run ``run_one`` for each selected identifier, confirming destructive `--all` first."""
    identifiers = _select_identifiers(args.target, args.all_targets, list_fn, id_attr)
    if not identifiers:  # --all but nothing stored
        print(f"no {noun}s")
        return 0
    if args.all_targets and destructive and not getattr(args, "yes", False):
        if not _confirm_bulk(verb, noun, len(identifiers)):
            print("aborted")
            return 1
    exit_code = 0
    for identifier in identifiers:
        exit_code |= run_one(identifier)
    return exit_code


def _add_routine_parser(subparsers: argparse._SubParsersAction) -> None:
    routine_parser = subparsers.add_parser(
        "routine", help="Create, run and schedule recurring metric routines."
    )
    actions = routine_parser.add_subparsers(dest="action", required=True)

    create = actions.add_parser("create", help="Create a routine.")
    create.add_argument("period", help="Recurrence period, e.g. 30s, 5m, 12h, 1d.")
    create.add_argument(
        "--name",
        metavar="NAME",
        help="Unique name to reference the routine (must not already exist).",
    )
    create.add_argument(
        "--annotation",
        metavar="TEXT",
        help="Free-text note stored in the .sonitor file.",
    )
    create.add_argument(
        "--log-size",
        type=int,
        metavar="N",
        help="Keep only the last N iteration blocks in the log.",
    )
    create.add_argument(
        "--log-to",
        action="append",
        dest="log_to",
        metavar="PATH",
        help="Full path of a file to write the log to. Repeatable; "
             "defaults to the storage logs dir when omitted.",
    )
    create.add_argument(
        "--metric",
        action="append",
        nargs="+",
        required=False,  # extracted from argv before argparse (see _extract_metric_groups)
        metavar=("NAME", "ARG"),
        dest="metrics",
        help="Metric name followed by its arguments and flags. Repeatable.",
    )
    _add_ssh_arguments(create)

    list_action = actions.add_parser("list", help="List stored routines.")
    list_action.add_argument(
        "--scheduler",
        metavar="NAME",
        help="Scheduler to query for enabled state (defaults to DEFAULT_SCHEDULER).",
    )

    for verb, helptext, destructive in (
        ("show", "Print a routine's .sonitor file and its log.", False),
        ("run", "Run a routine once now.", False),
        ("reset", "Clear a routine's log.", True),
    ):
        action = actions.add_parser(verb, help=helptext)
        action.add_argument("target", nargs="?", metavar="UUID|NAME", help="Routine uuid or name.")
        _add_all_argument(action, noun="routine")
        if destructive:
            _add_yes_argument(action)

    reschedule = actions.add_parser(
        "reschedule", help="Change a routine's period (re-applies the schedule if enabled)."
    )
    reschedule.add_argument("target", nargs="?", metavar="UUID|NAME", help="Routine uuid or name.")
    reschedule.add_argument("period", help="New recurrence period, e.g. 30s, 5m, 12h, 1d.")
    reschedule.add_argument(
        "--scheduler",
        metavar="NAME",
        help="Scheduler to use (defaults to DEFAULT_SCHEDULER).",
    )
    _add_all_argument(reschedule, noun="routine")

    for verb, helptext, destructive in (
        ("enable", "Schedule a routine for recurring execution.", False),
        ("disable", "Unschedule a routine.", False),
        ("delete", "Unschedule and remove a routine's .sonitor file (keeps its log).", True),
        ("purge", "Unschedule and remove a routine's .sonitor file and its log.", True),
    ):
        action = actions.add_parser(verb, help=helptext)
        action.add_argument("target", nargs="?", metavar="UUID|NAME", help="Routine uuid or name.")
        action.add_argument(
            "--scheduler",
            metavar="NAME",
            help="Scheduler to use (defaults to DEFAULT_SCHEDULER).",
        )
        _add_all_argument(action, noun="routine")
        if destructive:
            _add_yes_argument(action)


def _add_remote_parser(subparsers: argparse._SubParsersAction) -> None:
    remote_parser = subparsers.add_parser(
        "remote", help="Set up and manage remote SSH targets for agentless collection."
    )
    actions = remote_parser.add_subparsers(dest="action", required=True)

    setup = actions.add_parser(
        "setup",
        help="Provision a remote host (create the sonitor user + SSH key) and register it by name.",
    )
    setup.add_argument(
        "destination",
        metavar="[USER@]HOST[:PORT]",
        help="Privileged destination used once to provision (ssh asks for the password).",
    )
    setup.add_argument("--name", required=True, metavar="NAME", help="Name to register the target under.")
    setup.add_argument(
        "--no-privileges",
        action="store_true",
        help="Skip wiring metric privileges (asterisk group) on the target.",
    )
    setup.add_argument(
        "--force",
        action="store_true",
        help="Regenerate the SSH key even if one already exists for this name.",
    )

    actions.add_parser("list", help="List registered targets.")

    check = actions.add_parser(
        "check",
        help="Verify a registered target still connects over SSH (as agentless collection would).",
    )
    check.add_argument("target", nargs="?", metavar="NAME", help="Registered target name.")
    _add_all_argument(check, noun="target")

    rename = actions.add_parser(
        "rename", help="Rename a registered target (and its local SSH key files)."
    )
    rename.add_argument("current", metavar="CURRENT", help="Existing target name.")
    rename.add_argument("new", metavar="NEW", help="New target name.")

    forget = actions.add_parser("forget", help="Forget a registered target locally (and delete its key).")
    forget.add_argument("target", nargs="?", metavar="NAME", help="Registered target name.")
    forget.add_argument(
        "--keep-key",
        action="store_true",
        help="Keep the local SSH key files instead of deleting them.",
    )
    _add_all_argument(forget, noun="target")
    _add_yes_argument(forget)

    teardown = actions.add_parser(
        "teardown",
        help="Remove the sonitor user on a target's host, by registered name or explicit destination (keeps the local registration).",
    )
    teardown.add_argument(
        "target",
        nargs="?",
        metavar="NAME | [USER@]HOST[:PORT]",
        help="Registered target name, or an explicit privileged destination to tear down.",
    )
    teardown.add_argument(
        "--bootstrap-user",
        default="root",
        metavar="USER",
        help="Privileged user to connect as when TARGET is a registered name "
        "(default: root; ssh asks for the password; ignored for an explicit destination).",
    )
    _add_all_argument(teardown, noun="target")
    _add_yes_argument(teardown)

    purge = actions.add_parser(
        "purge",
        help="Tear down a registered target on its host (by name) and forget it locally.",
    )
    purge.add_argument("target", nargs="?", metavar="NAME", help="Registered target name.")
    purge.add_argument(
        "--bootstrap-user",
        default="root",
        metavar="USER",
        help="Privileged user to connect as for the teardown (default: root; ssh asks for the password).",
    )
    purge.add_argument(
        "--keep-key",
        action="store_true",
        help="Keep the local SSH key files instead of deleting them.",
    )
    _add_all_argument(purge, noun="target")
    _add_yes_argument(purge)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sonitor",
        description="Collect and log server metrics from Linux systems and networks.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"sonitor {__version__}",
        help="Show the sonitor version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    print_parser = subparsers.add_parser(
        "print", help="Single-shot snapshot to stdout or a file."
    )
    print_parser.add_argument(
        "--metric",
        action="append",
        nargs="+",
        required=False,  # extracted from argv before argparse (see _extract_metric_groups)
        metavar=("NAME", "ARG"),
        dest="metrics",
        help="Metric name followed by its arguments and flags. Repeatable.",
    )
    print_parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the snapshot to a file instead of stdout.",
    )
    _add_ssh_arguments(print_parser)

    metric_parser = subparsers.add_parser(
        "metric", help="Show the documentation (man) for a collector or a metric."
    )
    metric_parser.add_argument(
        "metric",
        metavar="COLLECTOR|METRIC",
        help="Collector name (e.g. voip) or metric name (e.g. net-public-ip).",
    )

    _add_routine_parser(subparsers)
    _add_remote_parser(subparsers)
    _add_audit_parser(subparsers)
    _add_debug_parser(subparsers)

    return parser


def _add_audit_parser(subparsers: argparse._SubParsersAction) -> None:
    audit_parser = subparsers.add_parser(
        "audit",
        help="Check every registered target and flag unused SSH keys or stale registry records.",
    )
    audit_parser.add_argument(
        "--no-check",
        action="store_true",
        help="Skip the per-target SSH connectivity check (offline, registry/key hygiene only).",
    )
    audit_parser.add_argument(
        "--prune-keys",
        action="store_true",
        help="Delete the unused SSH keys the audit finds (orphaned private keys and lone .pub files).",
    )


def _add_debug_parser(subparsers: argparse._SubParsersAction) -> None:
    debug_parser = subparsers.add_parser(
        "debug", help="Inspect what sonitor would run, without executing it."
    )
    actions = debug_parser.add_subparsers(dest="action", required=True)

    metric = actions.add_parser(
        "metric",
        help="Show the command layers (metric command, remote command, ssh wrapper) for a metric.",
    )
    metric.add_argument("metric", metavar="METRIC", help="Metric name, e.g. voip-contacts.")
    metric.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        metavar="ARG",
        help="Arguments forwarded to the metric (everything after METRIC).",
    )
    _add_ssh_arguments(metric)


def _dispatch_remote(args: argparse.Namespace) -> int:
    if args.action == "setup":
        return run_remote_setup(args.destination, args.name, args.no_privileges, args.force)
    if args.action == "list":
        return run_remote_list()
    if args.action == "check":
        return _run_over_targets(
            args, list_fn=remote_store.list_targets, id_attr="name",
            run_one=lambda name: run_remote_check(name),
            verb="check", noun="target", destructive=False)
    if args.action == "rename":
        return run_remote_rename(args.current, args.new)
    if args.action == "forget":
        return _run_over_targets(
            args, list_fn=remote_store.list_targets, id_attr="name",
            run_one=lambda name: run_remote_forget(name, args.keep_key),
            verb="forget", noun="target", destructive=True)
    if args.action == "teardown":
        return _run_over_targets(
            args, list_fn=remote_store.list_targets, id_attr="name",
            run_one=lambda name: run_remote_teardown(name, args.bootstrap_user),
            verb="teardown", noun="target", destructive=True)
    if args.action == "purge":
        return _run_over_targets(
            args, list_fn=remote_store.list_targets, id_attr="name",
            run_one=lambda name: run_remote_purge(name, args.bootstrap_user, args.keep_key),
            verb="purge", noun="target", destructive=True)
    raise ValueError(f"unknown remote action: {args.action}")


def _dispatch_debug(args: argparse.Namespace) -> int:
    if args.action == "metric":
        target = _build_target(args.target, args.identity, args.ssh_options)
        return run_debug_metric(args.metric, args.arguments, target)
    raise ValueError(f"unknown debug action: {args.action}")


def _dispatch_routine(args: argparse.Namespace) -> int:
    if args.action == "create":
        return run_routine_create(
            args.period, args.metrics, args.name, args.annotation, args.log_size,
            args.target, args.identity, args.ssh_options, args.log_to,
        )
    if args.action == "list":
        return run_routine_list(args.scheduler)
    if args.action == "show":
        return _run_over_targets(
            args, list_fn=store.list_routines, id_attr="uuid",
            run_one=lambda target: run_routine_show(target),
            verb="show", noun="routine", destructive=False)
    if args.action == "reschedule":
        return _run_over_targets(
            args, list_fn=store.list_routines, id_attr="uuid",
            run_one=lambda target: run_routine_reschedule(target, args.period, args.scheduler),
            verb="reschedule", noun="routine", destructive=False)
    if args.action == "run":
        return _run_over_targets(
            args, list_fn=store.list_routines, id_attr="uuid",
            run_one=lambda target: run_routine_run(target),
            verb="run", noun="routine", destructive=False)
    if args.action == "reset":
        return _run_over_targets(
            args, list_fn=store.list_routines, id_attr="uuid",
            run_one=lambda target: run_routine_reset(target),
            verb="reset", noun="routine", destructive=True)
    if args.action == "enable":
        return _run_over_targets(
            args, list_fn=store.list_routines, id_attr="uuid",
            run_one=lambda target: run_routine_enable(target, args.scheduler),
            verb="enable", noun="routine", destructive=False)
    if args.action == "disable":
        return _run_over_targets(
            args, list_fn=store.list_routines, id_attr="uuid",
            run_one=lambda target: run_routine_disable(target, args.scheduler),
            verb="disable", noun="routine", destructive=False)
    if args.action == "delete":
        return _run_over_targets(
            args, list_fn=store.list_routines, id_attr="uuid",
            run_one=lambda target: run_routine_delete(target, args.scheduler),
            verb="delete", noun="routine", destructive=True)
    if args.action == "purge":
        return _run_over_targets(
            args, list_fn=store.list_routines, id_attr="uuid",
            run_one=lambda target: run_routine_purge(target, args.scheduler),
            verb="purge", noun="routine", destructive=True)
    raise ValueError(f"unknown routine action: {args.action}")


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)

    try:
        # Pull metric groups (name + its own args/flags) out of argv before
        # argparse so per-metric dashed flags are not rejected as unknown options.
        residual, metric_groups = _extract_metric_groups(raw_argv)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    args = parser.parse_args(residual)

    # The --metric option is kept in argparse only for --help; the real groups
    # come from the pre-pass. Attach them to the commands that consume metrics.
    uses_metrics = args.command == "print" or (
        args.command == "routine" and getattr(args, "action", None) == "create"
    )
    if uses_metrics:
        if not metric_groups:
            parser.error("the following arguments are required: --metric")
        args.metrics = metric_groups

    try:
        if args.command == "print":
            target = _build_target(args.target, args.identity, args.ssh_options)
            return run_print(args.metrics, args.output, target)
        if args.command == "metric":
            return run_metric_man(args.metric)
        if args.command == "routine":
            return _dispatch_routine(args)
        if args.command == "remote":
            return _dispatch_remote(args)
        if args.command == "audit":
            return run_audit(args.no_check, args.prune_keys)
        if args.command == "debug":
            return _dispatch_debug(args)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except NotImplementedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
