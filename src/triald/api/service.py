"""One rig's session, and everything the routes are allowed to do to it.

The routes in :mod:`triald.api.app` are deliberately thin - parse, call a method
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
import datetime as dt
import hashlib
import logging
import random
import tempfile
import traceback
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Literal

from triald.api import schemas as sc
from triald.behaviour import SimulatedBehaviourSource
from triald.metadata import SessionEvent, SessionMetadata
from triald.policy import DeclarativePolicy, Policy, PolicyError, load_policy
from triald.recording import RecordingError, SessionRecorder
from triald.runner import run_trial
from triald.session import Session, SessionConfig, SessionError
from triald.trialtypes import TRIAL_TYPES_PER_SET, TrialTypeStore

log = logging.getLogger(__name__)

#: How many state frames a slow subscriber may fall behind before frames are
#: dropped. The stream is a *state* stream, not an event log: a subscriber that
#: cannot keep up wants the newest snapshot, never a backlog of stale ones.
STREAM_BACKLOG = 4


class ServiceError(Exception):
    """A call was refused, with a message meant to be shown to a person."""

    def __init__(self, detail: str, *, kind: str = "request", status: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind = kind
        self.status = status


class SessionService:
    """The daemon's mutable state, behind one object.

    Holds the trial type store, the session config, the live
    :class:`~triald.session.Session`, the simulated subject the debug controls
    drive, the loaded policy, and the WebSocket subscribers.
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

        self.sim = sc.SimSettingsModel()
        self._subject = self._build_subject()
        self._recorder: SessionRecorder | None = None

        self._session = self._build_session()

        self._subscribers: set[asyncio.Queue[sc.StreamMessage]] = set()
        self._sequence = 0
        self._free_run: asyncio.Task[None] | None = None
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
            **self.sim.model_dump(),
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
            raise ServiceError(str(exc), kind="session", status=400) from exc

    def stop(self, reason: str = "stopped by the operator") -> None:
        self._session.stop(reason)
        self._close_recorder()

    def require_running(self) -> Session:
        if not self._session.running:
            raise ServiceError(
                "the session is not running - arm it first", kind="session", status=409
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
                    status=500,
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

    def next_trial(self) -> sc.TrialSpecModel:
        session = self.require_running()
        try:
            spec = session.next_trial()
        except SessionError as exc:
            raise ServiceError(str(exc), kind="session") from exc
        self._subject.set_current_trial(spec)
        return sc.TrialSpecModel.of(spec)

    def report_outcome(self, report: sc.OutcomeReportModel) -> sc.TrialRecordModel:
        session = self.require_running()
        try:
            record = session.report_outcome(report.build())
        except SessionError as exc:
            raise ServiceError(str(exc), kind="session") from exc
        except RecordingError as exc:
            self._session.stop(f"the recording failed: {exc}")
            raise ServiceError(str(exc), kind="recording", status=500) from exc
        return sc.TrialRecordModel.of(record)

    def cancel_trial(self, reason: str) -> sc.TrialRecordModel:
        session = self.require_running()
        try:
            record = session.cancel_trial(reason)
        except SessionError as exc:
            raise ServiceError(str(exc), kind="session") from exc
        return sc.TrialRecordModel.of(record)

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
                raise ServiceError(str(exc), kind="session", status=500) from exc
            ran += 1
        if not session.running:
            self._close_recorder()
        return ran

    def set_sim(self, settings: sc.SimSettingsModel) -> None:
        """Retune the simulated subject without restarting the session.

        The RNG is left where it is: only the probabilities change, so a session
        stays reproducible up to the point somebody moved a slider.
        """
        self.sim = settings
        for name, value in settings.model_dump().items():
            setattr(self._subject, name, value)

    # -- free run ---------------------------------------------------------------

    def free_run_status(self) -> sc.FreeRunStatus:
        running = self._free_run is not None and not self._free_run.done()
        return sc.FreeRunStatus(running=running, interval_ms=self._free_run_interval_ms)

    async def set_free_run(self, running: bool, interval_ms: int) -> sc.FreeRunStatus:
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

    async def shutdown(self) -> None:
        await self._cancel_free_run()
        self._close_recorder()

    # -- sets -------------------------------------------------------------------

    def sets_model(self) -> sc.SetsModel:
        active = self._session.trial_type_set.name
        return sc.SetsModel(
            sets=[
                sc.TrialTypeSetModel.of(
                    s,
                    set_number=self.store.index_of(s.name) + 1,
                    active=s.name == active,
                )
                for s in self.store.sets()
            ],
            active=active,
            chain_problem=self.store.validate_switch_chain(active),
        )

    def put_set(self, model: sc.TrialTypeSetModel) -> sc.SetsModel:
        """Add or replace a set.

        Replacing the *active* set while a session runs rebuilds the bag, which
        restarts the round - there is no honest way to carry a half-finished
        round across a change of weights. The counters are banked by name and
        survive it.
        """
        try:
            new_set = model.build()
        except ValueError as exc:
            raise ServiceError(str(exc), kind="sets", status=400) from exc

        active = self._session.trial_type_set.name
        if self._session.running and model.name == active and not new_set.is_runnable():
            raise ServiceError(
                f"set {model.name!r} is running and every weight is zero, so a "
                f"round would be empty - give one trial type a weight first",
                kind="sets",
                status=400,
            )

        self.store.put(new_set)
        if self._session.running and model.name == active:
            self._session.load_set(model.name)
        return self.sets_model()

    def delete_set(self, name: str) -> sc.SetsModel:
        if name == self._session.trial_type_set.name:
            raise ServiceError(
                f"set {name!r} is the one that is loaded; load another first",
                kind="sets",
            )
        try:
            self.store.remove(name)
        except KeyError as exc:
            raise ServiceError(str(exc), kind="sets", status=404) from exc
        return self.sets_model()

    def load_set(self, name: str) -> None:
        """Make `name` the active set. Its block starts from nothing.

        The same thing the switch rule does automatically, so that loading by
        hand and switching by rule cannot disagree about what loading means.
        """
        session = self.require_running()
        try:
            session.load_set(name)
        except (KeyError, SessionError) as exc:
            raise ServiceError(str(exc), kind="sets", status=400) from exc

    # -- config -----------------------------------------------------------------

    def update_config(self, patch: sc.ConfigPatch) -> sc.ConfigUpdateResult:
        """Apply a partial config change, and say what it cost.

        The session holds the very same config object, so this goes through
        :meth:`triald.session.Session.reconfigure` whether or not anything has
        been armed - one set of rules about what may change when, rather than
        two that disagree at the edges.
        """
        armed = self._session.armed
        try:
            changed = self._session.reconfigure(patch.changes())
        except SessionError as exc:
            raise ServiceError(str(exc), kind="config", status=400) from exc

        # initial_set, the seed and the numbering are read when a session is
        # constructed, so a change to one has to build a new session rather than
        # half-apply itself to the one that is standing.
        if set(changed) & Session.ARM_TIME_FIELDS:
            self._session = self._build_session()

        return sc.ConfigUpdateResult(
            changed=changed,
            bag_rebuilt=armed and bool(set(changed) & Session.BAG_FIELDS),
            config=sc.SessionConfigModel.of(self.config),
        )

    def reset_rounds(self) -> None:
        self._session.reset_rounds()

    def reset_counters(self) -> None:
        self._session.reset_counters()

    # -- policy -----------------------------------------------------------------

    def policy_info(self, *, with_source: bool = False) -> sc.PolicyInfoModel:
        state = None
        with contextlib.suppress(Exception):
            state = self._policy.snapshot()
        return sc.PolicyInfoModel(
            name=self._policy_name,
            class_name=type(self._policy).__name__,
            sha256=self._policy_sha,
            origin=self._policy_origin,
            source=self._policy_source if with_source else None,
            state=state,
        )

    def check_policy(self, name: str, source: str) -> sc.PolicyCheckResult:
        """Import `source` and smoke-run it, without touching the session.

        The diagnostics carry line numbers because the alternative - a traceback
        printed underneath an editor - makes somebody count lines by hand at the
        exact moment they are least able to.
        """
        sha = _sha256(source)
        syntax = _syntax_diagnostic(source, name)
        if syntax is not None:
            return sc.PolicyCheckResult(
                ok=False, class_name=None, sha256=sha, diagnostics=[syntax]
            )

        with tempfile.TemporaryDirectory(prefix="triald-policy-") as tmp:
            path = Path(tmp) / f"{_safe_stem(name)}_{sha[:12]}.py"
            path.write_text(source, encoding="utf-8")
            try:
                policy = load_policy(path)
            except PolicyError as exc:
                return sc.PolicyCheckResult(
                    ok=False,
                    class_name=None,
                    sha256=sha,
                    diagnostics=[_diagnostic_from_exception(exc, path)],
                )

            ran, errors = self._smoke_run(policy)

        return sc.PolicyCheckResult(
            ok=not errors,
            class_name=type(policy).__name__,
            sha256=sha,
            diagnostics=[sc.PolicyDiagnostic(message=e) for e in errors],
            trials_run=ran,
        )

    def load_policy_source(self, name: str, source: str) -> sc.PolicyInfoModel:
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
            first = result.diagnostics[0].message if result.diagnostics else "unknown error"
            raise ServiceError(
                f"the policy did not pass its check, so it was not loaded: {first}",
                kind="policy",
                status=400,
            )

        directory = self.policy_dir or Path(tempfile.gettempdir()) / "triald-policies"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{_safe_stem(name)}_{result.sha256[:12]}.py"
        path.write_text(source, encoding="utf-8")

        try:
            self._policy = load_policy(path)
        except PolicyError as exc:  # pragma: no cover - check_policy just passed
            raise ServiceError(str(exc), kind="policy", status=400) from exc

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

    def clear_policy(self) -> sc.PolicyInfoModel:
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
        config = sc.SessionConfigModel.of(self.config).build()
        config.seed = 0
        store = TrialTypeStore([sc.TrialTypeSetModel.of(s).build() for s in self.store.sets()])
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

    def state_model(self) -> sc.SessionStateModel:
        return sc.SessionStateModel.of(
            self._session.state(),
            armed=self._session.armed,
            trial_type_set=self._session.trial_type_set,
            config=sc.SessionConfigModel.of(self.config),
            policy=self.policy_info(),
            policy_errors=self._session.policy_errors,
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
    def subscribe(self) -> Iterator[asyncio.Queue[sc.StreamMessage]]:
        """Register a queue for state frames, for as long as the block runs."""
        queue: asyncio.Queue[sc.StreamMessage] = asyncio.Queue(maxsize=STREAM_BACKLOG)
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
        message = sc.StreamMessage(
            sequence=self._sequence, at=self._clock(), state=self.state_model()
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


def _syntax_diagnostic(source: str, name: str) -> sc.PolicyDiagnostic | None:
    try:
        compile(source, f"<{name}>", "exec")
    except SyntaxError as exc:
        return sc.PolicyDiagnostic(
            line=exc.lineno, column=exc.offset, message=f"{type(exc).__name__}: {exc.msg}"
        )
    except ValueError as exc:  # null bytes, and other things compile() refuses
        return sc.PolicyDiagnostic(message=f"{type(exc).__name__}: {exc}")
    return None


def _diagnostic_from_exception(exc: Exception, path: Path) -> sc.PolicyDiagnostic:
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
    return sc.PolicyDiagnostic(line=line, message=str(exc))


def _sha256(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _safe_stem(name: str) -> str:
    """A module-safe stem, so a policy name cannot escape the policy directory."""
    stem = "".join(c if c.isalnum() or c == "_" else "_" for c in name)
    return stem.strip("_") or "policy"


def _wall_clock() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


__all__ = ["STREAM_BACKLOG", "ServiceError", "SessionService"]
