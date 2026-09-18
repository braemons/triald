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
it is not. It is now `statemachined.client`, which ships from that repository in
the same distribution as the daemon and is tested against it, and this file is
what is genuinely triald's: the translation between `TrialConfiguration` and a
call, and between a refusal and :class:`~triald.executor.ExecutorError`.

**Depending on `statemachined` is not depending on the daemon.** That package is
tiered: the base is the documents and the HTTP client, `[device]` is a serial
port, `[serve]` is the daemon. triald takes the base, which is pydantic, httpx
and websockets. INTERACTIONS.md §2's rule is unaffected -- the decision
authority knows its participants, and they know nobody.

That translation is small and it stays here, because it is where triald's
vocabulary meets somebody else's. `statemachine_graph` becomes `graph` in one
place; every error the client raises becomes the one exception the session loop
knows how to act on, in one place.

**triald is a subscriber here, not a recipient.** The executor publishes its
trace and assumes nobody read it; opening `WS /api/trace/stream` is the whole of
subscribing and closing it is the whole of leaving. Nothing on the far end waits
for triald, holds a trial for it, or retries. Which means the deadline is
triald's: only the side that knows a trial is in flight can tell "not yet" from
"never", and that is this side.

**`?observer=triald` is a label and nothing more.** It puts a name next to the
connection on the executor's own diagnostics page, so a person can see triald is
listening before they reach for a packet capture. Nothing is granted by it.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from typing import Any

import httpx
from statemachined.client import StatemachinedClient, StatemachinedError
from statemachined.client import finished_trials as published_trials_finishing

from triald.executor import (
    ExecutorError,
    TrialConfiguration,
    TrialExecutor,
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

__all__ = ["DEFAULT_TIMEOUT_SECONDS", "OBSERVER_NAME", "StateMachineExecutor"]


class StateMachineExecutor(TrialExecutor):
    """One `statemachined`, addressed by base URL."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
    ) -> None:
        """
        Args:
            client: what carries the requests. The default opens one on the
                network; the tests pass a client over the executor's own ASGI
                app, so the loop is exercised against the real far end rather
                than against triald's belief about it.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.rig = StatemachinedClient(
            self.base_url, timeout_seconds=timeout_seconds, http_client=client
        )

    def close(self) -> None:
        self.rig.close()

    # ------------------------------------------------------------- outwards ---

    def configure(self, configuration: TrialConfiguration) -> None:
        with _refusals_become_executor_errors():
            self.rig.trial.configure(
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
            self.rig.trial.start(trial_id)

    def cancel(self, trial_id: int, reason: str = "") -> None:
        with _refusals_become_executor_errors():
            self.rig.trial.cancel(trial_id)

    # ------------------------------------------------------------ the trial ---

    def events_for_trial(self, trial_id: int) -> list[dict[str, Any]]:
        """Everything the executor published about one trial, by its id.

        A *pull*, by id, and the reason a dropped notification is recoverable
        rather than fatal: whatever the stream did, this answers exactly.
        """
        with _refusals_become_executor_errors():
            return self.rig.trace.for_trial(trial_id)

    def outcome_of(self, trial_id: int) -> OutcomeReport:
        """The report for one finished trial, built from what it published."""
        return outcome_from_events(trial_id, self.events_for_trial(trial_id))

    # -------------------------------------------------------- the subscription ---

    def stream_url(self) -> str:
        """Where to watch. `ws(s)` derived from the base URL's scheme."""
        return self.rig.trace.stream_url(OBSERVER_NAME)

    def subscribe(self, timeout_seconds: float | None = None):
        """Open the subscription, for a caller that wants one opened.

        A convenience over :meth:`stream_url` and not a change to the contract:
        :meth:`finished_trials` still takes messages, so the *rule* stays
        testable with a list of strings and a caller that owns its own socket
        owes this nothing. What it buys is that triald no longer has to name a
        websocket library to do the one thing it does with a rig, which was the
        last piece of statemachined's API living in this repository.

        Returns a context manager; leaving it is the whole of unsubscribing.
        """
        return self.rig.trace.subscribe(OBSERVER_NAME, timeout_seconds=timeout_seconds)

    def finished_trials(self, messages: Iterator[str | bytes]) -> Iterator[int]:
        """The trial ids in a stream of published events, as they finish.

        Takes the messages rather than the socket so that the *rule* -- which
        event ends a trial, and what a torn stream means -- is testable with a
        list of strings, and so that the caller owns the connection. Whether it
        is `websockets`, Starlette's test client or a replay of a log file is not
        this function's business.

        Raises:
            ExecutorError: if the executor says the subscription lost entries.
                It is recoverable -- `events_for_trial` fetches any trial by id
                -- but it must not pass silently: a consumer that believes it
                saw everything is worse than one that knows it did not.
        """
        with _refusals_become_executor_errors():
            yield from published_trials_finishing(messages)


@contextlib.contextmanager
def _refusals_become_executor_errors():
    """One boundary, one exception, and every message kept.

    `statemachined.client` raises a small hierarchy -- a refusal that names the
    field to change, a transport error that means the rig said nothing at all --
    and triald's session loop acts on exactly one thing: this call did not
    happen. So the distinctions are folded here rather than at each call site,
    and nothing is thrown away in the folding: the client's message already
    carries what was being attempted, the daemon's own error code and the field
    it names, and `__cause__` keeps the original for anybody who wants to branch
    on it.
    """
    try:
        yield
    except StatemachinedError as refused:
        raise ExecutorError(str(refused)) from refused
