# SPDX-License-Identifier: AGPL-3.0-or-later
"""The gRPC server: eight services, one session, one port.

`grpc.aio` rather than the threaded server, because the service underneath is
already asynchronous — `publishing()` is an async context manager, the stream
is an `asyncio.Queue`, and free-run is a task on the loop. A threaded server
would have to marshal every call onto that loop and would gain nothing.

**This is the whole of the API.** The panels and the browser's transport live
in `web_edge.py`, which mounts the same servicers behind a protocol a browser
can speak; nothing about the daemon's own surface changes when that is or is
not there.
"""

from __future__ import annotations

import logging

import grpc

from triald.api.service import SessionService
from triald.api.servicers import (
    config_servicer,
    debug_servicer,
    events_servicer,
    policy_servicer,
    session_servicer,
    set_store_servicer,
    state_servicer,
    trial_servicer,
)

log = logging.getLogger(__name__)

#: Every service, in the order `service.proto` declares them. A new service is
#: a line here, and `tests/test_every_rpc_is_implemented.py` fails until it is.
REGISTRARS = (
    state_servicer.register,
    session_servicer.register,
    trial_servicer.register,
    set_store_servicer.register,
    config_servicer.register,
    policy_servicer.register,
    events_servicer.register,
    debug_servicer.register,
)


def build_server(service: SessionService, address: str) -> grpc.aio.Server:
    """A server with every service on it, bound and not yet started."""
    server = grpc.aio.server()
    for register in REGISTRARS:
        register(service, server)
    server.add_insecure_port(address)
    return server
