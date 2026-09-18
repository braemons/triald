// SPDX-License-Identifier: AGPL-3.0-or-later
//
// What every panel has in common: a shadow root, a `base` attribute, a way to
// poll without leaking a timer, and one honest place for a refusal to land.
//
// Copied in shape from statemachined's `base_panel_element.js` -- the two
// daemons are unrelated code, and the `/elements/` contract is what a console
// depends on, not a shared library. A change here does not ship to
// statemachined and a change there does not ship here; that is deliberate.

import { DaemonApiClient, DaemonRefusedTheRequest } from "./daemon_api_client.js";
import { adoptSharedStyles } from "./shared_panel_stylesheet.js";

/// The controls a panel may keep in its heading beside the title. A click on
/// one of them is that control's click, not a request to fold the panel.
const HEADING_CONTROL_TAGS = new Set(["button", "select", "input", "textarea", "a", "label"]);

/// A tag name, lowercase, however this DOM spells it.
function tagNameOf(node) {
  return (node?.tagName || "").toLowerCase();
}

export class BasePanelElement extends HTMLElement {
  static observedAttributes = ["base"];

  constructor() {
    super();
    this.root = this.attachShadow({ mode: "open" });
    adoptSharedStyles(this.root);
    this.pollTimers = [];
    this.openSockets = [];
    this.failure = null;
  }

  get api() {
    return new DaemonApiClient(this.getAttribute("base") || "");
  }

  connectedCallback() {
    this.renderShell();
    this.installDisclosure();
    this.start();
  }

  disconnectedCallback() {
    // A panel removed from the DOM must stop talking to the rig. Not tidiness:
    // a console that swaps panels on every nav click would otherwise
    // accumulate pollers against triald.
    this.stop();
  }

  attributeChangedCallback(name, previous, current) {
    if (previous !== current && this.isConnected) {
      this.stop();
      this.start();
    }
  }

  /// Subclasses override these three.
  renderShell() {}
  start() {}
  stopped() {}

  /// Whether this panel arrives folded when nobody has said otherwise.
  get collapsedByDefault() {
    return false;
  }

  /// Somebody just folded or unfolded this panel.
  theDisclosureWasToggled() {}

  // -------------------------------------------------------- disclosure ---

  /// Fold this panel's body under its heading, the way it was left last time.
  installDisclosure() {
    const section = this.childrenOf(this.root).find((child) => tagNameOf(child) === "section");
    if (section === undefined) return;
    const heading = this.childrenOf(section).find((child) => tagNameOf(child) === "h2");
    if (heading === undefined) return;

    const rest = this.childrenOf(section).filter((child) => child !== heading);
    const contents = this.make("div", { class: "panel-contents" }, rest);
    section.replaceChildren(heading, contents);

    this.disclosureToggle = this.make("button", { class: "disclosure", type: "button" });
    heading.replaceChildren(this.disclosureToggle, ...this.childrenOf(heading));
    this.disclosureSection = section;
    this.disclosureContents = contents;

    heading.addEventListener("click", (event) => {
      if (this.clickLandedOnAControl(event.target, heading)) return;
      this.setCollapsed(!this.collapsed);
    });

    this.setCollapsed(this.readRememberedCollapse(), { announce: false });
  }

  get collapsed() {
    return this.disclosureCollapsed === true;
  }

  setCollapsed(collapsed, { announce = true } = {}) {
    if (this.disclosureSection === undefined) return;
    this.disclosureCollapsed = collapsed;
    this.disclosureSection.className = collapsed ? "collapsed" : "";
    this.disclosureContents.hidden = collapsed;
    this.disclosureToggle.textContent = collapsed ? "▸" : "▾";
    this.disclosureToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    this.disclosureToggle.title = collapsed ? "unfold this panel" : "fold this panel away";
    this.rememberCollapse(collapsed);
    if (announce) return this.theDisclosureWasToggled();
    return undefined;
  }

  clickLandedOnAControl(target, heading) {
    let node = target;
    while (node !== null && node !== undefined && node !== heading) {
      if (node === this.disclosureToggle) return false;
      if (HEADING_CONTROL_TAGS.has(tagNameOf(node))) return true;
      node = node.parentNode;
    }
    return false;
  }

  childrenOf(node) {
    return Array.prototype.slice.call(node.children);
  }

  /// Where this panel's folded-or-not is written down. Per tag name, and
  /// namespaced to triald so its memory never collides with a statemachined or
  /// vstimd panel remembering the same key in the same browser.
  get collapseMemoryKey() {
    return `triald.collapsed.${(this.tagName || "panel").toLowerCase()}`;
  }

  readRememberedCollapse() {
    try {
      const remembered = globalThis.localStorage.getItem(this.collapseMemoryKey);
      if (remembered !== null) return remembered === "yes";
    } catch {
      /* no storage: a private window, or the fake DOM in the tests */
    }
    return this.collapsedByDefault;
  }

