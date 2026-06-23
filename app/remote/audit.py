"""Cross-cutting health check of the local remote registry, SSH keys and routines.

Where ``remote check`` probes a *single* registered target, ``audit`` looks at the
whole picture and flags inconsistencies a human would otherwise have to hunt for:

* every registered target — reachable / version drift (reusing :func:`provision.run_check`)
  plus the integrity of its on-disk key pair;
* **unused keys** — private keys under ``SSH_DIR`` no target *or* routine references
  anymore (left behind by ``forget --keep-key``, ``setup --force`` interruptions, etc.);
* lone ``.pub`` files whose private half is gone;
* ``.target`` files that no longer parse;
* routines pointing at an SSH key that has since been deleted.

Everything is read-only unless the caller asks to :func:`prune_orphan_keys`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app import settings
from app.remote import provision, store
from app.remote.model import Target
from app.routines import store as routine_store
from app.routines.model import Routine


def _resolved(path_str: str) -> str:
    """Canonical absolute form of a path string, for stable cross-reference comparison."""
    return str(Path(path_str).resolve())


@dataclass
class TargetAudit:
    """A single registered target's health: key-pair integrity + (optional) reachability."""

    entry: Target
    check: Optional[provision.CheckResult] = None  # None when connectivity check is skipped
    missing_private: bool = False
    missing_public: bool = False

    @property
    def name(self) -> str:
        return self.entry.name

    @property
    def no_identity(self) -> bool:
        return not self.entry.target.identity_file

    @property
    def has_issue(self) -> bool:
        if self.no_identity or self.missing_private or self.missing_public:
            return True
        return self.check is not None and self.check.status != provision.CHECK_OK


@dataclass
class OrphanKey:
    """A private key under ``SSH_DIR`` no target or routine references."""

    private: Path
    public: Optional[Path]  # the companion ``.pub`` if it is still on disk


@dataclass
class RoutineIssue:
    """A routine whose stored SSH target points at something that no longer exists."""

    uuid: str
    name: str
    detail: str


@dataclass
class AuditReport:
    targets: List[TargetAudit] = field(default_factory=list)
    orphan_keys: List[OrphanKey] = field(default_factory=list)
    lone_public_keys: List[Path] = field(default_factory=list)
    unreadable_targets: List[Path] = field(default_factory=list)
    routine_issues: List[RoutineIssue] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return (
            sum(1 for target in self.targets if target.has_issue)
            + len(self.orphan_keys)
            + len(self.lone_public_keys)
            + len(self.unreadable_targets)
            + len(self.routine_issues)
        )

    @property
    def clean(self) -> bool:
        return self.issue_count == 0


def _load_targets() -> Tuple[List[Target], List[Path]]:
    """Load every ``.target`` file, isolating the ones that no longer parse.

    ``store.list_targets`` would raise on the first corrupt file; audit must keep
    going and report it instead, so we read the directory directly here.
    """
    directory = settings.TARGETS_DIR
    if not directory.exists():
        return [], []
    loaded: List[Target] = []
    unreadable: List[Path] = []
    for path in sorted(directory.glob(f"*{store.TARGET_SUFFIX}")):
        try:
            loaded.append(Target.from_path(path))
        except Exception:  # malformed TOML, missing required fields, etc.
            unreadable.append(path)
    return loaded, unreadable


def _disk_private_keys() -> List[Path]:
    """Private key files under ``SSH_DIR`` (``id_<uuid>``, excluding their ``.pub``)."""
    directory = settings.SSH_DIR
    if not directory.exists():
        return []
    return sorted(
        path for path in directory.glob("id_*")
        if path.is_file() and path.suffix != ".pub"
    )


def _referenced_keys() -> Dict[str, List[str]]:
    """Map each resolved identity-file path to the referrers that keep it alive.

    A key is "used" if any registered target *or* any routine still points at it —
    routines embed their own SSH target, so pruning a key a routine relies on would
    silently break that routine.
    """
    references: Dict[str, List[str]] = {}

    targets, _ = _load_targets()
    for entry in targets:
        identity = entry.target.identity_file
        if identity:
            references.setdefault(_resolved(identity), []).append(f"target:{entry.name}")

    for routine in _load_routines()[0]:
        if routine.target and routine.target.identity_file:
            label = routine.name or routine.uuid
            references.setdefault(_resolved(routine.target.identity_file), []).append(f"routine:{label}")

    return references


def _load_routines() -> Tuple[List[Routine], List[Path]]:
    """Load every ``.sonitor`` routine, isolating the ones that no longer parse."""
    directory = settings.ROUTINES_DIR
    if not directory.exists():
        return [], []
    loaded: List[Routine] = []
    unreadable: List[Path] = []
    for path in sorted(directory.glob(f"*{routine_store.ROUTINE_SUFFIX}")):
        try:
            loaded.append(Routine.from_path(path))
        except Exception:
            unreadable.append(path)
    return loaded, unreadable


def _audit_routines() -> List[RoutineIssue]:
    """Flag routines that cannot run as recorded (unreadable, or key since deleted)."""
    issues: List[RoutineIssue] = []
    routines, unreadable = _load_routines()
    for path in unreadable:
        issues.append(RoutineIssue(uuid=path.stem, name="", detail="unreadable .sonitor file"))
    for routine in routines:
        target = routine.target
        if target and target.identity_file and not Path(target.identity_file).exists():
            issues.append(
                RoutineIssue(
                    uuid=routine.uuid,
                    name=routine.name,
                    detail=f"SSH key no longer exists: {target.identity_file}",
                )
            )
    return issues


def run_audit(do_check: bool = True) -> AuditReport:
    """Build a full :class:`AuditReport` of the local registry, keys and routines.

    When ``do_check`` is true each reachable target is probed over SSH (as agentless
    collection would); pass ``do_check=False`` for a fast, offline hygiene pass.
    """
    report = AuditReport()

    targets, report.unreadable_targets = _load_targets()
    referenced = _referenced_keys()

    for entry in sorted(targets, key=lambda t: t.name):
        audit = TargetAudit(entry=entry)
        identity = entry.target.identity_file
        if identity:
            private = Path(identity)
            audit.missing_private = not private.exists()
            audit.missing_public = not private.with_name(private.name + ".pub").exists()
        if do_check:
            audit.check = provision.run_check(entry.name)
        report.targets.append(audit)

    for private in _disk_private_keys():
        if _resolved(str(private)) not in referenced:
            public = private.with_name(private.name + ".pub")
            report.orphan_keys.append(OrphanKey(private=private, public=public if public.exists() else None))

    if settings.SSH_DIR.exists():
        for public in sorted(settings.SSH_DIR.glob("id_*.pub")):
            private = public.with_name(public.name[: -len(".pub")])
            if not private.exists():
                report.lone_public_keys.append(public)

    report.routine_issues = _audit_routines()
    return report


def prune_orphan_keys(report: AuditReport) -> List[Path]:
    """Delete the files of every orphan key (and lone ``.pub``) in ``report``.

    Returns the paths removed. Only keys the report already classified as unused are
    touched — referenced keys are never deleted.
    """
    removed: List[Path] = []
    for orphan in report.orphan_keys:
        provision.delete_key_files(str(orphan.private))  # drops both the key and its .pub
        removed.append(orphan.private)
    for public in report.lone_public_keys:
        public.unlink(missing_ok=True)
        removed.append(public)
    return removed
