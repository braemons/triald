# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scripting surface, and the rule that a policy bug never ends a session."""

from __future__ import annotations

from pathlib import Path

import pytest

from triald.outcomes import OutcomeReport, TrialOutcome
from triald.policy import Policy, PolicyError, load_policy
from triald.session import Session, SessionConfig
from triald.state import SessionState, TrialRecord
from triald.trialtypes import TrialType, TrialTypeSet, TrialTypeStore


def store() -> TrialTypeStore:
    return TrialTypeStore(
        [
            TrialTypeSet(
                name="main",
                trial_types=[
                    TrialType(name="easy", trials_per_round=2),
                    TrialType(name="hard", trials_per_round=2),
                ],
            )
        ]
    )


def session_with(policy: Policy, **kwargs: object) -> Session:
    session = Session(
        store(),
        SessionConfig(initial_set="main", seed=0, rounds=100, **kwargs),  # type: ignore[arg-type]
        policy=policy,
    )
    session.arm()
    return session


def run(session: Session, n: int, outcome: TrialOutcome = TrialOutcome.HIT) -> None:
    for _ in range(n):
        if not session.running:
            return
        session.next_trial()
        session.report_outcome(OutcomeReport(outcome=outcome))


# -- the hooks ------------------------------------------------------------------


def test_a_policy_can_choose_the_trial_type_by_name():
    class AlwaysHard(Policy):
        def select_trial(self, state: SessionState) -> str:
            return "hard"

    session = session_with(AlwaysHard())
    run(session, 5)
    assert {r.spec.trial_type_name for r in session.state().history} == {"hard"}


def test_a_policy_can_choose_by_index():
    class AlwaysFirst(Policy):
        def select_trial(self, state: SessionState) -> int:
            return 0

    session = session_with(AlwaysFirst())
    run(session, 4)
    assert {r.spec.trial_type_index for r in session.state().history} == {0}


def test_returning_none_falls_through_to_the_declarative_ordering():
    class Passive(Policy):
        def select_trial(self, state: SessionState) -> None:
            return None

    session = session_with(Passive())
    run(session, 8)
    # The weights are equal, so both types must appear.
    assert len({r.spec.trial_type_index for r in session.state().history}) == 2


def test_should_stop_ends_the_session():
    class StopAtThree(Policy):
        def should_stop(self, state: SessionState) -> bool:
            return state.totals.accepted >= 3

    session = session_with(StopAtThree())
    run(session, 20)
    assert not session.running
    assert "policy" in (session.stop_reason or "")


def test_on_outcome_sees_every_trial_and_its_acceptance():
    seen: list[tuple[int, bool]] = []

    class Watcher(Policy):
        def on_outcome(self, record: TrialRecord, state: SessionState) -> None:
            seen.append((record.spec.trial_number, record.accepted))

    session = session_with(Watcher())
    run(session, 3)
    assert seen == [(1, True), (2, True), (3, True)]


def test_snapshot_lands_in_the_trial_record():
    class Counting(Policy):
        def __init__(self) -> None:
            self.n = 0

        def on_outcome(self, record: TrialRecord, state: SessionState) -> None:
            self.n += 1

        def snapshot(self) -> dict[str, object]:
            return {"n": self.n}

    session = session_with(Counting())
    run(session, 3)
    assert session.state().history[-1].policy_state == {"n": 2}


# -- surviving a broken policy ---------------------------------------------------


def test_a_raising_select_trial_does_not_end_the_session():
    class Broken(Policy):
        def select_trial(self, state: SessionState) -> str:
            raise RuntimeError("boom")

    session = session_with(Broken())
    run(session, 5)

    assert session.running
    assert len(session.state().history) == 5
    assert all(e["hook"] == "select_trial" for e in session.policy_errors)


def test_a_raising_on_outcome_does_not_end_the_session():
    class Broken(Policy):
        def on_outcome(self, record: TrialRecord, state: SessionState) -> None:
            raise ValueError("nope")

    session = session_with(Broken())
    run(session, 3)
    assert session.running
    assert len(session.policy_errors) == 3


def test_an_unknown_trial_type_falls_back_rather_than_failing():
    class Confused(Policy):
        def select_trial(self, state: SessionState) -> str:
            return "no_such_type"

    session = session_with(Confused())
    run(session, 3)

    assert session.running
    assert len(session.state().history) == 3
    assert any("no_such_type" in str(e["error"]) for e in session.policy_errors)


def test_policy_errors_record_which_trial_they_happened_on():
    class Flaky(Policy):
        def on_outcome(self, record: TrialRecord, state: SessionState) -> None:
            if record.spec.trial_number == 2:
                raise RuntimeError("only trial 2")

    session = session_with(Flaky())
    run(session, 4)

    assert len(session.policy_errors) == 1
    assert session.policy_errors[0]["trial_number"] == 2


# -- loading --------------------------------------------------------------------


def test_load_policy_finds_the_single_subclass(tmp_path: Path):
    path = tmp_path / "mine.py"
    path.write_text(
        "from triald import Policy\n"
        "class Mine(Policy):\n"
        "    def select_trial(self, state):\n"
        "        return 'easy'\n",
        encoding="utf-8",
    )
    policy = load_policy(path)
    assert type(policy).__name__ == "Mine"


def test_load_policy_reports_a_missing_file(tmp_path: Path):
    with pytest.raises(PolicyError, match="no such policy file"):
        load_policy(tmp_path / "absent.py")


def test_load_policy_reports_an_import_error(tmp_path: Path):
    path = tmp_path / "bad.py"
    path.write_text("import a_module_that_does_not_exist\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="raised on import"):
        load_policy(path)


def test_load_policy_refuses_a_file_with_no_policy(tmp_path: Path):
    path = tmp_path / "empty.py"
    path.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(PolicyError, match="no Policy subclass"):
        load_policy(path)


def test_load_policy_refuses_an_ambiguous_file(tmp_path: Path):
    path = tmp_path / "two.py"
    path.write_text(
        "from triald import Policy\nclass A(Policy):\n    pass\nclass B(Policy):\n    pass\n",
        encoding="utf-8",
    )
    with pytest.raises(PolicyError, match="more than one"):
        load_policy(path)
