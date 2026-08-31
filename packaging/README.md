# Packaging — skeleton

**Nothing here is wired up yet.** The layout and the version script are lifted
from vstimd so the two daemons package the same way; the `nfpm` config, the
Docker builders and the Makefile targets still have to be written. See step 6 of
the roadmap in `dev/PLAN.md`.

The `triald.service` unit refers to `triald serve`, which does not exist yet
either — the RPC and web surfaces are step 3 and 4.

## The intended shape

- **Vendored interpreter.** `uv` plus python-build-standalone build a
  self-contained tree at `/opt/braemons/triald`, so the artifact does not depend
  on whatever Python the distribution ships and behaves like a compiled binary.
- **One `nfpm` config → both formats.** `.deb` for amd64/arm64 and `.rpm` for
  x86_64/aarch64. Simpler than vstimd's split, which needs `cargo-deb` for Debian
  and a hand-written `.spec` for RPM.
- **Published to the [braemons apt archive](https://github.com/braemons/packages)**,
  so rigs upgrade in place.

## Layout

| Path | Purpose |
|---|---|
| `/opt/braemons/triald/` | the vendored interpreter and the package |
| `/etc/braemons/triald.toml` | rig config — endpoints, results dir, `policy_dir`, `extra_packages` |
| `/var/lib/triald/` | state and recorded sessions |
| `/var/log/triald/` | logs, rotated weekly |

`triald` runs as its own unprivileged user, created via the sysusers entry.

## What goes in the package, and what does not

**In:** numpy and scipy. Roughly 80 MB together, against a vendored CPython
already around 50–80 MB. Not shipping them is discovered at 2 a.m. when a policy
will not load on the rig; shipping them costs disk. If the Pi image gets tight,
split scipy into a `triald-scipy` package that the main one `Recommends:`.

**Out:** PsychoPy. It drags pyglet, wx and a GUI stack onto a headless rig box.
Labs that want `QuestHandler` or `PsiHandler` install it into the daemon's own
vendored interpreter with `trialctl env install psychopy`, which is
ABI-compatible by construction because there is only one interpreter. See
`dev/PLAN.md`, "The runtime environment".
