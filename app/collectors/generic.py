from datetime import timedelta
from typing import Dict

class Metric():
    name: str = "_"

    def __init__(self, arguments: list[str]=[]) -> None:
        self.executions = 0
        self.arguments = arguments
    
    def to_str(self) -> str:
        return f"[Metric {self.name}: {self.arguments}]"
    
    def mount_shell_command(self) -> str:
        return self._mount_shell_command(self.arguments)

    def _mount_shell_command(self, arguments: str|None=None) -> str:
        return f"echo {arguments}"

class MetricResult():
    def __init__(
            self, name: str, command: str, response: str,
            started_at=float,
            finished_at=float) -> None:
        self.name = name
        self.command = command
        self.response = response
        self.started_at: float = started_at
        self.finished_at: float = finished_at
    
    def get_delta(self):
        return timedelta(seconds=(self.finished_at - self.started_at))
    
    def _as_prompt(self, command: str, response: str) -> str:
        return f"$ {command}\n{response}"
    
    def as_prompt(self) -> str:
        return self._as_prompt(self.command, self.response)

class Collector():
    base_name = "_"

    metrics: Dict[str, type[Metric]] = {}
    
    @staticmethod
    def _prefix_metrics(prefix: str, metrics: list[type[Metric]]) -> Dict[str, type[Metric]]:
        return {
            f"{prefix}-{metric.name}": metric for metric in metrics
        }

    @classmethod
    def get_metric(cls, request: str) -> type[Metric]:
        for fullname, metric in cls.metrics.items():
            if request == fullname:
                return metric
        
        raise ValueError(f"[Collector {cls.base_name}]: Given '{request}' does not resolve to a valid metric.")