# SPDX-License-Identifier: AGPL-3.0-or-later
"""The trial loop: counting, rounds, stopping, and automatic set switching."""

from __future__ import annotations

import pytest

from triald.counters import TrialCountCriterion
from triald.outcomes import (
    AcceptancePolicy,
    FrameLoss,
    OutcomeReport,
    TrialOutcome,
)
from triald.policy import Policy
from triald.selection import Ordering
from triald.session import Session, SessionConfig, SessionError
from triald.trialtypes import (
    SwitchRule,
    TrialType,
    TrialTypeSet,
    TrialTypeStore,
)


def one_set(name: str = "main", *weights: int, rule: SwitchRule | None = None) -> TrialTypeSet:
    return TrialTypeSet(
        name=name,
        trial_types=[
            TrialType(name=f"{name}_t{i}", trials_per_round=w, reward_ms=100 + i)
            for i, w in enumerate(weights or (2, 2))
        ],
        switch_rule=rule or SwitchRule(),
    )


def make_session(
    store: TrialTypeStore | None = None,
    *,
    policy: Policy | None = None,
    **config_kwargs: object,
) -> Session:
    store = store if store is not None else TrialTypeStore([one_set()])
    config = SessionConfig(
        initial_set=config_kwargs.pop("initial_set", "main"),  # type: ignore[arg-type]
        seed=0,
        **config_kwargs,  # type: ignore[arg-type]
    )
    session = Session(store, config, policy=policy)
    session.arm()
    return session


def run(session: Session, outcome: TrialOutcome, n: int = 1, **kwargs: object) -> None:
    for _ in range(n):
        if not session.running:
            return
        session.next_trial()
        session.report_outcome(OutcomeReport(outcome=outcome, **kwargs))  # type: ignore[arg-type]


# -- arming --------------------------------------------------------------------


def test_arming_refuses_a_set_with_no_trials():
    store = TrialTypeStore([one_set("empty", 0, 0)])
    session = Session(store, SessionConfig(initial_set="empty"))
    with pytest.raises(SessionError, match="no trials in it"):
        session.arm()


def test_arming_refuses_a_switch_chain_with_a_missing_target():
    store = TrialTypeStore(
        [one_set("a", 2, rule=SwitchRule(enabled=True, count=5, target="nowhere"))]
    )
    session = Session(store, SessionConfig(initial_set="a"))
    with pytest.raises(SessionError, match="not in the store"):
        session.arm()


def test_arming_walks_the_whole_chain():
    # a -> b is fine; b -> c is not. Catching it at arm time is the point: the
    # switch itself happens between trials with nobody watching.
    store = TrialTypeStore(
        [
            one_set("a", 2, rule=SwitchRule(enabled=True, count=1, target="b")),
            one_set("b", 2, rule=SwitchRule(enabled=True, count=1, target="c")),
        ]
    )
    session = Session(store, SessionConfig(initial_set="a"))
    with pytest.raises(SessionError, match="'c'"):
        session.arm()


def test_a_switch_loop_is_allowed():
    store = TrialTypeStore(
        [
            one_set("a", 2, rule=SwitchRule(enabled=True, count=1, target="b")),
            one_set("b", 2, rule=SwitchRule(enabled=True, count=1, target="a")),
        ]
    )
    Session(store, SessionConfig(initial_set="a")).arm()  # must not raise


# -- the loop ------------------------------------------------------------------


def test_a_trial_must_be_reported_before_the_next_is_selected():
    session = make_session()
    session.next_trial()
    with pytest.raises(SessionError, match="still in flight"):
        session.next_trial()


def test_reporting_with_no_trial_in_flight_is_an_error():
    session = make_session()
    with pytest.raises(SessionError, match="no trial is in flight"):
        session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT))


def test_trial_numbers_are_monotonic():
    session = make_session()
    run(session, TrialOutcome.HIT, 5)
    assert [r.spec.trial_number for r in session.state().history] == [1, 2, 3, 4, 5]


def test_recording_is_latched_at_selection():
    # Pausing mid-trial must not turn a recording trial into a non-recording one:
    # a trial that began recording finishes recording.
    session = make_session()
    session.start_recording()
    spec = session.next_trial()
    assert spec.recording

    session.pause_recording()
    assert session.state().current is not None
    assert spec.recording  # the latched value did not move