  rememberCollapse(collapsed) {
    try {
      globalThis.localStorage.setItem(this.collapseMemoryKey, collapsed ? "yes" : "no");
    } catch {
      /* nothing to remember it with; it still folds for this visit */
    }
  }

  stop() {
    for (const timer of this.pollTimers) clearInterval(timer);
    this.pollTimers = [];
    for (const socket of this.openSockets) {
      try {
        socket.close();
      } catch {
        /* already closing */
      }
    }
    this.openSockets = [];
    this.stopped();
  }

  /// Call `read` now and every `seconds`, and never let two overlap.
  pollEvery(seconds, read) {
    let inFlight = false;
    const once = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        await read();
        this.clearFailure();
      } catch (error) {
        this.showFailure(error);
      } finally {
        inFlight = false;
      }
    };
    once();
    this.pollTimers.push(setInterval(once, seconds * 1000));
    return once;
  }

  /// Run one action, showing whatever it refuses with.
  async attempt(action) {
    try {
      const result = await action();
      this.clearFailure();
      return result;
    } catch (error) {
      this.showFailure(error);
      return null;
    }
  }

  trackSocket(socket) {
    this.openSockets.push(socket);
    return socket;
  }

  // ------------------------------------------------------------ failures ---

  showFailure(error) {
    this.failure = error;
    this.paintFailure();
  }

  clearFailure() {
    if (this.failure !== null) {
      this.failure = null;
      this.paintFailure();
    }
  }

  paintFailure() {
    const slot = this.root.querySelector(".failure-slot");
    if (slot === null) return;
    if (this.failure === null) {
      slot.replaceChildren();
      return;
    }
    const banner = document.createElement("div");
    banner.className = "failure";
    const error = this.failure;
    if (error instanceof DaemonRefusedTheRequest) {
      banner.textContent = `${error.code}: ${error.detail}`;
      if (error.context) {
        const context = document.createElement("span");
        context.className = "context";
        context.textContent = `  (${error.context})`;
        banner.append(context);
      }
    } else {
      banner.textContent = `${error}`;
    }
    slot.replaceChildren(banner);
  }

  // ------------------------------------------------------------- markup ---
  //
  // Built rather than templated. There is no build step and no framework here,
  // so the alternative is string concatenation into innerHTML -- which is how
  // a policy name called `<script>` becomes an execution.

  make(tag, properties = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(properties)) {
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (key === "dataset") Object.assign(node.dataset, value);
      else if (key in node) node[key] = value;
      else node.setAttribute(key, value);
    }
    node.append(...children.filter((child) => child !== null && child !== undefined));
    return node;
  }

  /// Repaint, and put the cursor back where the person left it. See
  /// statemachined's copy of this method for the fuller rationale: a poll
  /// must not touch what a person is holding, and an edit-driven repaint has
  /// to put the caret back by position because there are no ids in this UI.
  repaintPreservingFocus(repaint) {
    const active = this.root.activeElement;
    const path = active === null ? null : this.pathToDescendant(active);
    let selectionStart = null;
    let selectionEnd = null;
    try {
      selectionStart = active?.selectionStart ?? null;
      selectionEnd = active?.selectionEnd ?? null;
    } catch {
      /* a field with no text selection. Focus is still worth restoring. */
    }

    repaint();

    if (path === null) return;
    const restored = this.descendantAtPath(path);
    if (restored === null || typeof restored.focus !== "function") return;
    restored.focus({ preventScroll: true });
    if (selectionStart === null || typeof restored.setSelectionRange !== "function") return;
    try {
      restored.setSelectionRange(selectionStart, selectionEnd);
    } catch {
      /* not a field that carries a selection */
    }
  }

  pathToDescendant(node) {
    const path = [];
    let current = node;
    while (current !== null && current !== this.root) {
      const parent = current.parentNode;
      if (parent === null || parent === undefined) return null;
      path.unshift(Array.prototype.indexOf.call(parent.children, current));
      current = parent;
    }
    return current === this.root ? path : null;
  }

  descendantAtPath(path) {
    let node = this.root;
    for (const index of path) {
      const children = node.children;
      if (!children || index < 0 || index >= children.length) return null;
      node = children[index];
    }
    return node === this.root ? null : node;
  }

  /// A definition list of label/value pairs -- the shape most of this UI is.
  fieldList(pairs) {
    const list = this.make("dl", { class: "fields" });
    for (const [label, value] of pairs) {
      list.append(
        this.make("dt", { text: label }),
        value instanceof Node ? this.make("dd", {}, [value]) : this.make("dd", { text: `${value}` }),
      );
    }
    return list;
  }
}

/// Registering twice is not an error worth throwing over: a console may load
/// this module and one of its panels' modules, and the second registration
/// would take down the page it was meant to draw.
export function defineElementOnce(tagName, elementClass) {
  if (!customElements.get(tagName)) customElements.define(tagName, elementClass);
}

export { DaemonRefusedTheRequest };
