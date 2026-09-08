# Packaging

```sh
make -C packaging deb           # this machine, fast
make -C packaging wheel         # the wheel and the sdist
make -C packaging packages      # amd64 and arm64, deb and rpm, in the pinned image
make -C packaging check         # stage the tree and run it, packaging nothing
make -C packaging repro         # build twice and prove the bytes match
```

`.github/workflows/release.yml` runs the last-but-one on a `v*` tag and attaches
everything to a GitHub Release.

## Two artifacts, two readers

The **packages** are for a rig: a vendored interpreter, a unit file, a user, a
conffile. The **wheel** is for everything that has to *import* triald rather
than run it — the end-to-end tests across the three daemons, statemachined's
`e2e` dependency group, an analysis script reading the outcome taxonomy. Neither
substitutes for the other, and until the wheel existed the only way to have
triald as a library was a git URL.

## What `check` catches that the test suite cannot

It runs the staged tree: *the* interpreter that is about to ship, with *the*
dependencies that are about to ship. Everything else in this repository runs
against a uv-built environment, so a `uvicorn[standard]` extra that resolved
differently, a web asset missing from the wheel, or a launcher whose shebang
names the build machine are all invisible until a Pi finds them.

It also parses the unit's own `ExecStart` with the conffile that ships beside
it, which is not a hypothetical: the unit shipped for months passing `--config
/etc/braemons/triald-rig-config.toml` — a rig config handed to the flag that
takes a *session* config JSON. That command line could never have started the
daemon, and nothing noticed, because nothing was packaged.

## The shape

- **Vendored interpreter.** `uv` plus python-build-standalone build a
  self-contained tree at `/opt/braemons/triald`, so the artifact does not depend
  on whatever Python the distribution ships and behaves like a compiled binary.
- **Named `braemons-triald`,** the way `braemons-vstimd` and
  `braemons-statemachined` are. The prefix is the archive's, not the daemon's:
  it makes `apt search braemons` the answer to "what is on this rig", and keeps
  a name this generic from colliding with a distribution package. Nothing
  *inside* the package carries it — the binary, the unit, the user and the
  logrotate entry stay plain `triald`, because that is what an operator types.
- **One `nfpm` config → both formats.** `.deb` for amd64/arm64 and `.rpm` for
  x86_64/aarch64. Simpler than vstimd's split, which needs `cargo-deb` for Debian
  and a hand-written `.spec` for RPM.
- **Published to the [braemons apt archive](https://github.com/braemons/packages)**,
  so rigs upgrade in place.
- **Not on PyPI.** The wheel is a release asset. Publishing to PyPI is a
  separate decision with a token behind it, and nothing needs it yet — the
  consumers all pin a URL or a tag.

## Layout

| Path | Purpose |
|---|---|
| `/opt/braemons/triald/` | the vendored interpreter and the package |
| `/etc/braemons/triald-rig-config.toml` | rig config — bind address, `results_directory`, `policy_directory`, and optionally a session config and policy to load at startup |
| `/var/lib/braemons/triald/` | state and recorded sessions |
| `/var/log/triald/` | logs, rotated weekly |
| `/usr/share/doc/braemons-triald/` | the docs that ship with the package, named after the package |

`triald` runs as its own unprivileged user, created via the sysusers entry.

The first two paths are the braemons convention rather than triald's own:
every daemon's conffile is `/etc/braemons/<daemon>-rig-config.toml` and every
daemon's state is `/var/lib/braemons/<daemon>/`, so a rig has one directory of
settings and one tree of state to back up — and vstimd's Samba shares export
both whole. Logs stay at `/var/log/<daemon>/`, which is systemd's
`LogsDirectory=` and not ours to move.

## What goes in the package, and what does not

**In:** numpy and scipy. Roughly 80 MB together, against a vendored CPython
already around 50–80 MB. Not shipping them is discovered at 2 a.m. when a policy
will not load on the rig; shipping them costs disk. If the Pi image gets tight,
split scipy into a `braemons-triald-scipy` package that the main one `Recommends:`.

**Out:** PsychoPy. It drags pyglet, wx and a GUI stack onto a headless rig box.
Labs that want `QuestHandler` or `PsiHandler` install it into the daemon's own
vendored interpreter with `trialctl env install psychopy`, which is
ABI-compatible by construction because there is only one interpreter. See
`dev/PLAN.md`, "The runtime environment".

`trialctl` does not exist yet, and neither does the rig config's
`extra_packages` — the rig config refuses keys it does not know rather than
ignoring them, so that key is not accepted today. Recording a setting nothing
acts on would be worse than not having it.

numpy and scipy are installed by `packaging/Makefile`'s `RIG_EXTRAS` rather than
declared in `pyproject.toml`. `dependencies = []` in the core is load-bearing:
it is what lets the domain logic, the policy API and the simulator import with
nothing installed. These belong to the *package*, not to the library.
