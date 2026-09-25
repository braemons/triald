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
from grpc_reflection.v1alpha import reflection

from triald._proto.triald.v1 import service_pb2
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

#: Every service, by the name `service.proto` gives it. A new service is a line
#: here, and `tests/test_every_rpc_is_implemented.py` fails until it is.
SERVICER_CLASSES = {
    "State": state_servicer.StateServicer,
    "Session": session_servicer.SessionServicer,
    "Trial": trial_servicer.TrialServicer,
    "SetStore": set_store_servicer.SetStoreServicer,
    "Config": config_servicer.ConfigServicer,
    "Policy": policy_servicer.PolicyServicer,
    "Events": events_servicer.EventsServicer,
    "Debug": debug_servicer.DebugServicer,
}

#: How each one is put on a gRPC server. Generated code, one function per
#: service, and the only thing that knows grpc's registration shape.
REGISTRARS = {
    "State": state_servicer.register,
    "Session": session_servicer.register,
    "Trial": trial_servicer.register,
    "SetStore": set_store_servicer.register,
    "Config": config_servicer.register,
    "Policy": policy_servicer.register,
    "Events": events_servicer.register,
    "Debug": debug_servicer.register,
}


def build_servicers(service: SessionService) -> dict[str, object]:
    """One instance of each service, for whichever transports are serving.

    **Built once and shared.** The gRPC port and the browser edge dispatch into
    the same objects, so an rpc cannot behave differently depending on which
    way a caller reached it — which is the failure mode of having two
    transports at all.
    """
    return {name: cls(service) for name, cls in SERVICER_CLASSES.items()}


def build_server(service: SessionService, address: str) -> grpc.aio.Server:
    """A server with every service on it, bound and not yet started."""
    server = grpc.aio.server()
    for register in REGISTRARS.values():
        register(service, server)
    enable_server_reflection(server)
    server.add_insecure_port(address)
    return server


def enable_server_reflection(server: grpc.aio.Server) -> None:
    """Answer gRPC server reflection, as statemachined and mousewheeld do.

    `grpcurl rig-3.local:8421 list` then names every service without a copy of
    `proto/` on the machine asking, and a generator can read the descriptors off
    the running daemon. The names come from the generated descriptor rather than
    from `REGISTRARS`, so a service added to the `.proto` is listed the day it
    is registered.
    """
    names = [service.full_name for service in service_pb2.DESCRIPTOR.services_by_name.values()]
    reflection.enable_server_reflection([*names, reflection.SERVICE_NAME], server)


#: The gRPC port, from the port a browser is pointed at.
#:
#: **Two listeners, one number to configure.** `port` stays what it has always
#: been — where the panels and the `/elements/` contract live, which is what a
#: console's `rigs.json` holds and what a person types into a browser — and
#: gRPC goes one above it. A Python daemon cannot serve both on one socket the
#: way a Rust one can: `grpc.aio` owns its port outright, and no ASGI server
#: speaks native gRPC. This is where that difference surfaces, and it surfaces
#: as a `+ 1` rather than as a second setting nobody remembers to change.
def grpc_port_for(web_port: int) -> int:
    return web_port + 1
