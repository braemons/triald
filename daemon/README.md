# triald

The trial-control daemon of a braemons rig: it decides what a trial is, asks
somebody to run it, and records what came back.

This directory is the **Python project** — the daemon and its tests. The
repository around it holds the rest: `../client/` for the console panels and the
Python client, `../proto/` for the interface those speak, `../packaging/` for
the rig package, and `../examples/` for policies you can copy.

Start at [the repository's README](https://github.com/braemons/triald), which
explains what this daemon is for. The API is in `../docs/reference/api.md` and
is served by a running daemon at `/api/proto`.

    uv sync --directory daemon --group dev
    make check

Licensed AGPL-3.0-or-later; the text is beside this file and at the repository
root, which are the same licence and not two.
