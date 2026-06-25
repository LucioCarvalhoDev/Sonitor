from __future__ import annotations

import base64
import socket
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from subprocess import run
from typing import Optional, Tuple

import tomli

from app import settings
from app.execution.target import SshTarget
from app.remote import store
from app.remote.model import Target
from app.version import __version__

REMOTE_USER = "sonitor"

# The version a host is provisioned with is simply the project version (the single
# source of truth in ``app/version.py``). Each host records it in ``version.toml``;
# ``run_check`` compares the host's version against this one to surface drift, so a
# host is "outdated" whenever it was provisioned by an older release.
PROVISION_VERSION = __version__

# ``run_check`` outcomes.
CHECK_OK = "ok"               # reachable, manifest version matches (or is newer)
CHECK_OUTDATED = "outdated"   # reachable, provisioned by an older version
CHECK_UNMANAGED = "unmanaged"  # reachable, but no manifest (legacy provisioning)
CHECK_UNREACHABLE = "unreachable"  # ssh failed


@dataclass
class CheckResult:
    """Outcome of :func:`run_check` — connectivity plus provisioning-version drift."""

    entry: Target
    status: str
    detail: str = ""
    remote_version: Optional[str] = None
    expected_version: str = PROVISION_VERSION

    @property
    def reachable(self) -> bool:
        return self.status != CHECK_UNREACHABLE


# Canonical source for the files dropped into the remote ``sonitor`` home. Keeping
# them as real files (instead of strings baked into functions) makes the manifest
# easy to read, diff and edit; ``@@TOKEN@@`` placeholders are filled at build time.
MANIFEST_DIR = Path(__file__).resolve().parent / "manifest"


def _load_template(name: str) -> str:
    return (MANIFEST_DIR / name).read_text()


def _render(template: str, **values: str) -> str:
    for key, value in values.items():
        template = template.replace(f"@@{key}@@", value)
    return template


def key_path(key_id: str) -> Path:
    """Absolute path of a key file named ``id_<uuid>`` under ``SSH_DIR``."""
    return (settings.SSH_DIR / f"id_{key_id}").resolve()


def generate_keypair(comment: str = REMOTE_USER) -> Tuple[str, str]:
    """Generate a fresh controller-side ed25519 keypair named ``id_<uuid>``.

    Returns ``(absolute_private_key_path, public_key_string)``. The file name is a
    UUID, independent of any target name — the target owns the path reference. The
    private key never leaves the controller; only the public key is sent to the target.
    """
    settings.SSH_DIR.mkdir(parents=True, exist_ok=True)
    settings.SSH_DIR.chmod(0o700)

    private = key_path(uuid.uuid4().hex)
    public = private.with_name(private.name + ".pub")
    result = run(
        ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(private), "-C", comment],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ssh-keygen failed: {result.stderr or result.stdout}")
    return str(private), public.read_text().strip()


def delete_key_files(identity_file: str) -> None:
    """Remove a private key file and its ``.pub`` companion (best-effort)."""
    private = Path(identity_file)
    private.unlink(missing_ok=True)
    private.with_name(private.name + ".pub").unlink(missing_ok=True)


