"""Session metadata, devices, and the custom-message event stream."""

from __future__ import annotations

from pathlib import Path

import pytest

from triald.metadata import (
    MAX_CUSTOM_BYTES,
    Device,
    MetadataError,
    SessionEvent,
    SessionMetadata,
    Subject,
)
from triald.outcomes import OutcomeReport, TrialOutcome
from triald.policy import Policy
from triald.recording import SessionRecorder, read_events, read_manifest
from triald.session import Session, SessionConfig
from triald.trialtypes import TrialType, TrialTypeSet, TrialTypeStore


def store() -> TrialTypeStore:
    return TrialTypeStore(
        [
            TrialTypeSet(
                name="main",
                trial_types=[TrialType(name="a", trials_per_round=1, reward_ms=100)],
            )
        ]
    )


def recorder_at(tmp_path: Path, **kwargs: object) -> SessionRecorder:
    r = SessionRecorder(tmp_path, session_id="s1", **kwargs)  # type: ignore[arg-type]
    r.open()
    return r


# -- custom payloads -------------------------------------------------------------


def test_extra_takes_anything_json_serialisable():
    meta = SessionMetadata(
        extra={"bremen": {"electrode_depth_um": 1420, "array": "Utah", "channels": [1, 2, 3]}}
    )
    assert meta.as_dict()["extra"]["bremen"]["electrode_depth_um"] == 1420


def test_a_non_serialisable_payload_is_refused():
    with pytest.raises(MetadataError, match="not JSON-serialisable"):
        SessionMetadata(extra={"handle": {1, 2, 3}})


def test_a_payload_must_be_a_dict():
    with pytest.raises(MetadataError, match="must be a dict"):
        SessionEvent(kind="note", data=["not", "a", "dict"])  # type: ignore[arg-type]


def test_an_oversized_payload_is_refused_with_advice():
    # Somebody will try to put an array in here. Refusing early, saying where the
    # data belongs instead, beats a 40 GB events.jsonl.
    huge = {"samples": "x" * (MAX_CUSTOM_BYTES + 1)}
    with pytest.raises(MetadataError, match="own file"):
        SessionEvent(kind="ephys", data=huge)


def test_an_event_needs_a_kind():
    with pytest.raises(MetadataError, match="needs a kind"):
        SessionEvent(kind="", data={})


# -- what lands in the manifest --------------------------------------------------


def test_the_subject_block_drops_empty_fields(tmp_path: Path):
    r = recorder_at(
        tmp_path, metadata=SessionMetadata(subject=Subject(subject_id="M1", sex="M"))
    )
    r.close()

    subject = read_manifest(tmp_path / "s1")["metadata"]["subject"]
    assert subject == {"subject_id": "M1", "sex": "M"}


def test_devices_are_recorded_with_their_versions(tmp_path: Path):
    r = recorder_at(tmp_path)
    r.register_device(
        Device(
            name="vstimd",
            role="stimulus",
            version="0.3.1",
            host="rig-a1b2c3",
            info={"display": "1920x1080@120", "renderer": "vulkan"},
        )
    )
    r.register_device(
        Device(name="mcu", role="behaviour", version="1.4", info={"firmware": "abc123"})
    )
    r.close()

    devices = read_manifest(tmp_path / "s1")["metadata"]["devices"]
    assert [d["name"] for d in devices] == ["vstimd", "mcu"]
    assert devices[0]["info"]["display"] == "1920x1080@120"

    # Also in the event stream, because a device swapped mid-session has a time.
    kinds = [e["kind"] for e in read_events(tmp_path / "s1")]
    assert kinds == ["device", "device"]


def test_the_has_flags_say_what_else_was_recorded(tmp_path: Path):
    r = recorder_at(
        tmp_path,
        metadata=SessionMetadata(has_electrophysiology=True, has_eye_data=True),
    )
    r.close()

    meta = read_manifest(tmp_path / "s1")["metadata"]
    assert meta["has_electrophysiology"] is True
    assert meta["has_eye_data"] is True
    assert meta["has_imaging"] is False


