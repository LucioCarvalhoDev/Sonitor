from __future__ import annotations

from typing import Optional, Union

from app.execution.shell_executor import ShellExecutor, RemoteShellExecutor
from app.execution.target import SshTarget

__all__ = ["ShellExecutor", "RemoteShellExecutor", "SshTarget", "get_executor"]


def get_executor(target: Union[SshTarget, str, None] = None) -> ShellExecutor:
    """Return the executor for a target: local when ``None``, remote otherwise.

    ``target`` may be an :class:`SshTarget` or a ``[user@]host[:port]`` string.
    """
    if target is None:
        return ShellExecutor()
    if isinstance(target, str):
        target = SshTarget.parse(target)
    return RemoteShellExecutor(target)
