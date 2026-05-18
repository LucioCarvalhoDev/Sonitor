from typing import Dict, Any
from datetime import datetime, timezone, timedelta
import subprocess
from subprocess import CompletedProcess
import re

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

class Metric():
    name: str = "_"

    def __init__(self, arguments: str) -> None:
        self.executions = 0
        self.arguments = arguments
    
    def collect(self) -> MetricResult:
        command = self._mount_shell_command(self.arguments)
        started_at: int = datetime.now(timezone.utc).timestamp()
        response = self.run()
        finished_at: int = datetime.now(timezone.utc).timestamp()

        metric_result = MetricResult(
            name=self.name,
            command=command,
            response=response,
            started_at=started_at,
            finished_at=finished_at)
        
        return metric_result
    
    def to_str(self) -> str:
        return f"[Metric {self.name}: {self.arguments}]"

    def _mount_shell_command(self, arguments: str) -> str:
        return f"echo {arguments}"

    def _execute_shell_command(self, command: str) -> str:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True
        )
        return result

    def _run(self, argument: str) -> str:
        return self._parse_shell_result_to_text(self._execute_shell_command(self._mount_shell_command(argument)))

    def run(self) -> str:
        return self._run(self.arguments)


    def _parse_shell_result_to_text(self, completed_process: CompletedProcess[str]) -> str:
        return completed_process.stderr if completed_process.stderr else completed_process.stdout

class PingMetric(Metric):
    name = "ping"

    def __init__(self, address: str) -> None:
        super().__init__(address)

    def _mount_shell_command(self, arguments: str) -> str:
        return f"ping {arguments} -c 5"

class DnsMetric(Metric):
    name = "dns"

    def _mount_shell_command(self, arguments: str) -> str:
        return f"nslookup {arguments}"

class PublicIPMetric(Metric):
    name = "public-ip"
    
    def _mount_shell_command(self, arguments: str) -> str:
        return f"curl -4 -s ifconfig.me"

class Collector():
    base_name = "_"

    _metrics: Dict[str, Metric] = {}

    def __init__(self) -> None:
        self.metrics: Dict[str, Metric] = {}

        for name in self._metrics:
            self.metrics[f"{self.base_name}-{name}"] = self._metrics[name]


    def _parse(self, metric_name: str, arguments: str|None = None) -> str:
        if metric_name not in self.metrics:
            raise ValueError(f"Metric '{metric_name}' not found.")
        
        metric = self.metrics[metric_name](arguments)
        return metric
        
        

class NetCollector(Collector):
    base_name = "net"

    _metrics: Dict[str, Metric] = {
        "dns": DnsMetric,
        "ping": PingMetric,
        "public-ip": PublicIPMetric
    }



INPUT = "net-ping 127.0.0.1"