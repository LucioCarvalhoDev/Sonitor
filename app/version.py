"""Single source of truth for the Sonitor version.

Semantic Versioning (https://semver.org): ``MAJOR.MINOR.PATCH``. This string is
the canonical version for the whole project — it is what the controller reports
and what each host records in its manifest (``version.toml``) at provisioning
time, so the repository and the hosts it provisions stay in lockstep.
"""

__version__ = "0.1.0"
