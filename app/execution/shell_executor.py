from app.collectors import Metric, MetricResult
from subprocess import run, CompletedProcess
from datetime import datetime, timezone

class ShellExecutor():

    @classmethod
    def collect(cls, metric: type[Metric]) -> MetricResult:
        command = cls.shell_command(metric)
        started_at: int = datetime.now(timezone.utc).timestamp()
        response = cls._parse_shell_result_to_text(cls.execute_shell_command(command))
        finished_at: int = datetime.now(timezone.utc).timestamp()

        metric_result = MetricResult(
            name=metric.name,
            command=command,
            response=response,
            started_at=started_at,
            finished_at=finished_at)
        
        return metric_result

    @staticmethod
    def shell_command(metric: type[Metric]) -> str:
        return metric.mount_shell_command()

    @staticmethod
    def execute_shell_command(command: str) -> CompletedProcess[str]:
        result = run(
            command,
            shell=True,
            capture_output=True,
            text=True
        )

        return result
    
    @classmethod
    def run_metric(cls, metric: type[Metric]) -> str:
        return cls._parse_shell_result_to_text(cls.execute_shell_command(cls.shell_command(metric)))


    @staticmethod
    def _parse_shell_result_to_text(completed_process: CompletedProcess[str]) -> str:
        return completed_process.stderr if completed_process.stderr else completed_process.stdout