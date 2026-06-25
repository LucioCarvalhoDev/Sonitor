from typing import Dict, Any
from app.collectors.generic import Metric
from app.collectors.generic import Collector

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
        "and usage percentage. Useful to spot disks that are running full."
    )
    shell = "df"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()
    
    def _mount_shell_command(self) -> str:
        return f"df"

class TopMetric(Metric):
    name = "top"
    description = (
        "Take a single snapshot of running processes ordered by resource "
        "usage, plus a summary of CPU and memory utilization."
    )
    shell = "top -bn1"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

    def _mount_shell_command(self):
        return f"top -bn1"


METRICS: list[type[Metric]] = [UptimeMetric, StorageMetric, TopMetric]

class SystemCollector(Collector):
    base_name = "sys"
    description = "Host system health metrics: uptime, storage and processes."

    metrics: Dict[str, type[Metric]] = Collector._prefix_metrics(base_name, METRICS)