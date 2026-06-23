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


def test_build_remote_script_writes_manifest_and_uninstall():
    script = provision.build_remote_script(
        "ssh-ed25519 AAAAPUB sonitor@demo",
        fingerprint="SHA256:abc",
        label="ctrl-01:pbx01",
        version="0.2.0",
        now="2026-06-23T00:00:00+00:00",
    )
    # version.toml + hosts.toml + README + uninstall.sh land in the home dir
    assert 'cat > "$H/version.toml"' in script
    assert 'version = "0.2.0"' in script
    assert 'cat > "$H/README.md"' in script
    assert 'cat > "$H/uninstall.sh"' in script
    assert "chmod 755" in script
    # this controller is recorded in hosts.toml, idempotently
    assert "[[controller]]" in script
    assert "SHA256:abc" in script
    assert "ctrl-01:pbx01" in script
    assert "grep -qF 'SHA256:abc'" in script
    # uninstall.sh embeds the full teardown body
    assert "userdel -r" in script


def test_build_remote_script_without_fingerprint_skips_controller_entry():
    script = provision.build_remote_script("ssh-ed25519 AAAAPUB sonitor@demo")
    # the manifest files are still written, but no controller entry without a key
    assert 'cat > "$H/version.toml"' in script
    assert "[[controller]]" not in script


# --- central version ------------------------------------------------------

def test_provision_version_is_the_central_app_version():
    from app.version import __version__

    assert provision.PROVISION_VERSION == __version__
    # a numeric MAJOR.MINOR.PATCH semver, so drift comparison can order it
    assert provision._version_tuple(__version__) >= (0, 1, 0)


# --- canonical manifest templates ----------------------------------------

def test_manifest_templates_exist():
    for name in ("README.md", "version.toml", "hosts.toml", "controller.toml", "uninstall.sh", "uninstall.privileges.sh"):
        assert (provision.MANIFEST_DIR / name).is_file(), f"missing manifest template: {name}"


def test_uninstall_template_drives_teardown_and_manifest():
    # the file dropped on the host and the pushed teardown are the same script
    body = provision.build_teardown_script()
    assert body == provision._render(
        provision._load_template("uninstall.sh"),
        USER=provision.REMOTE_USER,
        PRIVILEGES=provision._load_template("uninstall.privileges.sh"),
    )
    script = provision.build_remote_script("ssh-ed25519 K c@h", fingerprint="SHA256:x", label="c:p")
    assert body in script  # uninstall.sh content embedded verbatim in the setup script


# --- key_fingerprint -----------------------------------------------------

def test_key_fingerprint_extracts_sha256(monkeypatch):
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: CompletedProcess(
            args=argv, returncode=0, stdout="256 SHA256:abc123 sonitor@demo (ED25519)\n", stderr=""
        ),
    )
    assert provision.key_fingerprint("/abs/ssh/id_deadbeef.pub") == "SHA256:abc123"


def test_key_fingerprint_empty_on_failure(monkeypatch):
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: CompletedProcess(args=argv, returncode=1, stdout="", stderr="no such file"),
    )
    assert provision.key_fingerprint("/missing.pub") == ""


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
    monkeypatch.setattr(provision, "key_fingerprint", lambda path: "SHA256:test")

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
    monkeypatch.setattr(provision, "key_fingerprint", lambda path: "SHA256:test")
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
    teardown_call = next(c for c in calls if "-t" in c)
    assert teardown_call[0] == "ssh"
    assert "root@server.net" in teardown_call
    assert "2222" in teardown_call
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
    assert "admin@server.net" in next(c for c in calls if "-t" in c)


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

def _version_toml(version):
    return f'[provision]\nversion = "{version}"\nupdated_at = "2026-06-23T00:00:00+00:00"\n'


