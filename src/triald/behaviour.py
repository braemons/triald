"""Where outcomes come from: the microcontroller, or a simulated subject.

The daemon decides what runs; something else watches the animal and says what
happened. That something is a :class:`BehaviourSource` - in a real rig a
microcontroller on the end of a serial link, in ``triald sim`` a synthetic
subject. Both satisfy the same interface, so a simulated session exercises the
real code path rather than a parallel one built for testing.

**The division of authority.** The microcontroller is the timing authority: it
debounces the levers, timestamps responses in its own microsecond clock, and
drives the reward valve. triald is the decision authority: it chooses the trial
type and records what happened. Neither does the other's job, and the interface
below is the whole of what passes between them.

Note what is *not* sent: the trial type. The microcontroller receives a
:class:`TrialParameters` block - which response is correct, how long the windows
are, how much reward - and never learns what condition it is running. That is
what keeps firmware stable while paradigms change.
"""

from __future__ import annotations

import abc
import dataclasses
import random

from triald.outcomes import Manipulandum, OutcomeReport, TrialOutcome
from triald.state import TrialSpec


@dataclasses.dataclass(frozen=True, slots=True)
class TrialParameters:
    """What the behaviour source needs in order to run one trial.

    Deliberately semantic-free. ``correct_response`` is a channel number, not a
    condition name, because the microcontroller should not have to be reflashed
    when a paradigm gains a condition.
    """

    trial_id: int
    """Monotonic within the session. The whole correctness story - see
    :meth:`BehaviourSource.arm`."""

    correct_response: int
    """Which input channel counts as correct. -1 when no response is required."""

    response_window_ms: int
    """How long a response is accepted for, from the trigger edge."""

    hold_time_ms: int = 0
    """How long a manipulandum must be held before the window opens."""

    timeout_ms: int = 10_000
    """Abort the trial if nothing has happened by then."""

    reward_ms: int = 0
    """Valve open time on a correct response."""

    require_start_signal: bool = False
    """Whether the trial waits for the subject to signal readiness."""

    def as_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


class BehaviourSourceError(Exception):
    """The behaviour source could not be armed, or gave an unusable answer."""


class BehaviourSource(abc.ABC):
    """Runs one trial and says how it ended."""

    @abc.abstractmethod
    def arm(self, params: TrialParameters, timeout_s: float = 1.0) -> None:
        """Load `params` and confirm they were received.

        Must not return until the source has acknowledged the exact
        ``trial_id``. **No trial may start that the source was not confirmed
        configured for** - this is the microcontroller equivalent of
        ``StartPermittable()``, and skipping it is how a session ends up running
        the previous trial's parameters without anybody noticing.

        Raises:
            BehaviourSourceError: if the acknowledgement does not arrive, or is
                for a different trial.
        """

    @abc.abstractmethod
    def result(self, trial_id: int, timeout_s: float = 60.0) -> OutcomeReport:
        """Wait for the outcome of the trial with `trial_id`.

        The ``trial_id`` check is what stops a late result being attributed to
        the trial after it - the classic way a rig quietly mislabels a dataset.
        A result for any other trial is refused rather than accepted.

        Raises:
            BehaviourSourceError: on timeout, or on a result for another trial.
        """

    def close(self) -> None:  # noqa: B027 - optional hook, not every source holds anything
        """Release whatever the source holds. Must be safe to call twice."""


class SimulatedBehaviourSource(BehaviourSource):
    """A synthetic subject, for ``triald sim`` and for tests.

    Produces outcomes from a per-trial-type hit probability plus a scatter of the
    error kinds a real animal produces. It is not a model of behaviour and is not
    meant to be - it exists so that a policy can be run over 500 trials in a
    second and its logic checked before anything is connected to a rig.
    """

    def __init__(
        self,
        *,
        hit_rate: float = 0.75,
        not_started_rate: float = 0.05,
        eye_error_rate: float = 0.08,
        early_rate: float = 0.05,
        frame_loss_rate: float = 0.0,
        imprecise_fixation_rate: float = 0.0,
        reaction_time_ms: tuple[float, float] = (220.0, 45.0),
        hit_rate_by_type: dict[str, float] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.hit_rate = hit_rate
        self.not_started_rate = not_started_rate
        self.eye_error_rate = eye_error_rate
        self.early_rate = early_rate
        self.frame_loss_rate = frame_loss_rate
        self.imprecise_fixation_rate = imprecise_fixation_rate
        self.reaction_time_ms = reaction_time_ms
        self.hit_rate_by_type = hit_rate_by_type or {}
        self._rng = rng if rng is not None else random.Random()
        self._armed: TrialParameters | None = None
        self._spec: TrialSpec | None = None

    def set_current_trial(self, spec: TrialSpec) -> None:
        """Tell the subject which trial type it is running.

        Only the simulator needs this - it is how ``hit_rate_by_type`` finds the
        right probability. A real behaviour source is never told the condition.
        """
        self._spec = spec

    def arm(self, params: TrialParameters, timeout_s: float = 1.0) -> None:
        self._armed = params

    def result(self, trial_id: int, timeout_s: float = 60.0) -> OutcomeReport:
        if self._armed is None or self._armed.trial_id != trial_id:
            armed = None if self._armed is None else self._armed.trial_id
            raise BehaviourSourceError(
                f"asked for the result of trial {trial_id}, but the subject is "
                f"armed for {armed}"
            )

        outcome, manipulandum, rt = self._draw_outcome()
        report = OutcomeReport(
            outcome=outcome,
            manipulandum=manipulandum,
            reaction_time_ms=rt,
            terminating_interval=2 if outcome is TrialOutcome.HIT else 1,
            precise_fixation=self._rng.random() >= self.imprecise_fixation_rate,
            frame_loss=None,
            reward_ms=self._armed.reward_ms if outcome is TrialOutcome.HIT else 0,
            simulated=True,
        )
        self._armed = None
        return report

    def _draw_outcome(self) -> tuple[TrialOutcome, Manipulandum, float | None]:
        roll = self._rng.random()

        if roll < self.not_started_rate:
            return TrialOutcome.NOT_STARTED, Manipulandum.NONE, None
        roll -= self.not_started_rate

        if roll < self.eye_error_rate:
            return TrialOutcome.EYE_ERROR, Manipulandum.NONE, None
        roll -= self.eye_error_rate

        if roll < self.early_rate:
            return TrialOutcome.EARLY, Manipulandum.SIMULATED, None

        mean, sd = self.reaction_time_ms
        rt = max(1.0, self._rng.gauss(mean, sd))
        hit_rate = self._hit_rate_for_current_type()
        if self._rng.random() < hit_rate:
            return TrialOutcome.HIT, Manipulandum.SIMULATED, rt
        return TrialOutcome.WRONG_RESPONSE, Manipulandum.SIMULATED, rt

    def _hit_rate_for_current_type(self) -> float:
        if self._spec is not None:
            by_name = self.hit_rate_by_type.get(self._spec.trial_type_name)
            if by_name is not None:
                return by_name
        return self.hit_rate
