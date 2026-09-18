# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the generated types actually put on the wire.

The JSON these produce *is* the API — panels, `curl`, MATLAB and the Python
client all read it — and protobuf's JSON mapping has habits that are easy to
assume wrongly. Every assertion here was written by printing the bytes first,
not by reading the specification, and each one is a setting in
`triald.api.wire` that a future reader might otherwise think was arbitrary.

mousewheeld's `daemon/tests/wire_json.rs` is the same file on the Rust side,
asserting the same facts, because the point of them is that the two agree.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("google.protobuf", reason="the wire types need the serve extra")

# Below the skip on purpose, so a checkout without the `serve` extra skips this
# file rather than failing to collect it. ruff wants one import block at the
# top and cannot be given one here.
from triald.api import wire  # noqa: I001
from triald.v1 import config_pb2, outcomes_pb2, session_pb2, trial_pb2


def as_dict(message) -> dict:
    return json.loads(wire.to_json(message))


def test_a_field_at_its_default_is_still_written():
    # The mapping's own rule is to omit it, which would mean a session sitting
    # waiting to be armed answered without a `running` and every consumer read
    # `undefined`. A reading of false is a reading.
    state = session_pb2.SessionState(set_name="fixation")
    written = as_dict(state)
    assert written["running"] is False
    assert written["armed"] is False
    assert written["trials_started"] == "0"


def test_an_absent_optional_field_is_still_absent():
    # The other half of the rule above, and the reason it is not simply "print
    # everything": on `SessionConfig`, no `stop_after_trials` means no limit,
    # and a zero there means something else entirely — a patch uses it to clear
    # the limit.
    config = config_pb2.SessionConfig(initial_set="fixation", rounds=10)
    written = as_dict(config)
    assert "stop_after_trials" not in written
    assert written["rounds"] == 10


def test_a_units_name_survives_the_mapping():
    # Without `json_name` in the .proto every one of these would be camelCase.
    report = trial_pb2.OutcomeReport(
        trial_id=7, outcome=outcomes_pb2.HIT, reaction_time_ms=250.5, reward_ms=120
    )
    written = as_dict(report)
    for field in ("trial_id", "reaction_time_ms", "reward_ms"):
        assert field in written, f"{field} is not on the wire"


def test_a_64_bit_integer_is_a_string():
    # JSON numbers are doubles, so the mapping quotes anything 64-bit. Every
    # consumer of a trial id or a trial number has to parse it; this is the
    # fact they have to know, asserted rather than remembered.
    report = trial_pb2.OutcomeReport(trial_id=41822, outcome=outcomes_pb2.HIT)
    assert as_dict(report)["trial_id"] == "41822"


def test_an_outcome_is_its_name_with_no_prefix():
    # The whole argument for spelling the enum's values `HIT` rather than
    # `TRIAL_OUTCOME_HIT`: this is what goes on the wire, and it is what every
    # .tdr file and every analysis script says.
    report = trial_pb2.OutcomeReport(trial_id=1, outcome=outcomes_pb2.UNEXPECTED_START_SIGNAL)
    assert as_dict(report)["outcome"] == "UNEXPECTED_START_SIGNAL"

    undetermined = trial_pb2.Outcome(code=-1, name="UNDETERMINED", manipulandum="NONE")
    assert as_dict(undetermined)["code"] == -1


def test_an_outcome_can_be_sent_by_name_or_by_number():
    # §7 records that `schemas.py` exists so a scientist can send "HIT" rather
    # than 1. Protobuf's mapping accepts both, which is how that commitment
    # survives the move without a validator.
    by_name = wire.from_json('{"trial_id": "3", "outcome": "HIT"}', trial_pb2.OutcomeReport)
    by_number = wire.from_json('{"trial_id": "3", "outcome": 1}', trial_pb2.OutcomeReport)
    assert by_name.outcome == by_number.outcome == outcomes_pb2.HIT


def test_a_stream_frame_names_its_arm():
    # `{"state": {…}}`, replacing the `{"kind": "state", …}` the panels read
    # today. One arm now; the envelope exists so a second can be added without
    # every client learning a new one.
    frame = session_pb2.StreamFrame(sequence=3)
    frame.at.FromJsonString("2026-09-18T12:00:00Z")
    frame.state.running = True
    written = as_dict(frame)
    assert written["state"]["running"] is True
    assert written["sequence"] == "3"
    # RFC 3339 with a Z, which is what google.protobuf.Timestamp puts on the
    # wire and what a client's generator hands back as a datetime.
    assert written["at"] == "2026-09-18T12:00:00Z"


def test_an_unknown_field_in_a_request_is_refused():
    # A typo in a config somebody edits by hand should be a message naming the
    # field, not a setting that silently did nothing. §11 makes it a rule for
    # every request in the family.
    from google.protobuf import json_format

    with pytest.raises(json_format.ParseError):
        wire.from_json('{"trial_id": "1", "outcomee": "HIT"}', trial_pb2.OutcomeReport)

    accepted = wire.from_json('{"trial_id": "1", "outcome": "HIT"}', trial_pb2.OutcomeReport)
    assert accepted.trial_id == 1
