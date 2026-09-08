# SPDX-License-Identifier: AGPL-3.0-or-later
"""The trial that nobody ever reports, and how triald notices for itself.

Nothing is responsible for delivering an outcome, and that is correct: an
executor publishes what it observed and assumes nobody read it, because it
cannot know whether a consumer exists or is running a session. **Only the side
that is waiting can tell "not yet" from "never."**

Without a deadline, a subscription that dies is a session that quietly stops --
no error, no record, and a trial number that has to be explained months later.
"""

from __future__ import annotations

import datetime as dt

import pytest

from triald.outcomes import AcceptancePolicy, OutcomeReport, TrialOutcome
from triald.session import Session, SessionConfig
from triald.trialtypes import TrialType, TrialTypeSet, TrialTypeStore

START = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.UTC)


class Clock:
    """A hand the test moves, so nothing sleeps."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += dt.timedelta(seconds=seconds)


def make_session(cap_ms: int = 5000, **config: object) -> tuple[Session, Clock]:
    store = TrialTypeStore(
        [
            TrialTypeSet(
                name="main",
                trial_types=[
                    TrialType(name="a", trials_per_round=1, reward_ms=100),
                    TrialType(name="b", trials_per_round=1, reward_ms=100),
                ],
            )
        ]
    )
    clock = Clock()
    session = Session(
        store,
        SessionConfig(initial_set="main", seed=0, rounds=100, trial_cap_ms=cap_ms, **config),  # type: ignore[arg-type]
        clock=clock,
    )
    session.arm()
    return session, clock


# -- the deadline itself --------------------------------------------------------


def test_the_deadline_is_latched_at_selection():
    # Latched rather than computed on demand, so the record says what this trial
    # was *allowed* to take -- the number somebody needs when asking why a
    # session is full of NEVER_FINISHED.
    session, _ = make_session(cap_ms=5000)
    spec = session.next_trial()
    assert spec.deadline == START + dt.timedelta(seconds=5)
    assert spec.as_dict()["deadline"] == spec.deadline.isoformat()


def test_no_cap_means_no_deadline_and_waiting_for_ever():
    # The simulator cannot be late -- its outcome is synchronous -- and a desk
    # session somebody is watching does not want a watchdog.
    session, clock = make_session(cap_ms=0)
    spec = session.next_trial()
    assert spec.deadline is None

    clock.advance(60 * 60 * 24)
    assert session.overdue() is False
    assert session.expire_overdue_trial() is None
    assert session.state().current is not None


def test_nothing_is_overdue_when_no_trial_is_in_flight():
    session, clock = make_session()
    clock.advance(3600)
    assert session.overdue() is False
    assert session.expire_overdue_trial() is None


def test_a_trial_is_not_overdue_before_its_deadline():
    session, clock = make_session(cap_ms=5000)
    session.next_trial()

    clock.advance(4.9)
    assert session.overdue() is False
    assert session.expire_overdue_trial() is None

    # On the deadline, not only past it: a cap is the longest a trial may take.
    clock.advance(0.1)
    assert session.overdue() is True


# -- what expiring does ---------------------------------------------------------


def test_an_expired_trial_is_recorded_rather_than_dropped():
    # A gap in the trial numbering is a thing somebody has to explain later.
    # NEVER_FINISHED explains itself.
    session, clock = make_session(cap_ms=2000)
    spec = session.next_trial()
    clock.advance(3)

    record = session.expire_overdue_trial()
    assert record is not None
    assert record.spec.trial_number == spec.trial_number
    assert record.report.outcome is TrialOutcome.NEVER_FINISHED
    assert session.state().history[-1] is record


def test_the_note_says_what_was_waited_for_and_how_long():
    session, clock = make_session(cap_ms=2000)
    session.next_trial()
    clock.advance(7.5)

    note = session.expire_overdue_trial().report.note
    assert "trial 1" in note
    assert "2000 ms" in note
    assert "7.5 s" in note


def test_an_expired_trial_is_never_accepted():
    # A trial nobody observed must not consume from the round, move a set
    # towards its switch rule, or count towards a stop condition.
    session, clock = make_session(cap_ms=1000)
    session.next_trial()
    clock.advance(2)
    record = session.expire_overdue_trial()

    assert record.accepted is False
    totals = session.state().totals
    assert totals.total == 1  # counted: every outcome is
    assert totals.accepted == 0


def test_the_default_acceptance_refuses_it_and_nobody_has_to_remember_to():
    assert AcceptancePolicy().accepts_outcome(TrialOutcome.NEVER_FINISHED) is False


def test_the_session_carries_on_and_the_next_trial_can_be_selected():
    # The whole point: a dead executor costs one trial, not the session.
    session, clock = make_session(cap_ms=1000)
    session.next_trial()
    clock.advance(2)
    session.expire_overdue_trial()

    assert session.running
    assert session.state().current is None
    assert session.next_trial().trial_number == 2


def test_expiring_twice_does_nothing_the_second_time():
    # It is called on a timer, so it must be a no-op whenever there is nothing
    # overdue -- which is almost always.
    session, clock = make_session(cap_ms=1000)
    session.next_trial()
    clock.advance(2)

    assert session.expire_overdue_trial() is not None
    assert session.expire_overdue_trial() is None
    assert session.state().totals.total == 1


def test_a_real_outcome_arriving_first_wins():
    # The ordinary case, and the one the watchdog must not steal: the trial was
    # answered inside its cap, so there is nothing overdue afterwards.
    session, clock = make_session(cap_ms=5000)
    session.next_trial()
    clock.advance(1)
    session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT), trial_id=1)

    clock.advance(60)
    assert session.overdue() is False
    assert session.state().history[-1].report.outcome is TrialOutcome.HIT


def test_a_late_outcome_after_expiry_is_refused_rather_than_attributed():
    """The failure this all exists inside of.

    An executor that was merely slow, not dead, answers *after* triald gave up.
    By then the next trial is in flight, and accepting the answer would attribute
    it to the wrong trial -- the exact mislabelling `trial_id` exists to stop.
    """
    session, clock = make_session(cap_ms=1000)
    session.next_trial()
    clock.advance(2)
    session.expire_overdue_trial()

    session.next_trial()  # trial 2 is now in flight
    with pytest.raises(Exception, match="trial 2 is the one in flight"):
        session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT), trial_id=1)


# -- the cap as a setting -------------------------------------------------------


def test_the_cap_can_be_changed_while_a_session_runs():
    # It is a watchdog, not a paradigm parameter: somebody tightening it after
    # watching a rig should not have to re-arm and lose the counters.
    session, clock = make_session(cap_ms=10_000)
    session.next_trial()
    session.report_outcome(OutcomeReport(outcome=TrialOutcome.HIT), trial_id=1)

    assert session.reconfigure({"trial_cap_ms": 1000}) == ["trial_cap_ms"]
    assert session.next_trial().deadline == clock.now + dt.timedelta(seconds=1)


def test_changing_the_cap_does_not_move_the_deadline_of_a_trial_in_flight():
    # Latched means latched. A trial judged against a cap it did not start under
    # is a trial nobody can reason about afterwards.
    session, _ = make_session(cap_ms=10_000)
    spec = session.next_trial()
    session.reconfigure({"trial_cap_ms": 1})

    assert spec.deadline == START + dt.timedelta(seconds=10)
    assert session.overdue() is False
