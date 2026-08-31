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
| `/etc/braemons/triald.toml` | rig config — endpoints, results dir, `policy_path` |
| `/var/lib/triald/` | state and recorded sessions |
| `/var/log/triald/` | logs, rotated weekly |

`triald` runs as its own unprivileged user, created via the sysusers entry.

## Do not add PsychoPy to the package

It drags pyglet, wx and a GUI stack onto a headless rig box. Labs that want
`QuestHandler` or `PsiHandler` should build a virtualenv and point `policy_path`
at it — see `dev/PLAN.md`.