def test_run_check_ok_when_version_matches(monkeypatch):
    priv = _registered_with_key(host="server.net", port=2222)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return CompletedProcess(
            args=argv, returncode=0, stdout=_version_toml(provision.PROVISION_VERSION), stderr=""
        )

    monkeypatch.setattr(provision, "run", fake_run)

    result = provision.run_check("demo")

    assert result.status == provision.CHECK_OK
    assert result.reachable is True
    assert result.remote_version == provision.PROVISION_VERSION
    assert result.entry.name == "demo"
    # connects with the stored key as the sonitor user and reads the manifest
    assert calls[0][0] == "ssh"
    assert "-i" in calls[0] and str(priv) in calls[0]
    assert "sonitor@server.net" in calls[0]
    assert "2222" in calls[0]
    assert "version.toml" in calls[0][-1]


def test_run_check_outdated_when_version_older(monkeypatch):
    _registered_with_key()
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: CompletedProcess(
            args=argv, returncode=0, stdout=_version_toml("0.0.1"), stderr=""
        ),
    )

    result = provision.run_check("demo")

    assert result.status == provision.CHECK_OUTDATED
    assert result.reachable is True
    assert result.remote_version == "0.0.1"
    assert result.expected_version == provision.PROVISION_VERSION


def test_run_check_unmanaged_when_no_manifest(monkeypatch):
    _registered_with_key()
    # reachable, but the host has no version.toml (legacy provisioning)
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: CompletedProcess(args=argv, returncode=0, stdout="", stderr=""),
    )

    result = provision.run_check("demo")

    assert result.status == provision.CHECK_UNMANAGED
    assert result.reachable is True
    assert result.remote_version is None


def test_run_check_unreachable_and_reports_detail(monkeypatch):
    _registered_with_key()
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: CompletedProcess(args=argv, returncode=255, stdout="", stderr="Connection refused"),
    )

    result = provision.run_check("demo")

    assert result.status == provision.CHECK_UNREACHABLE
    assert result.reachable is False
    assert result.detail == "Connection refused"
    assert result.entry.name == "demo"


def test_run_check_unknown_target_raises():
    with pytest.raises(ValueError):
        provision.run_check("ghost")


# --- run_teardown multi-controller warning -------------------------------

_TWO_CONTROLLERS = (
    '# hosts\n\n'
    '[[controller]]\nfingerprint = "SHA256:a"\nlabel = "m1:demo"\n\n'
    '[[controller]]\nfingerprint = "SHA256:b"\nlabel = "m2:demo"\n'
)


def test_run_teardown_warns_when_multiple_controllers(monkeypatch, capsys):
    _registered_with_key(host="server.net")

    def fake_run(argv, **kwargs):
        if "hosts.toml" in (argv[-1] if argv else ""):
            return CompletedProcess(args=argv, returncode=0, stdout=_TWO_CONTROLLERS, stderr="")
        return CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(provision, "run", fake_run)

    provision.run_teardown("demo")

    err = capsys.readouterr().err
    assert "2 controllers" in err
    assert "m1:demo" in err and "m2:demo" in err


def test_run_teardown_no_warning_for_single_controller(monkeypatch, capsys):
    _registered_with_key(host="server.net")
    one = '# hosts\n\n[[controller]]\nfingerprint = "SHA256:a"\nlabel = "m1:demo"\n'

    def fake_run(argv, **kwargs):
        if "hosts.toml" in (argv[-1] if argv else ""):
            return CompletedProcess(args=argv, returncode=0, stdout=one, stderr="")
        return CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(provision, "run", fake_run)

    provision.run_teardown("demo")

    assert "controllers are registered" not in capsys.readouterr().err


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
    teardown_call = next(c for c in calls if "-t" in c)
    assert teardown_call[0] == "ssh"
    assert "root@server.net" in teardown_call
    assert "2222" in teardown_call


def test_run_purge_respects_bootstrap_user(monkeypatch):
    _registered_with_key(host="server.net")
    calls = []
    monkeypatch.setattr(
        provision,
        "run",
        lambda argv, **kw: calls.append(argv) or CompletedProcess(args=argv, returncode=0, stdout="", stderr=""),
    )

    provision.run_purge("demo", bootstrap_user="admin")
    assert "admin@server.net" in next(c for c in calls if "-t" in c)


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
