# SPDX-License-Identifier: AGPL-3.0-or-later
"""`_triald._tcp`: what the record says, and when there is none."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("zeroconf", reason="mDNS is in the serve extra")

from triald.api.mdns_service_advertisement import (
    MdnsServiceAdvertisement,
    is_loopback,
    salted_machine_identifier,
    text_records_for,
)


def test_the_rig_identifier_is_the_family_one(tmp_path):
    # The same machine-id, salted `braemons:`, is what statemachined and
    # mousewheeld advertise as `rig=` too; `id` is this daemon's own.
    machine_id = tmp_path / "machine-id"
    machine_id.write_text("dc4f4b06f2d84f6b9e2a7b0c1d2e3f40\n")
    assert salted_machine_identifier("statemachined:", machine_id) == "0b60208b6da842d7"
    rig = salted_machine_identifier("braemons:", machine_id)
    assert len(rig) == 16
    assert rig != salted_machine_identifier("triald:", machine_id)


def test_the_record_says_where_the_panels_and_the_rpcs_are():
    records = text_records_for("id", "rig", 8420, 8421, "1.2.3")
    assert records["elements"] == "/elements/triald.js"
    assert records["port"] == "8420"
    assert records["grpc_port"] == "8421"
    assert records["rig"] == "rig"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_a_daemon_nobody_else_can_reach_is_not_advertised(host):
    assert is_loopback(host)
    advertisement = MdnsServiceAdvertisement(host, 8420, 8421, "0")
    assert asyncio.run(advertisement.start()) is False


def test_the_rig_network_is_not_loopback():
    assert not is_loopback("0.0.0.0")
    assert not is_loopback("10.0.1.42")
