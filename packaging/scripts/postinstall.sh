#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# After the files land: the user, the state directory, the unit.
#
# Enabled but not started on a first install. Not for statemachined's reason --
# nothing here takes a rig, because triald holds no hardware link -- but because
# the daemon that comes up would be serving the built-in demo experiment on
# whatever address the conffile says, and the conffile has not been looked at
# yet. An upgrade is different: something that was running should still be
# running afterwards.
set -e

# systemd-sysusers rather than adduser/useradd, which differ per distro.
if [ -x /usr/bin/systemd-sysusers ] || [ -x /bin/systemd-sysusers ]; then
  systemd-sysusers /usr/lib/sysusers.d/triald.conf >/dev/null 2>&1 || true
fi

# The unit's StateDirectory= creates /var/lib/braemons/triald on start, but the
# conffile names two directories *inside* it and the daemon does not create what
# it was pointed at. Made here so a fresh install starts rather than refusing.
for directory in /var/lib/braemons/triald/sessions /var/lib/braemons/triald/policies; do
  mkdir -p "$directory" 2>/dev/null || true
  chown triald:triald "$directory" 2>/dev/null || true
  chmod 0750 "$directory" 2>/dev/null || true
done

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl enable triald.service >/dev/null 2>&1 || true
fi

# dpkg passes "configure" with the old version as $2 on an upgrade and nothing
# on a first install; rpm passes 1 and 2. Both shapes, one test.
upgrade=no
case "${1:-}" in
  configure) [ -n "${2:-}" ] && upgrade=yes ;;
  2|*[0-9]*) [ "${1:-}" != "1" ] && upgrade=yes ;;
esac

if [ "$upgrade" = yes ]; then
  systemctl try-restart triald.service >/dev/null 2>&1 || true
else
  cat <<'NOTE'

triald is installed and enabled, and is not running yet.

  1. Say what this rig is:  /etc/braemons/triald-rig-config.toml
  2. Start it:              sudo systemctl start triald
  3. Open it:               http://127.0.0.1:8420/

It listens on loopback until you say otherwise, and that is deliberate: a
policy is Python running inside the daemon, so this API is remote code
execution by design. Exposing it should be something you typed.

NOTE
fi