# -- the event stream ------------------------------------------------------------


def test_a_note_is_timestamped_without_being_asked(tmp_path: Path):
    r = recorder_at(tmp_path)
    r.note("animal settled after the first block", trial_number=42)
    r.close()

    (event,) = read_events(tmp_path / "s1")
    assert event["kind"] == "note"
    assert event["data"]["text"] == "animal settled after the first block"
    assert event["trial_number"] == 42
    assert event["at"] is not None


def test_custom_events_pass_through_untouched(tmp_path: Path):
    r = recorder_at(tmp_path)
    r.event(
        SessionEvent(
            kind="bremen.electrode_depth",
            data={"depth_um": 1420, "drive": "B"},
            source="experimenter",
            trial_number=17,
        )
    )
    r.close()

    (event,) = read_events(tmp_path / "s1")
    assert event["kind"] == "bremen.electrode_depth"
    assert event["data"] == {"depth_um": 1420, "drive": "B"}


def test_events_keep_their_order(tmp_path: Path):
    r = recorder_at(tmp_path)
    for i in range(5):
        r.note(f"note {i}")
    r.close()

    assert [e["data"]["text"] for e in read_events(tmp_path / "s1")] == [
        f"note {i}" for i in range(5)
    ]


def test_the_event_count_reaches_the_summary(tmp_path: Path):
    import json

    r = recorder_at(tmp_path)
    r.note("one")
    r.note("two")
    r.close()

    summary = json.loads((tmp_path / "s1" / "summary.json").read_text(encoding="utf-8"))
    assert summary["events_written"] == 2


# -- corrections -----------------------------------------------------------------


def test_a_correction_updates_the_manifest_and_leaves_a_trail(tmp_path: Path):
    # The manifest is a header and shows the final answer; the event stream is
    # evidence and shows that it changed. A record that silently shows only the
    # final answer cannot be audited.
    r = recorder_at(tmp_path, metadata=SessionMetadata(experimenter="typo"))
    r.update_metadata({"experimenter": "JS"}, trial_number=50)
    r.close()

    assert read_manifest(tmp_path / "s1")["metadata"]["experimenter"] == "JS"

    (event,) = read_events(tmp_path / "s1")
    assert event["kind"] == "metadata"
    assert event["data"] == {"experimenter": "JS"}
    assert event["trial_number"] == 50


def test_an_unknown_metadata_field_is_refused(tmp_path: Path):
    # A typo that vanishes into a record nobody checks is worse than an error.
    r = recorder_at(tmp_path)
    with pytest.raises(MetadataError, match="not a session metadata field"):
        r.update_metadata({"experimentor": "JS"})
    r.close()


def test_custom_metadata_goes_through_extra(tmp_path: Path):
    r = recorder_at(tmp_path)
    r.update_metadata({"extra": {"bremen": {"drive": "B", "turns": 3}}})
    r.close()

    extra = read_manifest(tmp_path / "s1")["metadata"]["extra"]
    assert extra["bremen"]["turns"] == 3


# -- wiring ----------------------------------------------------------------------


def test_a_policy_failure_lands_in_the_event_stream(tmp_path: Path):
    """Not just the log: a session that misbehaved should say so in its own directory."""

    class Broken(Policy):
        def select_trial(self, state):
            raise RuntimeError("boom")

    r = recorder_at(tmp_path)
    session = Session(
        store(),
        SessionConfig(initial_set="main", rounds=100, seed=0),
        policy=Broken(),
        recorder=r,
    )
    session.arm()
    session.start_recording()
    session.next_trial()
    session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT))
    r.close()

    errors = [e for e in read_events(tmp_path / "s1") if e["kind"] == "policy_error"]
    assert len(errors) == 1
    assert errors[0]["data"]["hook"] == "select_trial"
    assert "boom" in errors[0]["data"]["error"]
    assert session.running  # and the session carried on regardless


def test_events_survive_a_session_with_no_events(tmp_path: Path):
    r = recorder_at(tmp_path)
    r.close()
    assert read_events(tmp_path / "s1") == []
