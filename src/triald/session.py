"""The trial loop: the state machine everything else hangs off.

Ported from ``TrialTypeManager``'s ``GetNextTrialType`` / ``UpdateRounds`` /
``ApplyTrialTypeSetSwitchIfDue`` / ``StartPermittable``, with the same rules and
a different shape. In VStim the whole cycle runs on the render thread under one
recursive mutex; here it is an explicit object you can step, simulate and replay.

The single most important thing this module keeps straight is the difference
between a trial being **counted** and being **accepted**. Every reported outcome
is counted. Only an accepted one consumes from the bag, advances the round, and
moves a set towards its switch rule.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import random
from collections.abc import Mapping
from typing import Any, ClassVar

from triald.counters import ResultCount, TrialCountCriterion
from triald.metadata import SessionEvent
from triald.outcomes import (
    HIT_OUTCOMES,
    AcceptancePolicy,
    Manipulandum,
    OutcomeReport,
    TrialOutcome,
)
from triald.policy import DeclarativePolicy, Policy, safe_call
from triald.selection import Ordering, TrialBag
from triald.state import SessionState, SetProgress, TrialRecord, TrialSpec
from triald.trialtypes import (
    TRIAL_TYPES_PER_SET,
    TrialTypeSet,
    TrialTypeStore,
)

log = logging.getLogger(__name__)


class SessionError(Exception):
    """The session could not be armed, or was asked to do something out of order."""


@dataclasses.dataclass(slots=True)
class SessionConfig:
    """One experiment's settings. The declarative half of the scripting story.

    Everything here is data the web UI can edit and a file can hold. Anything
    that needs to be *computed* per trial belongs in a
    :class:`~triald.policy.Policy` instead.
    """

    initial_set: str
    """Name of the set to start in."""

    ordering: Ordering = Ordering.RANDOM_IN_ROUND
    rounds: int = 10
    avoid_repeat: bool = True

    acceptance: AcceptancePolicy = dataclasses.field(default_factory=AcceptancePolicy)

    stop_when_rounds_done: bool = False
    """Stop after the last trial of the last round. VStim's ``m_StopIfDone``."""

    stop_after_trials: int | None = None
    """Stop once this many trials of :attr:`stop_criterion` have been counted.

    Counted since the counters were last reset. A block length that does not
    depend on the weights, which is the thing :attr:`stop_when_rounds_done`
    cannot express (VStim issue #460).
    """

    stop_criterion: TrialCountCriterion = TrialCountCriterion.ACCEPTED_TRIALS
    """Which trials :attr:`stop_after_trials` counts."""

    extend_trial_type_number: bool = False
    """Make the effective trial type number ``set_number * 256 + index``.

    Preserved for ``.tdr`` compatibility. When it is on, the session refuses to
    arm unless a set has been loaded explicitly - VStim's ``StartPermittable()``
    check, which exists because the alternative is every trial being numbered as
    though it came from set zero.
    """

    seed: int | None = None
    """RNG seed. Generated and recorded when None, so every session is replayable."""

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["ordering"] = self.ordering.value
        return d


