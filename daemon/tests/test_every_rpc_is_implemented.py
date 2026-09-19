# SPDX-License-Identifier: AGPL-3.0-or-later
"""The proto is the interface, and an interface nothing checks is a wish.

In Rust this test does not exist: tonic generates a trait, and a service with a
missing method is a compile error. Python's generated `Servicer` base classes
are not that — an unimplemented method inherits a body that answers
`UNIMPLEMENTED` at runtime, on a rig, in the middle of a session. So the check
is written out here instead, and it reads the descriptor rather than a list:
adding an rpc to `service.proto` fails this test until something implements it.
"""

from __future__ import annotations

import pytest
from triald.v1 import service_pb2, service_pb2_grpc

from triald.api import grpc_server
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

#: Which class implements which service. The one hand-written list in this
#: file, and the only thing a new service has to be added to.
IMPLEMENTATIONS = {
    "State": state_servicer.StateServicer,
    "Session": session_servicer.SessionServicer,
    "Trial": trial_servicer.TrialServicer,
    "SetStore": set_store_servicer.SetStoreServicer,
    "Config": config_servicer.ConfigServicer,
    "Policy": policy_servicer.PolicyServicer,
    "Events": events_servicer.EventsServicer,
    "Debug": debug_servicer.DebugServicer,
}


def services_in_the_proto():
    return [
        service_pb2.DESCRIPTOR.services_by_name[name]
        for name in service_pb2.DESCRIPTOR.services_by_name
    ]


def test_every_service_in_the_proto_has_an_implementation():
    declared = set(service_pb2.DESCRIPTOR.services_by_name)
    assert declared == set(IMPLEMENTATIONS), (
        "service.proto and the servicers disagree about which services exist"
    )


def test_every_service_is_registered_on_the_server():
    """Implemented and *reachable* are different things.

    A servicer nobody registers is a class that imports cleanly and answers
    nothing, which is the failure this catches.
    """
    assert len(grpc_server.REGISTRARS) == len(IMPLEMENTATIONS)


@pytest.mark.parametrize("service_name", sorted(IMPLEMENTATIONS))
def test_every_rpc_has_a_body_of_its_own(service_name: str):
    """Not just present — *overridden*.

    The generated base class supplies every method already, so `hasattr` would
    pass for a service that implements nothing at all. What is checked is that
    the function object is not the generated one.
    """
    descriptor = service_pb2.DESCRIPTOR.services_by_name[service_name]
    implementation = IMPLEMENTATIONS[service_name]
    generated_base = getattr(service_pb2_grpc, f"{service_name}Servicer")

    missing = [
        method.name
        for method in descriptor.methods
        if getattr(implementation, method.name, None)
        is getattr(generated_base, method.name, None)
    ]
    assert not missing, (
        f"{implementation.__name__} inherits {missing} from the generated base, "
        f"so those rpcs answer UNIMPLEMENTED at runtime"
    )
