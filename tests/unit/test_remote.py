from subprocess import CompletedProcess

import pytest

from app.execution.target import SshTarget
from app.remote import provision
from app.remote import store
from app.remote.model import Target


# --- store ---------------------------------------------------------------

def _make(name="pbx01", host="server.net", user="sonitor", port=None, identity="/abs/ssh/id_deadbeef"):
    return Target(name=name, target=SshTarget(host=host, user=user, port=port, identity_file=identity))


def test_store_round_trip_and_list():
    target = _make()
    store.save(target)

    assert store.exists("pbx01")
    restored = store.resolve("pbx01")
    assert restored.name == "pbx01"
    assert restored.target == target.target
    assert [t.name for t in store.list_targets()] == ["pbx01"]


def test_resolve_unknown_raises():
    with pytest.raises(ValueError):
        store.resolve("nope")


def test_delete_removes_file():
    store.save(_make())
    store.delete("pbx01")
    assert not store.exists("pbx01")


@pytest.mark.parametrize("bad", ["", "has space", "a/b", "../etc", "name!"])
def test_validate_name_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        store.validate_name(bad)


# --- resolve_spec --------------------------------------------------------

def test_resolve_spec_uses_registered_target():
    store.save(_make(host="server.net", port=2222))
    resolved = store.resolve_spec("pbx01")
    assert resolved.destination == "sonitor@server.net"
    assert resolved.port == 2222


def test_resolve_spec_parses_raw_spec_when_not_registered():
    resolved = store.resolve_spec("root@10.0.0.5:22")
    assert resolved.user == "root"
    assert resolved.host == "10.0.0.5"
    assert resolved.port == 22


def test_resolve_spec_rejects_flags_with_registered_name():
    store.save(_make())
    with pytest.raises(ValueError):
        store.resolve_spec("pbx01", identity="/k")


# --- rename --------------------------------------------------------------

def test_rename_moves_registry_entry_and_keeps_key_path():
    priv = provision.key_path("deadbeef")
    priv.parent.mkdir(parents=True, exist_ok=True)
    priv.write_text("PRIVATE")

    store.save(_make(name="pbx01", identity=str(priv)))

    renamed = provision.rename_target("pbx01", "pbx02")

    assert not store.exists("pbx01")
    assert store.exists("pbx02")
    assert renamed.name == "pbx02"

    # the key file is named by UUID, so it stays put and the target keeps pointing at it
    assert renamed.target.identity_file == str(priv)
    assert priv.read_text() == "PRIVATE"
    assert store.resolve("pbx02").target.identity_file == str(priv)


def test_rename_preserves_created_at():
    store.save(_make())
    original = store.resolve("pbx01").created_at
    renamed = provision.rename_target("pbx01", "pbx02")
    assert renamed.created_at == original


def test_rename_unknown_current_raises():
    with pytest.raises(ValueError):
        provision.rename_target("missing", "whatever")


def test_rename_rejects_existing_new_name():
    store.save(_make(name="a"))
    store.save(_make(name="b"))
    with pytest.raises(ValueError):
        provision.rename_target("a", "b")


def test_rename_rejects_invalid_new_name():
    store.save(_make())
    with pytest.raises(ValueError):
        provision.rename_target("pbx01", "bad name")


# --- remote provisioning script -----------------------------------------

def test_build_remote_script_contains_key_user_and_guards():
    script = provision.build_remote_script("ssh-ed25519 AAAAPUB sonitor@demo")
    assert "ssh-ed25519 AAAAPUB sonitor@demo" in script
    assert "useradd" in script
    assert "passwd -l" in script
    assert "authorized_keys" in script
    assert "command -v restorecon" in script
    assert "asterisk" in script
    assert "setcap cap_net_raw" in script


def test_build_remote_script_no_privileges_skips_setcap():
    script = provision.build_remote_script("ssh-ed25519 AAAAPUB sonitor@demo", no_privileges=True)
    assert "setcap" not in script
    assert "usermod -aG asterisk" not in script


