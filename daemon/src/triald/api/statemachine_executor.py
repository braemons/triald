# SPDX-License-Identifier: AGPL-3.0-or-later
"""Talking to a state-machine daemon: three calls out, and a stream back.

The implementation of :class:`triald.executor.TrialExecutor` for a
`statemachined` on the network. It is in `api/` rather than beside the contract
because it needs a client library, and triald's core has no dependencies at all
-- importing `triald.executor` and testing the translation must not require a
network library, let alone a rig.

**What this file is now, and what it was.** It used to hold triald's own copy of
statemachined's paths, refusal shape and stream rules: `/api/trial/configure`,
the `{"error", "detail", "context"}` body, the `fell_out_of_the_ring` frame.
That was a second description of another daemon's API living in this repository,
and the failure mode of a second description is that it is right until the day
it is not. It is now `statemachined-client`, which is generated from
`proto/statemachined/v1/` in that repository and tested against the daemon that
serves it, and this file is what is genuinely triald's: the translation between
`TrialConfiguration` and a call, and between a refusal and
:class:`~triald.executor.ExecutorError`.

**Depending on `statemachined-client` is not depending on the daemon.** It is a
distribution of its own, and its whole dependency list is grpcio and protobuf.
Not pyserial: triald never opens a serial port. Not pydantic: the documents it
would validate are documents triald never reads. Not fastapi or uvicorn: triald
talks to a daemon rather than being one. INTERACTIONS.md §2's rule is
unaffected -- the decision authority knows its participants, and they know
nobody.

That translation is small and it stays here, because it is where triald's
vocabulary meets somebody else's. `statemachine_graph` becomes `graph` in one
place; every refusal the client raises becomes the one exception the session
loop knows how to act on, in one place.

**triald is a subscriber here, not a recipient.** The executor publishes its
trace and assumes nobody read it; opening `WatchTrace` is the whole of
subscribing and cancelling it is the whole of leaving. Nothing on the far end
waits for triald, holds a trial for it, or retries. Which means the deadline is
triald's: only the side that knows a trial is in flight can tell "not yet" from
"never", and that is this side.

**The observer name is a label and nothing more.** It puts `triald` next to the
connection on the executor's own diagnostics, so a person can see triald is
listening before they reach for a packet capture. Nothing is granted by it.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable, Iterator
from typing import Any

from statemachined_client import (
    DaemonRefusedTheRequest,
    StatemachinedClient,
    TraceEntry,
)

from triald.executor import (
    ExecutorError,
    TrialConfiguration,
    TrialExecutor,
    is_a_finished_trial,
    outcome_from_events,
)
from triald.outcomes import OutcomeReport

log = logging.getLogger(__name__)

#: What triald calls itself on the executor's observer list.
OBSERVER_NAME = "triald"

#: How long to wait on a call that arms or starts a trial. Generous, because the
#: far end may be uploading a graph set to a microcontroller over a serial link,
#: and short enough that a dead executor is a failed trial rather than a hung
#: session.
DEFAULT_TIMEOUT_SECONDS = 10.0

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "OBSERVER_NAME",
    "StateMachineExecutor",
    "flattened",
]


def flattened(entry: TraceEntry) -> dict[str, Any]:
    """One published trace entry as the flat dict triald's rules read.

    **The shape is statemachined's own, not a convenience invented here.** That
    daemon's trace ring holds flat records -- `kind`, `trial_id`, `outcome`,
    `exit_cause`, `measured_duration_microseconds` in one dict -- and its wire
    type names four of those fields and carries the rest in `payload`, because
    the set differs per kind and protobuf has no type for "and some other
    things". Putting them back together is the whole of this function.

    It happens here rather than in the client because it is the *executor's*
    reading of somebody else's record, and `triald.executor` must stay free of
    any dependency: `outcome_from_events` and `reaction_time_milliseconds` are
    triald's rules and are testable with a list of dicts, which is what keeps
    them testable without a rig.

    The named fields win over the payload deliberately. They are the ones the
    wire type promises, and a payload that happened to carry a `trial_id` of
    its own would otherwise decide which trial an entry belonged to.
    """
    return {
        **entry.payload,
        "entry_number": entry.entry_number,
        "kind": entry.kind,
        "trial_id": entry.trial_id,
    }


class StateMachineExecutor(TrialExecutor):
    """One `statemachined`, addressed by host or `host:port`."""

    def __init__(
        self,
        address: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: StatemachinedClient | None = None,
    ) -> None:
        """
        Args:
            address: `host`, or `host:port`. The port is the executor's **gRPC**
                one, which is one above the port its panels are served on; the
                client's `DEFAULT_PORT` is the same rule written on this side.
            client: an already-open client, for a caller that has one. The
                default opens its own.
        """
        self.address = address
        self.timeout_seconds = timeout_seconds
        self.rig = client or StatemachinedClient(address)

    def close(self) -> None:
        self.rig.close()

    # ------------------------------------------------------------- outwards ---

    def configure(self, configuration: TrialConfiguration) -> None:
        with _refusals_become_executor_errors():
            self.rig.configure_trial(
                configuration.trial_id,
                # The executor's own name for it. triald spells the field
                # `statemachine_graph` because in triald's vocabulary a bare
                # "graph" says nothing about whose it is; there, the namespace
                # supplies the rest. One field, mapped in one place.
                graph=configuration.statemachine_graph,
                cap_milliseconds=configuration.cap_milliseconds,
            )

    def start(self, trial_id: int) -> None:
        with _refusals_become_executor_errors():
            self.rig.start_trial(trial_id)

    def cancel(self, trial_id: int, reason: str = "") -> None:
        with _refusals_become_executor_errors():
            self.rig.cancel_trial(trial_id)

    # ------------------------------------------------------------ the trial ---

    def events_for_trial(self, trial_id: int) -> list[dict[str, Any]]:
        """Everything the executor published about one trial, by its id.

        A *pull*, by id, and the reason a dropped notification is recoverable
        rather than fatal: whatever the stream did, this answers exactly.
        """
        with _refusals_become_executor_errors():
            return [flattened(entry) for entry in self.rig.read_trial_trace(trial_id)]

    def outcome_of(self, trial_id: int) -> OutcomeReport:
        """The report for one finished trial, built from what it published."""
        return outcome_from_events(trial_id, self.events_for_trial(trial_id))

    # ------------------------------------------------------ the subscription ---

    def subscribe(self, since_entry_number: int = 0):
        """Open the subscription. Leaving the context manager is unsubscribing.

        A convenience and not a change to the contract: :meth:`finished_trials`
        still takes events, so the *rule* stays testable with a list of dicts
        and a caller that owns its own subscription owes this nothing.

        **`since_entry_number` is the deadline problem in one argument.** Left
        at 0 the stream carries everything the far end's ring still holds,
        which is the right thing for a session that is starting. A session
        resuming after a reconnect passes the number after the last entry it
        saw, and nothing is replayed and nothing is missed.
        """
        return self.rig.watch_trace(since_entry_number, observer=OBSERVER_NAME)

    def finished_trials(self, events: Iterable[TraceEntry | dict[str, Any]]) -> Iterator[int]:
        """The trial ids in a stream of published events, as they finish.

        Takes the events rather than the subscription so that the *rule* --
        which event ends a trial -- is testable with a list of dicts, and so
        that the caller owns the connection. Whether they came off a live
        stream, a `read_trial_trace` or a replay of a log file is not this
        function's business, which is why it accepts either the client's type
        or the flat dict.

        **A gap is not announced and is not detected here.** The executor's
        ring is bounded, and a subscriber that falls behind sees entry numbers
        that skip. That is recoverable -- :meth:`events_for_trial` fetches any
        trial by id -- and detecting it belongs to whoever is holding the
        subscription open, because only that side knows what it expected next.
        """
        with _refusals_become_executor_errors():
            for event in events:
                record = flattened(event) if isinstance(event, TraceEntry) else event
                if is_a_finished_trial(record) and record.get("trial_id") is not None:
                    yield int(record["trial_id"])


@contextlib.contextmanager
def _refusals_become_executor_errors():
    """One boundary, one exception, and every message kept.

    `statemachined-client` raises a small hierarchy -- a refusal that names the
    field to change, a silence that means nothing answered at all -- and
    triald's session loop acts on exactly one thing: this call did not happen.
    So the distinctions are folded here rather than at each call site, and
    nothing is thrown away in the folding: the refusal's message already
    carries the daemon's own error code, the sentence and the field it names,
    and `__cause__` keeps the original for anybody who wants to branch on it.
    """
    try:
        yield
    except DaemonRefusedTheRequest as refused:
        raise ExecutorError(str(refused)) from refused
