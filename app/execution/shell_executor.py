from __future__ import annotations

from subprocess import run, CompletedProcess
from datetime import datetime, timezone

from app.collectors import Metric, MetricResult
from app.execution.target import SshTarget


class ShellExecutor():
    """Runs a metric's command on the local host via the shell."""

    def collect(self, metric: Metric) -> MetricResult:
        command = self.shell_command(metric)
        started_at: float = datetime.now(timezone.utc).timestamp()
        response = self._parse_shell_result_to_text(self.execute_shell_command(command))
        finished_at: float = datetime.now(timezone.utc).timestamp()

        metric_result = MetricResult(
            name=metric.name,
            command=command,
            response=response,
            started_at=started_at,
            finished_at=finished_at)

        return metric_result

    def shell_command(self, metric: Metric) -> str:
        return metric.mount_shell_command()

    def execute_shell_command(self, command: str) -> CompletedProcess:
        return run(
            command,
            shell=True,
            capture_output=True,
            text=True
        )

    def run_metric(self, metric: Metric) -> str:
        return self._parse_shell_result_to_text(self.execute_shell_command(self.shell_command(metric)))

    @staticmethod
    def _parse_shell_result_to_text(completed_process: CompletedProcess) -> str:
        return completed_process.stderr if completed_process.stderr else completed_process.stdout


class RemoteShellExecutor(ShellExecutor):
    """Runs a metric's command on a remote host over SSH (agentless).

    ``shell_command`` still returns the bare metric command, so snapshots read
    the same as a local run; only the actual execution is wrapped in ``ssh``.
    """

    def __init__(self, target: SshTarget) -> None:
        self.target = target

    def execute_shell_command(self, command: str) -> CompletedProcess:
        return run(
            self.target.wrap(command),
            shell=True,
            capture_output=True,
            text=True
        )
