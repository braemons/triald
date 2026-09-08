"""What the runner hands a behaviour source before a trial runs."""

from __future__ import annotations

from triald.behaviour import BehaviourSource, TrialParameters
from triald.outcomes import OutcomeReport, TrialOutcome
from triald.runner import run_trial
from triald.session import Session, SessionConfig
from triald.trialtypes import TrialType, TrialTypeSet, TrialTypeStore


class RecordingSource(BehaviourSource):
    """Answers HIT to everything and keeps what it was armed with."""

    def __init__(self) -> None:
        self.armed: list[TrialParameters] = []

    def arm(self, params: TrialParameters) -> None:
        self.armed.append(params)

    def result(self, trial_id: int) -> OutcomeReport:
        return OutcomeReport(outcome=TrialOutcome.HIT)


def make_session(*graphs: str) -> Session:
    store = TrialTypeStore(
        [
            TrialTypeSet(
                name="main",
                trial_types=[
                    TrialType(
                        name=f"t{i}",
                        trials_per_round=1,
                        reward_ms=100 + i,
                        statemachine_graph=g,
                    )
                    for i, g in enumerate(graphs)
                ],
            )
        ]
    )
    session = Session(store, SessionConfig(initial_set="main", rounds=100, seed=0))
    session.arm()
    return session


def test_the_graph_name_reaches_the_behaviour_source():
    # The whole point of naming the graph on the trial type: an executor is
    # configured from the condition without ever learning what the condition is.
    session = make_session("detection", "detection")
    source = RecordingSource()

    record = run_trial(session, source)

    assert source.armed[-1].statemachine_graph == "detection"
    assert source.armed[-1].trial_id == record.spec.trial_number
    assert source.armed[-1].reward_ms == record.spec.reward_ms


def test_every_trial_is_armed_with_its_own_graph():
    # Two conditions on different machines, so a stale graph on the executor
    # would show up as the wrong one being asked for.
    session = make_session("detection", "discrimination")
    source = RecordingSource()

    for _ in range(6):
        run_trial(session, source)

    asked = {p.statemachine_graph for p in source.armed}
    assert asked == {"detection", "discrimination"}


def test_the_trial_type_is_never_sent():
    # An executor is configured from the trial type and never told which
    # condition it is running - that is what keeps firmware stable while
    # paradigms change.
    session = make_session("detection", "discrimination")
    source = RecordingSource()

    run_trial(session, source)

    fields = set(vars(TrialParameters).get("__slots__", ()))
    assert fields == {"trial_id", "statemachine_graph", "reward_ms"}
