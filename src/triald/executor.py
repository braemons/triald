"""What triald says to whatever runs a trial, and how it hears the answer.

triald decides *which* trial runs; something else runs it. On a rig that
something else is a state-machine daemon holding a microcontroller, and this is
the whole of what triald knows about it: three calls out, and one kind of event
back.

**triald observes; it is not reported to.** An executor publishes what it did
and assumes nobody read it -- its own record exists on the rig either way. triald
is one subscriber among however many there are, with no standing in the
executor's configuration and no way to make it wait. That is what keeps an
executor usable with no triald on the network at all, which is the state a bench
box is in every day.

**The translation is here, and it is triald's.** An executor reports what it
measured: which states a trial visited, how each one was left, how long each took
by the device's own clock. Deciding that the reaction time is *the last state a
response left* is an interpretation of behaviour, and interpretation is the
decision authority's job. An executor that made it would be a second decision
authority -- and would have to be changed to change the definition.

Nothing here imports anything. It is dictionaries in and an
:class:`~triald.outcomes.OutcomeReport` out, so the shape an executor publishes
can be checked without a device, a network or a daemon.
"""

from __future__ import annotations

import abc
import dataclasses
from collections.abc import Iterable, Sequence
from typing import Any

from triald.outcomes import Manipulandum, OutcomeReport, TrialOutcome

#: The event kinds triald cares about, of the many an executor publishes.
KIND_TRIAL_RESULT = "trial_result"
KIND_STATE_VISIT = "visit"

#: How a state was left, when it was left by something the subject did. Every
#: other exit cause is the machine's own (a timeout, a cancellation), and only
#: this one has a reaction time in it.
EXIT_CAUSE_TRANSITION = "transition"


class ExecutorError(Exception):
    """The executor refused a call, or published something unusable."""


@dataclasses.dataclass(frozen=True, slots=True)
class TrialConfiguration:
    """What an executor is told before a trial runs.

    Not the trial type, and never the trial type: an executor is configured
    *from* the condition and does not learn which condition it is, which is what
    keeps firmware stable while paradigms change.
    """

    trial_id: int
    """Monotonic within the session. What every message about this trial carries.

    A result for any other trial is refused rather than accepted - this is what
    stops a late outcome being attributed to the trial after it, which is how a
    rig quietly mislabels a dataset.
    """

    statemachine_graph: str = ""
    """Which state graph to run, by name. Empty leaves whatever is loaded.

    triald holds no graphs and never checks the name: the executor owns the
    store and refuses a name it does not have, which is a configuration error
    triald can report rather than a trial that quietly ran the wrong machine.
    """

    cap_milliseconds: int = 0
    """A wall-clock ceiling on the whole trial. Zero means the executor's own.

    The same number triald should arm its *own* deadline on: it is the longest
    this trial can honestly take, so a silence longer than it is a silence that
    will not end.
    """


class TrialExecutor(abc.ABC):
    """Whatever runs a trial: three calls out, and nothing else.

    Deliberately smaller than a daemon's API. An executor does a great many
    things triald has no business asking about - line maps, graph stores,
    firmware settings, its own recording - and every one of them that appeared
    here would be a way for triald to become the thing that configures the rig
    rather than the thing that decides the experiment.
    """

    @abc.abstractmethod
    def configure(self, configuration: TrialConfiguration) -> None:
        """Arm for exactly that trial, and do not return until it is armed.

        **No trial may start that the executor was not confirmed configured
        for**, which is the local form of VStim's ``StartPermittable()``.
        Skipping it is how a session runs the previous trial's parameters
        without anybody noticing.

        Raises:
            ExecutorError: if it will not arm - an unknown graph, no session, a
                trial already running.
        """

    @abc.abstractmethod
    def start(self, trial_id: int) -> None:
        """Begin the trial the executor was armed for.

        Raises:
            ExecutorError: if it is armed for any other trial, or for none.
        """

    @abc.abstractmethod
    def cancel(self, trial_id: int, reason: str = "") -> None:
        """Abandon the trial in flight. Idempotent: cancelling nothing is fine."""


def is_a_finished_trial(event: dict[str, Any]) -> bool:
    """Whether this published event says a trial ended.

    The one event kind triald acts on. Everything else an executor publishes -
    every state entered, every line raised, every setting saved - is for the
    record and for whoever else is watching.
    """
    return event.get("kind") == KIND_TRIAL_RESULT


def reaction_time_milliseconds(visits: Sequence[dict[str, Any]]) -> float | None:
    """How long the state that a *response* left was in, or None.

    None rather than zero when nothing responded: a trial that timed out has no
    reaction time, and zero is a measurement. VStim's `.tdr` has the same
    distinction and analysis scripts rely on it.

    The definition - *the last state left by a transition* - is triald's to
    make and to change. It lives here rather than in an executor so that
    changing it does not mean changing firmware, and so that the same rule
    applies to every executor triald ever talks to.
    """
    for visit in reversed(visits):
        if visit.get("exit_cause") == EXIT_CAUSE_TRANSITION:
            microseconds = visit.get("measured_duration_microseconds")
            if microseconds is None:
                return None
            return microseconds / 1000
    return None


def outcome_from_events(trial_id: int, events: Iterable[dict[str, Any]]) -> OutcomeReport:
    """Turn one trial's published events into the report triald acts on.

    Args:
        trial_id: the trial these events must all belong to. Events for any
            other are ignored rather than merged - a mixed batch is a bug
            somewhere upstream, and averaging two trials together is worse than
            dropping one.
        events: that trial's events, oldest first. Must contain exactly one
            `trial_result`.

    **What is deliberately not filled in.** ``precise_fixation`` comes from an
    eye monitor and ``frame_loss`` from vstimd; an executor has never heard of
    either, and either can veto acceptance on its own. They stay at their
    defaults so the veto belongs to whoever can actually observe it.

    ``simulated`` is False and not as a formality: ``triald sim`` produces
    outcomes with it true, and a rig whose records could not be told apart from
    a simulator's is a rig whose data cannot be trusted.

    Raises:
        ExecutorError: if there is no result for `trial_id`, or its outcome is
            not a name triald knows.
    """
    mine = [event for event in events if event.get("trial_id") == trial_id]
    results = [event for event in mine if is_a_finished_trial(event)]
    if not results:
        raise ExecutorError(f"the executor published no result for trial {trial_id}")
    if len(results) > 1:
        raise ExecutorError(
            f"the executor published {len(results)} results for trial {trial_id}; "
            f"one trial ends once"
        )

    result = results[0]
    name = result.get("outcome")
    try:
        outcome = TrialOutcome[str(name)]
    except KeyError:
        raise ExecutorError(
            f"trial {trial_id} ended on {name!r}, which is not one of the eleven "
            f".tdr outcomes: {', '.join(o.name for o in TrialOutcome)}"
        ) from None

    visits = [event for event in mine if event.get("kind") == KIND_STATE_VISIT]
    return OutcomeReport(
        outcome=outcome,
        manipulandum=Manipulandum.NONE,
        reaction_time_ms=reaction_time_milliseconds(visits),
        terminating_interval=len(visits) or None,
        reward_ms=0,
        simulated=False,
        note=_note_for(result),
    )


def _note_for(result: dict[str, Any]) -> str | None:
    """Why a trial was cancelled, when it was, recorded verbatim.

    Only the executor knows the difference between a host cancelling a trial and
    a link that went away underneath it, and the distinction is worth keeping
    even though nothing branches on it.
    """
    reason = result.get("cancel_reason")
    if reason in (None, "NONE"):
        return None
    return f"cancelled by the executor: {reason}"
