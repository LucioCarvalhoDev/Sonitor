from types import SimpleNamespace

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
    rc = cli.main(["debug", "metric", "voip-contacts", "-i", "2020@"])
    out = capsys.readouterr().out

    assert rc == 0
    assert 'metric command : asterisk -rx "pjsip show contacts" | grep -i 2020@' in out


def test_debug_metric_unknown_metric_errors(capsys):
    rc = cli.main(["debug", "metric", "voip-nope"])

    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_debug_metric_forwards_metric_flags(capsys):
    # debug uses REMAINDER, so a metric's own flags reach the metric
    rc = cli.main(["debug", "metric", "sys-top", "--head", "5"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "metric command : top -bn1 | head -n 5" in out


# --- per-metric flag extraction (_extract_metric_groups) --------------------

def test_extract_metric_groups_captures_metric_flags():
    residual, groups = cli._extract_metric_groups(
        ["print", "--metric", "sys-top", "--head", "5"]
    )
    assert groups == [["sys-top", "--head", "5"]]
    assert residual == ["print"]


def test_extract_metric_groups_splits_multiple_metrics():
    residual, groups = cli._extract_metric_groups(
        ["print", "--metric", "net-ping", "8.8.8.8", "--metric", "sys-top", "--tail", "2"]
    )
    assert groups == [["net-ping", "8.8.8.8"], ["sys-top", "--tail", "2"]]
    assert residual == ["print"]


def test_extract_metric_groups_sibling_option_ends_group():
    # --output is a print option, not a sys-top flag, so it stops the group
    residual, groups = cli._extract_metric_groups(
        ["print", "--metric", "sys-top", "--head", "5", "--output", "snap.txt"]
    )
    assert groups == [["sys-top", "--head", "5"]]
    assert residual == ["print", "--output", "snap.txt"]


def test_extract_metric_groups_equals_flag_form():
    _residual, groups = cli._extract_metric_groups(
        ["print", "--metric", "sys-top", "--head=5"]
    )
    assert groups == [["sys-top", "--head=5"]]


def test_extract_metric_groups_unknown_metric_stops_at_dashes():
    # unknown metric -> no known flags -> dashed token ends the group
    _residual, groups = cli._extract_metric_groups(
        ["print", "--metric", "sys-nope", "--head", "5"]
    )
    assert groups == [["sys-nope"]]


def test_extract_metric_groups_requires_a_name():
    with pytest.raises(ValueError):
        cli._extract_metric_groups(["print", "--metric"])


def test_print_requires_at_least_one_metric():
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["print"])
    assert excinfo.value.code == 2


# --- reusable --all modifier ------------------------------------------------

def _items(*names):
    return [SimpleNamespace(name=name) for name in names]


def test_select_identifiers_single_target():
    assert cli._select_identifiers("r1", False, lambda: _items("a", "b"), "name") == ["r1"]


def test_select_identifiers_all_expands_to_every_id():
    assert cli._select_identifiers(None, True, lambda: _items("a", "b"), "name") == ["a", "b"]


def test_select_identifiers_all_with_target_is_an_error():
    with pytest.raises(ValueError, match="--all cannot be combined"):
        cli._select_identifiers("r1", True, lambda: _items("a"), "name")


def test_select_identifiers_neither_target_nor_all_is_an_error():
    with pytest.raises(ValueError, match="a target is required"):
        cli._select_identifiers(None, False, lambda: _items("a"), "name")


def _run(target=None, all_targets=False, yes=False, *, items, destructive, run_one):
    args = SimpleNamespace(target=target, all_targets=all_targets, yes=yes)
    return cli._run_over_targets(
        args, list_fn=lambda: _items(*items), id_attr="name",
        run_one=run_one, verb="purge", noun="routine", destructive=destructive,
    )


def test_run_over_targets_all_destructive_aborts_without_yes(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    called = []
    rc = _run(all_targets=True, items=("a", "b"), destructive=True, run_one=lambda i: called.append(i) or 0)

    assert rc == 1
    assert called == []  # nothing ran
    assert "aborted" in capsys.readouterr().out


def test_run_over_targets_all_destructive_runs_on_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    called = []
    rc = _run(all_targets=True, items=("a", "b"), destructive=True, run_one=lambda i: called.append(i) or 0)

    assert rc == 0
    assert called == ["a", "b"]


def test_run_over_targets_yes_flag_skips_prompt(monkeypatch):
    def _boom(_prompt):
        raise AssertionError("input() must not be called when --yes is set")

    monkeypatch.setattr("builtins.input", _boom)
    called = []
    rc = _run(all_targets=True, yes=True, items=("a", "b"), destructive=True,
              run_one=lambda i: called.append(i) or 0)

    assert rc == 0
    assert called == ["a", "b"]


def test_run_over_targets_empty_store_is_a_noop(capsys):
    called = []
    rc = _run(all_targets=True, items=(), destructive=True, run_one=lambda i: called.append(i) or 0)

    assert rc == 0
    assert called == []
    assert "no routines" in capsys.readouterr().out


def test_run_over_targets_or_combines_exit_codes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    rc = _run(all_targets=True, items=("a", "b"), destructive=True, run_one=lambda i: 1 if i == "b" else 0)

    assert rc == 1
