# SPDX-License-Identifier: AGPL-3.0-or-later
"""Session records: written per trial, readable after a crash, loud on failure."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from triald.behaviour import SimulatedBehaviourSource
from triald.metadata import (
    SessionMetadata,
    Subject,
)
from triald.outcomes import OutcomeReport, TrialOutcome
from triald.recording import (
    RecordingError,
    SessionRecorder,
    read_manifest,
    read_session,
)
from triald.runner import run_session
from triald.session import Session, SessionConfig
from triald.trialtypes import TrialType, TrialTypeSet, TrialTypeStore


def store() -> TrialTypeStore:
    return TrialTypeStore(
        [
            TrialTypeSet(
                name="main",
                trial_types=[
                    TrialType(name="a", trials_per_round=1, reward_ms=100),
                    TrialType(name="b", trials_per_round=1, reward_ms=120),
                ],
            )
        ]
    )


def test_a_manifest_is_written_on_open(tmp_path: Path):
    recorder = SessionRecorder(
        tmp_path,
        session_id="s1",
        metadata=SessionMetadata(
            experimenter="JS",
            lab="Kreiter",
            session_type="training",
            subject=Subject(subject_id="M1", species="Macaca mulatta", weight_g=8400),
        ),
    )
    recorder.open(config={"rounds": 3}, seed=42)
    recorder.close()

    manifest = read_manifest(tmp_path / "s1")
    assert manifest["format"] == "triald/session"
    assert manifest["seed"] == 42
    assert manifest["config"] == {"rounds": 3}

    meta = manifest["metadata"]
    assert meta["session_id"] == "s1"
    assert meta["experimenter"] == "JS"
    assert meta["session_type"] == "training"
    assert meta["subject"]["subject_id"] == "M1"
    # Filled in without being asked for.
    assert meta["started_at"] and meta["ended_at"]
    assert meta["host"]


def test_trials_are_written_as_they_finish(tmp_path: Path):
    # Not held until close: a crash must cost at most the trial in flight.
    recorder = SessionRecorder(tmp_path, session_id="s1")
    recorder.open()

    session = Session(store(), SessionConfig(initial_set="main", seed=0), recorder=recorder)
    session.arm()
    session.start_recording()

    session.next_trial()
    session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT))

    # Readable before close().
    assert len(read_session(tmp_path / "s1")) == 1
    recorder.close()


def test_a_record_carries_the_outcome_and_its_modifiers(tmp_path: Path):
    recorder = SessionRecorder(tmp_path, session_id="s1")
    recorder.open()

    session = Session(store(), SessionConfig(initial_set="main", seed=0), recorder=recorder)
    session.arm()
    session.start_recording()
    session.next_trial()
    session.report_outcome(
        OutcomeReport(
            outcome=TrialOutcome.HIT,
            reaction_time_ms=234.5,
            terminating_interval=2,
            reward_ms=100,
        )
    )
    recorder.close()

    (trial,) = read_session(tmp_path / "s1")
    assert trial["outcome"]["code"] == 1
    assert trial["outcome"]["name"] == "HIT"
    assert trial["outcome"]["reaction_time_ms"] == 234.5
    assert trial["outcome"]["terminating_interval"] == 2
    assert trial["accepted"] is True
    assert trial["trial"]["trial_number"] == 1


def test_a_refused_trial_records_why(tmp_path: Path):
    from triald.outcomes import AcceptancePolicy

    recorder = SessionRecorder(tmp_path, session_id="s1")
    recorder.open()

    session = Session(
        store(),
        SessionConfig(
            initial_set="main",
            seed=0,
            acceptance=AcceptancePolicy(not_started=False),
        ),
        recorder=recorder,
    )
    session.arm()
    session.start_recording()
    session.next_trial()
    session.report_outcome(OutcomeReport(outcome=TrialOutcome.NOT_STARTED))
    recorder.close()

    (trial,) = read_session(tmp_path / "s1")
    assert trial["accepted"] is False
    assert "not accepted" in trial["refusal_reason"]


def test_pausing_trials_are_never_recorded(tmp_path: Path):
    recorder = SessionRecorder(tmp_path, session_id="s1")
    recorder.open()

    session = Session(store(), SessionConfig(initial_set="main", seed=0), recorder=recorder)
    session.arm()
    session.start_recording()
    session.pause_recording()

    session.next_trial()
    session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT))
    recorder.close()

    assert read_session(tmp_path / "s1") == []


def test_nothing_is_recorded_before_recording_starts(tmp_path: Path):
    recorder = SessionRecorder(tmp_path, session_id="s1")
    recorder.open()

    session = Session(store(), SessionConfig(initial_set="main", seed=0), recorder=recorder)
    session.arm()
    session.next_trial()  # recording was never started
    session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT))
    recorder.close()

    assert read_session(tmp_path / "s1") == []


def test_a_truncated_final_line_is_tolerated(tmp_path: Path):
    # What a crash mid-write leaves behind. Losing the last trial is expected;
    # losing the session is not.
    directory = tmp_path / "s1"
    directory.mkdir()
    (directory / "trials.jsonl").write_text(
        '{"trial": {"trial_number": 1}}\n{"trial": {"trial_num',
        encoding="utf-8",
    )
    assert len(read_session(directory)) == 1


def test_writing_before_open_is_an_error(tmp_path: Path):
    recorder = SessionRecorder(tmp_path)
    session = Session(store(), SessionConfig(initial_set="main", seed=0))
    session.arm()
    spec = session.next_trial()
    record = session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT))

    assert spec.trial_number == 1
    with pytest.raises(RecordingError, match="not open"):
        recorder.write(record)


def test_a_summary_is_written_on_close(tmp_path: Path):
    recorder = SessionRecorder(tmp_path, session_id="s1")
    recorder.open()
    recorder.close(summary={"stop_reason": "done"})

    summary = json.loads((tmp_path / "s1" / "summary.json").read_text(encoding="utf-8"))
    assert summary["trials_written"] == 0
    assert summary["stop_reason"] == "done"
    assert summary["write_failed"] is False


def test_close_is_safe_twice(tmp_path: Path):
    recorder = SessionRecorder(tmp_path, session_id="s1")
    recorder.open()
    recorder.close()
    recorder.close()


def test_a_full_simulated_session_records_every_accepted_trial(tmp_path: Path):
    """The wiring end to end: runner -> session -> recorder."""
    recorder = SessionRecorder(tmp_path, session_id="s1")
    recorder.open()

    session = Session(
        store(),
        SessionConfig(initial_set="main", rounds=100, seed=3),
        recorder=recorder,
    )
    session.arm()
    session.start_recording()

    summary = run_session(
        session, SimulatedBehaviourSource(rng=random.Random(3)), max_trials=50
    )
    recorder.close(summary=summary.as_dict())

    trials = read_session(tmp_path / "s1")
    assert len(trials) == 50
    assert [t["trial"]["trial_number"] for t in trials] == list(range(1, 51))
