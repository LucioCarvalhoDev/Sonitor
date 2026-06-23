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


def test_voip_sip_joins_sngrep_arguments():
    assert _command("voip-sip", ["-N -q -O /tmp/c.pcap"]) == "sngrep -N -q -O /tmp/c.pcap"
    assert _command("voip-sip", ["-N", "-q", "dst", "host", "10.0.0.1"]) == "sngrep -N -q dst host 10.0.0.1"


def test_voip_sip_requires_arguments():
    with pytest.raises(ValueError):
        _command("voip-sip")


def test_unknown_metric_raises():
    with pytest.raises(ValueError):
        CollectorRepository.resolve("voip-nope")
