# SPDX-License-Identifier: AGPL-3.0-or-later
"""`TrialdClient` — one rig's trial control, as methods.

Eight gRPC services in `proto/triald/v1/`, one object here. The services are an
organising device for the interface and not something a caller should have to
navigate, so this is flat: `rig.arm()`, `rig.next_trial()`,
`rig.report_outcome(...)`.

Methods are named after what they ask for rather than after their rpcs, which
is the same rule the browser client keeps. Where the two differ, the rpc is
named in the docstring.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import TracebackType

import grpc

from . import _wire_conversions as convert
from ._grpc_transport import call, stream
from ._proto.triald.v1 import (
    debug_pb2,
    policy_pb2,
    service_pb2,
    service_pb2_grpc,
    session_pb2,
    sets_pb2,
    trial_pb2,
)
from .api_types import (
    ConfigPatch,
    ConfigUpdateResult,
    FreeRunStatus,
    OutcomeReport,
    PolicyCheckResult,
    PolicyInfo,
    SessionConfig,
    SessionState,
    Sets,
    SimSettings,
    StepResult,
    StreamFrame,
    TrialRecord,
    TrialSpec,
    TrialTypeSet,
)
from .daemon_refusals import DaemonIsUnavailable

#: What a person types into a browser, and what a console's `rigs.json` holds.
#: The panels are served here; this client does not talk to it.
DEFAULT_WEB_PORT = 8420

#: Where this client connects: **one above the web port**.
#:
#: A Python daemon cannot serve gRPC and a browser on one socket the way a Rust
#: one can — `grpc.aio` owns its port outright, and no ASGI server speaks native
#: gRPC — so triald listens twice, and `grpc_port_for` in the daemon's
#: `api/grpc_server.py` is the same `+ 1` written on the other side. It is a
#: derived number rather than a second setting because a second setting is one
#: nobody remembers to change.
DEFAULT_PORT = DEFAULT_WEB_PORT + 1


class TrialdClient:
    """A connection to one triald daemon.

    ``address`` is ``host``, ``host:port`` or an empty string for localhost.
    One daemon is one rig and one session, so no call carries a session id.

    **The port is the daemon's gRPC one**, which is one above the port the
    panels are served on — see :data:`DEFAULT_PORT`. Pointing this at the
    browser's port reaches an ASGI server that does not speak gRPC, so the
    connection simply never becomes ready; the message says so.

    Use it as a context manager, or call :meth:`close`::

        with TrialdClient("rig.local") as rig:
            rig.arm()
            trial = rig.next_trial()

    **Every method may raise**
    :class:`~triald_client.daemon_refusals.DaemonRefusedTheRequest`. Nothing
    here returns an error code: a refusal carries a machine-readable `error`, a
    sentence, and the gRPC status, and it is raised so that a script cannot
    proceed as though a command had worked.
    """

    def __init__(self, address: str = "", *, port: int = DEFAULT_PORT) -> None:
        self.address = _target(address, port)
        self._channel = grpc.insecure_channel(self.address)
        self._state = service_pb2_grpc.StateStub(self._channel)
        self._session = service_pb2_grpc.SessionStub(self._channel)
        self._trial = service_pb2_grpc.TrialStub(self._channel)
        self._sets = service_pb2_grpc.SetStoreStub(self._channel)
        self._config = service_pb2_grpc.ConfigStub(self._channel)
        self._policy = service_pb2_grpc.PolicyStub(self._channel)
        self._events = service_pb2_grpc.EventsStub(self._channel)
        self._debug = service_pb2_grpc.DebugStub(self._channel)

    def close(self) -> None:
        self._channel.close()

    def __enter__(self) -> TrialdClient:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"TrialdClient({self.address!r})"

    def wait_until_ready(self, timeout_s: float = 10.0) -> None:
        """Block until the daemon answers, or raise `DaemonIsUnavailable`.

        A rig script that starts a daemon and talks to it immediately races the
        daemon's own startup; so does one that runs while a box is rebooting.
        This is the honest way to wait for that, rather than a `sleep` that is
        too short on the day it matters.
        """
        try:
            grpc.channel_ready_future(self._channel).result(timeout=timeout_s)
        except grpc.FutureTimeoutError:
            hint = ""
            if self.address.endswith(f":{DEFAULT_WEB_PORT}"):
                hint = f" — that is the port the panels are served on; gRPC is {DEFAULT_PORT}"
            raise DaemonIsUnavailable(
                "unavailable",
                "unavailable",
                f"no triald answered at {self.address} within {timeout_s:g}s{hint}",
            ) from None

    # -- what is happening ------------------------------------------------------

    def read_state(self) -> SessionState:
        """Everything true right now, in one answer. `State/ReadState`."""
        answer = call(lambda: self._state.ReadState(service_pb2.ReadStateRequest()))
        return convert.session_state_from_wire(answer)

    def watch_state(self) -> Iterator[StreamFrame]:
        """The same thing, pushed. `State/WatchState`.

        An iterator that does not end on its own: it yields the current state
        immediately and then a frame on every change, until the daemon stops or
        the caller stops iterating.

        Frames are coalesced under load, so `sequence` skips — and that is not
        loss. Each frame is a whole state, so the newest one is always the
        truth.
        """
        for frame in stream(lambda: self._state.WatchState(service_pb2.WatchStateRequest())):
            yield convert.stream_frame_from_wire(frame)

    def watch_states(self) -> Iterator[SessionState]:
        """`watch_state`, unwrapped, for the common case.

        The envelope carries a `oneof` so that a later kind of frame can be
        added without every client learning a second stream; a frame whose arm
        this client does not know is skipped rather than guessed at.
        """
        for frame in self.watch_state():
            if frame.state is not None:
                yield frame.state

    # -- the session ------------------------------------------------------------

    def arm(self) -> SessionState:
        """Build a session from the config and the active set, and start it.

        **A new session**: counters, rounds, history, the RNG and the simulated
        subject all start again. It refuses rather than failing later — a
        missing set, an empty set, an unusable switch chain three hops away.
        """
        answer = call(lambda: self._session.Arm(service_pb2.ArmRequest()))
        return convert.session_state_from_wire(answer)

    def stop(self, reason: str = "") -> SessionState:
        """End the session. The reason is recorded and shown."""
        answer = call(lambda: self._session.Stop(service_pb2.StopRequest(reason=reason)))
        return convert.session_state_from_wire(answer)

    def start_recording(self) -> SessionState:
        """Record from the next trial.

        Opens a session directory when the daemon was started with one. Without
        it the flags still move and nothing reaches the disk, which is right
        for a simulator and wrong for a rig — so the state says which it is.
        """
        answer = call(lambda: self._session.StartRecording(service_pb2.StartRecordingRequest()))
        return convert.session_state_from_wire(answer)

    def pause_recording(self) -> SessionState:
        """Keep running, stop recording. A trial already in flight finishes recording."""
        answer = call(lambda: self._session.PauseRecording(service_pb2.PauseRecordingRequest()))
        return convert.session_state_from_wire(answer)

    def resume_recording(self) -> SessionState:
        answer = call(
            lambda: self._session.ResumeRecording(service_pb2.ResumeRecordingRequest())
        )
        return convert.session_state_from_wire(answer)

    def stop_recording(self) -> SessionState:
        """Close the record. The session keeps running."""
        answer = call(lambda: self._session.StopRecording(service_pb2.StopRecordingRequest()))
        return convert.session_state_from_wire(answer)

    # -- the trial loop ---------------------------------------------------------

    def next_trial(self) -> TrialSpec:
        """Select the next trial and get its spec. `Trial/Next`.

        The selection is latched: asking twice without reporting an outcome is
        refused, not a redraw. That is what stops one trial's result being
        attributed to another.
        """
        answer = call(lambda: self._trial.Next(service_pb2.NextTrialRequest()))
        return convert.trial_spec_from_wire(answer)

    def report_outcome(self, trial_number: int, report: OutcomeReport) -> TrialRecord:
        """Report how a trial ended, and get back the record it became.

        `trial_number` addresses the message: it says *which* trial this is the
        outcome of, and a report naming any other is refused with
        `TheOutcomeIsForAnotherTrial` rather than attributed to whatever is in
        flight now. Pass `spec.trial_number` from the `next_trial` you are
        answering.

        Read `record.accepted` before anything else: every outcome is counted,
        and only an accepted one consumes from the round.
        """
        answer = call(
            lambda: self._trial.ReportOutcome(
                convert.outcome_report_to_wire(report, trial_id=trial_number)
            )
        )
        return convert.trial_record_from_wire(answer)

    def cancel_trial(self, reason: str = "cancelled by the experimenter") -> TrialRecord:
        """Abandon the trial in flight.

        It is recorded as `CANCELLED` rather than discarded: a trial that
        happened to an animal happened, and a gap in the numbering is a thing
        somebody has to explain later.
        """
        answer = call(lambda: self._trial.Cancel(trial_pb2.CancelTrial(reason=reason)))
        return convert.trial_record_from_wire(answer)

    # -- sets -------------------------------------------------------------------

    def read_sets(self) -> Sets:
        """Every set, with its rule and whether the chain hangs together."""
        answer = call(lambda: self._sets.ReadSets(service_pb2.ReadSetsRequest()))
        return convert.sets_from_wire(answer)

    def write_set(self, value: TrialTypeSet, *, name: str | None = None) -> Sets:
        """Add or replace a set. `SetStore/WriteSet`.

        Replacing the active set rebuilds the bag and restarts the round; the
        counters are banked by name and survive it. Renaming is a delete and a
        write.

        `name` is the name to store it under, and defaults to the set's own.
        They differ only when something is being renamed by hand.
        """
        request = sets_pb2.WriteSetRequest(name=name or value.name)
        request.set.CopyFrom(convert.trial_type_set_to_wire(value))
        answer = call(lambda: self._sets.WriteSet(request))
        return convert.sets_from_wire(answer)

    def delete_set(self, name: str) -> Sets:
        """Remove a set. Refused for the one that is loaded."""
        answer = call(lambda: self._sets.DeleteSet(sets_pb2.SetName(name=name)))
        return convert.sets_from_wire(answer)

    def load_set(self, name: str) -> SessionState:
        """Make a set active.

        Its block starts from nothing — exactly what an automatic switch does,
        so loading by hand and switching by rule cannot disagree about what
        loading means.
        """
        answer = call(lambda: self._sets.LoadSet(sets_pb2.SetName(name=name)))
        return convert.session_state_from_wire(answer)

    # -- config -----------------------------------------------------------------

    def read_config(self) -> SessionConfig:
        answer = call(lambda: self._config.ReadConfig(service_pb2.ReadConfigRequest()))
        return convert.session_config_from_wire(answer)

    def update_config(self, patch: ConfigPatch) -> ConfigUpdateResult:
        """Change the config, and learn what the change cost.

        The answer says which fields moved and whether the bag had to be
        rebuilt — which restarts the round, and is worth knowing before it
        happens rather than after.
        """
        answer = call(lambda: self._config.PatchConfig(convert.config_patch_to_wire(patch)))
        return convert.config_update_from_wire(answer)

    def reset_rounds(self) -> SessionState:
        """Start the rounds again. The counters are left alone."""
        answer = call(lambda: self._config.ResetRounds(service_pb2.ResetRoundsRequest()))
        return convert.session_state_from_wire(answer)

    def reset_counters(self) -> SessionState:
        """Clear every outcome tally, **in every set**.

        Not only the loaded one: a half-cleared session is worse than either
        state. The bag and the round are left alone; `reset_rounds` is the
        other half.
        """
        answer = call(lambda: self._config.ResetCounters(service_pb2.ResetCountersRequest()))
        return convert.session_state_from_wire(answer)

    # -- policy -----------------------------------------------------------------

    def read_policy(self, *, with_source: bool = False) -> PolicyInfo:
        """The loaded policy: its name, class, sha256, origin and last snapshot."""
        answer = call(
            lambda: self._policy.ReadPolicy(service_pb2.ReadPolicyRequest(source=with_source))
        )
        return convert.policy_info_from_wire(answer)

    def check_policy(self, name: str, source: str) -> PolicyCheckResult:
        """Import and smoke-run a policy without loading it.

        It runs over a throwaway copy of the experiment, so a check never
        touches counters somebody is watching. Diagnostics carry line numbers,
        so an editor can mark the offending line.
        """
        answer = call(
            lambda: self._policy.CheckPolicy(policy_pb2.PolicySource(name=name, source=source))
        )
        return convert.policy_check_from_wire(answer)

    def load_policy(self, name: str, source: str) -> PolicyInfo:
        """Store a policy and load it.

        **The source text, never a path.** The rig is not your laptop, and
        "which version of the staircase ran on Tuesday" has to be answerable
        from the session directory alone — which a filename cannot answer,
        because the file changes.

        It is checked first, always: a syntax error must never reach a session.
        Refused while a session runs; arming is the swap boundary.
        """
        answer = call(
            lambda: self._policy.LoadPolicy(policy_pb2.PolicySource(name=name, source=source))
        )
        return convert.policy_info_from_wire(answer)

    def clear_policy(self) -> PolicyInfo:
        """Back to the declarative behaviour."""
        answer = call(lambda: self._policy.ClearPolicy(service_pb2.ClearPolicyRequest()))
        return convert.policy_info_from_wire(answer)

    # -- events -----------------------------------------------------------------

    def note(self, text: str) -> None:
        """Append an experimenter's note to the event stream.

        Refused when nothing is recording, rather than silently dropped: a note
        that goes nowhere is worse than one that could not be written, because
        the person who typed it believes it was kept.
        """
        call(lambda: self._events.Note(session_pb2.NoteRequest(text=text)))

    # -- the simulated subject --------------------------------------------------

    def read_sim(self) -> SimSettings:
        answer = call(lambda: self._debug.ReadSim(service_pb2.ReadSimRequest()))
        return convert.sim_settings_from_wire(answer)

    def write_sim(self, settings: SimSettings) -> SimSettings:
        """Set the synthetic subject's dials.

        The RNG keeps its place, so a session stays reproducible up to the
        point somebody moved one.
        """
        answer = call(lambda: self._debug.WriteSim(convert.sim_settings_to_wire(settings)))
        return convert.sim_settings_from_wire(answer)

    def step(self, trials: int = 1) -> StepResult:
        """Run whole trials against the simulated subject.

        **Not a second code path**: a step goes through the same
        `runner.run_trial` a rig does, with a synthetic subject in place of the
        microcontroller. Refused with a trial in flight.
        """
        answer = call(lambda: self._debug.Step(debug_pb2.StepRequest(trials=trials)))
        return convert.step_result_from_wire(answer)

    def read_free_run(self) -> FreeRunStatus:
        answer = call(lambda: self._debug.ReadFreeRun(service_pb2.ReadFreeRunRequest()))
        return convert.free_run_from_wire(answer)

    def write_free_run(self, running: bool, interval_ms: int = 250) -> FreeRunStatus:
        """Step the simulated subject on a timer until stopped or the session ends."""
        answer = call(
            lambda: self._debug.WriteFreeRun(
                debug_pb2.FreeRun(running=running, interval_ms=interval_ms)
            )
        )
        return convert.free_run_from_wire(answer)


def _target(address: str, port: int) -> str:
    """`host`, `host:port` or nothing, as something grpc will dial.

    An IPv6 literal has colons in it, so "is there a colon" is not the
    question — "is there a port after the last one" is, and a bracketed
    literal answers it.
    """
    address = address.strip() or "127.0.0.1"
    if address.startswith("["):  # [::1] or [::1]:8420
        return address if address.rfind("]:") != -1 else f"{address}:{port}"
    if address.count(":") == 1:
        return address
    if ":" in address:  # a bare IPv6 literal
        return f"[{address}]:{port}"
    return f"{address}:{port}"
