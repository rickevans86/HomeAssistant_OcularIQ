/*
 * Ocular charger card for Home Assistant.
 * Served by the Ocular integration; finds the charger's entities on its own.
 *
 *   type: custom:ocular-charger-card
 *   device_id: <optional, defaults to the first Ocular charger>
 *   name: <optional>
 *   show_controls: true
 *   show_history: true
 */

const CARD_VERSION = "0.2.0";

const STATUS = {
  available: { label: "Ready", tone: "idle" },
  preparing: { label: "Plugged in", tone: "wait" },
  charging: { label: "Charging", tone: "go" },
  suspendedev: { label: "Paused by car", tone: "wait" },
  suspendedevse: { label: "Paused by charger", tone: "wait" },
  suspended: { label: "Paused", tone: "wait" },
  finishing: { label: "Finishing", tone: "wait" },
  reserved: { label: "Reserved", tone: "wait" },
  faulted: { label: "Fault", tone: "bad" },
  unavailable: { label: "Offline", tone: "bad" },
  offline: { label: "Offline", tone: "bad" },
};

const SESSION_MODES = [
  ["Fast", "Fast"],
  ["Eco", "Eco"],
  ["EcoPlus", "Eco+"],
];
const SOLAR_MODES = [
  ["Fast", "Grid"],
  ["Solar Assist", "Solar assist"],
  ["Solar", "Solar only"],
];

const KEYS = [
  "status", "charging_power", "charging_current", "active_current_limit",
  "session_energy", "session_time", "session_cost", "plugged_in", "online",
  "charge", "session_current_limit", "default_current_limit",
  "session_mode_select", "solar_mode_select", "last_session_energy",
  "last_session_end", "energy_last_30_days",
];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

