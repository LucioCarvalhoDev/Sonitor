"""SSH target description for agentless (remote) metric collection.

A target lets sonitor run from one modern host and execute a metric's command
on another machine over SSH, so the monitored servers need no Python at all —
only a shell and the tools the metric calls (``df``, ``asterisk``…).
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Defaults aimed at unattended (cron) use: never block on a password/host-key
# prompt, and give up quickly when the host is unreachable.
DEFAULT_SSH_OPTIONS: List[str] = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

# sshd runs ``ssh host command`` in a *non-interactive* shell whose PATH is often
# minimal (no /sbin, /usr/sbin) and never picks up the user's dotfiles, so tools
# like ``asterisk`` or ``tcpdump`` end up "command not found" for the locked
# ``sonitor`` user. Prepend the standard system dirs to the remote command's PATH
# so it resolves the same binaries an admin would find on an interactive login.
REMOTE_PATH: str = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


@dataclass
class SshTarget:
    """Where and how to reach a remote host for command execution."""

    host: str
    user: Optional[str] = None
    port: Optional[int] = None
    identity_file: Optional[str] = None
    # Extra ``-o KEY=VALUE`` options, stored as the bare ``KEY=VALUE`` strings.
    options: List[str] = field(default_factory=list)

    @property
    def destination(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    @classmethod
    def parse(
        cls,
        spec: str,
        identity_file: Optional[str] = None,
        options: Optional[List[str]] = None,
    ) -> "SshTarget":
        """Parse a ``[user@]host[:port]`` spec into an :class:`SshTarget`.

        Raises ``ValueError`` with a friendly message on a malformed spec.
        """
        text = (spec or "").strip()
        if not text:
            raise ValueError("ssh target is empty; expected [user@]host[:port]")

        user: Optional[str] = None
        if "@" in text:
            user, text = text.split("@", 1)
            if not user:
                raise ValueError(f"invalid ssh target '{spec}': empty user before '@'")

        port: Optional[int] = None
        # rsplit so IPv4/hostnames with a trailing ":port" split correctly.
        if ":" in text:
            text, port_text = text.rsplit(":", 1)
            if not port_text.isdigit():
                raise ValueError(f"invalid ssh target '{spec}': port '{port_text}' is not a number")
            port = int(port_text)

        host = text.strip()
        if not host:
            raise ValueError(f"invalid ssh target '{spec}': missing host")

        return cls(
            host=host,
            user=user or None,
            port=port,
            identity_file=identity_file,
            options=list(options or []),
        )

    def ssh_argv_prefix(self) -> List[str]:
        """The ``ssh ...`` argv up to and including the destination."""
        argv: List[str] = ["ssh", *DEFAULT_SSH_OPTIONS]
        if self.port:
            argv += ["-p", str(self.port)]
        if self.identity_file:
            argv += ["-i", self.identity_file]
        for option in self.options:
            argv += ["-o", option]
        argv.append(self.destination)
        return argv

    def remote_command(self, command: str) -> str:
        """The command exactly as the remote shell runs it (before SSH wrapping).

        A :data:`REMOTE_PATH` prefix is prepended (then the remote ``$PATH``) so
        system tools in /sbin and /usr/sbin resolve under the non-interactive SSH
        shell, which has a minimal PATH and ignores dotfiles.
        """
        return f'PATH="{REMOTE_PATH}:$PATH" {command}'

    def wrap(self, command: str) -> str:
        """Wrap a local shell command so it runs on the remote host.

        Builds the full ``ssh ... '<remote command>'`` string. The remote command
        (see :meth:`remote_command`) is single-quoted so it reaches the remote
        shell intact (e.g. ``asterisk -rx "core show channels count"``); ``$PATH``
        stays literal locally and is expanded by the remote shell.
        """
        prefix = " ".join(shlex.quote(arg) for arg in self.ssh_argv_prefix())
        return f"{prefix} {shlex.quote(self.remote_command(command))}"

    def to_dict(self) -> Dict:
        """Serialize for the ``.sonitor`` ``[ssh]`` table (omitting empty fields)."""
        data: Dict = {"host": self.host}
        if self.user:
            data["user"] = self.user
        if self.port:
            data["port"] = self.port
        if self.identity_file:
            data["identity_file"] = self.identity_file
        if self.options:
            data["options"] = list(self.options)
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "SshTarget":
        return cls(
            host=data["host"],
            user=data.get("user") or None,
            port=data.get("port"),
            identity_file=data.get("identity_file") or None,
            options=list(data.get("options", [])),
        )
