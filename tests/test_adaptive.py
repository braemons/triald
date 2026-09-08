# SPDX-License-Identifier: AGPL-3.0-or-later
"""Up/down staircases, and one end-to-end run through the session loop."""

from __future__ import annotations

import random

from triald.adaptive import Staircase, WeightedUpDown
from triald.behaviour import SimulatedBehaviourSource
from triald.outcomes import TrialOutcome
from triald.policy import Policy
from triald.runner import run_session
from triald.session import Session, SessionConfig
from triald.state import SessionState, TrialRecord
from triald.trialtypes import TrialType, TrialTypeSet, TrialTypeStore


def test_two_down_one_up_needs_two_correct_to_step_harder():
    s = Staircase(n_levels=10, level=5, n_down=2)
    assert s.update(correct=True) == 5  # one is not enough
    assert s.update(correct=True) == 6


def test_a_single_error_steps_easier():
    s = Staircase(n_levels=10, level=5, n_down=2)
    assert s.update(correct=False) == 4


def test_a_correct_run_is_broken_by_an_error():
    s = Staircase(n_levels=10, level=5, n_down=3)
    s.update(correct=True)
    s.update(correct=True)
    s.update(correct=False)  # resets the run
    s.update(correct=True)
    s.update(correct=True)
    assert s.level == 4  # only the error moved it


def test_the_staircase_stays_inside_the_ladder():
    s = Staircase(n_levels=3, level=0, n_down=1)
    for _ in range(10):
        s.update(correct=True)
    assert s.level == 2

    for _ in range(10):
        s.update(correct=False)
    assert s.level == 0


def test_reversals_are_counted():
    s = Staircase(n_levels=10, level=5, n_down=1)
    s.update(correct=True)  # up
    s.update(correct=False)  # down - one reversal
    s.update(correct=True)  # up - two
    assert s.reversals == 2


def test_threshold_is_none_before_there_are_enough_reversals():
    s = Staircase(n_levels=10, level=5, n_down=1)
    s.update(correct=True)
    assert s.threshold(last_n_reversals=6) is None


def test_weighted_up_down_steps_on_every_response():
    s = WeightedUpDown(n_levels=20, level=10, step_up=1, step_down=3)
    assert s.update(correct=True) == 11
    assert s.update(correct=False) == 8


def test_snapshot_carries_what_drove_the_decisions():
    s = Staircase(n_levels=10, level=4)
    s.update(correct=True)
    snapshot = s.snapshot()
    assert snapshot["level"] == 4
    assert snapshot["correct_run"] == 1


# -- through the whole loop -----------------------------------------------------


def test_a_staircase_policy_runs_end_to_end():
    """The wiring, not the class in isolation: policy -> session -> subject."""

    levels = [f"contrast_{i}" for i in range(6)]
    store = TrialTypeStore(
        [
            TrialTypeSet(
                name="main",
                trial_types=[
                    TrialType(name=name, trials_per_round=1, params={"contrast": i / 5})
                    for i, name in enumerate(levels)
                ],
            )
        ]
    )

    class StaircasePolicy(Policy):
        def on_session_start(self, state: SessionState) -> None:
            self.stair = Staircase(n_levels=len(levels), level=0, n_down=2)

        def select_trial(self, state: SessionState) -> str:
            return levels[self.stair.level]

        def on_outcome(self, record: TrialRecord, state: SessionState) -> None:
            if record.accepted:
                self.stair.update(record.report.outcome is TrialOutcome.HIT)

        def snapshot(self) -> dict[str, object]:
            return self.stair.snapshot()

    policy = StaircasePolicy()
    session = Session(
        store,
        SessionConfig(initial_set="main", rounds=1000, seed=7),
        policy=policy,
    )
    subject = SimulatedBehaviourSource(hit_rate=0.9, rng=random.Random(7))

    summary = run_session(session, subject, max_trials=120)

    assert summary.trials == 120
    assert summary.policy_errors == 0
    # A 90% subject on a 2-down-1-up staircase should climb well off the floor.
    assert policy.stair.level > 0
    # And the level that actually ran is in the record.
    assert session.state().history[-1].policy_state is not None
