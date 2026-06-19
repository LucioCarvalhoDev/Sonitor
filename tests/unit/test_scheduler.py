import pytest

from app import cli
from app.routines import store
from app.routines.model import Routine
from app.scheduler import CronScheduler, InprocScheduler, get_scheduler
from app.scheduler.cron import period_to_cron


def test_period_to_cron_mappings():
    assert period_to_cron("5m") == "*/5 * * * *"
    assert period_to_cron("12h") == "0 */12 * * *"
    assert period_to_cron("1d") == "0 0 */1 * *"


@pytest.mark.parametrize("bad", ["30s", "1s", "0m", "60m", "24h", "32d", "bogus"])
def test_period_to_cron_rejects(bad):
    with pytest.raises(ValueError):
        period_to_cron(bad)


def test_get_scheduler_default_and_override():
    assert isinstance(get_scheduler(), CronScheduler)
    assert isinstance(get_scheduler("cron"), CronScheduler)
    assert isinstance(get_scheduler("inproc"), InprocScheduler)


def test_get_scheduler_unknown_raises():
    with pytest.raises(ValueError):
        get_scheduler("nope")


def test_inproc_is_not_implemented():
    with pytest.raises(NotImplementedError):
        get_scheduler("inproc").enable(Routine(uuid="x", period="5m"))


@pytest.fixture
def fake_crontab(monkeypatch):
    """In-memory crontab so CronScheduler never touches the real one."""
    state = {"lines": []}
    monkeypatch.setattr(CronScheduler, "_read_crontab", staticmethod(lambda: list(state["lines"])))
    monkeypatch.setattr(
        CronScheduler, "_write_crontab", staticmethod(lambda lines: state.__setitem__("lines", list(lines)))
    )
    return state


def test_cron_enable_disable_round_trip(fake_crontab):
    scheduler = CronScheduler()
    routine = Routine(uuid="abc123", period="5m")

    scheduler.enable(routine)
    assert scheduler.is_enabled(routine)
    assert scheduler.list_enabled() == ["abc123"]
    assert any("*/5 * * * *" in line for line in fake_crontab["lines"])
    assert any("routine run abc123" in line for line in fake_crontab["lines"])

    scheduler.disable(routine)
    assert not scheduler.is_enabled(routine)
    assert fake_crontab["lines"] == []


def test_reschedule_updates_period_without_scheduling(fake_crontab):
    routine = store.create("30s", [{"name": "sys-uptime"}], name="short")

    assert cli.run_routine_reschedule("short", "1m", "cron") == 0

    assert store.resolve("short").period == "1m"
    assert fake_crontab["lines"] == []  # was never enabled


def test_reschedule_reapplies_schedule_when_enabled(fake_crontab):
    routine = store.create("1m", [{"name": "sys-uptime"}], name="short")
    CronScheduler().enable(routine)

    assert cli.run_routine_reschedule("short", "5m", "cron") == 0

    assert store.resolve("short").period == "5m"
    assert any("*/5 * * * *" in line for line in fake_crontab["lines"])
    assert not any("*/1 * * * *" in line for line in fake_crontab["lines"])


def test_reschedule_invalid_period_raises(fake_crontab):
    store.create("1m", [{"name": "sys-uptime"}], name="short")

    with pytest.raises(ValueError):
        cli.run_routine_reschedule("short", "5x", "cron")


def test_cron_enable_preserves_foreign_lines_and_replaces_dupes(fake_crontab):
    fake_crontab["lines"] = ["# other tool", "0 0 * * * /usr/bin/backup"]
    scheduler = CronScheduler()
    routine = Routine(uuid="abc123", period="1h")

    scheduler.enable(routine)
    scheduler.enable(routine)  # enabling twice must not duplicate the entry

    assert scheduler.list_enabled() == ["abc123"]
    assert "# other tool" in fake_crontab["lines"]
    assert "0 0 * * * /usr/bin/backup" in fake_crontab["lines"]
