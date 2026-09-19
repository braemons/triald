# SPDX-License-Identifier: AGPL-3.0-or-later
"""What this client raises when the daemon says no.

Public, and in a module of its own, because these are the names a caller writes
in an `except` — and the whole point of `triald.v1.Error` travelling as itself
is that there is something worth catching by name.
"""

from __future__ import annotations


class DaemonRefusedTheRequest(Exception):
    """The daemon refused, and said why.

    The same name the browser client uses, deliberately: one API, two clients,
    one word for the thing that happened.

    Three things, and all three are worth having:

    * `error` — stable and machine-readable: `session`, `request`, `set`,
      `policy`. **This is the one to branch on.** It is additive within an API
      major version: new kinds appear, none change meaning.
    * `detail` — one sentence, for a person. Usually the answer, because these
      sentences are written to be read.
    * `status` — the gRPC code, as its own name. The category rather than the
      case, and the one thing a caller may act on without reading the rest.

    The first two come from `triald.v1.Error` in the call's trailing metadata,
    not from parsing `detail`: a client that reads a sentence to find out which
    refusal it was breaks when the sentence is reworded.
    """

    def __init__(self, status: str, error: str, detail: str) -> None:
        super().__init__(f"{error}: {detail}")
        self.status = status
        self.error = error
        self.detail = detail

    @property
    def retryable(self) -> bool:
        """Whether retrying the identical request could work.

        Only `unavailable`. Everything else is a request to change something,
        and a loop that retried them would hammer a daemon about a typo.

        `failed_precondition` is the one that looks retryable and is not: "a
        trial is already in flight" clears when somebody reports its outcome,
        which is an action rather than a wait.
        """
        return self.status == "unavailable"


class TheOutcomeIsForAnotherTrial(DaemonRefusedTheRequest):
    """`trial_mismatch` — the report named a trial that is not in flight.

    The same name the daemon raises internally, deliberately.

    Its own class because it is the one refusal a rig loop can be *correct* and
    still hit: a report that crossed the network twice, or arrived after the
    watchdog gave up on the trial. Catching it means dropping that report,
    never retrying it against whatever is in flight now — which is exactly what
    the daemon refused to do on the caller's behalf
    (`contracts/INTERACTIONS.md` §5.1).
    """


class DaemonIsUnavailable(DaemonRefusedTheRequest):
    """`unavailable` — nothing answered.

    Its own class because it is the one a rig script legitimately *waits* on —
    a daemon starting, a box rebooting — and waiting on it should not mean
    catching everything.
    """
