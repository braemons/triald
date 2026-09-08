# SPDX-License-Identifier: AGPL-3.0-or-later
"""The HTTP and WebSocket face of the daemon.

Three things live here, in dependency order:

* :mod:`triald.api.schemas` - Pydantic models covering everything that crosses
  the wire. **This is the contract**, not :class:`triald.Session`: the web UI and
  every client is written against these models and the OpenAPI document
  generated from them.
* :mod:`triald.api.service` - one rig's session, the thing the routes mutate.
  Owns the store, the config, the live :class:`~triald.session.Session`, the
  simulated subject behind the debug controls, and the list of subscribers.
* :mod:`triald.api.app` - the FastAPI application and the routes themselves,
  which are deliberately thin: parse, call the service, return a model.

Importing this package needs the ``serve`` extra (``pip install triald[serve]``).
The domain logic in the rest of ``triald`` needs nothing at all, which is why
these three modules are off to one side rather than mixed in with it.

**The names below are resolved lazily, and that is not a micro-optimisation.**
Not everything under ``api/`` needs the same things: `statemachine_executor`
speaks HTTP and needs ``httpx``, `stimulus_subscriber` speaks ZeroMQ and needs
neither FastAPI nor httpx nor anything else at import time. Re-exporting
`create_app` eagerly would have made *every* module here cost a FastAPI import,
so a subscriber that was carefully written to need nothing could not be imported
on a machine without the ``serve`` extra — its own care defeated by a
neighbour's. PEP 562 keeps the convenient spelling without the coupling.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ServiceError", "SessionService", "create_app"]


def __getattr__(name: str) -> Any:
    if name == "create_app":
        from triald.api.app import create_app

        return create_app
    if name in ("ServiceError", "SessionService"):
        from triald.api import service

        return getattr(service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