def test_the_graph_name_is_latched_from_the_trial_type():
    # The graph is a name, not a slot: what the record carries has to be the
    # thing an executor was asked for, not an index into a store that can be
    # edited between sessions.
    store = TrialTypeStore(
        [
            TrialTypeSet(
                name="main",
                trial_types=[
                    TrialType(name="go", trials_per_round=1, statemachine_graph="detection"),
                    TrialType(name="catch", trials_per_round=1, statemachine_graph="detection"),
                ],
            )
        ]
    )
    session = make_session(store)

    spec = session.next_trial()
    assert spec.statemachine_graph == "detection"
    assert spec.as_dict()["statemachine_graph"] == "detection"


def test_a_trial_type_with_no_graph_names_none():
    # An empty name means "leave whatever the executor has loaded" - the desk
    # case, and the one every existing set is in.
    session = make_session()
    assert session.next_trial().statemachine_graph == ""


# -- counted versus accepted ----------------------------------------------------


def test_every_outcome_is_counted_even_when_refused():
    session = make_session(acceptance=AcceptancePolicy(not_started=False))
    run(session, TrialOutcome.NOT_STARTED, 3)

    totals = session.state().totals
    assert totals.total == 3
    assert totals.accepted == 0
    assert totals.by_outcome[TrialOutcome.NOT_STARTED] == 3


def test_a_refused_trial_does_not_consume_from_the_bag():
    session = make_session(acceptance=AcceptancePolicy(not_started=False))
    before = session.state().totals.remaining
    run(session, TrialOutcome.NOT_STARTED, 3)
    assert session.state().totals.remaining == before


def test_an_accepted_trial_consumes_from_the_bag():
    session = make_session()
    before = session.state().totals.remaining
    run(session, TrialOutcome.HIT, 1)
    assert session.state().totals.remaining == before - 1


def test_frame_loss_can_refuse_an_otherwise_good_trial():
    session = make_session(acceptance=AcceptancePolicy(frame_loss=False))
    run(session, TrialOutcome.HIT, 1, frame_loss=FrameLoss(interval=1, frame=4))

    totals = session.state().totals
    assert totals.total == 1
    assert totals.hits == 1  # still a hit
    assert totals.accepted == 0  # but it did not count
    assert totals.frame_loss == 1


def test_a_pausing_trial_runs_and_counts_but_is_never_accepted():
    session = make_session()
    session.start_recording()
    session.pause_recording()

    spec = session.next_trial()
    assert spec.paused
    assert not spec.recording

    record = session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT))
    assert not record.accepted
    assert record.refusal_reason == "pausing trial"


# -- rounds and stopping --------------------------------------------------------


def test_a_round_completes_after_its_weights_are_used_up():
    session = make_session(rounds=3)  # 2 + 2 = 4 trials per round
    run(session, TrialOutcome.HIT, 4)
    assert session.state().rounds_completed == 1


def test_stop_when_rounds_done():
    session = make_session(rounds=2, stop_when_rounds_done=True)
    run(session, TrialOutcome.HIT, 8)  # 2 rounds of 4
    assert not session.running
    assert "2 rounds completed" in (session.stop_reason or "")


def test_stop_after_accepted_trials():
    session = make_session(rounds=100, stop_after_trials=5)
    run(session, TrialOutcome.HIT, 20)
    assert not session.running
    assert session.state().totals.accepted == 5


def test_stop_after_accepted_trials_counts_only_accepted_ones():
    session = make_session(
        rounds=100,
        stop_after_trials=3,
        acceptance=AcceptancePolicy(not_started=False),
    )
    run(session, TrialOutcome.NOT_STARTED, 10)
    assert session.running  # none of them counted
    run(session, TrialOutcome.HIT, 3)
    assert not session.running


def test_stop_criterion_hits():
    session = make_session(
        rounds=100, stop_after_trials=3, stop_criterion=TrialCountCriterion.HITS
    )
    # Eye errors are accepted by default, so they fill the round - but they are
    # not hits, and the hit criterion must not see them.
    run(session, TrialOutcome.EYE_ERROR, 10)
    assert session.running
    run(session, TrialOutcome.HIT, 3)
    assert not session.running


def test_stop_criterion_all_trials_counts_refused_ones_too():
    session = make_session(
        rounds=100,
        stop_after_trials=4,
        stop_criterion=TrialCountCriterion.ALL_TRIALS,
        acceptance=AcceptancePolicy(not_started=False),
    )
    run(session, TrialOutcome.NOT_STARTED, 4)
    assert not session.running
    assert session.state().totals.accepted == 0  # none of them counted as accepted


