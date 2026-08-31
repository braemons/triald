"""Writing sessions down.

One directory per session, holding four files:

============== ==========================================================
`manifest.json` who, what, which devices, the config and the seed. Written
               at open and refreshed at close with the end time and any
               metadata corrected along the way.
`trials.jsonl`  one line per trial, appended the moment the trial ends.
`events.jsonl`  everything that happened which was not a trial - notes,
               manual rewards, device reports, metadata corrections.
`summary.json`  counts and the stop reason, written at close.
============== ==========================================================

Deliberately not ``.tdr``: triald does not have the eye data, common resources or
object data that a ``.tdr`` file carries, because those live in vstimd and in the
behaviour source. Assembling a ``.tdr`` from several daemons' records is a
separate tool's job - see dev/PLAN.md.

Three properties are worth more here than efficiency:

* **Complete after a crash** - a line is flushed the moment a trial ends rather
  than held until the session closes.
* **Append-only evidence** - trials and events are never rewritten. A correction
  is a new event, so the record shows both what was believed and when it changed.
  The manifest is a header rather than evidence, and is refreshed at close.
* **Loud on failure** - a write failure stops the experiment by default. A
  recording that silently misses the disk is worse than an aborted one, which is
  why VStim's ``m_StopExperimentOnTdrWriteFailure`` defaults on.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
import os
import platform
from pathlib import Path
from typing import Any

from triald.metadata import Device, MetadataError, SessionEvent, SessionMetadata
from triald.state import TrialRecord

log = logging.getLogger(__name__)


class RecordingError(Exception):
    """A trial record or event could not be written."""


class SessionRecorder:
    """Append-only recorder for one session."""

    def __init__(
        self,
        directory: str | Path,
        *,
        session_id: str | None = None,
        metadata: SessionMetadata | None = None,
        fsync: bool = False,
        stop_on_write_failure: bool = True,
        clock: Any = None,
    ) -> None:
        self.session_id = session_id or dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        self.directory = Path(directory) / self.session_id
        self.metadata = metadata if metadata is not None else SessionMetadata()
        self.fsync = fsync
        """fsync after every trial. Costs a few ms; survives a power cut."""

        self.stop_on_write_failure = stop_on_write_failure
        self.failed = False
        """Latched on the first write failure, for the session to notice."""

        self._clock = clock if clock is not None else _wall_clock
        self._trials_path = self.directory / "trials.jsonl"
        self._events_path = self.directory / "events.jsonl"
        self._trials: Any = None
        self._events: Any = None
        self._config: dict[str, Any] | None = None
        self._seed: int | None = None
        self._count = 0
        self._event_count = 0

    # -- opening and closing ----------------------------------------------------

    def open(self, config: dict[str, Any] | None = None, seed: int | None = None) -> None:
        """Create the session directory and write the manifest."""
        self.directory.mkdir(parents=True, exist_ok=True)

        self._config = config
        self._seed = seed
        self.metadata.session_id = self.session_id
        self.metadata.started_at = self.metadata.started_at or self._clock()
        self.metadata.host = self.metadata.host or platform.node()
        self.metadata.software.setdefault("python", platform.python_version())
        self.metadata.software.setdefault("platform", platform.platform())

        self._write_manifest()
        self._trials = self._trials_path.open("a", encoding="utf-8")
        self._events = self._events_path.open("a", encoding="utf-8")
        log.info("recording session %s to %s", self.session_id, self.directory)

    def close(self, summary: dict[str, Any] | None = None) -> None:
        """Flush, close, refresh the manifest and write the summary.

        Safe to call twice.
        """
        self.metadata.ended_at = self.metadata.ended_at or self._clock()

        for handle in (self._trials, self._events):
            if handle is not None:
                handle.close()
        self._trials = None
        self._events = None

        if not self.directory.exists():
            return

        self._write_manifest()
        _write_json(
            self.directory / "summary.json",
            {
                "session_id": self.session_id,
                "closed_at": self._clock().isoformat(),
                "trials_written": self._count,
                "events_written": self._event_count,
                "write_failed": self.failed,
                **(summary or {}),
            },
        )

    def _write_manifest(self) -> None:
        _write_json(
            self.directory / "manifest.json",
            {
                "format": "triald/session",
                "format_version": 1,
                "metadata": self.metadata.as_dict(),
                "seed": self._seed,
                "config": self._config,
            },
        )

    # -- the streams ------------------------------------------------------------

    def write(self, record: TrialRecord) -> None:
        """Append one trial.

        Raises:
            RecordingError: on a write failure, when `stop_on_write_failure` is
                set. Otherwise the failure is latched on :attr:`failed` and
                logged, and the session carries on.
        """
        if self._trials is None:
            raise RecordingError("the recorder is not open")
        if self._append(self._trials, record.as_dict(), f"trial {record.spec.trial_number}"):
            self._count += 1

    def event(self, event: SessionEvent) -> None:
        """Append one session event.

        Timestamps it if it has none, so callers do not have to.
        """
        if self._events is None:
            raise RecordingError("the recorder is not open")

        if event.at is None:
            event = SessionEvent(
                kind=event.kind,
                data=event.data,
                source=event.source,
                at=self._clock(),
                trial_number=event.trial_number,
            )
        if self._append(self._events, event.as_dict(), f"event {event.kind!r}"):
            self._event_count += 1

    def note(
        self, text: str, *, trial_number: int | None = None, source: str = "experimenter"
    ) -> None:
        """Shorthand for the commonest event: somebody wrote something down."""
        self.event(
            SessionEvent(
                kind="note", data={"text": text}, source=source, trial_number=trial_number
            )
        )

    def register_device(self, device: Device) -> None:
        """Add a device to the metadata and record that it appeared.

        Devices register themselves as they connect, so the record says what
        produced it without anybody having to remember. The event carries the
        moment, which matters when a device is swapped mid-session.
        """
        self.metadata.add_device(device)
        self.event(SessionEvent(kind="device", data=device.as_dict(), source=device.name))

    def update_metadata(
        self, changes: dict[str, Any], *, trial_number: int | None = None
    ) -> None:
        """Apply metadata `changes` and record that they were made.

        The manifest is refreshed at close, but the *history* lives in the event
        stream: realising at trial 50 that the subject ID was typed wrong leaves
        both the correction and the fact that it was corrected. A record that
        silently shows only the final answer cannot be audited.

        Raises:
            MetadataError: for an unknown field, so a typo does not vanish into
                a record nobody checks.
        """
        known = {f.name for f in dataclasses.fields(SessionMetadata)}
        for key, value in changes.items():
            if key not in known:
                raise MetadataError(
                    f"{key!r} is not a session metadata field. Custom fields go "
                    f"in 'extra', namespaced - extra={{'bremen': {{...}}}}."
                )
            setattr(self.metadata, key, value)

        self.event(
            SessionEvent(
                kind="metadata", data=changes, source="experimenter", trial_number=trial_number
            )
        )

    def _append(self, handle: Any, payload: dict[str, Any], what: str) -> bool:
        try:
            handle.write(json.dumps(payload, default=str) + "\n")
            handle.flush()
            if self.fsync:
                os.fsync(handle.fileno())
        except OSError as exc:
            self.failed = True
            message = f"could not write {what}: {exc}"
            log.error("%s", message)
            if self.stop_on_write_failure:
                raise RecordingError(message) from exc
            return False
        return True

    def __enter__(self) -> SessionRecorder:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# -- reading back ---------------------------------------------------------------


def read_session(directory: str | Path) -> list[dict[str, Any]]:
    """Read a recorded session's trials back."""
    return _read_jsonl(Path(directory) / "trials.jsonl")


def read_events(directory: str | Path) -> list[dict[str, Any]]:
    """Read a recorded session's events back."""
    return _read_jsonl(Path(directory) / "events.jsonl")


def read_manifest(directory: str | Path) -> dict[str, Any]:
    """Read a recorded session's manifest."""
    path = Path(directory) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, tolerating a truncated final line.

    A truncated last line is what a crash mid-write leaves behind. Losing the
    last record is expected; losing the file is not.
    """
    if not path.is_file():
        return []

    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("%s line %d is truncated; ignoring it", path, number)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _wall_clock() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
