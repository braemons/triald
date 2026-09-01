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
"""

from __future__ import annotations

from triald.api.app import create_app
from triald.api.service import ServiceError, SessionService

__all__ = ["ServiceError", "SessionService", "create_app"]
