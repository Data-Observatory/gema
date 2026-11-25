"""Error types shared by the processing steps.

``TransientError`` is the only kind the processor retries (network blips, HTTP 5xx, rate
limits). Everything else ends the record as ``failed`` straight away.
"""

from __future__ import annotations


class ConfigError(Exception):
    """Startup misconfiguration (missing key, wrong provider...). Fail fast."""


class StepError(Exception):
    """A processing step failed. ``str(exc)`` is what the admin sees."""


class TransientError(StepError):
    """Worth one automatic retry."""


class PermanentError(StepError):
    """Retrying would not help."""
