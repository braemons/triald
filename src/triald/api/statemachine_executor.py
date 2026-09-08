# SPDX-License-Identifier: AGPL-3.0-or-later
"""Talking to a state-machine daemon: three calls out, and a stream back.

The implementation of :class:`triald.executor.TrialExecutor` for a
`statemachined` on the network. It is in `api/` rather than beside the contract
because it needs `httpx`, and triald's core has no dependencies at all --
importing `triald.executor` and testing the translation must not require a
network library, let alone a rig.

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

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx

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
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------- outwards ---

    def configure(self, configuration: TrialConfiguration) -> None:
        self._post(
            "/api/trial/configure",
            {
                "trial_id": configuration.trial_id,
                # The executor's own name for it. triald spells the field
                # `statemachine_graph` because in triald's vocabulary a bare
                # "graph" says nothing about whose it is; there, the namespace
                # supplies the rest. One field, mapped in one place.
                "graph": configuration.statemachine_graph,
                "cap_milliseconds": configuration.cap_milliseconds,
            },
            doing=f"arming trial {configuration.trial_id}",
        )

    def start(self, trial_id: int) -> None:
        self._post(
            "/api/trial/start", {"trial_id": trial_id}, doing=f"starting trial {trial_id}"
        )

    def cancel(self, trial_id: int, reason: str = "") -> None:
        self._post(
            "/api/trial/cancel", {"trial_id": trial_id}, doing=f"cancelling trial {trial_id}"
        )

    def _post(self, path: str, body: dict[str, Any], *, doing: str) -> dict[str, Any]:
        try:
            response = self._client.post(f"{self.base_url}{path}", json=body)
        except httpx.HTTPError as exc:
            raise ExecutorError(f"the executor did not answer while {doing}: {exc}") from exc
        if response.status_code >= 400:
            raise ExecutorError(f"the executor refused while {doing}: {_why(response)}")
        return response.json() if response.content else {}

    # ------------------------------------------------------------ the trial ---

    def events_for_trial(self, trial_id: int) -> list[dict[str, Any]]:
        """Everything the executor published about one trial, by its id.

        A *pull*, by id, and the reason a dropped notification is recoverable
        rather than fatal: whatever the stream did, this answers exactly.
        """
        try:
            response = self._client.get(f"{self.base_url}/api/trace/trial/{trial_id}")
        except httpx.HTTPError as exc:
            raise ExecutorError(
                f"the executor did not answer for trial {trial_id}: {exc}"
            ) from exc
        if response.status_code == 404:
            raise ExecutorError(f"the executor has nothing recorded for trial {trial_id}")
        if response.status_code >= 400:
            raise ExecutorError(f"the executor refused trial {trial_id}: {_why(response)}")
        return response.json().get("entries", [])

    def outcome_of(self, trial_id: int) -> OutcomeReport:
        """The report for one finished trial, built from what it published."""
        return outcome_from_events(trial_id, self.events_for_trial(trial_id))

    # -------------------------------------------------------- the subscription ---

    def stream_url(self) -> str:
        """Where to watch. `ws(s)` derived from the base URL's scheme."""
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        rest = self.base_url.split("://", 1)[-1]
        return f"{scheme}://{rest}/api/trace/stream?observer={OBSERVER_NAME}"

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
        for message in messages:
            event = json.loads(message)
            if "error" in event:
                raise ExecutorError(
                    f"the subscription lost entries {event.get('lost_from_entry_number')} "
                    f"to {event.get('lost_to_entry_number')}: {event['error']}"
                )
            if is_a_finished_trial(event):
                yield int(event["trial_id"])


def _why(response: httpx.Response) -> str:
    """The executor's own words for a refusal, which name the field at fault."""
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    if isinstance(detail, dict):
        return f"{detail.get('error', response.status_code)}: {detail.get('detail', detail)}"
    return f"{response.status_code}: {detail}"