def test_the_stop_rule_is_armed_again_by_a_counter_reset():
    # Latched so it fires once per reset, not on every trial after the count is
    # passed - VStim's m_StoppedAfterTrials.
    session = make_session(rounds=100, stop_after_trials=2)
    run(session, TrialOutcome.HIT, 2)
    assert not session.running

    session.reset_counters()
    session._running = True  # as restarting the experiment controller would
    run(session, TrialOutcome.HIT, 2)
    assert not session.running


def test_stop_uses_at_least_not_equality():
    # VStim compares nDone == TrialsBeforeStop, which never fires again if the
    # counter is ever past the target. ">=" is robust to that.
    session = make_session(rounds=100, stop_after_trials=2)
    run(session, TrialOutcome.HIT, 1)
    assert session.running
    run(session, TrialOutcome.HIT, 1)
    assert not session.running


# -- automatic set switching (#239) ---------------------------------------------


def test_switching_on_hits():
    store = TrialTypeStore(
        [
            one_set(
                "a",
                2,
                2,
                rule=SwitchRule(
                    enabled=True, criterion=TrialCountCriterion.HITS, count=3, target="b"
                ),
            ),
            one_set("b", 2, 2),
        ]
    )
    session = make_session(store, initial_set="a", rounds=100)
    run(session, TrialOutcome.HIT, 3)
    assert session.state().set_name == "b"


def test_switching_on_accepted_trials():
    store = TrialTypeStore(
        [
            one_set(
                "a",
                2,
                2,
                rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.ACCEPTED_TRIALS,
                    count=4,
                    target="b",
                ),
            ),
            one_set("b", 2, 2),
        ]
    )
    session = make_session(store, initial_set="a", rounds=100)
    run(session, TrialOutcome.EYE_ERROR, 4)  # accepted by default, but not hits
    assert session.state().set_name == "b"


def test_a_hit_counts_towards_the_switch_even_when_it_is_refused():
    # VStim reaches this by calling ApplyTrialTypeSetSwitchIfDue() from OnHit()
    # when UpdateRounds() was skipped. A hit that lost a frame is still a hit.
    store = TrialTypeStore(
        [
            one_set(
                "a",
                2,
                2,
                rule=SwitchRule(
                    enabled=True, criterion=TrialCountCriterion.HITS, count=2, target="b"
                ),
            ),
            one_set("b", 2, 2),
        ]
    )
    session = make_session(
        store,
        initial_set="a",
        rounds=100,
        acceptance=AcceptancePolicy(frame_loss=False),
    )
    run(session, TrialOutcome.HIT, 2, frame_loss=FrameLoss(interval=0, frame=1))
    assert session.state().totals.accepted == 0
    assert session.state().set_name == "b"


def test_an_early_hit_does_not_count_towards_the_hit_criterion():
    # Faithful to VStim: only OnHit() touches m_HitsInCurrentSet.
    store = TrialTypeStore(
        [
            one_set(
                "a",
                2,
                2,
                rule=SwitchRule(
                    enabled=True, criterion=TrialCountCriterion.HITS, count=2, target="b"
                ),
            ),
            one_set("b", 2, 2),
        ]
    )
    session = make_session(store, initial_set="a", rounds=100)
    run(session, TrialOutcome.EARLY_HIT, 5)
    assert session.state().set_name == "a"


def test_a_switch_resets_the_new_sets_progress():
    store = TrialTypeStore(
        [
            one_set("a", 2, 2, rule=SwitchRule(enabled=True, count=2, target="b")),
            one_set("b", 2, 2, rule=SwitchRule(enabled=True, count=3, target="a")),
        ]
    )
    session = make_session(store, initial_set="a", rounds=100)
    run(session, TrialOutcome.HIT, 2)

    progress = session.state().set_progress
    assert progress.set_name == "b"
    assert progress.hits == 0
    assert progress.accepted_trials == 0


def test_a_disabled_rule_never_fires():
    store = TrialTypeStore(
        [
            one_set("a", 2, 2, rule=SwitchRule(enabled=False, count=1, target="b")),
            one_set("b", 2, 2),
        ]
    )
    session = make_session(store, initial_set="a", rounds=100)
    run(session, TrialOutcome.HIT, 10)
    assert session.state().set_name == "a"