class OcularChargerCard extends HTMLElement {
  static getStubConfig() {
    return {};
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "device_id", selector: { device: { integration: "ocular" } } },
        { name: "name", selector: { text: {} } },
        { name: "show_controls", default: true, selector: { boolean: {} } },
        { name: "show_history", default: true, selector: { boolean: {} } },
      ],
      computeLabel: (s) =>
        ({ device_id: "Charger", name: "Name", show_controls: "Show current and mode controls", show_history: "Show charging history" }[s.name]),
    };
  }

  setConfig(config) {
    this._config = { show_controls: true, show_history: true, ...config };
    this._sig = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._dragging) return;
    const ents = this._entities();
    const sig = JSON.stringify(Object.values(ents).map((id) => {
      const s = hass.states[id];
      return s ? [s.state, s.attributes.max, s.attributes.min] : null;
    })) + (this._busy || "");
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  // ------------------------------------------------------------ discovery
  _deviceId() {
    const h = this._hass;
    if (this._config.device_id) return this._config.device_id;
    if (this._config.entity) return h.entities?.[this._config.entity]?.device_id;
    const first = Object.values(h.entities || {}).find((e) => e.platform === "ocular" && e.translation_key === "status");
    return first?.device_id;
  }

  _entities() {
    const h = this._hass;
    const dev = this._deviceId();
    const out = {};
    if (!dev) return out;
    for (const e of Object.values(h.entities || {})) {
      if (e.device_id !== dev || e.platform !== "ocular" || !e.translation_key) continue;
      // first connector wins (connector 2+ entities have a _2 suffix in unique_id, registered later)
      if (KEYS.includes(e.translation_key) && !out[e.translation_key]) out[e.translation_key] = e.entity_id;
    }
    return out;
  }

  // -------------------------------------------------------------- helpers
  _st(key) {
    const id = this._ents[key];
    return id ? this._hass.states[id] : undefined;
  }

  _num(key) {
    const s = this._st(key);
    const n = s ? Number(s.state) : NaN;
    return Number.isFinite(n) ? n : null;
  }

  _fmt(n, digits) {
    if (n === null || n === undefined) return "–";
    return n.toLocaleString(this._hass.locale?.language || undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  _duration(mins) {
    if (mins === null) return "–";
    const h = Math.floor(mins / 60);
    const m = Math.floor(mins % 60);
    return h ? `${h} h ${m} min` : `${m} min`;
  }

  _money(n) {
    if (n === null) return "–";
    const cur = this._hass.config?.currency || "AUD";
    try {
      return n.toLocaleString(this._hass.locale?.language || undefined, { style: "currency", currency: cur });
    } catch (e) {
      return this._fmt(n, 2);
    }
  }

  _moreInfo(key) {
    const entityId = this._ents[key];
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  async _call(domain, service, data, busyKey) {
    this._busy = busyKey;
    this._sig = null;
    this._render();
    try {
      await this._hass.callService(domain, service, data);
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._busy = null;
      this._sig = null;
      this._render();
      clearTimeout(this._errTimer);
      this._errTimer = setTimeout(() => { this._error = null; this._sig = null; this._render(); }, 6000);
    }
  }

  // --------------------------------------------------------------- render
  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._ents = this._entities();

    if (!this._ents.status) {
      this.shadowRoot.innerHTML = `<ha-card><div class="empty">No Ocular charger found. Add the Ocular integration, or pick a charger in this card's settings.</div></ha-card>${STYLE}`;
      return;
    }

    const statusRaw = this._st("status")?.state || "unknown";
    const key = statusRaw.toLowerCase().replace(/[^a-z]/g, "");
    const online = this._st("online")?.state !== "off" && statusRaw !== "unavailable";
    const st = online ? STATUS[key] || { label: statusRaw, tone: "idle" } : STATUS.offline;
    const plugged = this._st("plugged_in")?.state === "on" || ["preparing", "charging", "suspendedev", "suspendedevse", "suspended", "finishing"].includes(key);
    const charging = key === "charging";
    const switchOn = this._st("charge")?.state === "on";

    const name = this._config.name || this._hass.devices?.[this._deviceId()]?.name_by_user || this._hass.devices?.[this._deviceId()]?.name || "EV charger";
    const power = this._num("charging_power");
    const amps = this._num("charging_current");
    const limit = this._num("active_current_limit");
    const energy = this._num("session_energy");
    const mins = this._num("session_time");
    const cost = this._num("session_cost");

    // primary action
    let action;
    if (switchOn) action = { label: "Stop charging", svc: "turn_off", enabled: true, kind: "stop" };
    else if (plugged) action = { label: "Start charging", svc: "turn_on", enabled: online, kind: "start" };
    else action = { label: online ? "Plug in your car to charge" : "Charger is offline", enabled: false, kind: "idle" };
    if (this._busy === "charge") action = { ...action, label: action.svc === "turn_off" ? "Stopping…" : "Starting…", enabled: false };

    // current limit: session limit while charging, else default
    const limitKey = this._hass.states[this._ents.session_current_limit]?.state !== "unavailable" && this._ents.session_current_limit
      ? "session_current_limit" : "default_current_limit";
    const limitState = this._st(limitKey);
    const limitVal = limitState ? Number(limitState.state) : null;

    const sessionMode = this._st("session_mode_select");
    const solarMode = this._st("solar_mode_select");

    const showControls = this._config.show_controls !== false;
    const showHistory = this._config.show_history !== false;
    const live = switchOn || charging || energy > 0;

    const lastE = this._num("last_session_energy");
    const lastEnd = this._st("last_session_end")?.state;
    const month = this._num("energy_last_30_days");
    let lastWhen = "";
    if (lastEnd && lastEnd !== "unknown" && lastEnd !== "unavailable") {
      const d = new Date(lastEnd);
      lastWhen = d.toLocaleDateString(this._hass.locale?.language || undefined, { weekday: "short", day: "numeric", month: "short" });
    }

    this.shadowRoot.innerHTML = `
      <ha-card class="tone-${st.tone} ${plugged ? "plugged" : ""} ${charging ? "flowing" : ""}">
        <header>
          <h2>${esc(name)}</h2>
          <button class="status" data-more="status" aria-label="Status: ${esc(st.label)}"><span class="dot"></span>${esc(st.label)}</button>
        </header>

        ${this._illustration(plugged, charging)}

        <section class="figures">
          <button class="hero" data-more="charging_power">
            <span class="big">${this._fmt(charging ? power : 0, 1)}</span><span class="unit">kW</span>
          </button>
          <button class="amps" data-more="charging_current">
            ${this._fmt(charging ? amps : 0, 0)} A <span class="of">of ${this._fmt(limit, 0)} A</span>
          </button>
        </section>

        <section class="session ${live ? "" : "quiet"}">
          <button data-more="session_energy"><span class="v">${this._fmt(energy, 2)} kWh</span><span class="l">This session</span></button>
          <button data-more="session_time"><span class="v">${this._duration(mins)}</span><span class="l">Time charging</span></button>
          ${this._ents.session_cost ? `<button data-more="session_cost"><span class="v">${this._money(cost)}</span><span class="l">Cost so far</span></button>` : ""}
        </section>

        <button class="action ${action.kind}" ${action.enabled ? "" : "disabled"} data-action="${action.svc || ""}">${esc(action.label)}</button>
        ${this._error ? `<p class="error" role="alert">Couldn't reach the charger: ${esc(this._error)}</p>` : ""}

        ${showControls ? `
        <section class="controls">
          ${limitState ? `
          <label class="row limit">
            <span class="l">${limitKey === "session_current_limit" ? "Current for this session" : "Maximum current"}</span>
            <span class="v" id="limitv">${this._fmt(limitVal, 0)} A</span>
            <input type="range" min="${limitState.attributes.min ?? 6}" max="${limitState.attributes.max ?? 32}" step="1"
              value="${Number.isFinite(limitVal) ? limitVal : 6}" data-limit="${limitKey}" ${limitState.state === "unavailable" ? "disabled" : ""}>
          </label>` : ""}
          ${sessionMode ? this._seg("Charge mode", "session_mode_select", SESSION_MODES, sessionMode, "Available while charging") : ""}
          ${solarMode ? this._seg("Power source", "solar_mode_select", SOLAR_MODES, solarMode, "", "solar") : ""}
        </section>` : ""}

        ${showHistory && (lastE !== null || month !== null) ? `
        <footer>
          ${lastE !== null ? `<button data-more="last_session_energy">Last charge ${this._fmt(lastE, lastE < 1 ? 2 : 1)} kWh${lastWhen ? ` on ${esc(lastWhen)}` : ""}</button>` : ""}
          ${month !== null ? `<button data-more="energy_last_30_days">${this._fmt(month, 0)} kWh in 30 days</button>` : ""}
        </footer>` : ""}
      </ha-card>
      ${STYLE}`;

    this._wire();
  }

  _seg(label, key, options, stateObj, hintWhenOff, flavour = "") {
    const off = stateObj.state === "unavailable";
    const busy = this._busy === key;
    return `
      <div class="row seg ${flavour}">
        <span class="l">${label}${off && hintWhenOff ? ` <span class="hint">${hintWhenOff}</span>` : ""}</span>
        <div class="chips" role="radiogroup" aria-label="${label}">
          ${options.map(([value, text]) => `
            <button role="radio" aria-checked="${stateObj.state === value}" class="${stateObj.state === value ? "on" : ""} ${flavour === "solar" && value !== "Fast" ? "sun" : ""}"
              data-select="${key}" data-option="${value}" ${off || busy ? "disabled" : ""}>${text}</button>`).join("")}
        </div>
      </div>`;
  }

  _illustration(plugged, charging) {
    // Wall unit on the left, cable to a plug on the right. The cable path changes with plug state.
    const cable = plugged
      ? "M58 62 C 110 92, 170 30, 236 52"
      : "M58 62 C 80 112, 112 112, 122 88";
    const plugX = plugged ? 236 : 122;
    const plugY = plugged ? 52 : 88;
    const plugRot = plugged ? -8 : -62;
    return `
      <svg class="scene" viewBox="0 0 300 110" role="img" aria-label="${plugged ? "Car connected" : "Cable not connected"}">
        <rect class="wall" x="18" y="14" width="40" height="72" rx="12"/>
        <rect class="screen" x="28" y="26" width="20" height="5" rx="2.5"/>
        <path class="cable" d="${cable}"/>
        ${charging ? `<path class="pulse" d="${cable}"/>` : ""}
        <g transform="translate(${plugX} ${plugY}) rotate(${plugRot})">
          <rect class="plug" x="-2" y="-9" width="22" height="18" rx="6"/>
        </g>
        ${plugged ? `<path class="car" d="M256 74 q4-24 22-26 h10 v40 h-30 z"/>` : ""}
      </svg>`;
  }

  _wire() {
    const root = this.shadowRoot;
    root.querySelectorAll("[data-more]").forEach((el) =>
      el.addEventListener("click", () => this._moreInfo(el.dataset.more)));

    const act = root.querySelector(".action[data-action]");
    if (act && act.dataset.action) {
      act.addEventListener("click", () =>
        this._call("switch", act.dataset.action, { entity_id: this._ents.charge }, "charge"));
    }

    root.querySelectorAll("[data-select]").forEach((el) =>
      el.addEventListener("click", () => {
        if (el.classList.contains("on")) return;
        this._call("select", "select_option", { entity_id: this._ents[el.dataset.select], option: el.dataset.option }, el.dataset.select);
      }));

    const range = root.querySelector("input[data-limit]");
    if (range) {
      const out = root.getElementById("limitv");
      range.addEventListener("pointerdown", () => (this._dragging = true));
      range.addEventListener("input", () => (out.textContent = `${range.value} A`));
      range.addEventListener("change", () => {
        this._dragging = false;
        this._call("number", "set_value", { entity_id: this._ents[range.dataset.limit], value: Number(range.value) }, "limit");
      });
      range.addEventListener("blur", () => (this._dragging = false));
    }
  }
}

const STYLE = `<style>
  :host {
    --oc-go: #13a37f;
    --oc-wait: #d99a1e;
    --oc-bad: #d3463a;
    --oc-sun: #e8b10a;
    --oc-idle: var(--secondary-text-color, #727272);
    --oc-line: var(--divider-color, rgba(127,127,127,.25));
    --oc-text: var(--primary-text-color, #1c1c1c);
    --oc-sub: var(--secondary-text-color, #6b6b6b);
  }
  ha-card { padding: 18px 18px 14px; overflow: hidden; --tone: var(--oc-idle); }
  ha-card.tone-go { --tone: var(--oc-go); }
  ha-card.tone-wait { --tone: var(--oc-wait); }
  ha-card.tone-bad { --tone: var(--oc-bad); }
  button { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; text-align: left; }
  button:focus-visible, input:focus-visible { outline: 2px solid var(--tone); outline-offset: 3px; border-radius: 6px; }
  .empty { padding: 8px 0; color: var(--oc-sub); line-height: 1.5; }

  header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  h2 { margin: 0; font-size: 1.15rem; font-weight: 600; letter-spacing: -0.01em; color: var(--oc-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .status { display: inline-flex; align-items: center; gap: 7px; font-size: .9rem; font-weight: 500; color: var(--tone); white-space: nowrap; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--tone); }
  .tone-go .dot { box-shadow: 0 0 0 0 var(--oc-go); animation: beat 2s ease-out infinite; }

  .scene { display: block; width: 100%; height: auto; max-height: 120px; margin: 6px 0 2px; }
  .wall { fill: none; stroke: var(--oc-text); stroke-width: 2.5; opacity: .85; }
  .screen { fill: var(--tone); }
  .cable { fill: none; stroke: var(--oc-line); stroke-width: 5; stroke-linecap: round; }
  .plugged .cable { stroke: color-mix(in srgb, var(--tone) 35%, var(--oc-line)); }
  .pulse { fill: none; stroke: var(--oc-go); stroke-width: 5; stroke-linecap: round; stroke-dasharray: 6 26; animation: flow 1.1s linear infinite; }
  .plug { fill: var(--card-background-color, #fff); stroke: var(--oc-text); stroke-width: 2.5; opacity: .85; }
  .car { fill: none; stroke: var(--oc-sub); stroke-width: 2.5; stroke-linejoin: round; opacity: .7; }

  .figures { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .hero { display: inline-flex; align-items: baseline; gap: 6px; color: var(--oc-text); }
  .big { font-size: 3rem; line-height: 1; font-weight: 300; letter-spacing: -0.03em; font-variant-numeric: tabular-nums; }
  .flowing .big { color: var(--oc-go); font-weight: 400; }
  .hero .unit { font-size: 1.05rem; color: var(--oc-sub); }
  .amps { font-size: 1rem; font-variant-numeric: tabular-nums; color: var(--oc-text); }
  .of { color: var(--oc-sub); }

  .session { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 4px 16px; margin: 16px 0 14px; padding: 12px 0; border-top: 1px solid var(--oc-line); border-bottom: 1px solid var(--oc-line); }
  .session.quiet { opacity: .6; }
  .session button { display: flex; flex-direction: column; gap: 2px; }
  .v { font-size: 1.02rem; font-weight: 500; color: var(--oc-text); font-variant-numeric: tabular-nums; }
  .l { font-size: .82rem; color: var(--oc-sub); }

  .action { display: block; width: 100%; text-align: center; padding: 13px 16px; border-radius: 14px; font-weight: 600; font-size: 1rem; transition: filter .15s, transform .1s; }
  .action.start { background: var(--oc-go); color: #fff; }
  .action.stop { background: transparent; color: var(--oc-bad); box-shadow: inset 0 0 0 2px var(--oc-bad); }
  .action.idle, .action:disabled { background: color-mix(in srgb, var(--oc-idle) 12%, transparent); color: var(--oc-sub); cursor: default; box-shadow: none; }
  .action:not(:disabled):active { transform: scale(.985); }
  .action:not(:disabled):hover { filter: brightness(1.06); }
  .error { margin: 8px 0 0; color: var(--oc-bad); font-size: .85rem; }

  .controls { margin-top: 16px; display: grid; gap: 14px; }
  .row { display: grid; gap: 8px; }
  .limit { grid-template-columns: 1fr auto; align-items: baseline; }
  .limit input { grid-column: 1 / -1; width: 100%; accent-color: var(--tone); margin: 0; }
  .hint { color: var(--oc-sub); font-style: italic; }
  .chips { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; border-radius: 10px; box-shadow: inset 0 0 0 1px var(--oc-line); padding: 3px; gap: 3px; }
  .chips button { text-align: center; padding: 7px 6px; border-radius: 8px; font-size: .88rem; color: var(--oc-sub); }
  .chips button.on { background: var(--oc-go); color: #fff; font-weight: 600; }
  .chips button.on.sun { background: var(--oc-sun); color: #2a2100; }
  .chips button:disabled { cursor: default; opacity: .55; }
  .chips button.on:disabled { opacity: .7; }

  footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 16px; margin-top: 16px; font-size: .84rem; color: var(--oc-sub); }

  @keyframes flow { to { stroke-dashoffset: -32; } }
  @keyframes beat { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--oc-go) 60%, transparent); } 100% { box-shadow: 0 0 0 8px transparent; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none; stroke-dasharray: none; opacity: .8; } .tone-go .dot { animation: none; } }
</style>`;

customElements.define("ocular-charger-card", OcularChargerCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ocular-charger-card",
  name: "Ocular charger",
  description: "Status, start/stop, current and charge modes for an Ocular EV charger.",
  preview: true,
});
console.info(`%c OCULAR-CHARGER-CARD %c ${CARD_VERSION} `, "background:#13a37f;color:#fff", "");
