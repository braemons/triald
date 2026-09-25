# SPDX-License-Identifier: AGPL-3.0-or-later
"""Telling the network this rig has a triald: `_triald._tcp`.

Beside `_vstimd._tcp`, `_statemachined._tcp` and `_mousewheeld._tcp`, so one
browse of the local domain finds every braemons daemon on a rig and a console
needs no `rigs.json` line for this one. statemachined's
`mdns_service_advertisement.rs` is the reference; the TXT keys and the hashing
are the same.

- **`id`** — this daemon on this box: `sha256("triald:" + machine-id)[:16]`.
- **`rig`** — the box: `sha256("braemons:" + machine-id)[:16]`, the same string
  in every braemons daemon's record on it, which is what lets a console show a
  rig once rather than once per daemon.
- **`elements`**, **`port`** — where the panels are. The SRV port is the
  panels' port, which is what a console loads them from; **`grpc_port`** is the
  one above it, because a Python daemon binds two (`contracts/DAEMON_LAYOUT.md`).

**Only where the daemon answers.** triald binds loopback unless told otherwise,
because a policy is Python running in its process. Advertising a LAN address
for a daemon that does not listen on one would be a console's dead panel, so a
loopback-bound daemon is not advertised at all, and says so.

**Never fatal.** A daemon with no network still runs a session.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import logging
import socket
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE_TYPE = "_triald._tcp.local."
MACHINE_ID_PATH = Path("/etc/machine-id")


def salted_machine_identifier(salt: str, machine_id_path: Path = MACHINE_ID_PATH) -> str:
    """Sixteen hex digits of `sha256(salt + machine-id)`; the hostname if there is none."""
    try:
        seed = machine_id_path.read_text().strip()
    except OSError:
        seed = ""
    seed = seed or socket.gethostname()
    return hashlib.sha256(f"{salt}{seed}".encode()).hexdigest()[:16]


def text_records_for(
    daemon_identifier: str, rig_identifier: str, port: int, grpc_port: int, version: str
) -> dict[str, str]:
    return {
        "id": daemon_identifier,
        "rig": rig_identifier,
        "version": version,
        "elements": "/elements/triald.js",
        "port": str(port),
        "grpc_port": str(grpc_port),
    }


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class MdnsServiceAdvertisement:
    """One `_triald._tcp` registration, for as long as the daemon runs."""

    def __init__(self, host: str, port: int, grpc_port: int, version: str) -> None:
        self.host = host
        self.port = port
        self.grpc_port = grpc_port
        self.version = version
        self._zeroconf = None
        self._info = None

    async def start(self) -> bool:
        """Register. Returns whether it did; never raises."""
        if is_loopback(self.host):
            log.info(
                "mDNS: not advertising, because triald is bound to %s and nobody else "
                "could reach it. Bind the rig network (--host) to be found.",
                self.host,
            )
            return False
        try:
            from zeroconf import IPVersion, ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf

            hostname = socket.gethostname().split(".")[0]
            properties = text_records_for(
                salted_machine_identifier("triald:"),
                salted_machine_identifier("braemons:"),
                self.port,
                self.grpc_port,
                self.version,
            )
            # Bound to one address: advertise that one. Bound to every
            # interface: let zeroconf advertise each of the box's own.
            bound_everywhere = self.host in ("0.0.0.0", "::")
            self._info = ServiceInfo(
                SERVICE_TYPE,
                f"{hostname}.{SERVICE_TYPE}",
                port=self.port,
                properties=properties,
                server=f"{hostname}.local.",
                parsed_addresses=None if bound_everywhere else [self.host],
            )
            self._zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
            if bound_everywhere:
                self._info.addresses = [socket.inet_aton(a) for a in _own_ipv4_addresses()]
            await self._zeroconf.async_register_service(self._info)
        except Exception as error:
            log.warning(
                "mDNS: not advertising (%s). The API is still served; a console will "
                "need this rig's address by hand.",
                error,
            )
            await self.stop()
            return False
        log.info("mDNS: advertising %s", self._info.name)
        return True

    async def stop(self) -> None:
        """Withdraw the record, then close. Never raises."""
        zeroconf, info = self._zeroconf, self._info
        self._zeroconf = self._info = None
        if zeroconf is None:
            return
        try:
            if info is not None:
                await zeroconf.async_unregister_service(info)
        except Exception:
            pass
        await zeroconf.async_close()


def _own_ipv4_addresses() -> list[str]:
    """This box's non-loopback IPv4 addresses, as its own resolver sees them."""
    addresses: set[str] = set()
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = str(entry[4][0])
            if not ipaddress.ip_address(address).is_loopback:
                addresses.add(address)
    except OSError:
        pass
    if not addresses:
        # The address this box would use to reach the outside, without sending
        # anything: connect() on a UDP socket only picks a route.
        with (
            contextlib.suppress(OSError),
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe,
        ):
            probe.connect(("192.0.2.1", 9))
            addresses.add(probe.getsockname()[0])
    return sorted(addresses)
