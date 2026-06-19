from subprocess import CompletedProcess

import pytest

import app.execution.shell_executor as shell_executor
from app.collectors import CollectorRepository
from app.execution import get_executor
from app.execution.shell_executor import RemoteShellExecutor, ShellExecutor
from app.execution.target import SshTarget


def test_parse_user_host_port():
    target = SshTarget.parse("root@pbx:2222")
    assert target.user == "root"
    assert target.host == "pbx"
    assert target.port == 2222
    assert target.destination == "root@pbx"


def test_parse_bare_host_has_no_user_or_port():
    target = SshTarget.parse("pbx.example.com")
    assert target.user is None
    assert target.port is None
    assert target.destination == "pbx.example.com"


@pytest.mark.parametrize("bad", ["", "   ", "@host", "host:abc"])
def test_parse_invalid(bad):
    with pytest.raises(ValueError):
        SshTarget.parse(bad)


def test_wrap_single_quotes_the_remote_command():
    target = SshTarget.parse("root@10.0.0.5")
    wrapped = target.wrap('asterisk -rx "core show channels count"')
    assert wrapped == (
        "ssh -o BatchMode=yes -o ConnectTimeout=10 root@10.0.0.5 "
        "'asterisk -rx \"core show channels count\"'"
    )


def test_wrap_includes_port_identity_and_options():
    target = SshTarget.parse(
        "admin@pbx:2222", identity_file="/keys/id", options=["StrictHostKeyChecking=accept-new"]
    )
    wrapped = target.wrap("df")
    assert "-p 2222" in wrapped
    assert "-i /keys/id" in wrapped
    assert "-o StrictHostKeyChecking=accept-new" in wrapped
    assert wrapped.endswith("admin@pbx df")


def test_target_dict_round_trip():
    target = SshTarget.parse("root@pbx:2222", identity_file="/keys/id", options=["X=y"])
    assert SshTarget.from_dict(target.to_dict()) == target


def test_get_executor_selects_local_or_remote():
    assert isinstance(get_executor(None), ShellExecutor)
    assert not isinstance(get_executor(None), RemoteShellExecutor)
    assert isinstance(get_executor("root@host"), RemoteShellExecutor)
    assert isinstance(get_executor(SshTarget.parse("root@host")), RemoteShellExecutor)


def test_remote_collect_runs_ssh_but_keeps_command_clean(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return CompletedProcess(args=command, returncode=0, stdout="4 active channels\n", stderr="")

    monkeypatch.setattr(shell_executor, "run", fake_run)

    executor = get_executor("root@10.0.0.5")
    metric = CollectorRepository.resolve("voip-channels-count")([])
    result = executor.collect(metric)

    assert captured["command"].startswith("ssh ")
    # The snapshot records the bare metric command, not the ssh wrapper.
    assert result.command == 'asterisk -rx "core show channels count"'
    assert result.response.strip() == "4 active channels"