def key_fingerprint(public_key_path: str) -> str:
    """SHA256 fingerprint of a public key file (``""`` if it cannot be read).

    Used to identify a controller's key in the host-side ``hosts.toml`` manifest,
    so re-provisioning from the same controller is idempotent.
    """
    result = run(["ssh-keygen", "-lf", public_key_path], capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    for token in result.stdout.split():
        if token.startswith(("SHA256:", "MD5:")):
            return token
    return ""


def _readme_text() -> str:
    """The reassuring README left in the ``sonitor`` home so admins know what it is."""
    return _render(_load_template("README.md"), USER=REMOTE_USER)


def _build_manifest_section(
    fingerprint: Optional[str],
    label: Optional[str],
    version: str,
    now: str,
    teardown_body: str,
) -> str:
    """Shell that writes the host-side manifest (version/hosts/README/uninstall) into ``$H``.

    Appended to the provisioning script and run as root. Each file's content comes
    from a canonical template under :data:`MANIFEST_DIR`. ``hosts.toml`` gains a
    ``[[controller]]`` entry for this controller only when its fingerprint is not
    already present (idempotent re-provision); the rest are rewritten each run so
    they track the latest version. Heredocs are quoted so the already-rendered
    content lands verbatim (no shell expansion).
    """
    version_toml = _render(_load_template("version.toml"), VERSION=str(version), UPDATED_AT=now)
    hosts_header = _load_template("hosts.toml")
    readme = _readme_text()

    controller_block = ""
    if fingerprint:
        safe_label = (label or "").replace('"', "").replace("\\", "")
        entry = _render(
            _load_template("controller.toml"),
            FINGERPRINT=fingerprint,
            LABEL=safe_label,
            REGISTERED_AT=now,
        )
        controller_block = f"""
grep -qF '{fingerprint}' "$H/hosts.toml" 2>/dev/null || cat >> "$H/hosts.toml" <<'SONITOR_HOST_EOF'
{entry}SONITOR_HOST_EOF"""
    return f"""
# --- sonitor manifest (visibility, versioning, self-removal) ---
cat > "$H/version.toml" <<'SONITOR_VERSION_EOF'
{version_toml}SONITOR_VERSION_EOF
[ -f "$H/hosts.toml" ] || cat > "$H/hosts.toml" <<'SONITOR_HOSTS_EOF'
{hosts_header}SONITOR_HOSTS_EOF{controller_block}
cat > "$H/README.md" <<'SONITOR_README_EOF'
{readme}SONITOR_README_EOF
cat > "$H/uninstall.sh" <<'SONITOR_UNINSTALL_EOF'
{teardown_body}SONITOR_UNINSTALL_EOF
chmod 755 "$H/uninstall.sh"
chown "$U":"$U" "$H/version.toml" "$H/hosts.toml" "$H/README.md" "$H/uninstall.sh"
"""


def build_remote_script(
    public_key: str,
    no_privileges: bool = False,
    *,
    fingerprint: Optional[str] = None,
    label: Optional[str] = None,
    version: str = PROVISION_VERSION,
    now: str = "",
) -> str:
    """POSIX sh run as root on the target: create the user, install the key, grant privileges.

    Also writes the host-side manifest (see :func:`_build_manifest_section`): a
    ``version.toml``/``hosts.toml`` for versioning and audit, a ``README.md`` so a
    sysadmin understands the account, and an ``uninstall.sh`` self-removal script.
    """
    safe_key = public_key.replace("'", "")  # public keys never contain single quotes
    privileges = "" if no_privileges else """
if getent group asterisk >/dev/null 2>&1; then usermod -aG asterisk "$U" || true; fi"""
    manifest = _build_manifest_section(
        fingerprint, label, version, now, build_teardown_script()
    )
    return f"""set -e
umask 077
U={REMOTE_USER}
id -u "$U" >/dev/null 2>&1 || useradd -m -s /bin/bash "$U"
passwd -l "$U" >/dev/null 2>&1 || true
H=$(getent passwd "$U" | cut -d: -f6)
[ -n "$H" ] || H=/home/"$U"
mkdir -p "$H/.ssh"
K='{safe_key}'
grep -qF "$K" "$H/.ssh/authorized_keys" 2>/dev/null || printf '%s\\n' "$K" >> "$H/.ssh/authorized_keys"
chmod 700 "$H/.ssh"
chmod 600 "$H/.ssh/authorized_keys"
chown -R "$U":"$U" "$H/.ssh"
command -v restorecon >/dev/null 2>&1 && restorecon -R "$H/.ssh" || true{privileges}
{manifest}echo "sonitor: remote setup complete"
"""


def _ssh_argv(prefix_opts, dest, command, port=None):
    argv = ["ssh", *prefix_opts]
    if port:
        argv += ["-p", str(port)]
    argv += [dest, command]
    return argv


def run_setup(bootstrap_dest: str, name: str, no_privileges: bool = False, force: bool = False) -> Target:
    """Provision a target over an interactive SSH session and register it by name.

    ``bootstrap_dest`` is the privileged ``[user@]host[:port]`` used once to set
    things up (ssh prompts for the password on the terminal). The registered
    target connects as the ``sonitor`` user with the generated key.
    """
    store.validate_name(name)
    boot = SshTarget.parse(bootstrap_dest)

    existing = store.resolve(name) if store.exists(name) else None
    if existing and not force and existing.target.identity_file:
        # Re-provisioning an existing target: reuse its key (idempotent re-push).
        private_path = existing.target.identity_file
        public_key = Path(private_path + ".pub").read_text().strip()
    else:
        if existing and existing.target.identity_file:
            delete_key_files(existing.target.identity_file)  # --force: drop the stale key
        private_path, public_key = generate_keypair(comment=f"{REMOTE_USER}@{boot.host}")

    fingerprint = key_fingerprint(private_path + ".pub")
    label = f"{socket.gethostname()}:{name}"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    script = build_remote_script(
        public_key,
        no_privileges=no_privileges,
        fingerprint=fingerprint,
        label=label,
        version=PROVISION_VERSION,
        now=now,
    )
    blob = base64.b64encode(script.encode()).decode()
    remote_cmd = f"printf %s '{blob}' | base64 -d | sh"

    # Interactive: no capture, so the password / host-key prompt reaches the user's TTY.
    result = run(_ssh_argv(["-t", "-o", "StrictHostKeyChecking=accept-new"], boot.destination, remote_cmd, boot.port))
    if result.returncode != 0:
        raise RuntimeError(
            f"remote provisioning failed on {boot.destination} (ssh exit {result.returncode})."
        )

    target = SshTarget(host=boot.host, user=REMOTE_USER, port=boot.port, identity_file=private_path)

    verify = run(
        _ssh_argv(
            ["-i", private_path, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"],
            target.destination,
            "true",
            boot.port,
        ),
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        raise RuntimeError(
            f"key auth to {target.destination} failed after setup: {verify.stderr.strip() or verify.stdout.strip()}"
        )

    registered = Target(name=name, target=target)
    store.save(registered)
    return registered


def build_teardown_script() -> str:
    """POSIX sh run as root on the target: remove the sonitor user.

    The inverse of :func:`build_remote_script`, rendered from the canonical
    ``manifest/uninstall.sh`` template — the very script also dropped on the host
    as ``uninstall.sh`` (single source of truth for removal). ``userdel -r``
    drops the home directory (and its ``authorized_keys``) and any group
    memberships, so the ``asterisk`` group does not need separate handling.
    """
    return _render(_load_template("uninstall.sh"), USER=REMOTE_USER)


def run_teardown(
    target: str,
    bootstrap_user: str = "root",
) -> Target | None:
    """Undo a setup on a target's host — the remote side only.

    ``target`` is either a registered target name or an explicit privileged
    ``[user@]host[:port]`` destination:

    * a registered name → host/port come from the registry and the connection
      bootstraps as ``bootstrap_user`` (default ``root``; ssh prompts for the
      password on the terminal), then a best-effort check confirms the
      ``sonitor`` key no longer authenticates.
    * an explicit destination → used verbatim (you supply the privileged user),
      with no registry lookup.

    Either way the locked ``sonitor`` user — which cannot remove itself — is
    removed on the host. The local registry entry and SSH key are always left in
    place; use ``forget`` to drop those, or ``purge`` to do both at once.

    Returns the registered :class:`Target` when ``target`` is a known name, or
    ``None`` for an explicit destination.
    """
    entry = store.resolve(target) if store.exists(target) else None
    if entry:
        dest = f"{bootstrap_user}@{entry.target.host}"
        if entry.target.port:
            dest += f":{entry.target.port}"
    else:
        dest = target
    boot = SshTarget.parse(dest)

    # Teardown is global (userdel -r drops every controller's key). If the host's
    # manifest lists more than one controller, warn before the destructive step so
    # the operator can abort (they are about to type the root password anyway).
    if entry and entry.target.identity_file:
        _warn_if_other_controllers(entry)

    script = build_teardown_script()
    blob = base64.b64encode(script.encode()).decode()
    remote_cmd = f"printf %s '{blob}' | base64 -d | sh"

    # Interactive: no capture, so the password / host-key prompt reaches the user's TTY.
    result = run(_ssh_argv(["-t", "-o", "StrictHostKeyChecking=accept-new"], boot.destination, remote_cmd, boot.port))
    if result.returncode != 0:
        raise RuntimeError(
            f"remote teardown failed on {boot.destination} (ssh exit {result.returncode})."
        )

    # Best-effort sanity check: the sonitor key should no longer authenticate.
    if entry and entry.target.identity_file:
        check = run(
            _ssh_argv(
                ["-i", entry.target.identity_file, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"],
                f"{REMOTE_USER}@{boot.host}",
                "true",
                boot.port,
            ),
            capture_output=True,
            text=True,
        )
        if check.returncode == 0:
            print(
                f"warning: the '{REMOTE_USER}' key still authenticates to {boot.host}; "
                "the remote user may not have been removed."
            )
    return entry


def run_purge(
    name: str,
    bootstrap_user: str = "root",
    keep_key: bool = False,
) -> Target:
    """Tear down a *registered* target on its host *and* erase it locally.

    Runs :func:`run_teardown` (remote cleanup) then removes the registry entry
    and, unless ``keep_key``, the local SSH key — i.e. ``teardown`` + ``forget``.
    ``name`` must be a registered target (not a raw destination); raises
    ``ValueError`` otherwise.
    """
    entry = store.resolve(name)  # name-based: must be registered (raises otherwise)
    run_teardown(name, bootstrap_user=bootstrap_user)
    store.delete(name)
    if not keep_key and entry.target.identity_file:
        delete_key_files(entry.target.identity_file)
    return entry


def _parse_provision_version(text: str) -> Optional[str]:
    """Read ``[provision] version`` from a ``version.toml`` body (``None`` if absent/invalid)."""
    if not text.strip():
        return None
    try:
        value = tomli.loads(text).get("provision", {}).get("version")
        return str(value) if value is not None else None
    except tomli.TOMLDecodeError:
        return None


def _version_tuple(value: str) -> Tuple[int, ...]:
    """Numeric ``MAJOR.MINOR.PATCH`` tuple for ordering (raises ``ValueError`` if not numeric)."""
    return tuple(int(part) for part in value.split("."))


def _warn_if_other_controllers(entry: Target) -> None:
    """Best-effort warning when a host's manifest lists more than one controller."""
    argv = entry.target.ssh_argv_prefix() + ["cat ~/hosts.toml 2>/dev/null || true"]
    try:
        result = run(argv, capture_output=True, text=True)
    except Exception:
        return
    if result.returncode != 0 or not result.stdout.strip():
        return
    try:
        controllers = tomli.loads(result.stdout).get("controller", [])
    except tomli.TOMLDecodeError:
        return
    if len(controllers) > 1:
        labels = ", ".join(str(c.get("label", "?")) for c in controllers)
        print(
            f"warning: {len(controllers)} controllers are registered on "
            f"{entry.target.host} ({labels}); tearing down runs 'userdel -r' and "
            "revokes ALL of them, not just this machine.",
            file=sys.stderr,
        )


def run_check(name: str) -> CheckResult:
    """Verify a registered target still authenticates *and* report provisioning drift.

    Connects using the target's stored identity and reads the host-side ``version.toml``. 
    Returns a :class:`CheckResult` whose ``status`` is one of ``CHECK_OK`` (version matches
    or is newer), ``CHECK_OUTDATED`` (provisioned by an older version — re-run
    ``setup --force``), ``CHECK_UNMANAGED`` (reachable but no manifest, i.e. a
    legacy provisioning) or ``CHECK_UNREACHABLE`` (ssh failed). Raises
    ``ValueError`` when ``name`` is not a registered target.
    """
    entry = store.resolve(name)  # raises ValueError if unknown
    argv = entry.target.ssh_argv_prefix() + ["cat ~/version.toml 2>/dev/null || true"]
    result = run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"ssh exit {result.returncode}"
        return CheckResult(entry, CHECK_UNREACHABLE, detail=detail)

    remote_version = _parse_provision_version(result.stdout)
    if remote_version is None:
        return CheckResult(entry, CHECK_UNMANAGED)
    try:
        outdated = _version_tuple(remote_version) < _version_tuple(PROVISION_VERSION)
    except ValueError:
        # A version we cannot order numerically — treat as unmanaged rather than guess.
        return CheckResult(entry, CHECK_UNMANAGED, remote_version=remote_version)
    status = CHECK_OUTDATED if outdated else CHECK_OK
    return CheckResult(entry, status, remote_version=remote_version)


def rename_target(current: str, new: str) -> Target:
    """Rename a registered target.

    Pure registry operation: the entry is rewritten under ``new`` and the old one
    removed. The SSH key file is named by UUID, not by target name, so it stays put
    — its path travels with the target, keeping existing routines valid.
    """
    store.validate_name(new)
    entry = store.resolve(current)  # raises ValueError if `current` is unknown
    if new == current:
        raise ValueError(f"target is already named '{current}'.")
    if store.exists(new):
        raise ValueError(f"a target named '{new}' already exists.")

    renamed = Target(name=new, target=entry.target, created_at=entry.created_at)
    store.save(renamed)
    store.delete(current)
    return renamed