def test_set_progress_reports_the_right_criterion():
    store = TrialTypeStore(
        [
            one_set(
                "a",
                4,
                rule=SwitchRule(
                    enabled=True, criterion=TrialCountCriterion.HITS, count=10, target="b"
                ),
            ),
            one_set("b", 2),
        ]
    )
    session = make_session(store, initial_set="a", rounds=100)
    run(session, TrialOutcome.HIT, 4)

    progress = session.state().set_progress
    assert progress.criterion is TrialCountCriterion.HITS
    assert progress.reached == 4
    assert progress.target == 10
    assert progress.fraction == pytest.approx(0.4)


# -- extended numbering ---------------------------------------------------------


def test_extended_trial_type_numbers():
    store = TrialTypeStore([one_set("a", 2, 2), one_set("b", 2, 2)])
    session = make_session(store, initial_set="b", rounds=100, extend_trial_type_number=True)
    spec = session.next_trial()
    # "b" is the second set in the store, so 2 * 256 + index.
    assert spec.trial_type_number == 512 + spec.trial_type_index


def test_plain_trial_type_numbers_are_the_index():
    session = make_session()
    spec = session.next_trial()
    assert spec.trial_type_number == spec.trial_type_index


# -- resets ---------------------------------------------------------------------


def test_reset_counters_leaves_the_bag_alone():
    session = make_session()
    run(session, TrialOutcome.HIT, 2)
    remaining = session.state().totals.remaining

    session.reset_counters()
    assert session.state().totals.total == 0
    assert session.state().totals.remaining == remaining


def test_reset_rounds_refills_the_bag():
    session = make_session()
    run(session, TrialOutcome.HIT, 2)
    session.reset_rounds()

    state = session.state()
    assert state.totals.remaining == state.trials_per_round
    assert state.rounds_completed == 0


# -- ordering pass-through ------------------------------------------------------


def test_ascending_ordering_reaches_the_session():
    session = make_session(ordering=Ordering.ASCENDING, rounds=100)
    session.next_trial()
    assert session.state().current is not None
    assert session.state().current.trial_type_index == 0


# -- per-set counter banks -------------------------------------------------------


def two_sets() -> TrialTypeStore:
    return TrialTypeStore([one_set("a", 2, 2), one_set("b", 2, 2)])


def test_counts_are_kept_per_set_when_numbers_are_extended():
    # With the extension on the sets are separate experiments whose trial type 3
    # have nothing to do with each other, so each keeps its own counts.
    session = make_session(
        two_sets(), initial_set="a", rounds=100, extend_trial_type_number=True
    )
    run(session, TrialOutcome.HIT, 4)
    assert sum(c.total for c in session.state().per_trial_type) == 4

    session.load_set("b")
    assert sum(c.total for c in session.state().per_trial_type) == 0

    run(session, TrialOutcome.HIT, 2)
    assert sum(c.total for c in session.state().per_trial_type) == 2

    # Coming back finds set a's counts where it left them, rather than cleared.
    session.load_set("a")
    assert sum(c.total for c in session.state().per_trial_type) == 4


def test_sets_share_one_bank_when_numbers_are_not_extended():
    # Trial type 3 means the same thing in every set - it plays the same objects
    # and shares its name - so the counts belong to the number, not the set.
    session = make_session(
        two_sets(), initial_set="a", rounds=100, extend_trial_type_number=False
    )
    run(session, TrialOutcome.HIT, 4)
    session.load_set("b")

    assert sum(c.total for c in session.state().per_trial_type) == 4


def test_session_totals_climb_across_a_switch():
    session = make_session(two_sets(), initial_set="a", rounds=100)
    run(session, TrialOutcome.HIT, 4)
    session.load_set("b")
    run(session, TrialOutcome.HIT, 2)

    assert session.state().totals.total == 6


def test_reset_counters_clears_every_set():
    session = make_session(
        two_sets(), initial_set="a", rounds=100, extend_trial_type_number=True
    )
    run(session, TrialOutcome.HIT, 4)
    session.load_set("b")
    run(session, TrialOutcome.HIT, 2)

    session.reset_counters()

    assert sum(c.total for c in session.state().per_trial_type) == 0
    session.load_set("a")
    assert sum(c.total for c in session.state().per_trial_type) == 0


# -- the all-trials criterion ----------------------------------------------------


def test_switching_on_all_trials_counts_refused_ones():
    store = TrialTypeStore(
        [
            one_set(
                "a",
                2,
                2,
                rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.ALL_TRIALS,
                    count=3,
                    target="b",
                ),
            ),
            one_set("b", 2, 2),
        ]
    )
    # Not-started errors are refused by default, so they are neither accepted nor
    # hits - but they are completed trials, and this criterion counts them.
    session = make_session(
        store,
        initial_set="a",
        rounds=100,
        acceptance=AcceptancePolicy(not_started=False),
    )
    run(session, TrialOutcome.NOT_STARTED, 3)

    assert session.state().totals.accepted == 0
    assert session.state().set_name == "b"


