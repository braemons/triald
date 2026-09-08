"""Where outcomes come from: a simulated subject, or whatever the rig reports.

The daemon decides what runs; something else watches the animal and says what
happened. :class:`BehaviourSource` is that seam, and it exists so a simulated
session exercises the *real* trial loop rather than a parallel one written for
testing. :func:`triald.runner.run_trial` is its only caller, and ``triald sim``,
the web UI's debug stepper and the tests all go through it.

**On a real rig this is not the microcontroller link.** An earlier plan had
triald holding a serial connection to the behaviour controller; it no longer
does. The microcontroller is a participant on the rig's trigger bus - it arms on
the edges the stimulators raise, names the outcome, and reports the finished
trial to triald over the API. Nothing here describes that protocol, because it is
the rig's to define and not triald's. See dev/PLAN.md, *The shape of the rig*.

**The division of authority is unchanged.** Whoever executes the trial is the
timing authority: it debounces the inputs, timestamps responses in its own clock,
and drives the reward. triald is the decision authority: it chooses the trial
type, decides whether the outcome was *accepted*, and records what happened.

Note what is *not* sent: the trial type. An executor is configured from it
elsewhere and never learns which condition it is running, which is what keeps
firmware stable while paradigms change.
"""

from __future__ import annotations

import abc
import dataclasses
import random

from triald.outcomes import Manipulandum, OutcomeReport, TrialOutcome
from triald.state import TrialSpec


@dataclasses.dataclass(frozen=True, slots=True)
class TrialParameters:
    """What a behaviour source is told before a trial runs.

    Three fields, because three are what a source actually needs from triald. It
    once carried a response channel, a response window, a hold time, a timeout
    and a start-signal flag - the shape of a serial protocol to a
    microcontroller. triald no longer owns that link, nothing ever read those
    fields, and inventing values for them in the runner was worse than not
    having them: `correct_response` was filled in from the trial type *index*,
    which is right only by accident for a two-condition set and wrong for every
    other one.

    What an executor needs in order to run a trial is the executor's
    configuration, and on a real rig it is configured from the trial type
    directly. See dev/PLAN.md, *The interval table, decomposed*.

    Note that :attr:`graph` is still not the trial type: it names a state
    machine, and several conditions routinely share one.
    """

    trial_id: int
    """Monotonic within the session, and the whole correctness story.

    A result for any other trial is refused rather than accepted - this is what
    stops a late outcome being attributed to the trial after it, which is how a
    rig quietly mislabels a dataset.
    """

    graph: str = ""
    """Name of the state graph to run. Empty means leave whatever is loaded.

    A **name**, never a slot: triald has no opinion about where a graph sits in
    the executor's store, and an index would silently point at a different
    machine the moment that store were edited. The executor refuses a name it
    does not have, which is a configuration error triald can report rather than
    a trial that quietly ran the wrong thing.
    """

    reward_ms: int = 0
    """What a correct response is worth, so the source can report what it gave."""


class BehaviourSourceError(Exception):
    """The behaviour source could not be armed, or gave an unusable answer."""


class BehaviourSource(abc.ABC):
    """Runs one trial and says how it ended.

    The seam that keeps a simulated session on the *real* trial loop:
    :func:`triald.runner.run_trial` is written against this, so ``triald sim``,
    the web UI's debug stepper and the tests exercise the same four calls rather
    than a loop written for testing.
    """

    @abc.abstractmethod
    def arm(self, params: TrialParameters) -> None:
        """Prepare for the trial `params` describes.

        Must not return until the source is ready for that exact ``trial_id``.
        **No trial may start that the source was not confirmed configured for**
        - the local form of ``StartPermittable()``, and skipping it is how a
        session ends up running the previous trial's parameters without anybody
        noticing.

        Raises:
            BehaviourSourceError: if it cannot be armed for that trial.
        """

    @abc.abstractmethod
    def result(self, trial_id: int) -> OutcomeReport:
        """Give the outcome of the trial with `trial_id`.

        Raises:
            BehaviourSourceError: on a result for any other trial.
        """


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

    def arm(self, params: TrialParameters) -> None:
        self._armed = params

    def result(self, trial_id: int) -> OutcomeReport:
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
