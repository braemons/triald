# SPDX-License-Identifier: AGPL-3.0-or-later
"""The API, as the eight services `proto/triald/v1/service.proto` declares.

One module per service, named for it. Every method is thin: convert the
request, call one method on `SessionService`, convert the answer — everything
about *when* something may be done lives in the service, and everything about
*what shape* it has lives in `proto/triald/v1/`. A servicer that grows a
decision has put it in the wrong place.

Two conventions run through all of it, both inherited from the routes these
replaced:

* **Every mutating call answers with the new state.** The stream pushes it too,
  but a client that has just changed something should not have to wait for a
  frame to find out what it did.
* **A mutation happens inside `service.publishing()`**, which is what makes the
  stream fire. A servicer that mutates outside it changes the rig without
  telling anybody watching.

The `Debug` service drives the *simulated* subject and exists so the whole loop
can be exercised with no rig attached. It is the same loop: a debug step goes
through `triald.runner.run_trial`, exactly as a real session does.
"""

from __future__ import annotations

from triald.api import convert
from triald.api.service import SessionService
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    session_pb2,
)


def state_message(service: SessionService) -> session_pb2.SessionState:
    """The whole snapshot, as the wire says it.

    A free function rather than a base class: eight servicers need it and
    inheritance would be the only reason any of them had a parent.
    """
    return convert.session_state_to_wire_from_snapshot(service.snapshot())
