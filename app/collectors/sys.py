from typing import Dict, Any
from app.collectors.generic import Metric
from app.collectors.generic import Collector

class UptimeMetric(Metric):
    name = "uptime"

    def __init__(self) -> None:
        pass

    def _mount_shell_command(self) -> str:
        return f"uptime"
    
    def mount_shell_command(self) -> str:
        return self._mount_shell_command()

class StorageMetric(Metric):
    name = "storage"

    def mount_shell_command(self) -> str:
        return self._mount_shell_command()
    
    def _mount_shell_command(self) -> str:
        return f"df"

class TopMetric(Metric):
    name = "top"

    def mount_shell_command(self) -> str:
        return self.mount_shell_command()

    def _mount_shell_command(self):
        return f"top"


METRICS: list[type[Metric]] = [UptimeMetric, StorageMetric, TopMetric]

class SystemCollector(Collector):
    base_name = "sys"

    metrics: Dict[str, type[Metric]] = Collector._prefix_metrics(base_name, METRICS)