class Session:
    """One experiment, from armed to stopped."""

    def __init__(
        self,
        store: TrialTypeStore,
        config: SessionConfig,
        *,
        policy: Policy | None = None,
        recorder: Any = None,
        clock: Any = None,
    ) -> None:
        self._store = store
        self._config = config
        self._policy = policy if policy is not None else DeclarativePolicy()
        self._recorder = recorder
        self._clock = clock if clock is not None else _wall_clock

        self._seed = config.seed if config.seed is not None else random.randrange(2**32)
        self._rng = random.Random(self._seed)

        self._set: TrialTypeSet = store.get(config.initial_set)
        self._bag: TrialBag | None = None

        self._trial_number = 0
        self._rounds_completed = 0
        self._totals = ResultCount()

        # Per-trial-type counters, banked by set. With the trial type number
        # extended by the set number the sets are separate experiments whose
        # trial type 3 have nothing to do with each other, so each keeps its own
        # counts; without it, trial type 3 means the same thing in every set and
        # they share one bank. VStim reaches the same result with a
        # CounterOffset into one flat array.
        #
        # Banking rather than clearing on load is what stops a session that
        # alternates between two sets losing a set's counts every time it comes
        # back to it.
        self._per_type_banks: dict[str, list[ResultCount]] = {}

        self._accepted_in_set = 0
        self._hits_in_set = 0
        self._all_trials_in_set = 0

        # Latched so the stop fires once per counter reset rather than on every
        # trial after the count is passed. VStim's m_StoppedAfterTrials.
        self._stopped_after_trials = False

        self._running = False
        self._recording = False
        self._paused = False
        self._stop_requested = False
        self._stop_reason: str | None = None

        self._current: TrialSpec | None = None
        self._history: list[TrialRecord] = []
        self._policy_errors: list[dict[str, object]] = []

    # -- arming -----------------------------------------------------------------

    def arm(self) -> None:
        """Validate everything and get ready to run.

        Refuses rather than failing later. VStim does this in
        ``StartPermittable()`` and it earns its keep: an empty target set makes
        ``trials_per_round`` zero, and the round arithmetic divides by it - on
        the render thread, mid-session, with nobody to tell.

        Raises:
            SessionError: with a description of the first problem found.
        """
        if self._config.initial_set not in self._store:
            raise SessionError(f"no trial type set named {self._config.initial_set!r}")

        if not self._set.is_runnable():
            raise SessionError(
                f"set {self._set.name!r} has no trials in it - every trial type "
                f"has a weight of zero, so a round would be empty"
            )

        if self._config.rounds < 1:
            raise SessionError(f"rounds must be at least 1, got {self._config.rounds}")

        if self._config.extend_trial_type_number and not self._store.names():
            raise SessionError(
                "'extend trial type number by set number' is on but the store is "
                "empty, so there is no set number to extend by"
            )

        problem = self._store.validate_switch_chain(self._set.name)
        if problem is not None:
            raise SessionError(f"the set switch chain is unusable: {problem}")

        self._bag = TrialBag(
            self._set,
            ordering=self._config.ordering,
            rounds=self._config.rounds,
            avoid_repeat=self._config.avoid_repeat,
            rng=self._rng,
        )
        self._sync_remaining()

        self._running = True
        self._stop_requested = False
        self._stop_reason = None
        self._stopped_after_trials = False

        safe_call(
            self._policy.on_session_start,
            self.state(),
            fallback=None,
            hook="on_session_start",
            on_error=self._note_policy_error,
        )

    # -- the loop ---------------------------------------------------------------

    def next_trial(self) -> TrialSpec:
        """Select the next trial type and publish it.

        Everything about the trial is latched here, including whether it records.
        A trial that began recording finishes recording even if somebody pauses
        in the middle of it.

        Raises:
            SessionError: if the session is not running, or a trial is in flight.
        """
        if not self._running:
            raise SessionError("the session is not running; call arm() first")
        if self._current is not None:
            raise SessionError(
                f"trial {self._current.trial_number} is still in flight; report "
                f"its outcome before selecting another"
            )
        assert self._bag is not None  # arm() built it

        index = self._select_index()

        self._trial_number += 1
        trial_type = self._set[index]
        paused = self._paused

        self._current = TrialSpec(
            trial_number=self._trial_number,
            trial_type_index=index,
            trial_type_number=self._effective_number(index),
            trial_type_name=trial_type.name,
            set_name=self._set.name,
            time_sequence=trial_type.time_sequence,
            reward_ms=trial_type.reward_ms,
            recording=self._recording and not paused,
            paused=paused,
            started_at=self._clock(),
        )
        return self._current

    def _select_index(self) -> int:
        """Ask the policy, fall back to the bag."""
        assert self._bag is not None

        chosen = safe_call(
            self._policy.select_trial,
            self.state(),
            fallback=None,
            hook="select_trial",
            on_error=self._note_policy_error,
        )
        if chosen is None:
            return self._bag.draw()

        index = self._resolve_trial_type(chosen)
        if index is None:
            log.error(
                "policy select_trial returned %r, which is not a trial type in "
                "set %r - falling back to the declarative ordering",
                chosen,
                self._set.name,
            )
            self._note_policy_error(
                "select_trial",
                ValueError(f"unknown trial type {chosen!r}"),
                f"set {self._set.name!r} has no trial type {chosen!r}",
            )
            return self._bag.draw()
        return index

    def _resolve_trial_type(self, chosen: str | int) -> int | None:
        if isinstance(chosen, int):
            return chosen if 0 <= chosen < len(self._set) else None
        try:
            return self._set.index_of(chosen)
        except KeyError:
            return None

    def report_outcome(self, report: OutcomeReport) -> TrialRecord:
        """Take the outcome of the trial in flight and advance the session.

        Counts it, decides whether it was accepted, advances the round if it was,
        fires the set switch if its criterion has been reached, checks the stop
        conditions, records it, and tells the policy - in that order.

        Raises:
            SessionError: if no trial is in flight.
        """
        if self._current is None:
            raise SessionError("no trial is in flight")

        spec = self._current
        self._current = None

        accepted = self._config.acceptance.accepts(report)
        refusal = self._config.acceptance.refusal_reason(report)

        # A pausing trial runs and its outcome is real, but it scores nothing and
        # is never recorded - VStim returns early from every On*() for these.
        if spec.paused:
            accepted = False
            refusal = "pausing trial"
        else:
            self._count(spec, report, accepted=accepted)

        record = TrialRecord(
            spec=spec,
            report=report,
            accepted=accepted,
            refusal_reason=refusal,
            ended_at=self._clock(),
            policy_state=safe_call(
                self._policy.snapshot,
                fallback=None,
                hook="snapshot",
                on_error=self._note_policy_error,
            ),
        )
        self._history.append(record)

        if spec.recording and self._recorder is not None:
            self._recorder.write(record)

        if not spec.paused:
            self._advance(accepted)

        safe_call(
            self._policy.on_outcome,
            record,
            self.state(),
            fallback=None,
            hook="on_outcome",
            on_error=self._note_policy_error,
        )

        if safe_call(
            self._policy.should_stop,
            self.state(),
            fallback=False,
            hook="should_stop",
            on_error=self._note_policy_error,
        ):
            self.stop("the policy asked to stop")

        return record

    def cancel_trial(self, reason: str = "cancelled by the experimenter") -> TrialRecord:
        """End the trial in flight as :attr:`TrialOutcome.CANCELLED`.

        Recorded as a cancellation rather than dropped, so a gap in the trial
        numbering never has to be explained later.
        """
        return self.report_outcome(
            OutcomeReport(
                outcome=TrialOutcome.CANCELLED,
                manipulandum=Manipulandum.NONE,
                note=reason,
            )
        )

    # -- counting and advancing -------------------------------------------------

    def _count(self, spec: TrialSpec, report: OutcomeReport, *, accepted: bool) -> None:
        self._totals.record(report, accepted=accepted)
        self._per_type[spec.trial_type_index].record(report, accepted=accepted)

        # Hits move the set's switch progress whether or not the trial was
        # accepted: a hit that lost a frame is still a hit. VStim reaches the
        # same result by calling ApplyTrialTypeSetSwitchIfDue() from OnHit()
        # when UpdateRounds() was skipped.
        if report.outcome in HIT_OUTCOMES:
            self._hits_in_set += 1
        if accepted:
            self._accepted_in_set += 1
        self._all_trials_in_set += 1

    def _advance(self, accepted: bool) -> None:
        """Consume from the bag, close the round, switch sets, check the stops."""
        assert self._bag is not None

        if accepted:
            index = self._history[-1].spec.trial_type_index
            self._bag.consume(index)
            self._sync_remaining()

            remaining = self._bag.total_remaining
            trials_per_round = self._bag.trials_per_round

            if remaining % trials_per_round == 0:
                self._rounds_completed += 1
                if self._rounds_completed >= self._config.rounds:
                    self._rounds_completed = 0
                    if self._config.stop_when_rounds_done:
                        self.stop(f"{self._config.rounds} rounds completed")
                        return

            if remaining == 0:
                self._bag.refill()
                self._sync_remaining()

        # Stopping wins over switching: there is nothing to switch to once the
        # experiment is ending. VStim orders these the same way in
        # OnTrialCompleted().
        if not self._stop_after_trials_if_due():
            self._apply_switch_if_due()

    def _stop_after_trials_if_due(self) -> bool:
        """Stop if enough trials of the chosen kind have been counted (#460).

        Latched, so it fires once per counter reset rather than on every trial
        after the count is passed. The comparison is ">=" rather than an
        equality, which would silently never fire again if a counter jumped past
        the target.
        """
        if self._stopped_after_trials:
            return False

        limit = self._config.stop_after_trials
        if limit is None or limit <= 0:
            return False

        criterion = self._config.stop_criterion
        if self._totals.counted(criterion) < limit:
            return False

        self._stopped_after_trials = True
        self.stop(f"{limit} {criterion.value.replace('_', ' ')} counted")
        return True

    def _apply_switch_if_due(self) -> bool:
        """Load the set this one's rule points at, if its criterion is reached."""
        rule = self._set.switch_rule
        if not rule.is_armed():
            return False
        assert rule.target is not None

        if rule.target == self._set.name:
            return False

        if self._counted_in_set(rule.criterion) < rule.count:
            return False

        if rule.target not in self._store:
            log.error(
                "set %r switches to %r, which is not in the store",
                self._set.name,
                rule.target,
            )
            return False

        target = self._store.get(rule.target)
        if not target.is_runnable():
            log.error(
                "set %r switches to %r, which has no trials in it; staying put",
                self._set.name,
                rule.target,
            )
            return False

        previous = self._set.name
        self.load_set(rule.target)
        log.info("switched from trial type set %r to %r", previous, rule.target)

        safe_call(
            self._policy.on_set_switch,
            previous,
            rule.target,
            self.state(),
            fallback=None,
            hook="on_set_switch",
            on_error=self._note_policy_error,
        )
        return True

    # -- sets, rounds, counters -------------------------------------------------

    def load_set(self, name: str) -> None:
        """Make `name` the active set and start its block from nothing."""
        target = self._store.get(name)
        if not target.is_runnable():
            raise SessionError(f"set {name!r} has no trials in it and cannot run")

        self._set = target
        self._bag = TrialBag(
            target,
            ordering=self._config.ordering,
            rounds=self._config.rounds,
            avoid_repeat=self._config.avoid_repeat,
            rng=self._rng,
        )
        self._rounds_completed = 0
        self._accepted_in_set = 0
        self._hits_in_set = 0
        self._all_trials_in_set = 0
        self._sync_remaining()

    #: Config fields that may not change while the session is running.
    #:
    #: Each of them decides something that has already happened: which set was
    #: loaded, how the trial types were numbered into the record, which sequence
    #: the RNG has been drawing from. Changing one mid-session would leave a
    #: record whose first half means something different from its second.
    ARM_TIME_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"initial_set", "extend_trial_type_number", "seed"}
    )

    #: Config fields the bag holds its own copy of, so changing one rebuilds it.
    BAG_FIELDS: ClassVar[frozenset[str]] = frozenset({"ordering", "rounds", "avoid_repeat"})

    def reconfigure(self, changes: Mapping[str, Any]) -> list[str]:
        """Apply `changes` to the live config, and say what actually changed.

        The declarative settings split three ways, and the split is the whole
        content of this method:

        * **live** - the accept flags and the stop rules are read fresh on every
          trial, so a change takes effect on the next one and costs nothing;
        * **bag-shaped** - the ordering, the round count and avoid-repeat are
          held by the bag, so changing one rebuilds it. The current round starts
          again from a full bag; the outcome counters are untouched;
        * **arm-time** - :data:`ARM_TIME_FIELDS` are refused while the session
          runs.

        Raises:
            SessionError: for an unknown field, a value that will not validate,
                or an arm-time field while the session is running.
        """
        known = {f.name for f in dataclasses.fields(SessionConfig)}
        unknown = sorted(set(changes) - known)
        if unknown:
            raise SessionError(
                f"not session config fields: {', '.join(unknown)}. "
                f"Known fields are {', '.join(sorted(known))}."
            )

        coerced = {key: self._coerce_config(key, value) for key, value in changes.items()}
        changed = [k for k, v in coerced.items() if getattr(self._config, k) != v]

        if self._running:
            refused = sorted(set(changed) & self.ARM_TIME_FIELDS)
            if refused:
                raise SessionError(
                    f"{', '.join(refused)} cannot change while the session is "
                    f"running - stop it first, or the record's first half would "
                    f"mean something different from its second"
                )

        if "rounds" in coerced and coerced["rounds"] < 1:
            raise SessionError(f"rounds must be at least 1, got {coerced['rounds']}")

        for key in changed:
            setattr(self._config, key, coerced[key])

        if set(changed) & self.BAG_FIELDS and self._bag is not None:
            self._bag = TrialBag(
                self._set,
                ordering=self._config.ordering,
                rounds=self._config.rounds,
                avoid_repeat=self._config.avoid_repeat,
                rng=self._rng,
            )
            self._rounds_completed = 0
            self._sync_remaining()

        return changed

    @staticmethod
    def _coerce_config(key: str, value: Any) -> Any:
        """Turn a wire value into the type the config field holds.

        A JSON caller sends ``"ascending"`` and a dict of accept flags; a Python
        caller sends the enum and the dataclass. Both arrive here.
        """
        try:
            if key == "ordering":
                return Ordering(value)
            if key == "stop_criterion":
                return TrialCountCriterion(value)
            if key == "acceptance" and isinstance(value, Mapping):
                return AcceptancePolicy(**value)
        except (ValueError, TypeError) as exc:
            raise SessionError(f"{key}: {exc}") from exc
        return value

    def reset_rounds(self) -> None:
        """Refill the bag and clear the round and set-progress counters."""
        if self._bag is not None:
            self._bag.reset()
            self._sync_remaining()
        self._rounds_completed = 0
        self._accepted_in_set = 0
        self._hits_in_set = 0
        self._all_trials_in_set = 0

    def reset_counters(self) -> None:
        """Clear every outcome tally, in every set. The bag and round are left alone.

        Every bank, not only the loaded set's: VStim's Reset Counts clears them
        all, and a half-cleared session is worse than either state.
        """
        self._totals.reset()
        for bank in self._per_type_banks.values():
            for c in bank:
                c.reset()
        self._accepted_in_set = 0
        self._hits_in_set = 0
        self._all_trials_in_set = 0
        # The stop rule counts since the last reset, so it is armed again.
        self._stopped_after_trials = False

    _SHARED_BANK = ""

    @property
    def _per_type(self) -> list[ResultCount]:
        """The counter bank the loaded set counts into, grown to fit it."""
        key = self._set.name if self._config.extend_trial_type_number else self._SHARED_BANK
        bank = self._per_type_banks.setdefault(key, [])
        while len(bank) < len(self._set):
            bank.append(ResultCount())
        return bank

    def _sync_remaining(self) -> None:
        assert self._bag is not None
        remaining = self._bag.remaining
        for counter, n in zip(self._per_type, remaining, strict=False):
            counter.remaining = n
        # From the bag rather than the sum: with replacement a type can be drawn
        # after its quota is spent, so the per-type counts no longer add up to
        # the trials left in the round.
        self._totals.remaining = self._bag.total_remaining

    # -- recording and running --------------------------------------------------

    def start_recording(self) -> None:
        self._recording = True
        self._paused = False

    def stop_recording(self) -> None:
        self._recording = False
        self._paused = False

    def pause_recording(self) -> None:
        """Keep running, stop recording. Pausing trials still run and count."""
        self._paused = True

    def resume_recording(self) -> None:
        self._paused = False

    def stop(self, reason: str = "stopped") -> None:
        self._running = False
        self._stop_requested = True
        self._stop_reason = reason
        log.info("session stopped: %s", reason)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def armed(self) -> bool:
        """Whether :meth:`arm` has run. A stopped session stays armed."""
        return self._bag is not None

    @property
    def recorder(self) -> Any:
        return self._recorder

    @recorder.setter
    def recorder(self, recorder: Any) -> None:
        """Attach or detach the recorder.

        Settable mid-session because recording starts and stops mid-session:
        VStim opens the ``.tdr`` on Start Rec, not when the experiment is armed.
        Only trials whose :attr:`~triald.state.TrialSpec.recording` was latched
        true reach it, so attaching one does not retrospectively record anything.
        """
        self._recorder = recorder

    @property
    def store(self) -> TrialTypeStore:
        return self._store

    @property
    def trial_type_set(self) -> TrialTypeSet:
        """The set that is loaded. Read it; change it through :meth:`load_set`."""
        return self._set

    @property
    def config(self) -> SessionConfig:
        """The live config. Change it through :meth:`reconfigure`, not in place."""
        return self._config

    @property
    def policy(self) -> Policy:
        return self._policy

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    @property
    def seed(self) -> int:
        return self._seed

    @property
    def policy_errors(self) -> list[dict[str, object]]:
        """Policy failures so far, for the web UI. Newest last."""
        return list(self._policy_errors)

    # -- the snapshot -----------------------------------------------------------

    def state(self) -> SessionState:
        """The read-only view handed to policies, RPC callers and the web UI."""
        return SessionState(
            running=self._running,
            recording=self._recording and not self._paused,
            paused=self._paused,
            current=self._current,
            last=self._history[-1] if self._history else None,
            totals=self._totals,
            per_trial_type=list(self._per_type),
            trial_type_names=tuple(t.name for t in self._set),
            p_next=tuple(self._bag.probabilities()) if self._bag else (),
            set_name=self._set.name,
            set_progress=self._set_progress(),
            rounds_completed=self._rounds_completed,
            rounds_configured=self._config.rounds,
            trials_per_round=self._set.trials_per_round,
            trials_remaining=self._bag.total_remaining if self._bag else 0,
            stop_reason=self._stop_reason,
            history=tuple(self._history),
            seed=self._seed,
            config=self._config.as_dict(),
        )

    def _counted_in_set(self, criterion: TrialCountCriterion) -> int:
        """Progress of the loaded set under `criterion`, since it was loaded."""
        if criterion is TrialCountCriterion.HITS:
            return self._hits_in_set
        if criterion is TrialCountCriterion.ALL_TRIALS:
            return self._all_trials_in_set
        return self._accepted_in_set

    def _set_progress(self) -> SetProgress:
        rule = self._set.switch_rule
        armed = rule.is_armed()
        return SetProgress(
            set_name=self._set.name,
            accepted_trials=self._accepted_in_set,
            hits=self._hits_in_set,
            all_trials=self._all_trials_in_set,
            criterion=rule.criterion if armed else None,
            target=rule.count if armed else None,
            switch_to=rule.target if armed else None,
        )

    # -- helpers ----------------------------------------------------------------

    def _effective_number(self, index: int) -> int:
        """The trial type number as the record and the wire see it."""
        if not self._config.extend_trial_type_number:
            return index
        names = self._store.names()
        set_number = names.index(self._set.name) + 1 if self._set.name in names else 0
        return set_number * TRIAL_TYPES_PER_SET + index

    def _note_policy_error(self, hook: str, exc: Exception, formatted: str) -> None:
        error = {
            "hook": hook,
            "trial_number": self._trial_number,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": formatted,
            "at": self._clock().isoformat(),
        }
        self._policy_errors.append(error)

        # Into the record as well as the log. A session that behaved oddly at
        # trial 200 should be able to say why from its own directory.
        if self._recorder is not None:
            try:
                self._recorder.event(
                    SessionEvent(
                        kind="policy_error",
                        data=error,
                        source="triald",
                        trial_number=self._trial_number,
                    )
                )
            except Exception:
                log.exception("could not record the policy error; ignoring")


def _wall_clock() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
