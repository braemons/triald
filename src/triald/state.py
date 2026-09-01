"""What the daemon publishes: the current trial, the session snapshot, the record.

These three types are the daemon's outward face. The same
:class:`SessionState` goes to a policy hook, to an RPC caller, and to the web UI,
so there is one description of what is happening rather than three that drift.

They are all frozen. A policy that could mutate the snapshot it was handed would
be able to corrupt a session by accident, and the RPC layer would have to copy
defensively on every call.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

from triald.counters import ResultCount, TrialCountCriterion
from triald.outcomes import OutcomeReport, TrialOutcome


@dataclasses.dataclass(frozen=True, slots=True)
class TrialSpec:
    """The selection for one trial, published the moment it is made.

    Latched at selection and stable for the whole trial. In particular
    :attr:`recording` is decided here rather than at the end, so a trial that
    began recording finishes recording even if somebody hits pause in the middle
    of it - the behaviour VStim gets right by latching ``m_RecordingTrial`` in
    ``GetNextTrialType()``.
    """

    trial_number: int
    """Monotonic within the session, never reset. VStim's ``m_iTrial``."""

    trial_type_index: int
    """Index into the active set."""

    trial_type_number: int
    """The effective number, extended by the set when that is enabled."""

    trial_type_name: str
    set_name: str
    time_sequence: int
    reward_ms: int

    recording: bool
    """Whether this trial will be written to the session record."""

    paused: bool
    """A pausing trial runs and counts, but is never recorded."""

    started_at: dt.datetime
    """Wall-clock time the selection was made."""

    def as_dict(self) -> dict[str, object]:
        return {
            "trial_number": self.trial_number,
            "trial_type_index": self.trial_type_index,
            "trial_type_number": self.trial_type_number,
            "trial_type_name": self.trial_type_name,
            "set_name": self.set_name,
            "time_sequence": self.time_sequence,
            "reward_ms": self.reward_ms,
            "recording": self.recording,
            "paused": self.paused,
            "started_at": self.started_at.isoformat(),
        }


@dataclasses.dataclass(frozen=True, slots=True)
class SetProgress:
    """How far the active set has got towards its switch rule."""

    set_name: str
    accepted_trials: int
    hits: int
    all_trials: int
    criterion: TrialCountCriterion | None
    """None when the set has no armed rule."""

    target: int | None
    """The count the criterion has to reach, or None when there is no rule."""

    switch_to: str | None

    @property
    def reached(self) -> int:
        """Progress under whichever criterion the rule uses."""
        if self.criterion is TrialCountCriterion.HITS:
            return self.hits
        if self.criterion is TrialCountCriterion.ALL_TRIALS:
            return self.all_trials
        return self.accepted_trials

    @property
    def fraction(self) -> float | None:
        """Progress as 0..1, or None when the set has no armed rule."""
        if not self.target:
            return None
        return min(1.0, self.reached / self.target)

    def as_dict(self) -> dict[str, object]:
        return {
            "set_name": self.set_name,
            "accepted_trials": self.accepted_trials,
            "hits": self.hits,
            "all_trials": self.all_trials,
            "criterion": self.criterion.value if self.criterion else None,
            "target": self.target,
            "switch_to": self.switch_to,
            "reached": self.reached,
            "fraction": self.fraction,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class TrialRecord:
    """One finished trial, as it is written to the session record.

    Carries the policy's own state so an adaptive session can be reconstructed
    afterwards: without it, a staircase's decisions are unexplainable from the
    record alone.
    """

    spec: TrialSpec
    report: OutcomeReport
    accepted: bool
    refusal_reason: str | None
    """Why the trial was not accepted, or None when it was."""

    ended_at: dt.datetime
    policy_state: dict[str, object] | None = None

    def as_dict(self) -> dict[str, object]:
        r = self.report
        return {
            "trial": self.spec.as_dict(),
            "outcome": {
                "code": int(r.outcome),
                "name": r.outcome.name,
                "manipulandum": r.manipulandum.name,
                "reaction_time_ms": r.reaction_time_ms,
                "terminating_interval": r.terminating_interval,
                "precise_fixation": r.precise_fixation,
                "frame_loss": (
                    None
                    if r.frame_loss is None
                    else {"interval": r.frame_loss.interval, "frame": r.frame_loss.frame}
                ),
                "reward_ms": r.reward_ms,
                "hit_condition": r.hit_condition,
                "simulated": r.simulated,
                "note": r.note,
            },
            "accepted": self.accepted,
            "refusal_reason": self.refusal_reason,
            "ended_at": self.ended_at.isoformat(),
            "policy_state": self.policy_state,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class SessionState:
    """Everything a policy, an RPC caller or the web UI can see.

    Read-only by construction. A policy gets exactly this and nothing else, which
    is what keeps a scripting bug from being able to corrupt a session.
    """

    running: bool
    recording: bool
    paused: bool

    current: TrialSpec | None
    """The trial in flight, or None between trials."""

    last: TrialRecord | None
    """The last finished trial."""

    totals: ResultCount
    per_trial_type: list[ResultCount]
    trial_type_names: tuple[str, ...]
    """Names of the active set's trial types, parallel to `per_trial_type`."""

    p_next: tuple[float, ...]
    """Chance of each trial type being drawn next, parallel to `per_trial_type`.

    What the declarative ordering would do. A policy that selects for itself
    makes this advisory - see :meth:`~triald.selection.TrialBag.probabilities`.
    """

    set_name: str
    set_progress: SetProgress
    rounds_completed: int
    rounds_configured: int
    trials_per_round: int
    trials_remaining: int
    """Trials left before the bag refills - the round, or the whole experiment."""

    stop_reason: str | None
    """Why the session stopped, or None while it runs."""

    history: tuple[TrialRecord, ...]
    """Every finished trial this session, oldest first."""

    seed: int
    config: dict[str, object]
    """The resolved session config, exactly as it was armed."""

    @property
    def accepted(self) -> int:
        return self.totals.accepted

    @property
    def hits(self) -> int:
        return self.totals.hits

    def outcomes(self) -> list[TrialOutcome]:
        """Just the outcome codes, oldest first - what a staircase usually wants."""
        return [r.report.outcome for r in self.history]

    def recent(self, n: int = 20) -> tuple[TrialRecord, ...]:
        return self.history[-n:]
