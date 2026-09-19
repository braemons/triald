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

#: Which class implements which service — read from the daemon rather than
#: restated here, so this test cannot pass by agreeing with a copy of the list
#: it is supposed to be checking.
IMPLEMENTATIONS = grpc_server.SERVICER_CLASSES


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
    assert set(grpc_server.REGISTRARS) == set(IMPLEMENTATIONS)


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


def test_the_browser_edge_reaches_every_rpc_too():
    """Two transports, one implementation — and both able to reach all of it.

    The edge builds its dispatch table from the same descriptor, so this is
    really asking whether anything about a method's shape stops it being
    addressable over HTTP. An rpc the panels cannot call is an rpc a panel
    author will reimplement badly somewhere else.
    """
    from triald.api.web_edge import rpcs_of

    # `rpcs_of` only reads the handlers off each servicer, so instances with
    # no session behind them are enough to ask what is addressable.
    servicers = {name: cls.__new__(cls) for name, cls in IMPLEMENTATIONS.items()}
    table = rpcs_of(servicers)

    expected = {
        f"/{descriptor.full_name}/{method.name}"
        for descriptor in service_pb2.DESCRIPTOR.services_by_name.values()
        for method in descriptor.methods
    }
    assert set(table) == expected
    assert len(expected) == 29, "the proto declares 29 rpcs; this is a count of them"
