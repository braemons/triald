// SPDX-License-Identifier: AGPL-3.0-or-later
//
// The rig's own page: navigation, and nothing else.
//
// Deliberately thin, and the same thinness the console repo has for the same
// reason (statemachined's dev/DAEMON.md §5, which this daemon follows too):
// every view here is one custom element with a shadow root, served from
// `/elements/triald.js`; this file only chooses which ones are on screen and
// hands them the same `base` a console would. If this shell grew domain
// logic, the console would either duplicate it or do without -- so it has
// none, and the panels are the only place anything is decided.
//
// This is also why the page a person opens at `http://rig:8420/` looks like
// the panels a console embeds: they are the same elements, not a second
// implementation of the same idea that can drift from it.

import "/elements/triald.js";

//: Empty, meaning same-origin: this page is served by the daemon it is about.
//: A console passes its own value, which is why every panel takes it as an
//: attribute rather than assuming.
const BASE_URL = "";

// A view is a question, not a panel -- the same principle statemachined's
// shell states. "Run" is the loop as a rig actually runs it: what is
// happening now, what it decided, and what it did. "Setup" is what governs
// that decision without being it. "Bench" is the one view a rig itself never
// needs -- driving the loop with a simulated subject -- and is the only
// reason this shell exists rather than every panel simply sitting on one page.
const VIEWS = [
  {
    id: "run",
    label: "Run",
    tags: ["triald-session", "triald-trials"],
    description:
      "What the trial loop is doing, and what it just did: arm or stop a session, record, " +
      "and read back the trials as they finish. On a rig, triald drives this on its own -- " +
      "these controls are the bench equivalent.",
  },
  {
    id: "setup",
    label: "Setup",
    tags: ["triald-sets", "triald-config"],
    description:
      "What governs the decision: the sets a session draws from and their switch rules, and " +
      "the declarative settings underneath -- ordering, rounds, the stop rules, and which " +
      "outcomes accept. A policy is real Python and has no editor here; see `triald policy check`.",
  },
  {
    id: "counters",
    label: "Counters",
    tags: ["triald-counters"],
    description:
      "The per-trial-type tally, the columns VStim's Trial Type Manager showed. Counted is " +
      "not accepted -- see the Accept column against All.",
  },
  {
    id: "bench",
    label: "Bench",
    tags: ["triald-debug"],
    description:
      "Drive the real trial loop with a simulated subject, for a rig with nothing else " +
      "attached yet. Nothing here is a second code path: it is the same four calls a rig " +
      "makes, with a synthetic subject standing in for vstimd and the microcontroller.",
  },
];

const navigation = document.getElementById("view-navigation");
const container = document.getElementById("view-container");
const summary = document.getElementById("rig-summary");

function showView(viewId) {
  const view = VIEWS.find((each) => each.id === viewId) || VIEWS[0];
  // Replaced rather than hidden, so panels that leave the screen stop
  // polling: `disconnectedCallback` is where a panel gives back its
  // attention, and a hidden-but-connected one would keep it.
  const panels = view.tags.map((tag) => {
    const panel = document.createElement(tag);
    panel.setAttribute("base", BASE_URL);
    return panel;
  });
  const description = document.createElement("p");
  description.className = "view-description";
  description.textContent = view.description;
  container.replaceChildren(description, ...panels);

  for (const button of navigation.children) {
    button.classList.toggle("current", button.dataset.viewId === view.id);
  }
  if (location.hash !== `#${view.id}`) history.replaceState(null, "", `#${view.id}`);
}

for (const view of VIEWS) {
  const button = document.createElement("button");
  button.textContent = view.label;
  button.title = view.description;
  button.dataset.viewId = view.id;
  button.addEventListener("click", () => showView(view.id));
  navigation.append(button);
}

window.addEventListener("hashchange", () => showView(location.hash.slice(1)));
showView(location.hash.slice(1) || "run");

// The header is the one thing on this page that is not a panel: whether this
// rig is running right now, which is what makes two browser tabs on two rigs
// tellable apart at a glance.
import("/elements/daemon_api_client.js").then(({ DaemonApiClient }) => {
  const api = new DaemonApiClient(BASE_URL);

  async function refreshSummary() {
    try {
      const state = await api.readState();
      summary.textContent = state.running
        ? `running -- set ${state.set_name}, trial ${state.current?.trial_number ?? "-"}`
        : state.armed
          ? "armed, not running"
          : "not armed";
      summary.className = state.running ? "summary good" : "summary";
    } catch (error) {
      summary.textContent = `the daemon did not answer: ${error}`;
      summary.className = "summary bad";
    }
  }

  refreshSummary();
  setInterval(refreshSummary, 2000);
});
