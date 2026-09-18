// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The `/elements/` contract, on triald's side of it.
//
//     <script type="module" src="http://rig.local:8420/elements/triald.js"></script>
//     <triald-session  base="http://rig.local:8420"></triald-session>
//     <triald-sets     base="http://rig.local:8420"></triald-sets>
//     <triald-counters base="http://rig.local:8420"></triald-counters>
//     <triald-trials   base="http://rig.local:8420"></triald-trials>
//     <triald-config   base="http://rig.local:8420"></triald-config>
//     <triald-debug    base="http://rig.local:8420"></triald-debug>
//
// **This URL and these tag names are what the console repo depends on**
// (`console.js`'s `DAEMONS["_triald._tcp"]`). statemachined's dev/DAEMON.md §5
// specifies the contract and triald follows it for the reason given there: a
// console holds no domain logic, so every panel is an element served by the
// daemon that owns what it shows, at that daemon's own version.
//
// The same six elements are what triald's own page (`/`) is built from --
// see `application_shell.js` -- so a panel looks the same and behaves the
// same whether it is embedded in a console or opened directly against the
// rig. There is one implementation, not two that can drift.
//
// A policy is real Python, not data (triald's CLAUDE.md: "two levels, no
// DSL"), so it has no element here -- `triald policy check` is the tool for
// it, deliberately outside the browser.
//
// Importing this module registers all six. Importing one panel's module
// directly registers only that one, for a console that wants less.

export { DaemonApiClient, DaemonRefusedTheRequest } from "./daemon_api_client.js";
export { BasePanelElement } from "./base_panel_element.js";
export { SessionPanelElement } from "./session_panel_element.js";
export { SetsPanelElement } from "./sets_panel_element.js";
export { CountersPanelElement } from "./counters_panel_element.js";
export { TrialsPanelElement } from "./trials_panel_element.js";
export { ConfigPanelElement } from "./config_panel_element.js";
export { DebugPanelElement } from "./debug_panel_element.js";

/// The tag names, so a console can iterate them rather than hard-code a list
/// that goes stale when a panel is added.
export const TRIALD_ELEMENT_NAMES = [
  "triald-session",
  "triald-sets",
  "triald-counters",
  "triald-trials",
  "triald-config",
  "triald-debug",
];
