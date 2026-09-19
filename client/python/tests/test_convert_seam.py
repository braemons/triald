# SPDX-License-Identifier: AGPL-3.0-or-later
"""The seam, with no daemon and no network.

**What is checked here is that nothing is dropped or mistranslated**, in both
directions, for the fields where getting it wrong is silent: a presence-tracked
field that is absent, an enum whose wire spelling carries a prefix, a number
that means something different when it is zero.

These are the failures a round trip against a running daemon does *not* catch,
because a daemon that answers with its own defaults agrees with a client that
invented the same ones.
"""

from __future__ import annotations

import datetime as dt

import pytest
from triald_client import _wire_conversions as convert
from triald_client._proto.triald.v1 import (
    common_pb2,
    config_pb2,
    policy_pb2,
    session_pb2,
    sets_pb2,
    trial_pb2,
)
from triald_client.api_types import (
    Acceptance,
    ConfigPatch,
    FrameLoss,
    Manipulandum,
    Ordering,
    OutcomeReport,
    SimSettings,
    SwitchRule,
    TrialCountCriterion,
    TrialOutcome,
    TrialType,
    TrialTypeSet,
)

# -- enums ----------------------------------------------------------------------


@pytest.mark.parametrize("ordering", list(Ordering))
def test_every_ordering_survives_a_round_trip(ordering: Ordering):
    assert convert.ordering_from_wire(convert.ordering_to_wire(ordering)) is ordering


@pytest.mark.parametrize("criterion", list(TrialCountCriterion))
def test_every_criterion_survives_a_round_trip(criterion: TrialCountCriterion):
    assert convert.criterion_from_wire(convert.criterion_to_wire(criterion)) is criterion


def test_the_enum_tables_cover_the_wire():
    """Every value the proto defines is translatable, except `UNSPECIFIED`.

    Read from the descriptor rather than listed, so a value added to the proto
    and forgotten here fails instead of being silently read as the default.
    """
    for descriptor, translate in (
        (common_pb2.Ordering.DESCRIPTOR, convert.ordering_from_wire),
        (common_pb2.TrialCountCriterion.DESCRIPTOR, convert.criterion_from_wire),
    ):
        for value in descriptor.values:
            if value.name.endswith("_UNSPECIFIED"):
                continue
            assert translate(value.number) is not None, f"{value.name} has no Python spelling"


def test_an_unspecified_criterion_is_absent_rather_than_a_default():
    # A set with no switch rule has no criterion, and answering ACCEPTED_TRIALS
    # would invent one that a UI would then draw a progress bar for.
    assert convert.criterion_from_wire(common_pb2.TRIAL_COUNT_CRITERION_UNSPECIFIED) is None


def test_an_unspecified_ordering_is_the_daemon_s_default():
    # Unlike a criterion, an absent ordering has a real meaning: the proto says
    # so, and the daemon behaves that way.
    assert (
        convert.ordering_from_wire(common_pb2.ORDERING_UNSPECIFIED) is Ordering.RANDOM_IN_ROUND
    )


def test_an_outcome_code_this_client_has_never_seen_is_kept():
    # A newer daemon, not a broken one: the taxonomy grows by addition, and a
    # client that refused an unknown code would stop working on upgrade.
    assert convert.outcome_code_from_wire(99) == 99
    assert convert.outcome_code_from_wire(1) is TrialOutcome.HIT


# -- presence -------------------------------------------------------------------


def test_an_absent_optional_is_none_rather_than_zero():
    """The failure this exists to stop: `reaction_time_ms` of 0.0 read as a
    reaction time of zero milliseconds rather than as "nobody measured one"."""
    outcome = convert.outcome_from_wire(trial_pb2.Outcome(code=1, name="HIT"))
    assert outcome.reaction_time_ms is None
    assert outcome.terminating_interval is None
    assert outcome.frame_loss is None
    assert outcome.note is None


def test_a_zero_that_was_sent_is_kept():
    message = trial_pb2.Outcome(code=1, name="HIT", reaction_time_ms=0.0)
    assert convert.outcome_from_wire(message).reaction_time_ms == 0.0


def test_an_absent_timestamp_is_none_and_not_the_epoch():
    # protobuf's zero timestamp is 1970-01-01, which is a real moment and not
    # the same thing as "the daemon did not say".
    spec = convert.trial_spec_from_wire(trial_pb2.TrialSpec(trial_number=1))
    assert spec.started_at is None
    assert spec.deadline is None


def test_a_timestamp_comes_back_aware_and_in_utc():
    message = trial_pb2.TrialSpec(trial_number=1)
    message.started_at.FromDatetime(dt.datetime(2026, 9, 19, 10, 45, tzinfo=dt.UTC))
    spec = convert.trial_spec_from_wire(message)
    assert spec.started_at is not None
    assert spec.started_at == dt.datetime(2026, 9, 19, 10, 45, tzinfo=dt.UTC)
    assert spec.started_at.tzinfo is not None  # aware, so arithmetic is unambiguous


# -- the accept flags -----------------------------------------------------------


def test_every_acceptance_flag_travels():
    """All fourteen, in both directions.

    A flag that exists in the proto and is missing from `_ACCEPTANCE_FIELDS`
    would be silently dropped on the way out — the config would look set and
    the daemon would never hear about it.
    """
    descriptor = config_pb2.Acceptance.DESCRIPTOR
    from_proto = {field.name for field in descriptor.fields}  # ty: ignore[unresolved-attribute]
    assert from_proto == set(convert._ACCEPTANCE_FIELDS)

    # An inverted copy, so that a flag stuck at its default would show up.
    inverted = Acceptance(**{name: False for name in convert._ACCEPTANCE_FIELDS})
    assert convert.acceptance_from_wire(convert.acceptance_to_wire(inverted)) == inverted


