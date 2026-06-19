from datetime import datetime, timezone

import pytest

from app.execution.target import SshTarget
from app.routines import runner, store
from app.routines.model import Routine, parse_period


def test_parse_period_valid():
    assert parse_period("30s") == 30
    assert parse_period("5m") == 300
    assert parse_period("12h") == 12 * 3600
    assert parse_period("1d") == 86400


@pytest.mark.parametrize("bad", ["", "5", "5x", "m5", "-1m", "0s", "abc"])
def test_parse_period_invalid(bad):
    with pytest.raises(ValueError):
        parse_period(bad)


def test_routine_toml_round_trip():
    when = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)
    routine = Routine(
        uuid="deadbeef",
        period="12h",
        metrics=[{"name": "sys-storage"}, {"name": "net-ping", "args": ["8.8.8.8", "1.1.1.1"]}],
        name="smoke",
        annotation="nightly smoke check",
        spawn_command="routine create 12h --metric sys-storage",
        log_max_lines=500,
        created_at=when,
        last_run_at=when,
    )

    restored = Routine.from_toml(routine.to_toml(), uuid="deadbeef")
    assert restored == routine


def test_routine_toml_round_trip_with_ssh_target():
    when = datetime(2026, 5, 18, 12, 0, 0, tzinfo=timezone.utc)
    routine = Routine(
        uuid="deadbeef",
        period="12h",
        metrics=[{"name": "voip-channels-count"}],
        target=SshTarget.parse("root@10.0.0.5:2222", options=["StrictHostKeyChecking=accept-new"]),
        created_at=when,
        last_run_at=when,
    )

    restored = Routine.from_toml(routine.to_toml(), uuid="deadbeef")
    assert restored == routine
    assert restored.target.destination == "root@10.0.0.5"


def test_routine_without_target_has_no_ssh_table():
    routine = Routine(uuid="x", period="5m", metrics=[{"name": "sys-uptime"}])
    assert "[ssh]" not in routine.to_toml()
    assert Routine.from_toml(routine.to_toml(), uuid="x").target is None


def test_create_and_resolve_by_uuid_and_name():
    routine = store.create("5m", [{"name": "sys-storage"}], name="smoke")
    assert store.resolve(routine.uuid).uuid == routine.uuid
    assert store.resolve("smoke").uuid == routine.uuid


def test_resolve_unknown_raises():
    with pytest.raises(ValueError):
        store.resolve("does-not-exist")


def test_create_rejects_duplicate_name():
    store.create("5m", [{"name": "sys-storage"}], name="dup")
    with pytest.raises(ValueError):
        store.create("1h", [{"name": "sys-uptime"}], name="dup")


def test_annotation_round_trips_through_store():
    routine = store.create("5m", [{"name": "sys-storage"}], name="noted", annotation="watch disk")
    assert store.resolve("noted").annotation == "watch disk"


def test_log_rotation_keeps_last_n_blocks():
    routine = store.create("1m", [{"name": "sys-storage"}], name="rot", log_size=3)
    for _ in range(5):
        path = runner.run_once(routine)

    content = path.read_text()
    headers = [line for line in content.splitlines() if line.startswith("--- ")]
    assert len(headers) == 3
    # Newest preserved: iterations should be the last three (3, 4, 5).
    assert "Iteration 005" in content
    assert "Iteration 001" not in content


def test_reset_clears_log():
    routine = store.create("1m", [{"name": "sys-storage"}])
    path = runner.run_once(routine)
    assert path.read_text().strip() != ""

    runner.reset(routine)
    assert path.read_text() == ""