# --- run_setup (ssh + keygen mocked) -------------------------------------

def test_run_setup_provisions_verifies_and_registers(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(provision, "run", fake_run)
    monkeypatch.setattr(
        provision, "generate_keypair", lambda comment=None: ("/abs/ssh/id_deadbeef", "ssh-ed25519 AAAA demo")
    )

    result = provision.run_setup("root@server.net:2222", "demo")

    assert result.name == "demo"
    assert result.target.user == "sonitor"
    assert result.target.host == "server.net"
    assert result.target.port == 2222
    assert result.target.identity_file == "/abs/ssh/id_deadbeef"

    # registered and persisted
    assert store.exists("demo")
    assert store.resolve("demo").target == result.target

    # two ssh invocations: interactive provisioning, then key-auth verification
    assert len(calls) == 2
    assert calls[0][0] == "ssh" and "-t" in calls[0]
    assert "root@server.net" in calls[0]
    assert "-i" in calls[1] and "/abs/ssh/id_deadbeef" in calls[1]
    assert calls[1][-1] == "true"


def test_run_setup_reuses_key_when_target_already_registered(monkeypatch):
    # an already-registered target with a real key file on disk
    priv = provision.key_path("cafe")
    priv.parent.mkdir(parents=True, exist_ok=True)
    priv.write_text("PRIV")
    priv.with_name(priv.name + ".pub").write_text("ssh-ed25519 REUSED demo")
    store.save(_make(name="demo", host="server.net", identity=str(priv)))

    def boom(*args, **kwargs):  # generate_keypair must not be called on reuse
        raise AssertionError("generate_keypair should not run when reusing a key")

    monkeypatch.setattr(provision, "generate_keypair", boom)
    monkeypatch.setattr(
        provision, "run", lambda argv, **kw: CompletedProcess(args=argv, returncode=0, stdout="", stderr="")
    )

    result = provision.run_setup("root@server.net", "demo")
    assert result.target.identity_file == str(priv)


# --- teardown script -----------------------------------------------------

def test_build_teardown_script_removes_user_and_reverts_caps():
    script = provision.build_teardown_script()
    assert "userdel -r" in script
    assert "sonitor" in script
    assert "setcap -r" in script


def test_build_teardown_script_no_privileges_skips_setcap():
    script = provision.build_teardown_script(no_privileges=True)
    assert "userdel -r" in script
    assert "setcap" not in script


# --- run_teardown (ssh mocked) -------------------------------------------

def _registered_with_key(name="demo", host="server.net", port=None):
    priv = provision.key_path("feed")
    priv.parent.mkdir(parents=True, exist_ok=True)
    priv.write_text("PRIV")
    priv.with_name(priv.name + ".pub").write_text("ssh-ed25519 AAAA demo")
    store.save(_make(name=name, host=host, port=port, identity=str(priv)))
    return priv


def test_run_teardown_undoes_remote_only_and_keeps_registration(monkeypatch):
    priv = _registered_with_key(host="server.net", port=2222)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        # key-auth sanity check should fail (user gone); provisioning succeeds
        rc = 255 if "-i" in argv else 0
        return CompletedProcess(args=argv, returncode=rc, stdout="", stderr="")

    monkeypatch.setattr(provision, "run", fake_run)

    entry = provision.run_teardown("demo")

    assert entry is not None and entry.name == "demo"
    # remote-only: the registration and key are left in place
    assert store.exists("demo")
    assert priv.exists()
    assert priv.with_name(priv.name + ".pub").exists()

    # destination is derived from the registry: interactive ssh -t as root@host:port
    assert calls[0][0] == "ssh" and "-t" in calls[0]
    assert "root@server.net" in calls[0]
    assert "2222" in calls[0]
    # then the sanity check with the sonitor key
    assert any("-i" in c and str(priv) in c for c in calls)


def test_run_teardown_respects_bootstrap_user(monkeypatch):
    _registered_with_key(host="server.net")
    calls = []
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: calls.append(argv) or CompletedProcess(args=argv, returncode=0, stdout="", stderr=""),
    )

    provision.run_teardown("demo", bootstrap_user="admin")
    assert "admin@server.net" in calls[0]


