from typing import Dict
from datetime import datetime, timezone, timedelta

class MetricResult():
    def __init__(
            self, name: str, command: str, response: str, data: Dict[str, any],
            started_at=float,
            finished_at=float) -> None:
        self.name = name
        self.command = command
        self.response = response
        self.data = data
        self.started_at: float = started_at
        self.finished_at: float = finished_at
    
    def get_delta(self):
        return timedelta(milliseconds=(self.finished_at - self.started_at))
    
    def _as_prompt(self, command: str, response: str) -> str:
        return f"$ {command}\n{response}"
    
    def as_prompt(self) -> str:
        return self._as_prompt(self.command, self.response)

class Metric():
    name: str = "_"
    
    @classmethod
    def collect(cls) -> MetricResult:
        command = cls._mount_shell_command()
        started_at: int = datetime.now(timezone.utc).timestamp()
        response = cls._execute_shell_command(command)
        ended_at: int = datetime.utc(timezone.utc).timestamp()

        data = cls._parse_response_to_data(response)

        MetricResult.new(
            name=cls.name,
            command=command,
            response=response,
            data=data,
            started_at=started_at,
            ended_at=ended_at)
    
    def to_str(self) -> str:
        pass

    def _mount_shell_command(self) -> str:
        pass

    def _execute_shell_command(self, command: str) -> str:
        # stdout counts as a result
        pass

    def run(self) -> str:
        return self._run_shell_command(self._mount_shell_command())
    
    def _parse_response_to_data(self, response: str) -> str:
        pass



class PingMetric(Metric):
    name = "ping"

    def __init__(self, address: str) -> None:
        super().__init__()
        self.address = address

    def _mount_shell_command(self) -> str:
        return f"ping {self.address}"

class Snapshot():
    def __init__(self, iteration: int) -> None:
        self.started_at: float = datetime.now(timezone.utc).timestamp
        self.metrics: list[MetricResult] = []
        self.iteration = iteration
    
    def to_str(self) -> str:
        header :str = f"\n--- {self.started_at} - {datetime.fromtimestamp(self.started_at), timezone.utc} - Iteration {self.iteration} ---"
        content = "\n".join([ metric.as_prompt() for metric in self.metrics ])
        return header + content

    def append_metric(self, metric: MetricResult) -> None:
        self.metrics.append(metric)
        

class Collector():
    def __init__(self):
        self.metrics = {} # name x Metric
        pass

