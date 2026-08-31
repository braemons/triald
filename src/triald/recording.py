"""Writing sessions down.

One directory per session holding a manifest and an append-only JSONL stream, one
line per trial. Deliberately not ``.tdr``: triald does not have the eye data,
common resources or object data that a ``.tdr`` file carries, because those live
in vstimd and in the behaviour source. Assembling a ``.tdr`` from several
daemons' records is a separate tool's job - see dev/PLAN.md.

Two properties are worth more here than efficiency. The record is **complete
after a crash**, because a line is flushed the moment a trial ends rather than
being held until the session closes. And a write failure **stops the
experiment** by default: a recording that silently misses the disk is worse than
an aborted one, which is why VStim's ``m_StopExperimentOnTdrWriteFailure``
defaults on.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform
from pathlib import Path
from typing import Any

from triald.state import TrialRecord

log = logging.getLogger(__name__)


class RecordingError(Exception):
    """A trial record could not be written."""


class SessionRecorder:
    """Append-only JSONL recorder for one session."""

    def __init__(
        self,
        directory: str | Path,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        fsync: bool = False,
        stop_on_write_failure: bool = True,
    ) -> None:
        self.session_id = session_id or dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        self.directory = Path(directory) / self.session_id
        self.metadata = dict(metadata or {})
        self.fsync = fsync
        """fsync after every trial. Costs a few ms; survives a power cut."""

        self.stop_on_write_failure = stop_on_write_failure
        self.failed = False
        """Latched on the first write failure, for the session to notice."""

        self._trials_path = self.directory / "trials.jsonl"
        self._handle: Any = None
        self._count = 0

    def open(self, config: dict[str, Any] | None = None, seed: int | None = None) -> None:
        """Create the session directory and write the manifest."""
        self.directory.mkdir(parents=True, exist_ok=True)

        manifest = {
            "session_id": self.session_id,
            "opened_at": dt.datetime.now(dt.UTC).isoformat(),
            "host": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "seed": seed,
            "metadata": self.metadata,
            "config": config,
        }
        (self.directory / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )
        self._handle = self._trials_path.open("a", encoding="utf-8")
        log.info("recording session %s to %s", self.session_id, self.directory)

    def write(self, record: TrialRecord) -> None:
        """Append one trial.

        Raises:
            RecordingError: on a write failure, when `stop_on_write_failure` is
                set. Otherwise the failure is latched on :attr:`failed` and
                logged, and the session carries on.
        """
        if self._handle is None:
            raise RecordingError("the recorder is not open")

        try:
            self._handle.write(json.dumps(record.as_dict(), default=str) + "\n")
            self._handle.flush()
            if self.fsync:
                os.fsync(self._handle.fileno())
        except OSError as exc:
            self.failed = True
            message = f"could not write trial {record.spec.trial_number}: {exc}"
            log.error("%s", message)
            if self.stop_on_write_failure:
                raise RecordingError(message) from exc
            return

        self._count += 1

    def close(self, summary: dict[str, Any] | None = None) -> None:
        """Flush, close, and write the session summary. Safe to call twice."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

        if not self.directory.exists():
            return

        (self.directory / "summary.json").write_text(
            json.dumps(
                {
                    "session_id": self.session_id,
                    "closed_at": dt.datetime.now(dt.UTC).isoformat(),
                    "trials_written": self._count,
                    "write_failed": self.failed,
                    **(summary or {}),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

    def __enter__(self) -> SessionRecorder:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def read_session(directory: str | Path) -> list[dict[str, Any]]:
    """Read a recorded session's trials back.

    Tolerates a truncated final line, which is what a crash mid-write leaves
    behind - losing the last trial is expected, losing the session is not.
    """
    path = Path(directory) / "trials.jsonl"
    trials: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                trials.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("%s line %d is truncated; ignoring it", path, number)
    return trials
