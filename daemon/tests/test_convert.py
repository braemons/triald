# SPDX-License-Identifier: AGPL-3.0-or-later
"""The seam, against a session that actually ran.

`triald.api.convert` is field-for-field in most places and quietly clever in a
few — an omitted switch-rule criterion means hits while an omitted stop
criterion means accepted trials, an absent `precise_fixation` means true, a
zero `stop_after_trials` in a patch means *clear the limit*. None of that is
visible in a type, so it is checked here against real values rather than
constructed ones: the session below is armed, stepped and reported on exactly
as the API would do it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("google.protobuf", reason="the wire types need the serve extra")

# Below the skip, so a checkout without the `serve` extra skips this file rather
# than failing to collect it.
from google.protobuf import json_format  # noqa: I001
from triald.api import convert
from triald.counters import TrialCountCriterion
from triald.outcomes import Manipulandum, OutcomeReport, TrialOutcome
from triald.selection import Ordering
from triald.session import Session, SessionConfig
from triald.trialtypes import SwitchRule, TrialType, TrialTypeSet, TrialTypeStore
from triald._proto.triald.v1 import config_pb2, sets_pb2


def as_dict(message) -> dict:
    """A message as the dict a person reads: `json_name` spellings, defaults written."""
    return json_format.MessageToDict(message, always_print_fields_with_no_presence=True)


def parse(text: str, message_type):
    """A message from JSON, refusing a field it does not know."""
    return json_format.Parse(text, message_type(), ignore_unknown_fields=False)


def a_set() -> TrialTypeSet:
    # The rule names a target, so it is *armed* — `SetProgress.criterion` is
    # None otherwise, which is a distinction the seam has to carry.
    return TrialTypeSet(
        name="easy",
        trial_types=[
            TrialType(name="a", trials_per_round=2, reward_ms=100, params={"contrast": 0.5}),
            TrialType(name="b", trials_per_round=1, reward_ms=120),
        ],
        switch_rule=SwitchRule(
            enabled=True, criterion=TrialCountCriterion.HITS, count=3, target="hard"
        ),
    )


def a_store() -> TrialTypeStore:
    return TrialTypeStore(
        [
            a_set(),
            TrialTypeSet(name="hard", trial_types=[TrialType(name="c", trials_per_round=1)]),
        ]
    )


def a_session() -> Session:
    session = Session(a_store(), SessionConfig(initial_set="easy", rounds=2, seed=0))
    session.arm()
    spec = session.next_trial()
    session.report_outcome(
        OutcomeReport(
            outcome=TrialOutcome.HIT,
            manipulandum=Manipulandum.LEVER,
            reaction_time_ms=240.5,
            reward_ms=100,
        ),
        trial_id=spec.trial_number,
    )
    return session


def test_a_finished_trial_survives_the_seam():
    session = a_session()
    record = session.state().last
    assert record is not None

    written = as_dict(convert.trial_record_to_wire(record))

    assert written["outcome"]["name"] == "HIT"
    assert written["outcome"]["code"] == 1
    assert written["outcome"]["manipulandum"] == "LEVER"
    assert written["outcome"]["reaction_time_ms"] == 240.5
    assert written["accepted"] is True
    # A 64-bit number is a string, and an instant is RFC 3339.
    assert written["trial"]["trial_number"] == "1"
    assert written["ended_at"].endswith("Z")
    # Absent rather than null: the trial was accepted, so there is no reason.
    assert "refusal_reason" not in written


def test_a_whole_session_state_survives_the_seam():
    session = a_session()
    message = convert.session_state_to_wire(
        session.state(),
        armed=True,
        trial_type_set=session.trial_type_set,
        config=session.config,
        policy={
            "name": "default",
            "class_name": "NoPolicy",
            "origin": "default",
            "sha256": None,
            "source": None,
            "state": None,
        },
        policy_errors=[],
    )
    written = as_dict(message)

    assert written["set_name"] == "easy"
    assert written["totals"]["by_outcome"] == {"HIT": 1}
    assert [row["name"] for row in written["counters"]] == ["a", "b"]
    assert written["config"]["ordering"] == "ORDERING_RANDOM_IN_ROUND"
    # `reached` and `fraction` are properties on the dataclass, computed from
    # whichever criterion the rule watches, and are sent so a UI need not know.
    assert written["set_progress"]["reached"] == 1
    assert written["set_progress"]["criterion"] == "TRIAL_COUNT_CRITERION_HITS"


def test_an_omitted_criterion_means_a_different_thing_in_each_place():
    # The one enum two rules share. A switch rule counts hits when it does not
    # say; a stop rule counts accepted trials. UNSPECIFIED cannot mean both, so
    # each caller says which, and this is the test that they still disagree.
    rule = convert.sets.switch_rule_from_wire(sets_pb2.SwitchRule(enabled=True, count=5))
    assert rule.criterion is TrialCountCriterion.HITS

    # Through JSON rather than constructed in Python, because that is the
    # distinction being tested: a field left out of the *document* has no
    # presence, while one written as UNSPECIFIED has presence and asks for the
    # default back. Constructing the message in Python sets presence either way.
    left_out = parse('{"rounds": 3}', config_pb2.ConfigPatch)
    assert convert.config_patch_from_wire(left_out) == {"rounds": 3}

    written_out = parse(
        '{"rounds": 3, "stop_criterion": "TRIAL_COUNT_CRITERION_UNSPECIFIED"}',
        config_pb2.ConfigPatch,
    )
    assert convert.config_patch_from_wire(written_out) == {
        "rounds": 3,
        "stop_criterion": TrialCountCriterion.ACCEPTED_TRIALS,
    }


def test_zero_clears_the_trial_limit_and_absence_leaves_it_alone():
    # The exception the shape cannot express, spelled out in the proto and
    # here: on the config, absent *is* a value meaning no limit, so a patch
    # needs some other way to say "remove it".
    assert convert.config_patch_from_wire(config_pb2.ConfigPatch()) == {}
    assert convert.config_patch_from_wire(config_pb2.ConfigPatch(stop_after_trials=0)) == {
        "stop_after_trials": None
    }
    assert convert.config_patch_from_wire(config_pb2.ConfigPatch(stop_after_trials=50)) == {
        "stop_after_trials": 50
    }


def test_an_absent_precise_fixation_means_fixation_held():
    # The eye monitor is optional, and a rig without one must not refuse every
    # trial. The only field in the inbound message where absent is not false.
    report = convert.outcome_report_from_wire(
        parse(
            '{"trial_id": "1", "outcome": "HIT"}',
            __import__(
                "triald._proto.triald.v1.trial_pb2", fromlist=["OutcomeReport"]
            ).OutcomeReport,
        )
    )
    assert report.precise_fixation is True


def test_a_trial_type_set_round_trips():
    original = a_set()
    returned = convert.trial_type_set_from_wire(convert.trial_type_set_to_wire(original))
    assert returned == original


def test_an_ordering_this_build_does_not_know_is_refused_by_name():
    # Never read as the first variant: a session ordered by something nobody
    # asked for is a session whose balance is silently wrong.
    with pytest.raises(convert.config.Refused):
        convert.config.ordering_from_wire(999)
    assert convert.config.ordering_from_wire(0) is Ordering.RANDOM_IN_ROUND