def test_run_teardown_explicit_destination_skips_registry(monkeypatch):
    calls = []
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: calls.append(argv) or CompletedProcess(args=argv, returncode=0, stdout="", stderr=""),
    )

    # An unregistered value is treated as an explicit destination, used verbatim.
    result = provision.run_teardown("ops@other.net:2200")

    assert result is None
    # remote teardown ran against the given destination; no key-auth sanity check
    assert len(calls) == 1 and "-t" in calls[0]
    assert "ops@other.net" in calls[0]
    assert "2200" in calls[0]


def test_run_teardown_raises_when_remote_fails(monkeypatch):
    _registered_with_key()
    monkeypatch.setattr(
        provision, "run", lambda argv, **kw: CompletedProcess(args=argv, returncode=255, stdout="", stderr="boom")
    )

    with pytest.raises(RuntimeError):
        provision.run_teardown("demo")
    # local entry untouched on remote failure
    assert store.exists("demo")


# --- run_check (ssh mocked) ----------------------------------------------

def test_run_check_ok_when_ssh_succeeds(monkeypatch):
    priv = _registered_with_key(host="server.net", port=2222)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(provision, "run", fake_run)

    entry, ok, detail = provision.run_check("demo")

    assert ok is True
    assert detail == ""
    assert entry.name == "demo"
    # connects with the stored key as the sonitor user and runs a trivial command
    assert calls[0][0] == "ssh"
    assert "-i" in calls[0] and str(priv) in calls[0]
    assert "sonitor@server.net" in calls[0]
    assert "2222" in calls[0]
    assert calls[0][-1] == "true"


def test_run_check_fails_and_reports_detail(monkeypatch):
    _registered_with_key()
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: CompletedProcess(args=argv, returncode=255, stdout="", stderr="Connection refused"),
    )

    entry, ok, detail = provision.run_check("demo")

    assert ok is False
    assert detail == "Connection refused"
    assert entry.name == "demo"


def test_run_check_unknown_target_raises():
    with pytest.raises(ValueError):
        provision.run_check("ghost")


# --- run_purge (name-based teardown) -------------------------------------

def test_run_purge_derives_root_destination_and_forgets(monkeypatch):
    priv = _registered_with_key(host="server.net", port=2222)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        rc = 255 if "-i" in argv else 0  # key no longer authenticates
        return CompletedProcess(args=argv, returncode=rc, stdout="", stderr="")

    monkeypatch.setattr(provision, "run", fake_run)

    entry = provision.run_purge("demo")

    assert entry is not None and entry.name == "demo"
    assert not store.exists("demo")
    assert not priv.exists()
    # bootstrapped as root@<host>:<port> derived from the registry
    assert calls[0][0] == "ssh" and "-t" in calls[0]
    assert "root@server.net" in calls[0]
    assert "2222" in calls[0]


def test_run_purge_respects_bootstrap_user(monkeypatch):
    _registered_with_key(host="server.net")
    calls = []
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: calls.append(argv) or CompletedProcess(args=argv, returncode=0, stdout="", stderr=""),
    )

    provision.run_purge("demo", bootstrap_user="admin")
    assert "admin@server.net" in calls[0]


def test_run_purge_unknown_target_raises():
    with pytest.raises(ValueError):
        provision.run_purge("ghost")


def test_run_setup_raises_when_verification_fails(monkeypatch):
    def fake_run(argv, **kwargs):
        # provisioning ok, verification fails
        rc = 0 if "-t" in argv else 255
        return CompletedProcess(args=argv, returncode=rc, stdout="", stderr="Permission denied")

    monkeypatch.setattr(provision, "run", fake_run)
    monkeypatch.setattr(
        provision, "generate_keypair", lambda comment=None: ("/abs/ssh/id_deadbeef", "ssh-ed25519 AAAA demo")
    )

    with pytest.raises(RuntimeError):
        provision.run_setup("root@server.net", "demo")