def test_set_progress_reports_all_three_tallies():
    store = TrialTypeStore(
        [
            one_set(
                "a",
                4,
                rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.ALL_TRIALS,
                    count=10,
                    target="b",
                ),
            ),
            one_set("b", 2),
        ]
    )
    session = make_session(
        store,
        initial_set="a",
        rounds=100,
        acceptance=AcceptancePolicy(eye_error=False),
    )
    run(session, TrialOutcome.HIT, 2)
    run(session, TrialOutcome.EYE_ERROR, 3)

    progress = session.state().set_progress
    assert progress.hits == 2
    assert progress.accepted_trials == 2  # the eye errors were refused
    assert progress.all_trials == 5
    assert progress.reached == 5  # the rule counts all trials


# -- sequences -------------------------------------------------------------------
#
# There is no separate "sequence" type: a sequence is what a chain of per-set
# rules makes. Two sets pointing at each other alternate; three walk in order;
# the last one having no rule ends the walk. Tested explicitly because it is the
# behaviour a training session is actually left alone with overnight.


def sequence_store(*names: str, count: int = 2) -> TrialTypeStore:
    """Sets chained head to tail, the last one with no rule."""
    sets = []
    for i, name in enumerate(names):
        rule = (
            SwitchRule(
                enabled=True,
                criterion=TrialCountCriterion.HITS,
                count=count,
                target=names[i + 1],
            )
            if i + 1 < len(names)
            else SwitchRule()
        )
        sets.append(one_set(name, 2, 2, rule=rule))
    return TrialTypeStore(sets)


def test_a_three_set_sequence_walks_in_order():
    session = make_session(
        sequence_store("fixation", "one_line", "one_half_cyc", count=2),
        initial_set="fixation",
        rounds=100,
    )

    visited = [session.state().set_name]
    for _ in range(3):
        run(session, TrialOutcome.HIT, 2)
        visited.append(session.state().set_name)

    assert visited == ["fixation", "one_line", "one_half_cyc", "one_half_cyc"]


def test_the_last_set_in_a_sequence_keeps_running():
    session = make_session(sequence_store("a", "b", count=2), initial_set="a", rounds=100)
    run(session, TrialOutcome.HIT, 20)

    assert session.state().set_name == "b"
    assert session.running


def test_two_sets_pointing_at_each_other_alternate():
    store = TrialTypeStore(
        [
            one_set(
                "easy",
                2,
                2,
                rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.HITS,
                    count=3,
                    target="hard",
                ),
            ),
            one_set(
                "hard",
                2,
                2,
                rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.HITS,
                    count=3,
                    target="easy",
                ),
            ),
        ]
    )
    session = make_session(store, initial_set="easy", rounds=100)

    visited = []
    for _ in range(4):
        run(session, TrialOutcome.HIT, 3)
        visited.append(session.state().set_name)

    assert visited == ["hard", "easy", "hard", "easy"]


def test_each_set_in_a_sequence_uses_its_own_criterion_and_count():
    store = TrialTypeStore(
        [
            one_set(
                "a",
                2,
                2,
                rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.HITS,
                    count=2,
                    target="b",
                ),
            ),
            one_set(
                "b",
                2,
                2,
                rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.ALL_TRIALS,
                    count=5,
                    target="c",
                ),
            ),
            one_set("c", 2, 2),
        ]
    )
    session = make_session(store, initial_set="a", rounds=100)

    run(session, TrialOutcome.HIT, 2)
    assert session.state().set_name == "b"

    # b counts every completed trial, so refused ones move it along too.
    run(session, TrialOutcome.CANCELLED, 5)
    assert session.state().set_name == "c"


def test_stopping_wins_over_switching():
    # There is nothing to switch to once the experiment is ending, and VStim
    # orders these the same way in OnTrialCompleted().
    store = TrialTypeStore(
        [
            one_set(
                "a",
                2,
                2,
                rule=SwitchRule(
                    enabled=True,
                    criterion=TrialCountCriterion.HITS,
                    count=3,
                    target="b",
                ),
            ),
            one_set("b", 2, 2),
        ]
    )
    session = make_session(store, initial_set="a", rounds=100, stop_after_trials=3)
    run(session, TrialOutcome.HIT, 3)

    assert not session.running
    assert session.state().set_name == "a"
