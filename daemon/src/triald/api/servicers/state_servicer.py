# SPDX-License-Identifier: AGPL-3.0-or-later
"""What is happening, and who is watching."""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator

import grpc

from triald._proto.triald.v1 import (
    service_pb2_grpc,
    session_pb2,
)
from triald.api import convert
from triald.api.service import SessionService
from triald.api.servicers import state_message


class StateServicer(service_pb2_grpc.StateServicer):
    def __init__(self, service: SessionService) -> None:
        self.service = service

    async def ReadState(self, request, context) -> session_pb2.SessionState:
        """Everything true right now, in one answer."""
        return state_message(self.service)

    async def WatchState(self, request, context) -> AsyncIterator[session_pb2.StreamFrame]:
        """Push a frame on every change, plus one on connect.

        The opening frame is what makes this usable on its own: a panel that
        subscribed and then waited would show nothing until the rig next did
        something, which on a rig sitting armed is a long time.

        Frames are coalesced rather than queued for a slow client — every frame
        is a whole state, so the newest is the only one worth having and a gap
        in `sequence` is not loss. The generator ends when the client goes
        away, which is what closes the subscription.
        """
        opening = session_pb2.StreamFrame(sequence=0)
        opening.at.FromDatetime(dt.datetime.now(dt.UTC))
        opening.state.CopyFrom(state_message(self.service))
        yield opening

        with self.service.subscribe() as queue:
            while True:
                frame = await queue.get()
                yield convert.stream_frame_to_wire(frame)


def register(service: SessionService, server: grpc.aio.Server) -> None:
    service_pb2_grpc.add_StateServicer_to_server(StateServicer(service), server)
