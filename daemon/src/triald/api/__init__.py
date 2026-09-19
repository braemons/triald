# SPDX-License-Identifier: AGPL-3.0-or-later
"""The HTTP and WebSocket face of the daemon.

Three things live here, in dependency order:

* :mod:`triald.api.wire` - protobuf's JSON mapping, with this API's settings
  pinned. The types themselves are generated from ``proto/triald/v1/``, which
  **is** the contract: types and behaviours both, hand-authored, and everything
  a client reads is generated from it rather than describing it afterwards.
* :mod:`triald.api.convert` - the seam. Wire types on one side, this daemon's
  own frozen dataclasses on the other, and every conversion between them in one
  place. Nothing below this layer names a protobuf type.
* :mod:`triald.api.service` - one rig's session, the thing the routes mutate.
  Owns the store, the config, the live :class:`~triald.session.Session`, the
  simulated subject behind the debug controls, and the list of subscribers.
* :mod:`triald.api.servicers` - the eight services, one module each, and
  deliberately thin: convert, call the service, convert back.
* :mod:`triald.api.grpc_server` - those servicers on a gRPC port.
* :mod:`triald.api.web_edge` - the same servicers behind the Connect protocol,
  and the panels, for a browser that cannot speak gRPC.

Two things used to be here and are gone, for one reason between them.
``schemas.py`` was pydantic models that were the contract, with an OpenAPI
document generated from them; ``app.py`` was the FastAPI routes. A description
generated from the code can only ever restate what the code happens to do,
which is the second description ``contracts/DAEMON_LAYOUT.md`` exists to
prevent now that the first one is written by hand in ``proto/triald/v1/``.

Importing this package needs the ``serve`` extra (``pip install triald[serve]``).
The domain logic in the rest of ``triald`` needs nothing at all, which is why
these three modules are off to one side rather than mixed in with it.

**The names below are resolved lazily, and that is not a micro-optimisation.**
Not everything under ``api/`` needs the same things: `statemachine_executor`
speaks HTTP and needs ``httpx``, `stimulus_subscriber` speaks ZeroMQ and needs
neither. Re-exporting the serving layer eagerly would have made *every* module
here cost a grpcio import, so a subscriber that was carefully written to need
nothing could not be imported on a machine without the ``serve`` extra — its
own care defeated by a neighbour's. PEP 562 keeps the convenient spelling
without the coupling.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ServiceError", "SessionService"]


def __getattr__(name: str) -> Any:
    if name in ("ServiceError", "SessionService"):
        from triald.api import service

        return getattr(service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
