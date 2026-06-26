import pytest

from app.collectors import CollectorRepository


def _command(fullname, args=None):
    return CollectorRepository.resolve(fullname)(args or []).mount_shell_command()


def test_voip_metrics_resolve_to_expected_commands():
    assert _command("voip-channels-count") == 'asterisk -rx "core show channels count"'
    assert _command("voip-channels") == 'asterisk -rx "pjsip show channels"'
    assert _command("voip-channelstats") == 'asterisk -rx "pjsip show channelstats"'
    assert _command("voip-contacts") == 'asterisk -rx "pjsip show contacts"'


def test_voip_contacts_optional_grep_filter():
    # no argument: the bare asterisk command
    assert _command("voip-contacts") == 'asterisk -rx "pjsip show contacts"'
    # an argument is passed straight through to a grep filter
    assert _command("voip-contacts", ["2020@"]) == 'asterisk -rx "pjsip show contacts" | grep 2020@'
    assert _command("voip-contacts", ["sip", "2020"]) == 'asterisk -rx "pjsip show contacts" | grep sip 2020'


def test_unknown_metric_raises():
    with pytest.raises(ValueError):
        CollectorRepository.resolve("voip-nope")


def test_sys_metrics_resolve_to_expected_commands():
    assert _command("sys-uptime") == "uptime"
    assert _command("sys-storage") == "df -BM"
    assert _command("sys-memory") == "free -m"
    assert _command("sys-services") == "systemctl --failed"


def test_net_metrics_resolve_to_expected_commands():
    assert _command("net-ip") == "ip -brief address"
    assert _command("net-connections") == "ss -s; ss -tunp"
    assert _command("net-listening") == "ss -tlnp"
    assert _command("net-route") == "ip route"


def test_net_http_requires_url():
    with pytest.raises(ValueError):
        _command("net-http")
    command = _command("net-http", ["https://example.com"])
    assert command.startswith("curl -s -o /dev/null -w ")
    assert command.endswith(" https://example.com")
    assert "%{http_code}" in command and "%{time_total}" in command


def test_sys_top_flags():
    assert _command("sys-top") == "top -bn1"
    assert _command("sys-top", ["--head", "5"]) == "top -bn1 | head -n 5"
    assert _command("sys-top", ["--tail", "3"]) == "top -bn1 | tail -n 3"
    # head is applied before tail, regardless of flag order
    assert _command("sys-top", ["--tail", "3", "--head", "5"]) == "top -bn1 | head -n 5 | tail -n 3"


def test_sys_top_rejects_unknown_flag():
    with pytest.raises(ValueError):
        _command("sys-top", ["--bogus", "1"])