def test_an_absent_acceptance_flag_takes_the_client_s_default():
    # Absent means "the daemon's default", not False - and the dataclass holds
    # the same defaults the daemon does.
    empty = convert.acceptance_from_wire(config_pb2.Acceptance())
    assert empty == Acceptance()
    assert empty.hit is True and empty.not_started is False


# -- a patch is only what was set -----------------------------------------------


def test_an_empty_patch_sets_nothing():
    message = convert.config_patch_to_wire(ConfigPatch())
    assert message.ListFields() == []


def test_a_patch_carries_only_the_fields_that_were_set():
    message = convert.config_patch_to_wire(ConfigPatch(rounds=7))
    assert [field.name for field, _ in message.ListFields()] == ["rounds"]
    assert message.rounds == 7


def test_a_patch_can_set_a_false():
    # The reason every field of the patch is `optional`: False is a value, and
    # a truthiness test here would make it unsettable.
    message = convert.config_patch_to_wire(ConfigPatch(avoid_repeat=False))
    assert message.HasField("avoid_repeat")
    assert message.avoid_repeat is False


# -- sets -----------------------------------------------------------------------


def test_a_set_round_trips_with_its_rule_and_its_params():
    value = TrialTypeSet(
        name="fixation",
        trial_types=(
            TrialType(
                name="fix_only",
                trials_per_round=4,
                statemachine_graph="fixation",
                reward_ms=120,
                params={"contrast": 0.5},
            ),
        ),
        switch_rule=SwitchRule(
            enabled=True, criterion=TrialCountCriterion.HITS, count=20, target="one_line"
        ),
    )
    back = convert.trial_type_set_from_wire(convert.trial_type_set_to_wire(value))
    assert back.name == value.name
    assert back.trial_types[0].params == {"contrast": 0.5}
    assert back.switch_rule == value.switch_rule


def test_the_daemon_s_own_view_of_a_set_is_not_sent_back():
    # `set_number`, `runnable`, `active` and `trials_per_round` are answers. A
    # client that sent them would be telling the daemon what it knows better.
    value = TrialTypeSet(
        name="x", trial_types=(), set_number=3, runnable=False, active=True, trials_per_round=9
    )
    message = convert.trial_type_set_to_wire(value)
    assert message.set_number == 0
    assert message.runnable is False  # the proto3 default, not the set's True
    assert message.active is False
    assert message.trials_per_round == 0


def test_a_switch_rule_with_no_target_stays_without_one():
    rule = convert.switch_rule_from_wire(sets_pb2.SwitchRule(enabled=False, count=0))
    assert rule.target is None


# -- an outcome report ----------------------------------------------------------


def test_an_outcome_report_carries_every_modifier():
    report = OutcomeReport(
        outcome=TrialOutcome.HIT,
        manipulandum=Manipulandum.LEVER,
        reaction_time_ms=212.5,
        terminating_interval=2,
        precise_fixation=False,
        frame_loss=FrameLoss(interval=1, frame=7),
        reward_ms=140,
        hit_condition=True,
        simulated=False,
        note="looked away first",
    )
    message = convert.outcome_report_to_wire(report, trial_id=42)
    assert message.trial_id == 42
    assert message.outcome == 1
    assert message.manipulandum == 1
    assert message.reaction_time_ms == 212.5
    assert message.terminating_interval == 2
    assert message.precise_fixation is False
    assert (message.frame_loss.interval, message.frame_loss.frame) == (1, 7)
    assert message.reward_ms == 140
    assert message.hit_condition is True
    assert message.note == "looked away first"


def test_an_outcome_report_leaves_out_what_was_not_measured():
    message = convert.outcome_report_to_wire(
        OutcomeReport(outcome=TrialOutcome.EARLY), trial_id=1
    )
    assert not message.HasField("reaction_time_ms")
    assert not message.HasField("terminating_interval")
    assert not message.HasField("frame_loss")
    assert not message.HasField("note")


def test_trial_id_is_always_sent_even_for_trial_zero():
    # `optional` in the proto precisely so that trial 0 is tellable from "no
    # trial named", which the daemon refuses rather than guessing at.
    message = convert.outcome_report_to_wire(
        OutcomeReport(outcome=TrialOutcome.HIT), trial_id=0
    )
    assert message.HasField("trial_id")
    assert message.trial_id == 0


# -- the state ------------------------------------------------------------------


def test_an_empty_state_converts_without_inventing_anything():
    state = convert.session_state_from_wire(session_pb2.SessionState())
    assert state.running is False
    assert state.current is None
    assert state.last is None
    assert state.totals is None
    assert state.config is None
    assert state.policy is None
    assert state.counters == ()
    assert state.recent == ()


def test_a_stream_frame_without_a_state_has_none():
    # The envelope carries a oneof so a later kind of frame can be added. A
    # client that read `state` unconditionally would break on the first one.
    frame = convert.stream_frame_from_wire(session_pb2.StreamFrame(sequence=7))
    assert frame.sequence == 7
    assert frame.state is None


def test_policy_state_comes_back_as_plain_python():
    message = policy_pb2.PolicyInfo(name="staircase", class_name="Staircase")
    message.state.update({"level": 3, "reversals": [1, 2]})
    info = convert.policy_info_from_wire(message)
    assert info.state == {"level": 3.0, "reversals": [1.0, 2.0]}
    assert isinstance(info.state["reversals"], list)  # not a protobuf ListValue


# -- the simulated subject ------------------------------------------------------


def test_sim_settings_round_trip_including_the_per_type_rates():
    settings = SimSettings(hit_rate=0.9, hit_rate_by_type={"fix_only": 0.5})
    back = convert.sim_settings_from_wire(convert.sim_settings_to_wire(settings))
    assert back == settings
