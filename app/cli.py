import argparse
import sys
from pathlib import Path
from typing import Dict, List

from app.collectors import CollectorRepository, Metric, MetricResult, Snapshot
from app.execution.shell_executor import ShellExecutor
from app.routines import runner, store
from app.routines.model import parse_period
from app.scheduler import get_scheduler


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


def run_print(metric_specs: List[List[str]], output: str | None) -> int:
    metrics = build_metrics(metric_specs)

    results: List[MetricResult] = [ShellExecutor.collect(metric) for metric in metrics]
    snapshot = Snapshot(results)
    text = snapshot.as_text()

    if output:
        Path(output).write_text(text + "\n")
    else:
        print(text)

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
) -> int:
    parse_period(period)  # validate early with a friendly error
    metrics = _metric_specs_to_dicts(metric_specs)

    parts = ["routine", "create", period]
    if name:
        parts += ["--name", name]
    if annotation:
        parts += ["--annotation", annotation]
    if log_size:
        parts += ["--log-size", str(log_size)]
    for spec in metric_specs:
        parts += ["--metric", *spec]

    routine = store.create(
        period=period,
        metrics=metrics,
        name=name or "",
        annotation=annotation or "",
        log_size=log_size,
        spawn_command=" ".join(parts),
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
    log = runner.log_path(routine)

    print(f"# {routine_path}")
    print(routine_path.read_text().rstrip())
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
    path = runner.run_once(routine)
    print(f"ran routine {routine.uuid} -> {path}")
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
    runner.log_path(routine).unlink(missing_ok=True)  # clear: remove the log
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
        "--metric",
        action="append",
        nargs="+",
        required=True,
        metavar=("NAME", "ARG"),
        dest="metrics",
        help="Metric name followed by its arguments. Repeatable.",
    )

    list_action = actions.add_parser("list", help="List stored routines.")
    list_action.add_argument(
        "--scheduler",
        metavar="NAME",
        help="Scheduler to query for enabled state (defaults to DEFAULT_SCHEDULER).",
    )

    for verb, helptext in (
        ("show", "Print a routine's .sonitor file and its log."),
        ("run", "Run a routine once now."),
        ("reset", "Clear a routine's log."),
    ):
        action = actions.add_parser(verb, help=helptext)
        action.add_argument("target", metavar="UUID|NAME", help="Routine uuid or name.")

    reschedule = actions.add_parser(
        "reschedule", help="Change a routine's period (re-applies the schedule if enabled)."
    )
    reschedule.add_argument("target", metavar="UUID|NAME", help="Routine uuid or name.")
    reschedule.add_argument("period", help="New recurrence period, e.g. 30s, 5m, 12h, 1d.")
    reschedule.add_argument(
        "--scheduler",
        metavar="NAME",
        help="Scheduler to use (defaults to DEFAULT_SCHEDULER).",
    )

    for verb, helptext in (
        ("enable", "Schedule a routine for recurring execution."),
        ("disable", "Unschedule a routine."),
        ("delete", "Unschedule and remove a routine's .sonitor file (keeps its log)."),
        ("purge", "Unschedule and remove a routine's .sonitor file and its log."),
    ):
        action = actions.add_parser(verb, help=helptext)
        action.add_argument("target", metavar="UUID|NAME", help="Routine uuid or name.")
        action.add_argument(
            "--scheduler",
            metavar="NAME",
            help="Scheduler to use (defaults to DEFAULT_SCHEDULER).",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sonitor",
        description="Collect and log server metrics from Linux systems and networks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    print_parser = subparsers.add_parser(
        "print", help="Single-shot snapshot to stdout or a file."
    )
    print_parser.add_argument(
        "--metric",
        action="append",
        nargs="+",
        required=True,
        metavar=("NAME", "ARG"),
        dest="metrics",
        help="Metric name followed by its arguments. Repeatable.",
    )
    print_parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write the snapshot to a file instead of stdout.",
    )

    _add_routine_parser(subparsers)

    return parser


def _dispatch_routine(args: argparse.Namespace) -> int:
    if args.action == "create":
        return run_routine_create(
            args.period, args.metrics, args.name, args.annotation, args.log_size
        )
    if args.action == "list":
        return run_routine_list(args.scheduler)
    if args.action == "show":
        return run_routine_show(args.target)
    if args.action == "reschedule":
        return run_routine_reschedule(args.target, args.period, args.scheduler)
    if args.action == "run":
        return run_routine_run(args.target)
    if args.action == "reset":
        return run_routine_reset(args.target)
    if args.action == "enable":
        return run_routine_enable(args.target, args.scheduler)
    if args.action == "disable":
        return run_routine_disable(args.target, args.scheduler)
    if args.action == "delete":
        return run_routine_delete(args.target, args.scheduler)
    if args.action == "purge":
        return run_routine_purge(args.target, args.scheduler)
    raise ValueError(f"unknown routine action: {args.action}")


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "print":
            return run_print(args.metrics, args.output)
        if args.command == "routine":
            return _dispatch_routine(args)
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
