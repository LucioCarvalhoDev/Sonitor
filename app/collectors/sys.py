from typing import Dict, Any
from app.collectors.generic import Metric
from app.collectors.generic import Collector
from app.collectors.generic import _MetricArgParser

class UptimeMetric(Metric):
    name = "uptime"
    description = (
        "Report how long the host has been running, the number of logged-in "
        "users and the system load averages (1, 5 and 15 minutes)."
    )
    shell = "uptime"

    def _mount_shell_command(self) -> str:
        return f"uptime"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class StorageMetric(Metric):
    name = "storage"
    description = (
        "List mounted filesystems with their size, used and available space "
        "and usage percentage in MegaBytes. Useful to spot disks running full."
    )
    shell = "df -BM"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

    def _mount_shell_command(self) -> str:
        return f"df -BM"

class MemoryMetric(Metric):
    name = "memory"
    description = (
        "Report total, used, free and available RAM and swap, in MegaBytes. "
        "Useful to spot memory pressure and swap usage."
    )
    shell = "free -m"

    def _mount_shell_command(self) -> str:
        return f"free -m"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class ServicesMetric(Metric):
    name = "services"
    description = (
        "List the systemd units that are currently in a failed state. Useful "
        "to spot crashed or misconfigured services at a glance."
    )
    shell = "systemctl --failed"

    def _mount_shell_command(self) -> str:
        return f"systemctl --failed"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class TopMetric(Metric):
    name = "top"
    description = (
        "Take a single snapshot of running processes ordered by resource "
        "usage, plus a summary of CPU and memory utilization."
    )
    shell = "top -bn1 [| head -n N] [| tail -n N]"
    flags_doc = "--head N — keep only the first N lines; --tail N — keep the last N lines."

    @classmethod
    def arg_parser(cls):
        parser = _MetricArgParser(prog="sys-top", add_help=False)
        parser.add_argument("--head", type=int, metavar="N")
        parser.add_argument("--tail", type=int, metavar="N")
        return parser

    def mount_shell_command(self) -> str:
        options = self.arg_parser().parse_args(self.arguments)
        command = "top -bn1"
        if options.head:
            command += f" | head -n {options.head}"
        if options.tail:
            command += f" | tail -n {options.tail}"
        return command


METRICS: list[type[Metric]] = [UptimeMetric, StorageMetric, MemoryMetric, ServicesMetric, TopMetric]

class SystemCollector(Collector):
    base_name = "sys"
    description = "Host system health metrics: uptime, storage, memory, services and processes."

    metrics: Dict[str, type[Metric]] = Collector._prefix_metrics(base_name, METRICS)