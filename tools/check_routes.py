#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Is every route this daemon serves declared in the proto, and vice versa?

`proto/triald/v1/` is the interface (`contracts/DAEMON_LAYOUT.md`), and an
interface nothing checks is a wish. What nothing catches on its own is a
**route**: a handler decorated into the router with no rpc above it is a piece
of public API that exists and is written down nowhere, and an rpc whose route
was never wired is a promise to a client that 404s.

Python needs this more than Rust does, not less. In mousewheeld a field renamed
in the proto stops the daemon compiling; here the generated types and the
handlers are held together by tests and by nothing else, so the one structural
check available is worth having.

It reads both sides:

  * every FastAPI decorator under `daemon/src/triald/api/`, which is the truth
    about what is served;
  * the `option (braemons.v1.route)` on every rpc, which is the truth about
    what is promised.

The `.proto` files are read as text rather than as a descriptor set,
deliberately: a custom option is only legible in a descriptor with the protobuf
runtime and the generated extension to hand, and this has to run in CI on a
machine with nothing installed but `python3` — the same reason
`check_outcomes.py` is regexes over source files.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
API_DIR = HERE / "daemon" / "src" / "triald" / "api"
PROTO_DIR = HERE / "proto" / "triald" / "v1"

#: FastAPI's router carries this prefix; the decorators do not repeat it.
PREFIX = "/api"

#: Served, and deliberately not rpcs.
#:
#: The shell and the panels are a UI contract rather than an interface, and
#: `/api/proto` serves the interface files — it is how the rpcs are read, so it
#: cannot be one of them without describing itself.
NOT_API = {
    ("GET", "/"),
    ("GET", "/elements/{}"),
    ("GET", "/{}"),
    ("GET", "/api/proto"),
    ("GET", "/api/proto/{}"),
}

#: `@router.get("/state", …)`, over however many lines it is written across.
ROUTE_CALL = re.compile(
    r'@(?P<on>router|app)\.(?P<verb>get|post|put|patch|delete|websocket)\(\s*\n?\s*"(?P<path>[^"]*)"'
)

#: Up to the `}` that ends the option, not the first `}` inside it: a path like
#: `/api/sets/{name}` contains one, and `[^}]*` would stop there.
OPTION_BLOCK = re.compile(
    r"option\s*\(braemons\.v1\.route\)\s*=\s*\{(?P<body>.*?)\}\s*;", re.DOTALL
)
RPC_NAME = re.compile(r"\brpc\s+(\w+)\s*\(")


def routes_the_router_serves() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for source in sorted(API_DIR.glob("*.py")):
        for match in ROUTE_CALL.finditer(source.read_text()):
            verb, path = match.group("verb"), match.group("path")
            # A websocket is reached by an HTTP GET that upgrades, which is what
            # the proto's `websocket: true` means and what a router registers.
            if verb == "websocket":
                verb = "get"
            found.add((verb.upper(), normalise(with_prefix(path, match.group("on")))))
    return found


def with_prefix(path: str, decorated_on: str) -> str:
    """The router's prefix, which its own decorators leave off.

    Only `@router` routes wear it. The shell and the panels hang off `@app`
    and already carry their whole path — which is why this reads which object
    was decorated rather than guessing from the path.
    """
    if decorated_on != "router" or path.startswith(PREFIX):
        return path
    return PREFIX + path


def routes_the_proto_declares() -> dict[tuple[str, str], str]:
    declared: dict[tuple[str, str], str] = {}
    for proto in sorted(PROTO_DIR.glob("*.proto")):
        text = proto.read_text()
        for option in OPTION_BLOCK.finditer(text):
            body = option.group("body")
            method, path = field(body, "method"), field(body, "path")
            if not method or not path:
                print(f"{proto.name}: a route option with no method or path")
                continue
            names = RPC_NAME.findall(text[: option.start()])
            declared[(method.upper(), normalise(path))] = names[-1] if names else "?"
    return declared


def field(body: str, name: str) -> str:
    match = re.search(rf'{name}\s*:\s*"([^"]*)"', body)
    return match.group(1) if match else ""


def normalise(path: str) -> str:
    """A path parameter is a path parameter, whatever either side calls it.

    FastAPI writes `{name}` and `{relative_path:path}`; the proto writes
    `{name}`. Comparing the spellings would fail on a rename that changed
    nothing.
    """
    return re.sub(r"\{[^}]*\}", "{}", path)


def main() -> int:
    served = {route for route in routes_the_router_serves() if route not in NOT_API}
    declared = routes_the_proto_declares()

    undeclared = sorted(served - set(declared))
    unserved = sorted(set(declared) - served)

    for method, path in undeclared:
        print(f"served but not in the proto:   {method:6} {path}")
    for method, path in unserved:
        print(f"in the proto but not served:   {method:6} {path}  ({declared[(method, path)]})")

    if undeclared or unserved:
        print()
        print("every route this daemon serves is part of its public interface,")
        print("and its public interface is proto/triald/v1/. Add the rpc, or add")
        print("the route to NOT_API in this file and say why.")
        return 1

    print(f"the router and the proto agree on {len(served)} routes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
