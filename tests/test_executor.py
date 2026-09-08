"""Turning what an executor published into the report triald acts on.

Dictionaries in, an `OutcomeReport` out. No network, no daemon, no device -- the
shape an executor publishes is a thing triald can be checked against on its own,
which is what stops the translation being a belief that is only tested by
running a rig.
"""

from __future__ import annotations

import pytest

from triald.executor import (
    ExecutorError,
    TrialConfiguration,
    is_a_finished_trial,
    outcome_from_events,
    reaction_time_milliseconds,
)
from triald.outcomes import Manipulandum, TrialOutcome


def visit(
    trial_id: int = 1,
    *,
    state: str = "Wait",
    exit_cause: str = "timeout",
    microseconds: int = 500_000,
) -> dict:
    return {
        "kind": "visit",
        "trial_id": trial_id,
        "state_name": state,
        "exit_cause": exit_cause,
        "measured_duration_microseconds": microseconds,
    }


def result(trial_id: int = 1, *, outcome: str = "HIT", cancel_reason: str = "NONE") -> dict:
    return {
        "kind": "trial_result",
        "trial_id": trial_id,
        "outcome": outcome,
        "cancel_reason": cancel_reason,
    }


# -- what ends a trial ----------------------------------------------------------


def test_only_a_result_ends_a_trial():
    # An executor publishes a great deal; one kind of it means "this trial is
    # over and here is how".
    assert is_a_finished_trial(result())
    assert not is_a_finished_trial(visit())
    assert not is_a_finished_trial({"kind": "trial_started", "trial_id": 1})
    assert not is_a_finished_trial({})


# -- the outcome ----------------------------------------------------------------


def test_the_outcome_is_the_one_the_executor_named():
    report = outcome_from_events(1, [visit(), result(outcome="LATE")])
    assert report.outcome is TrialOutcome.LATE
    assert report.simulated is False


def test_an_outcome_name_triald_does_not_know_is_refused_with_the_alternatives():
    # The two sides spell the eleven .tdr outcomes independently, so this is
    # where a drift shows up -- and it says what the legal names are rather than
    # leaving somebody to guess at EARLY_WRONG_RESPONSE from a KeyError.
    with pytest.raises(ExecutorError) as refused:
        outcome_from_events(1, [result(outcome="SPLENDID")])
    assert "SPLENDID" in str(refused.value)
    assert "EARLY_WRONG_RESPONSE" in str(refused.value)


def test_events_for_another_trial_are_ignored_rather_than_merged():
    # A mixed batch is a bug upstream. Averaging two trials together is worse
    # than dropping one, and dropping one is what the missing-result error is.
    events = [visit(2, exit_cause="transition"), result(2, outcome="EARLY"), result(1)]
    report = outcome_from_events(1, events)
    assert report.outcome is TrialOutcome.HIT
    assert report.reaction_time_ms is None  # trial 2's visit was not borrowed


def test_no_result_for_this_trial_is_an_error_and_not_an_empty_report():
    with pytest.raises(ExecutorError, match="no result for trial 7"):
        outcome_from_events(7, [visit(7), visit(7)])


def test_two_results_for_one_trial_are_refused():
    # One trial ends once. Picking one of two would be picking at random.
    with pytest.raises(ExecutorError, match="one trial ends once"):
        outcome_from_events(1, [result(), result(outcome="LATE")])


# -- the reaction time, which is triald's interpretation ------------------------


def test_the_reaction_time_is_the_last_state_a_response_left():
    events = [
        visit(state="Foreperiod", exit_cause="timeout", microseconds=500_000),
        visit(state="Cue", exit_cause="transition", microseconds=183_044),
        result(),
    ]
    assert outcome_from_events(1, events).reaction_time_ms == pytest.approx(183.044)


def test_a_trial_that_timed_out_has_no_reaction_time_rather_than_zero():
    # Zero is a measurement. A trial where nothing responded has none, and the
    # .tdr keeps that distinction because analysis relies on it.
    assert reaction_time_milliseconds([visit(exit_cause="timeout")]) is None
    assert outcome_from_events(1, [visit(), result()]).reaction_time_ms is None


def test_a_visit_with_no_measurement_gives_no_reaction_time():
    # A truncated path can name the state without its duration. None, not a
    # crash and not a zero that looks like an instant response.
    torn = visit(exit_cause="transition")
    del torn["measured_duration_microseconds"]
    assert reaction_time_milliseconds([torn]) is None


def test_no_visits_at_all_is_not_a_crash():
    # The executor truncates long paths, and a cancelled trial may have none.
    report = outcome_from_events(1, [result(outcome="CANCELLED", cancel_reason="HOST")])
    assert report.reaction_time_ms is None
    assert report.terminating_interval is None


# -- what triald deliberately does not learn from an executor -------------------


def test_the_veto_fields_are_left_for_whoever_can_observe_them():
    # precise_fixation comes from an eye monitor and frame_loss from vstimd.
    # Either can veto acceptance on its own, and an executor has never heard of
    # either -- so they stay at their defaults rather than being invented.
    report = outcome_from_events(1, [visit(), result()])
    assert report.precise_fixation is True
    assert report.frame_loss is None
    assert report.manipulandum is Manipulandum.NONE


def test_a_cancellation_keeps_the_executors_own_reason():
    # Only the executor knows a host cancelling from a link that went away.
    report = outcome_from_events(1, [result(outcome="CANCELLED", cancel_reason="LINK_LOST")])
    assert report.outcome is TrialOutcome.CANCELLED
    assert report.note is not None and "LINK_LOST" in report.note


def test_a_finished_trial_carries_no_note():
    assert outcome_from_events(1, [result()]).note is None


# -- what goes out --------------------------------------------------------------


def test_a_configuration_names_a_graph_and_never_the_condition():
    # An executor is configured *from* the trial type and never learns which
    # condition it is running, which is what keeps firmware stable while
    # paradigms change.
    configuration = TrialConfiguration(trial_id=3, statemachine_graph="detection")
    assert set(vars(TrialConfiguration).get("__slots__", ())) == {
        "trial_id",
        "statemachine_graph",
        "cap_milliseconds",
    }
    assert configuration.cap_milliseconds == 0


def test_a_configuration_that_names_no_graph_leaves_whatever_is_loaded():
    assert TrialConfiguration(trial_id=1).statemachine_graph == ""
