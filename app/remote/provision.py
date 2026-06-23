from __future__ import annotations

import base64
import uuid
from pathlib import Path
from subprocess import run
from typing import Tuple

from app import settings
from app.execution.target import SshTarget
from app.remote import store
from app.remote.model import Target

REMOTE_USER = "sonitor"


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


def build_remote_script(public_key: str, no_privileges: bool = False) -> str:
    """POSIX sh run as root on the target: create the user, install the key, grant privileges."""
    safe_key = public_key.replace("'", "")  # public keys never contain single quotes
    privileges = "" if no_privileges else """
if getent group asterisk >/dev/null 2>&1; then usermod -aG asterisk "$U" || true; fi
if command -v sngrep >/dev/null 2>&1 && command -v setcap >/dev/null 2>&1; then
    setcap cap_net_raw,cap_net_admin+eip "$(command -v sngrep)" || true
fi"""
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
echo "sonitor: remote setup complete"
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

    script = build_remote_script(public_key, no_privileges=no_privileges)
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


def build_teardown_script(no_privileges: bool = False) -> str:
    """POSIX sh run as root on the target: remove the user and revert privileges.

    The inverse of :func:`build_remote_script`. ``userdel -r`` also drops the home
    directory (and its ``authorized_keys``) and any group memberships, so the
    ``asterisk`` group does not need separate handling.
    """
    privileges = "" if no_privileges else """
if command -v sngrep >/dev/null 2>&1 && command -v setcap >/dev/null 2>&1; then
    setcap -r "$(command -v sngrep)" 2>/dev/null || true
fi"""
    return f"""set -e
U={REMOTE_USER}
if id -u "$U" >/dev/null 2>&1; then
    userdel -r "$U" 2>/dev/null || userdel "$U" || true
fi{privileges}
echo "sonitor: teardown complete"
"""


def run_teardown(
    target: str,
    bootstrap_user: str = "root",
    no_privileges: bool = False,
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

    script = build_teardown_script(no_privileges=no_privileges)
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
    no_privileges: bool = False,
    keep_key: bool = False,
) -> Target:
    """Tear down a *registered* target on its host *and* forget it locally.

    Runs :func:`run_teardown` (remote cleanup) then removes the registry entry
    and, unless ``keep_key``, the local SSH key — i.e. ``teardown`` + ``forget``.
    ``name`` must be a registered target (not a raw destination); raises
    ``ValueError`` otherwise.
    """
    entry = store.resolve(name)  # name-based: must be registered (raises otherwise)
    run_teardown(name, bootstrap_user=bootstrap_user, no_privileges=no_privileges)
    store.delete(name)
    if not keep_key and entry.target.identity_file:
        delete_key_files(entry.target.identity_file)
    return entry


def run_check(name: str, command: str = "true") -> Tuple[Target, bool, str]:
    """Verify a registered target still authenticates over SSH.

    Connects exactly as agentless collection would — using the target's stored
    identity and options, in ``BatchMode`` so it never blocks on a password or
    host-key prompt — and runs a trivial command on the remote host. Returns
    ``(entry, ok, detail)`` where ``ok`` is whether the connection succeeded and
    ``detail`` carries ssh's error output when it did not. Raises ``ValueError``
    when ``name`` is not a registered target.
    """
    entry = store.resolve(name)  # raises ValueError if unknown
    argv = entry.target.ssh_argv_prefix() + [command]
    result = run(argv, capture_output=True, text=True)
    ok = result.returncode == 0
    detail = "" if ok else (
        result.stderr.strip() or result.stdout.strip() or f"ssh exit {result.returncode}"
    )
    return entry, ok, detail


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
