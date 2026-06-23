import pytest

from app import cli
from app.version import __version__


def test_version_flag_prints_central_version_and_exits(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.strip() == f"sonitor {__version__}"


def test_missing_command_is_an_error():
    # subcommands are required; no command (and no --version) is a usage error
    with pytest.raises(SystemExit) as excinfo:
        cli.build_parser().parse_args([])

    assert excinfo.value.code == 2


def test_debug_metric_local_shows_only_the_bare_command(capsys):
    rc = cli.main(["debug", "metric", "voip-contacts", "2020@"])
    out = capsys.readouterr().out

    assert rc == 0
    assert 'metric command : asterisk -rx "pjsip show contacts" | grep 2020@' in out
    assert "local" in out
    # no remote/ssh layers without a target
    assert "remote command" not in out
    assert "ssh wrapper" not in out


def test_debug_metric_remote_shows_all_layers(capsys):
    rc = cli.main(["debug", "metric", "--target", "sonitor@pbx:2222", "voip-contacts", "2020@"])
    out = capsys.readouterr().out

    assert rc == 0
    lines = {line.split(":", 1)[0].strip(): line.split(":", 1)[1].strip() for line in out.splitlines()}
    assert lines["metric command"] == 'asterisk -rx "pjsip show contacts" | grep 2020@'
    # the server-side command carries the PATH prefix; the wrapper carries ssh
    assert lines["remote command"].startswith('PATH="')
    assert "/usr/sbin" in lines["remote command"]
    assert lines["ssh wrapper"].startswith("ssh ")
    assert "sonitor@pbx" in lines["ssh wrapper"] and "-p 2222" in lines["ssh wrapper"]


def test_debug_metric_forwards_dashed_arguments(capsys):
    rc = cli.main(["debug", "metric", "voip-sip", "-N", "-q", "-O", "/tmp/c.pcap"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "metric command : sngrep -N -q -O /tmp/c.pcap" in out


def test_debug_metric_unknown_metric_errors(capsys):
    rc = cli.main(["debug", "metric", "voip-nope"])

    assert rc == 1
    assert "error:" in capsys.readouterr().err
