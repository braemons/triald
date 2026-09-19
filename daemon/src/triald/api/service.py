# SPDX-License-Identifier: AGPL-3.0-or-later
"""One rig's session, and everything the routes are allowed to do to it.

The servicers in :mod:`triald.api.servicers` are deliberately thin - convert, call a method
here, return a model - so that this is the only place that knows the rules about
*when* something may be done. Two of those rules are worth naming:

* **Arming builds a new session.** Counters, rounds, history and the RNG start
  again from the config as it stands. Editing the config or the sets does not
  quietly restart anything; :meth:`SessionService.arm` is the only thing that
  does, and it is a button somebody presses.
* **The debug controls drive the real loop.** ``step`` goes through
  :func:`triald.runner.run_trial` - the same four calls a rig makes - with a
  :class:`~triald.behaviour.SimulatedBehaviourSource` standing in for the
  microcontroller. They are not a second code path pretending to be the first,
  which is the whole reason the behaviour source is an interface.

**One daemon, one session.** There is no session id in any of this, matching the
one-daemon-per-rig shape in dev/PLAN.md. Cross-rig aggregation is a separate
tool's job; putting a session id through every call to leave room for it would
cost every client something today for something nobody has asked for yet.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import dataclasses
import datetime as dt
import enum
import hashlib
import logging
import random
import tempfile
import traceback
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Literal

from triald.behaviour import SimulatedBehaviourSource
from triald.metadata import SessionEvent, SessionMetadata
from triald.outcomes import OutcomeReport
from triald.policy import DeclarativePolicy, Policy, PolicyError, load_policy
from triald.recording import RecordingError, SessionRecorder
from triald.runner import run_trial
from triald.session import (
    Session,
    SessionConfig,
    SessionError,
    TheOutcomeIsForAnotherTrial,
)
from triald.state import SessionState, TrialRecord, TrialSpec
from triald.trialtypes import TRIAL_TYPES_PER_SET, TrialTypeSet, TrialTypeStore

log = logging.getLogger(__name__)


# -- what this layer hands to `triald.api.convert` -----------------------------
#
# Small carriers, not wire types. The API layer assembles an answer out of
# several places — a session, a store, a policy — and something has to carry
# the pieces from here to the seam. These do, and they are dataclasses for the
# same reason everything else in this daemon is: a protobuf message here would
# put the wire format inside the service.


@dataclasses.dataclass(frozen=True, slots=True)
class StateSnapshot:
    """Everything the state message is assembled from."""

    state: SessionState
    armed: bool
    trial_type_set: TrialTypeSet
    config: SessionConfig
    policy: dict[str, Any]
    policy_errors: list[dict[str, Any]]
    number_offset: int


@dataclasses.dataclass(frozen=True, slots=True)
class SetsSnapshot:
    """Every set in the store, and whether the switch chain hangs together."""

    sets: list[TrialTypeSet]
    active: str | None
    chain_problem: str | None


@dataclasses.dataclass(frozen=True, slots=True)
class ConfigUpdate:
    """What a config change actually did."""

    changed: list[str]
    bag_rebuilt: bool
    config: SessionConfig


@dataclasses.dataclass(slots=True)
class SimSettings:
    """The synthetic subject's probabilities.

    Mutable and not frozen: the debug panel moves a slider and the subject is
    retuned in place, which is the whole point of it.
    """

    hit_rate: float = 0.75
    not_started_rate: float = 0.05
    eye_error_rate: float = 0.08
    early_rate: float = 0.05
    frame_loss_rate: float = 0.0
    imprecise_fixation_rate: float = 0.0
    hit_rate_by_type: dict[str, float] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True, slots=True)
class StreamFrame:
    """One frame of the state stream, before it is a wire message."""

    sequence: int
    at: dt.datetime
    snapshot: StateSnapshot


@dataclasses.dataclass(frozen=True, slots=True)
class FreeRun:
    """Whether the simulator is stepping on a timer, and how fast."""

    running: bool
    interval_ms: int


@dataclasses.dataclass(frozen=True, slots=True)
class PolicyCheck:
    """What checking a policy found. `diagnostics` are messages, with a line
    number when the failure was a syntax error and none when it was not."""

    ok: bool
    class_name: str | None
    sha256: str
    diagnostics: list[tuple[int | None, int | None, str]]
    trials_run: int = 0


#: How often the watchdog looks at the trial in flight. Coarse on purpose: it is
#: guarding against a daemon that has stopped answering, not measuring anything,
#: and a trial cap is seconds at least. See `SessionConfig.trial_cap_ms`.
WATCHDOG_INTERVAL_SECONDS = 0.5

#: How many state frames a slow subscriber may fall behind before frames are
#: dropped. The stream is a *state* stream, not an event log: a subscriber that
#: cannot keep up wants the newest snapshot, never a backlog of stale ones.
STREAM_BACKLOG = 4


class Refusal(enum.Enum):
    """Why a call was refused — the category, in this daemon's own words.

    **These used to be HTTP status codes**, carried as integers from the days
    when this API was routes: `409` for a wrong moment, `422` for a body that
    did not validate. The API is gRPC now and nothing here answers HTTP, so an
    integer somebody has to look up was a fossil twice over — `api/servicers/`
    translated it, and the domain layer had to know a number that meant nothing
    to it.

    Four categories, and the whole vocabulary. Each maps to exactly one gRPC
    status in `api/servicers/refusals.py`; the *case* within a category is
    `ServiceError.kind`, which is what a client actually switches on.
    """

    #: The daemon is not in a state where this call means anything: no session
    #: armed, a trial already in flight. Nothing about the request is wrong.
    WRONG_MOMENT = "wrong_moment"

    #: Understood and refused: a set whose weights are all zero, an arm-time
    #: setting changed mid-session, a policy that did not pass its check.
    BAD_REQUEST = "bad_request"

    #: No such set, no such policy.
    NO_SUCH_THING = "no_such_thing"

    #: The daemon broke, not the caller. A recording that could not be written
    #: is the one that matters: it stops the session rather than continuing
    #: quietly.
    THE_DAEMON_BROKE = "the_daemon_broke"


class ServiceError(Exception):
    """A call was refused, with a message meant to be shown to a person."""

    def __init__(
        self, detail: str, *, kind: str = "request", refusal: Refusal = Refusal.WRONG_MOMENT
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind = kind
        self.refusal = refusal


class SessionService:
    """The daemon's mutable state, behind one object.

    Holds the trial type store, the session config, the live
    :class:`~triald.session.Session`, the simulated subject the debug controls
    drive, the loaded policy, and whoever is following the state stream.
    """

    def __init__(
        self,
        store: TrialTypeStore,
        config: SessionConfig,
        *,
        policy: Policy | None = None,
        policy_dir: Path | None = None,
        results_dir: Path | None = None,
        clock: Any = None,
    ) -> None:
        self.store = store
        self.config = config
        self.policy_dir = policy_dir
        self.results_dir = results_dir
        self._clock = clock if clock is not None else _wall_clock

        self._policy: Policy = policy if policy is not None else DeclarativePolicy()
        self._policy_name = "declarative"
        self._policy_source: str | None = None
        self._policy_sha: str | None = None
        self._policy_origin: Literal["default", "file", "uploaded"] = "default"

        self.sim = SimSettings()
        self._subject = self._build_subject()
        self._recorder: SessionRecorder | None = None

        self._session = self._build_session()

        self._subscribers: set[asyncio.Queue[StreamFrame]] = set()
        self._sequence = 0
        self._free_run: asyncio.Task[None] | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._free_run_interval_ms = 250

    # -- building the pieces ----------------------------------------------------

    def _build_session(self) -> Session:
        return Session(
            self.store,
            self.config,
            policy=self._policy,
            recorder=self._recorder,
            clock=self._clock,
        )

    def _build_subject(self) -> SimulatedBehaviourSource:
        """A fresh simulated subject on the session's seed.

        Seeded from the config so that a simulated run is reproducible end to
        end: the same seed gives the same selections *and* the same outcomes,
        which is what makes "it did something odd at trial 300" a thing you can
        reproduce rather than describe.
        """
        return SimulatedBehaviourSource(
            rng=random.Random(self.config.seed),
            **dataclasses.asdict(self.sim),
        )

    # -- session lifecycle ------------------------------------------------------

    @property
    def session(self) -> Session:
        return self._session

    def arm(self) -> None:
        """Build a new session from the current config and validate it.

        Everything starts again: counters, rounds, history, the RNG and the
        simulated subject.

        Raises:
            ServiceError: with the first problem ``Session.arm`` found. It
                refuses rather than failing later, which is the point of it -
                see :meth:`triald.session.Session.arm`.
        """
        if self._session.running:
            raise ServiceError(
                "a session is already running; stop it before arming another",
                kind="session",
            )

        self._subject = self._build_subject()
        self._session = self._build_session()
        try:
            self._session.arm()
        except SessionError as exc:
            raise ServiceError(str(exc), kind="session", refusal=Refusal.BAD_REQUEST) from exc

    def stop(self, reason: str = "stopped by the operator") -> None:
        self._session.stop(reason)
        self._close_recorder()

    def require_running(self) -> Session:
        if not self._session.running:
            raise ServiceError(
                "the session is not running - arm it first",
                kind="session",
                refusal=Refusal.WRONG_MOMENT,
            )
        return self._session

    # -- recording --------------------------------------------------------------

    def start_recording(self) -> None:
        """Begin recording. Opens a session directory when one is configured.

        With no ``results_dir`` the flags still move - a trial is latched as
        recording or not, and the UI shows it - but nothing reaches the disk.
        That is the right behaviour for a simulator on a laptop and the wrong
        one for a rig, so the state says which it is.
        """
        session = self.require_running()
        if self.results_dir is not None and self._recorder is None:
            recorder = SessionRecorder(self.results_dir, metadata=SessionMetadata())
            try:
                recorder.open(config=self.config.as_dict(), seed=session.seed)
            except OSError as exc:
                raise ServiceError(
                    f"could not open a session directory under {self.results_dir}: {exc}",
                    kind="recording",
                    refusal=Refusal.THE_DAEMON_BROKE,
                ) from exc
            self._recorder = recorder
            session.recorder = recorder
        session.start_recording()

    def stop_recording(self) -> None:
        self._session.stop_recording()
        self._close_recorder()

    def pause_recording(self) -> None:
        self.require_running().pause_recording()

    def resume_recording(self) -> None:
        self.require_running().resume_recording()

    def _close_recorder(self) -> None:
        if self._recorder is None:
            return
        state = self._session.state()
        with contextlib.suppress(RecordingError, OSError):
            self._recorder.close(
                {
                    "trials": len(state.history),
                    "accepted": state.totals.accepted,
                    "hits": state.totals.hits,
                    "final_set": state.set_name,
                    "stop_reason": self._session.stop_reason,
                }
            )
        self._recorder = None
        self._session.recorder = None

    def note(self, text: str) -> None:
        """Append an experimenter's note to the event stream.

        Refused rather than silently dropped when nothing is recording: a note
        that goes nowhere is worse than one that could not be written, because
        the person who typed it believes it was kept.
        """
        if self._recorder is None:
            raise ServiceError(
                "nothing is being recorded, so there is nowhere to put a note",
                kind="recording",
            )
        state = self._session.state()
        self._recorder.note(
            text, trial_number=state.current.trial_number if state.current else None
        )

    # -- the trial loop ---------------------------------------------------------

    def next_trial(self) -> TrialSpec:
        session = self.require_running()
        try:
            spec = session.next_trial()
        except SessionError as exc:
            raise ServiceError(str(exc), kind="session") from exc
        self._subject.set_current_trial(spec)
        return spec

    def report_outcome(self, report: OutcomeReport, *, trial_id: int) -> TrialRecord:
        session = self.require_running()
        try:
            record = session.report_outcome(report, trial_id=trial_id)
        except TheOutcomeIsForAnotherTrial as exc:
            # Its own kind, so a rig loop can catch this one by name: it is the
            # refusal a correct caller can hit, and the answer is to drop the
            # report rather than to retry it against whatever is in flight now.
            raise ServiceError(str(exc), kind="trial_mismatch") from exc
        except SessionError as exc:
            raise ServiceError(str(exc), kind="session") from exc
        except RecordingError as exc:
            self._session.stop(f"the recording failed: {exc}")
            raise ServiceError(
                str(exc), kind="recording", refusal=Refusal.THE_DAEMON_BROKE
            ) from exc
        return record

    def cancel_trial(self, reason: str) -> TrialRecord:
        session = self.require_running()
        try:
            record = session.cancel_trial(reason)
        except SessionError as exc:
            raise ServiceError(str(exc), kind="session") from exc
        return record

    # -- the debug stepper ------------------------------------------------------

    def step(self, trials: int) -> int:
        """Run `trials` whole simulated trials, or fewer if the session stops.

        Goes through :func:`triald.runner.run_trial`, so it exercises the same
        path a rig does with the microcontroller replaced by the simulated
        subject.

        Returns:
            How many trials actually ran.
        """
        session = self.require_running()
        if session.state().current is not None:
            raise ServiceError(
                "a trial is in flight - report or cancel it before stepping",
                kind="session",
            )

        ran = 0
        for _ in range(trials):
            if not session.running:
                break
            try:
                run_trial(session, self._subject)
            except (SessionError, RecordingError) as exc:
                session.stop(f"the step failed: {exc}")
                raise ServiceError(
                    str(exc), kind="session", refusal=Refusal.THE_DAEMON_BROKE
                ) from exc
            ran += 1
        if not session.running:
            self._close_recorder()
        return ran

    def set_sim(self, settings: SimSettings) -> None:
        """Retune the simulated subject without restarting the session.

        The RNG is left where it is: only the probabilities change, so a session
        stays reproducible up to the point somebody moved a slider.
        """
        self.sim = settings
        for name, value in dataclasses.asdict(settings).items():
            setattr(self._subject, name, value)

    # -- free run ---------------------------------------------------------------

    def free_run_status(self) -> FreeRun:
        running = self._free_run is not None and not self._free_run.done()
        return FreeRun(running=running, interval_ms=self._free_run_interval_ms)

    async def set_free_run(self, running: bool, interval_ms: int) -> FreeRun:
        """Start or stop stepping the simulator on a timer."""
        self._free_run_interval_ms = interval_ms
        await self._cancel_free_run()
        if running:
            self.require_running()
            self._free_run = asyncio.create_task(self._free_run_loop())
        return self.free_run_status()

    async def _cancel_free_run(self) -> None:
        task, self._free_run = self._free_run, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _free_run_loop(self) -> None:
        """Step one trial per interval until the session stops or is cancelled."""
        try:
            while self._session.running:
                try:
                    self.step(1)
                except ServiceError as exc:
                    log.error("free run stopped: %s", exc.detail)
                    break
                await self.publish()
                await asyncio.sleep(self._free_run_interval_ms / 1000)
        except asyncio.CancelledError:
            raise
        finally:
            await self.publish()

    # -- the watchdog -----------------------------------------------------------

    async def start_watchdog(self) -> None:
        """Begin checking whether the trial in flight has stopped being answered.

        **Nobody is responsible for delivering an outcome**, and that is correct:
        an executor publishes what it saw and assumes nobody read it, because it
        cannot know whether a consumer exists or is running a session. So only
        this side can tell "not yet" from "never", and without this a
        subscription that dies is a session that quietly stops with no error
        anywhere and nothing in the record to say why.

        Cheap and unconditional: the check is a comparison against a latched
        deadline, it does nothing when `trial_cap_ms` is zero, and it does
        nothing when no trial is in flight. Started for the app's whole life
        rather than per session, so there is no state saying whether it is
        running.
        """
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._watchdog_loop())

    async def _watchdog_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
                try:
                    record = self._session.expire_overdue_trial()
                except Exception:
                    # A watchdog that can kill the session it guards is worse
                    # than none. There is an animal in the rig.
                    log.exception("the trial watchdog failed")
                    continue
                if record is not None:
                    log.error(
                        "trial %d expired: %s", record.spec.trial_number, record.report.note
                    )
                    await self.publish()
        except asyncio.CancelledError:
            raise

    async def shutdown(self) -> None:
        await self._cancel_free_run()
        task, self._watchdog = self._watchdog, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._close_recorder()

    # -- sets -------------------------------------------------------------------

    def sets(self) -> SetsSnapshot:
        """Every set in the store, with what the daemon knows about them.

        The pieces rather than a wire message: `triald.api.convert` turns these
        into one, and nothing below the API layer names a protobuf type.
        """
        active = self._session.trial_type_set.name
        return SetsSnapshot(
            sets=list(self.store.sets()),
            active=active,
            chain_problem=self.store.validate_switch_chain(active),
        )

    def put_set(self, new_set: TrialTypeSet) -> SetsSnapshot:
        """Add or replace a set.

        Replacing the *active* set while a session runs rebuilds the bag, which
        restarts the round - there is no honest way to carry a half-finished
        round across a change of weights. The counters are banked by name and
        survive it.
        """
        active = self._session.trial_type_set.name
        if self._session.running and new_set.name == active and not new_set.is_runnable():
            raise ServiceError(
                f"set {new_set.name!r} is running and every weight is zero, so a "
                f"round would be empty - give one trial type a weight first",
                kind="sets",
                refusal=Refusal.BAD_REQUEST,
            )

        self.store.put(new_set)
        if self._session.running and new_set.name == active:
            self._session.load_set(new_set.name)
        return self.sets()

    def delete_set(self, name: str) -> SetsSnapshot:
        if name == self._session.trial_type_set.name:
            raise ServiceError(
                f"set {name!r} is the one that is loaded; load another first",
                kind="sets",
            )
        try:
            self.store.remove(name)
        except KeyError as exc:
            raise ServiceError(str(exc), kind="sets", refusal=Refusal.NO_SUCH_THING) from exc
        return self.sets()

    def load_set(self, name: str) -> None:
        """Make `name` the active set. Its block starts from nothing.

        The same thing the switch rule does automatically, so that loading by
        hand and switching by rule cannot disagree about what loading means.
        """
        session = self.require_running()
        try:
            session.load_set(name)
        except KeyError as exc:
            # Its own arm: a set that is not there is `not_found`, the same as
            # deleting one that is not there. Folded in with SessionError it
            # answered `invalid_argument`, which says the request was wrong
            # rather than that the thing it named does not exist.
            raise ServiceError(str(exc), kind="sets", refusal=Refusal.NO_SUCH_THING) from exc
        except SessionError as exc:
            raise ServiceError(str(exc), kind="sets", refusal=Refusal.BAD_REQUEST) from exc

    # -- config -----------------------------------------------------------------

    def update_config(self, changes: dict[str, Any]) -> ConfigUpdate:
        """Apply a partial config change, and say what it cost.

        The session holds the very same config object, so this goes through
        :meth:`triald.session.Session.reconfigure` whether or not anything has
        been armed - one set of rules about what may change when, rather than
        two that disagree at the edges.
        """
        armed = self._session.armed
        try:
            changed = self._session.reconfigure(changes)
        except SessionError as exc:
            raise ServiceError(str(exc), kind="config", refusal=Refusal.BAD_REQUEST) from exc

        # initial_set, the seed and the numbering are read when a session is
        # constructed, so a change to one has to build a new session rather than
        # half-apply itself to the one that is standing.
        if set(changed) & Session.ARM_TIME_FIELDS:
            self._session = self._build_session()

        return ConfigUpdate(
            changed=changed,
            bag_rebuilt=armed and bool(set(changed) & Session.BAG_FIELDS),
            config=self.config,
        )

    def reset_rounds(self) -> None:
        self._session.reset_rounds()

    def reset_counters(self) -> None:
        self._session.reset_counters()

    # -- policy -----------------------------------------------------------------

    def policy_info(self, *, with_source: bool = False) -> dict[str, Any]:
        """What is loaded, as plain values for `triald.api.convert`.

        A policy's `snapshot()` is somebody's Python and may raise; a session
        that cannot describe its policy is still a session worth looking at, so
        the failure costs the field rather than the answer.
        """
        state = None
        with contextlib.suppress(Exception):
            state = self._policy.snapshot()
        return {
            "name": self._policy_name,
            "class_name": type(self._policy).__name__,
            "sha256": self._policy_sha,
            "origin": self._policy_origin,
            "source": self._policy_source if with_source else None,
            "state": state,
        }

    def check_policy(self, name: str, source: str) -> PolicyCheck:
        """Import `source` and smoke-run it, without touching the session.

        The diagnostics carry line numbers because the alternative - a traceback
        printed underneath an editor - makes somebody count lines by hand at the
        exact moment they are least able to.
        """
        sha = _sha256(source)
        syntax = _syntax_diagnostic(source, name)
        if syntax is not None:
            return PolicyCheck(ok=False, class_name=None, sha256=sha, diagnostics=[syntax])

        with tempfile.TemporaryDirectory(prefix="triald-policy-") as tmp:
            path = Path(tmp) / f"{_safe_stem(name)}_{sha[:12]}.py"
            path.write_text(source, encoding="utf-8")
            try:
                policy = load_policy(path)
            except PolicyError as exc:
                return PolicyCheck(
                    ok=False,
                    class_name=None,
                    sha256=sha,
                    diagnostics=[_diagnostic_from_exception(exc, path)],
                )

            ran, errors = self._smoke_run(policy)

        return PolicyCheck(
            ok=not errors,
            class_name=type(policy).__name__,
            sha256=sha,
            # No line number: the policy imported and then misbehaved, so there
            # is nothing to point at in the source.
            diagnostics=[(None, None, message) for message in errors],
            trials_run=ran,
        )

    def load_policy_source(self, name: str, source: str) -> dict[str, Any]:
        """Store `source`, import it, and use it from the next arm onwards.

        The daemon holds the text rather than a path: a session record has to be
        able to say which version of a policy ran, from its own directory, and a
        filename cannot say that because the file changes.

        Refused while a session runs. VStim swaps at a trial boundary; here,
        arming is the boundary, and it is one somebody presses on purpose.
        """
        if self._session.running:
            raise ServiceError(
                "a session is running - stop it before loading another policy",
                kind="policy",
            )

        result = self.check_policy(name, source)
        if not result.ok:
            first = result.diagnostics[0][2] if result.diagnostics else "unknown error"
            raise ServiceError(
                f"the policy did not pass its check, so it was not loaded: {first}",
                kind="policy",
                refusal=Refusal.BAD_REQUEST,
            )

        directory = self.policy_dir or Path(tempfile.gettempdir()) / "triald-policies"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_safe_stem(name)}_{result.sha256[:12]}.py"
        path.write_text(source, encoding="utf-8")

        try:
            self._policy = load_policy(path)
        except PolicyError as exc:  # pragma: no cover - check_policy just passed
            raise ServiceError(str(exc), kind="policy", refusal=Refusal.BAD_REQUEST) from exc

        self._policy_name = name
        self._policy_source = source
        self._policy_sha = result.sha256
        self._policy_origin = "uploaded"
        self._session = self._build_session()

        if self._recorder is not None:
            self._recorder.event(
                SessionEvent(
                    kind="policy",
                    data={"name": name, "sha256": result.sha256},
                    source="triald",
                )
            )
        return self.policy_info()

    def clear_policy(self) -> dict[str, Any]:
        """Go back to the declarative behaviour."""
        if self._session.running:
            raise ServiceError(
                "a session is running - stop it before unloading the policy",
                kind="policy",
            )
        self._policy = DeclarativePolicy()
        self._policy_name = "declarative"
        self._policy_source = None
        self._policy_sha = None
        self._policy_origin = "default"
        self._session = self._build_session()
        return self.policy_info()

    def _smoke_run(self, policy: Policy) -> tuple[int, list[str]]:
        """Run `policy` over a throwaway copy of this experiment.

        A copy, on its own seed, so a check never touches the counters of a
        session somebody is watching.
        """
        # A deep copy, because the smoke run arms a session against it and a
        # session mutates its config. This used to round-trip through the wire
        # models to get one, which worked and hid what it was doing.
        config = dataclasses.replace(copy.deepcopy(self.config), seed=0)
        store = TrialTypeStore([copy.deepcopy(s) for s in self.store.sets()])
        session = Session(store, config, policy=policy)
        subject = SimulatedBehaviourSource(rng=random.Random(0))

        ran = 0
        try:
            session.arm()
            while session.running and ran < 50:
                run_trial(session, subject)
                ran += 1
        except Exception as exc:
            return ran, [f"the smoke run raised {type(exc).__name__}: {exc}"]

        return ran, [f"{e['hook']}: {e['error']}" for e in session.policy_errors]

    # -- the state snapshot and the stream --------------------------------------

    def snapshot(self) -> StateSnapshot:
        """Everything the state message is assembled from, and nothing more.

        The pieces rather than the message: this layer holds the session, and
        `triald.api.convert` is the only thing that knows what a wire type
        looks like.
        """
        return StateSnapshot(
            state=self._session.state(),
            armed=self._session.armed,
            trial_type_set=self._session.trial_type_set,
            config=self.config,
            policy=self.policy_info(),
            policy_errors=list(self._session.policy_errors),
            number_offset=self._number_offset(),
        )

    def _number_offset(self) -> int:
        """What the loaded set contributes to its trial types' numbers.

        Mirrors ``Session._effective_number``: the set's 1-based position times
        the block size when the numbering is extended, and nothing otherwise.
        """
        if not self.config.extend_trial_type_number:
            return 0
        return (self.store.index_of(self._session.trial_type_set.name) + 1) * (
            TRIAL_TYPES_PER_SET
        )

    @contextlib.contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[StreamFrame]]:
        """Register a queue for state frames, for as long as the block runs."""
        queue: asyncio.Queue[StreamFrame] = asyncio.Queue(maxsize=STREAM_BACKLOG)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def publish(self) -> None:
        """Push the current state to every subscriber.

        A subscriber that is full has its oldest frame dropped rather than the
        newest: this is a state stream, so the freshest snapshot is the only one
        worth having, and a slow browser tab must not be able to hold up the
        session.
        """
        if not self._subscribers:
            return

        self._sequence += 1
        message = StreamFrame(
            sequence=self._sequence, at=self._clock(), snapshot=self.snapshot()
        )
        for queue in list(self._subscribers):
            while True:
                try:
                    queue.put_nowait(message)
                    break
                except asyncio.QueueFull:
                    with contextlib.suppress(asyncio.QueueEmpty):
                        queue.get_nowait()

    @contextlib.asynccontextmanager
    async def publishing(self) -> AsyncIterator[None]:
        """Publish the new state once the block has changed something."""
        try:
            yield
        finally:
            await self.publish()


# -- policy diagnostics ---------------------------------------------------------


#: One diagnostic: a line, a column, and what is wrong. A tuple rather than a
#: type, because it is three values with no behaviour and it crosses one seam.
Diagnostic = tuple[int | None, int | None, str]


def _syntax_diagnostic(source: str, name: str) -> Diagnostic | None:
    try:
        compile(source, f"<{name}>", "exec")
    except SyntaxError as exc:
        return (exc.lineno, exc.offset, f"{type(exc).__name__}: {exc.msg}")
    except ValueError as exc:  # null bytes, and other things compile() refuses
        return (None, None, f"{type(exc).__name__}: {exc}")
    return None


def _diagnostic_from_exception(exc: Exception, path: Path) -> Diagnostic:
    """Point at the last line *in the policy* that the traceback passed through.

    The deepest frame is usually inside the standard library or triald itself,
    which is no use to somebody looking at their own file.
    """
    line = next(
        (
            frame.lineno
            for frame in reversed(traceback.extract_tb(exc.__traceback__))
            if frame.filename == str(path)
        ),
        None,
    )
    return (line, None, str(exc))


def _sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _safe_stem(name: str) -> str:
    """A module-safe stem, so a policy name cannot escape the policy directory."""
    stem = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    return stem.strip("_") or "policy"


def _wall_clock() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = ["STREAM_BACKLOG", "ServiceError", "SessionService"]
