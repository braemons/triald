# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trial outcomes, their modifiers, and the rules that decide whether one counts.

The numeric values of :class:`TrialOutcome` are a wire contract, not an
implementation detail: every ``.tdr`` file the lab has ever written encodes them,
and every analysis script decodes them. They match ``TDR::TrialOutcome`` in
VStim's ``VStimLib/TDR.h`` exactly and must not be renumbered.

The distinction this module exists to keep straight is **counted** versus
**accepted**. Every reported outcome is counted. Only an accepted one consumes a
slot in the round, advances the round, and moves a set towards its switch rule.
Acceptance is decided by three independent things: the outcome's own accept flag,
whether frame loss occurred, and whether fixation was precise. Any of the three
can veto on its own.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import ClassVar


class TrialOutcome(enum.IntEnum):
    """How a trial ended. Values are the ``.tdr`` wire contract; never renumber."""

    UNDETERMINED = -1
    """Nothing decided yet - the trial is still in flight."""

    NOT_STARTED = 0
    """A start signal was required and never delivered."""

    HIT = 1
    """Correct response in an interval that required one."""

    WRONG_RESPONSE = 2
    """Wrong response where one was required."""

    EARLY_HIT = 3
    """Correct response on an early-release occasion."""

    EARLY_WRONG_RESPONSE = 4
    """Wrong response on an early-release occasion."""

    EARLY = 5
    """Responded before the response window opened."""

    LATE = 6
    """Responded after the response window closed."""

    EYE_ERROR = 7
    """Gaze left the fixation window."""

    UNEXPECTED_START_SIGNAL = 8
    """Start signal arrived in an interval that is not a start interval."""

    WRONG_START_SIGNAL = 9
    """The wrong start signal was given."""

    CANCELLED = 10
    """Aborted by the experimenter."""


class Manipulandum(enum.IntEnum):
    """Which input device produced the outcome. Mirrors ``TDR::Manipulandum``."""

    NONE = 0
    LEVER = 1
    TOUCH_BAR = 2
    BUTTON = 3
    JOYSTICK = 4
    GAMEPAD = 5
    SERIAL = 6
    SIMULATED = 7


#: Outcomes that count as a hit for the ``HITS`` set-switch criterion.
#:
#: Only :attr:`TrialOutcome.HIT`, deliberately. VStim increments
#: ``m_HitsInCurrentSet`` in ``OnHit()`` alone - ``OnEarlyHit()`` does not touch
#: it - so an early hit moves the accepted-trial count but not the hit count.
#: Faithful to the original; revisit only with the lab, since it changes how long
#: a training block runs.
HIT_OUTCOMES: frozenset[TrialOutcome] = frozenset({TrialOutcome.HIT})


@dataclasses.dataclass(frozen=True, slots=True)
class FrameLoss:
    """Where the first lost frame of a trial was seen."""

    interval: int
    """Index of the interval the loss occurred in."""

    frame: int
    """Frame number of the loss, relative to the start of that interval."""


@dataclasses.dataclass(frozen=True, slots=True)
class OutcomeReport:
    """One trial's result, as reported by whatever owns the behaviour.

    This is the daemon's primary inbound message. Everything downstream -
    counters, rounds, set switching, the record, the policy - is driven from it,
    so it has to carry every modifier that participates in the accept decision.
    """

    outcome: TrialOutcome

    manipulandum: Manipulandum = Manipulandum.NONE
    """Which input device produced the outcome."""

    reaction_time_ms: float | None = None
    """Recorded, never used in the accept decision."""

    terminating_interval: int | None = None
    """The interval the trial ended in."""

    precise_fixation: bool = True
    """False if gaze left the inner fixation window without ending the trial."""

    frame_loss: FrameLoss | None = None
    """Set when at least one frame was lost during the trial."""

    reward_ms: int = 0
    """Reward actually delivered, which may differ from the trial type's setting."""

    hit_condition: bool = False
    """Whether the time sequence set a hit condition for this trial."""

    simulated: bool = False
    """The outcome came from a simulated subject, not an animal."""

    note: str | None = None
    """Free text, recorded verbatim. Used for cancellation reasons."""

    @property
    def had_frame_loss(self) -> bool:
        return self.frame_loss is not None


@dataclasses.dataclass(slots=True)
class AcceptancePolicy:
    """Which outcomes consume a slot in the round.

    Defaults are VStim's shipping defaults (``TrialTypeManagerConfig``), which
    exist because they are what the lab's rigs actually run with, not because
    they are obviously right. The two modifier flags at the bottom cut across
    every outcome.
    """

    not_started: bool = False
    hit: bool = True
    wrong_response: bool = True
    early_hit: bool = True
    early_wrong_response: bool = True
    early: bool = True
    late: bool = True
    eye_error: bool = True
    unexpected_start_signal: bool = False
    wrong_start_signal: bool = False
    cancelled: bool = False

    frame_loss: bool = True
    """Accept a trial that also lost at least one frame."""

    imprecise_fixation: bool = True
    """Accept a trial where gaze left the inner fixation window."""

    _BY_OUTCOME: ClassVar[dict[TrialOutcome, str]] = {
        TrialOutcome.NOT_STARTED: "not_started",
        TrialOutcome.HIT: "hit",
        TrialOutcome.WRONG_RESPONSE: "wrong_response",
        TrialOutcome.EARLY_HIT: "early_hit",
        TrialOutcome.EARLY_WRONG_RESPONSE: "early_wrong_response",
        TrialOutcome.EARLY: "early",
        TrialOutcome.LATE: "late",
        TrialOutcome.EYE_ERROR: "eye_error",
        TrialOutcome.UNEXPECTED_START_SIGNAL: "unexpected_start_signal",
        TrialOutcome.WRONG_START_SIGNAL: "wrong_start_signal",
        TrialOutcome.CANCELLED: "cancelled",
    }

    def accepts_outcome(self, outcome: TrialOutcome) -> bool:
        """Whether this outcome kind is accepted, ignoring the modifiers."""
        field = self._BY_OUTCOME.get(outcome)
        return False if field is None else bool(getattr(self, field))

    def accepts(self, report: OutcomeReport) -> bool:
        """Whether `report` consumes a slot in the round.

        All three checks have to pass. An outcome that is accepted in principle
        is still refused when it lost a frame and frame loss is not accepted, or
        when fixation was imprecise and imprecise fixation is not accepted.
        """
        if not self.accepts_outcome(report.outcome):
            return False
        if report.had_frame_loss and not self.frame_loss:
            return False
        return report.precise_fixation or self.imprecise_fixation

    def refusal_reason(self, report: OutcomeReport) -> str | None:
        """Why `report` was not accepted, or None when it was.

        For the log and the trial record. An experimenter watching a session
        stall at 40 accepted trials needs to see *which* of the three rules is
        turning trials away.
        """
        if not self.accepts_outcome(report.outcome):
            return f"outcome {report.outcome.name} is not accepted"
        if report.had_frame_loss and not self.frame_loss:
            return "frame loss, and frame-loss trials are not accepted"
        if not report.precise_fixation and not self.imprecise_fixation:
            return "imprecise fixation, and imprecise fixation is not accepted"
        return None
