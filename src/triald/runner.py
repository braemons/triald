"""Driving a session against a behaviour source.

The loop in :func:`run_session` is the same one whether the outcomes come from a
microcontroller or from a simulated subject, which is the point of the
:class:`~triald.behaviour.BehaviourSource` interface: ``triald sim`` exercises the
real code path rather than a parallel one written for testing.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable

from triald.behaviour import BehaviourSource, SimulatedBehaviourSource, TrialParameters
from triald.session import Session
from triald.state import TrialRecord

log = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class RunSummary:
    """What a finished run amounted to."""

    trials: int
    accepted: int
    hits: int
    rounds_completed: int
    final_set: str
    stop_reason: str | None
    policy_errors: int

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def run_trial(session: Session, source: BehaviourSource) -> TrialRecord:
    """Select a trial, run it against `source`, and report what came back.

    One turn of the loop, on its own, so that everything which drives a session
    a trial at a time - the web UI's step buttons, an interactive client, a test
    - goes through the same four calls the full run does rather than a
    reimplementation of them that can drift.

    Raises:
        SessionError: if the session is not running, or a trial is already in
            flight.
        BehaviourSourceError: if the source will not arm, or answers for another
            trial.
    """
    spec = session.next_trial()

    # Only the simulator is told the condition; a real source never is.
    if isinstance(source, SimulatedBehaviourSource):
        source.set_current_trial(spec)

    source.arm(TrialParameters(trial_id=spec.trial_number, reward_ms=spec.reward_ms))
    report = source.result(spec.trial_number)
    return session.report_outcome(report)


def run_session(
    session: Session,
    source: BehaviourSource,
    *,
    max_trials: int | None = None,
    on_trial: Callable[[TrialRecord], None] | None = None,
) -> RunSummary:
    """Run `session` against `source` until it stops.

    Args:
        max_trials: a hard ceiling, independent of the session's own stop
            conditions. Always set one in a simulation - a policy bug that never
            satisfies its stop condition would otherwise spin for ever.
        on_trial: called after every finished trial, for progress output.
    """
    if not session.running:
        session.arm()

    trials = 0
    while session.running:
        if max_trials is not None and trials >= max_trials:
            session.stop(f"reached the {max_trials}-trial ceiling")
            break

        record = run_trial(session, source)
        trials += 1

        if on_trial is not None:
            on_trial(record)

    state = session.state()
    return RunSummary(
        trials=trials,
        accepted=state.totals.accepted,
        hits=state.totals.hits,
        rounds_completed=state.rounds_completed,
        final_set=state.set_name,
        stop_reason=session.stop_reason,
        policy_errors=len(session.policy_errors),
    )
