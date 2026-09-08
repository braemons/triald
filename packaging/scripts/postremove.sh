#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# What is left behind, and what is not.
#
# The state directory stays. /var/lib/braemons/triald holds recorded sessions
# and the policies somebody wrote -- an experiment's data and an experiment's
# code, neither of which a package removal is permission to delete. `dpkg
# --purge` does not delete it either; that is a decision for a person with
# `rm`, who at least knows what is in there.
set -e

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload >/dev/null 2>&1 || true
fi
