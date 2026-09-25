# SPDX-License-Identifier: AGPL-3.0-or-later
"""The gRPC port answers server reflection, and names every service in the proto.

statemachined and mousewheeld answer it, so `grpcurl <rig>:<port> list` works
against every daemon in the family without a copy of `proto/` on the machine
asking. The expected names come from the descriptor, not from a list here, so a
service added to `service.proto` and not registered fails this test.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

pytest.importorskip("grpc_reflection", reason="reflection is in the serve extra")

import grpc
from grpc_reflection.v1alpha.proto_reflection_descriptor_database import (
    ProtoReflectionDescriptorDatabase,
)

from triald._proto.triald.v1 import service_pb2
from triald.api import SessionService
from triald.api.grpc_server import build_server
from triald.cli import demo_experiment


def a_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_reflection_lists_every_service_in_the_proto():
    port = a_free_port()

    def list_services() -> list[str]:
        with grpc.insecure_channel(f"127.0.0.1:{port}") as channel:
            return list(ProtoReflectionDescriptorDatabase(channel).get_services())

    async def serve_and_ask() -> list[str]:
        # The server is built inside the loop it runs on, and the synchronous
        # client asks from a thread so that loop keeps answering.
        server = build_server(SessionService(*demo_experiment()), f"127.0.0.1:{port}")
        await server.start()
        try:
            return await asyncio.to_thread(list_services)
        finally:
            await server.stop(None)

    listed = asyncio.run(serve_and_ask())

    declared = {s.full_name for s in service_pb2.DESCRIPTOR.services_by_name.values()}
    assert declared <= set(listed)
    assert "grpc.reflection.v1alpha.ServerReflection" in listed
