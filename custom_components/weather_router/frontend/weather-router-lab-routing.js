const LAB_ELEMENT = "weather-router-lab";
const ROUTING_MENU_STATE_KEY = "weather_router_lab_menu_state_v1";

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor der Router-Steuerung registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterRoutingEnhanced) {
  proto.__weatherRouterRoutingEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousEnsureProviderCatalog = proto._ensureProviderCatalog;
  const previousEventLogSnapshot = proto._wrEventLogSnapshot;

  proto._routingSettingsState = function() {
    if (!this._routingSettings) {
      this._routingSettings = {
        schema: "weather_router.routing_settings.v1",
        router_enabled: true,
        domains: [],
        providers: [],
      };
    }
    return this._routingSettings;
  };

  proto._routingInstallUI = function() {
    const root = this.shadowRoot;
    if (!root) return;

    if (!root.getElementById("weather-router-routing-style")) {
      const style = document.createElement("style");
      style.id = "weather-router-routing-style";
      style.textContent = `
        .router-master {
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:12px;
          padding:10px;
          border:1px solid color-mix(in srgb,#d4af37 45%,var(--divider-color,#555));
          border-radius:10px;
          background:color-mix(in srgb,#d4af37 5%,transparent);
        }
        .router-master strong { display:block; font-size:13px; }
        .router-master small { display:block; margin-top:2px; opacity:.62; font-size:10px; }
        .router-switch {
          display:inline-flex;
          align-items:center;
          gap:7px;
          margin:0;
          min-height:34px;
          cursor:pointer;
          user-select:none;
          touch-action:manipulation;
        }
        .router-switch input {
          width:20px;
          height:20px;
          margin:0;
          accent-color:var(--primary-color,#03a9f4);
          cursor:pointer;
        }
        .router-fold {
          margin-top:8px;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 72%,transparent);
          border-radius:9px;
          overflow:hidden;
          background:rgba(128,128,128,.022);
        }
        .router-fold > summary,
        .router-provider-group > summary {
          cursor:pointer;
          list-style:none;
          user-select:none;
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:10px;
        }
        .router-fold > summary::-webkit-details-marker,
        .router-provider-group > summary::-webkit-details-marker { display:none; }
        .router-fold > summary {
          min-height:38px;
          padding:8px 10px;
          color:#d4af37;
          font-size:11px;
          font-weight:800;
          background:rgba(128,128,128,.045);
        }
        .router-fold > summary::before,
        .router-provider-group > summary::before {
          content:"▸";
          flex:0 0 auto;
          opacity:.7;
          transition:transform .12s ease;
        }
        .router-fold[open] > summary::before,
        .router-provider-group[open] > summary::before { transform:rotate(90deg); }
        .router-fold-title {
          display:flex;
          align-items:center;
          gap:6px;
          min-width:0;
          margin-right:auto;
        }
        .router-fold-count {
          flex:0 0 auto;
          font-size:9px;
          font-weight:600;
          opacity:.62;
          color:var(--primary-text-color,#eee);
        }
        .router-fold-body { padding:8px; }
        .router-domain-grid {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(145px,1fr));
          gap:6px;
        }
        .router-domain {
          display:flex;
          align-items:center;
          gap:7px;
          min-height:38px;
          margin:0;
          padding:7px 8px;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 75%,transparent);
          border-radius:8px;
          background:rgba(128,128,128,.035);
          cursor:pointer;
          user-select:none;
          touch-action:manipulation;
          opacity:1;
        }
        .router-domain input,
        .router-provider input {
          width:18px;
          height:18px;
          min-width:18px;
          margin:0;
          accent-color:var(--primary-color,#03a9f4);
        }
        .router-provider-groups {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(250px,1fr));
          gap:8px;
          align-items:start;
        }
        .router-provider-group {
          min-width:0;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 70%,transparent);
          border-radius:9px;
          overflow:hidden;
          background:rgba(128,128,128,.025);
        }
        .router-provider-group > summary {
          min-height:36px;
          padding:7px 9px;
          color:#d4af37;
          font-size:10px;
          font-weight:800;
          background:rgba(128,128,128,.045);
        }
        .router-provider-group-title {
          display:flex;
          min-width:0;
          align-items:center;
          gap:5px;
          margin-right:auto;
        }
        .router-provider-list {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(215px,1fr));
          gap:0;
          padding:0;
        }
        .router-provider {
          display:grid;
          grid-template-columns:auto minmax(0,1fr);
          gap:7px;
          align-items:start;
          margin:0;
          padding:7px 9px;
          border-top:1px solid color-mix(in srgb,var(--divider-color,#555) 45%,transparent);
          cursor:pointer;
          user-select:none;
          touch-action:manipulation;
          opacity:1;
        }
        .router-provider:first-child { border-top:0; }
        .router-provider-name { display:block; font-size:11px; font-weight:700; }
        .router-provider-meta { display:block; margin-top:2px; font-size:9px; opacity:.58; }

        /* A checked provider whose parent domain is disabled remains configured
           as enabled, but is runtime-blocked. Make that inherited lock visually
           unmistakable without changing the checkbox state itself. */
        .router-provider.router-provider-domain-locked {
          border-left:3px solid var(--error-color,#f44336);
          background:color-mix(in srgb,var(--error-color,#f44336) 10%,transparent);
        }
        .router-provider.router-provider-domain-locked .router-provider-name {
          color:var(--error-color,#f44336);
        }
        .router-provider.router-provider-domain-locked .router-provider-meta {
          color:var(--error-color,#f44336);
          opacity:.95;
          font-weight:700;
        }
        .router-provider.router-provider-domain-locked input {
          accent-color:var(--error-color,#f44336);
        }
        .router-provider-new {
          display:inline-block;
          margin-left:5px;
          padding:1px 4px;
          border:1px solid color-mix(in srgb,#d4af37 55%,transparent);
          border-radius:4px;
          color:#d4af37;
          font-size:8px;
          vertical-align:1px;
        }
        .router-provider-private {
          display:inline-block;
          margin-left:5px;
          padding:1px 4px;
          border:1px solid color-mix(in srgb,#ff4d4d 70%,transparent);
          border-radius:4px;
          color:#ff6b6b;
          background:color-mix(in srgb,#ff4d4d 9%,transparent);
          font-size:8px;
          font-weight:800;
          vertical-align:1px;
        }
        .router-view-switch {
          display:inline-flex;
          gap:4px;
          margin:0 0 9px;
          padding:3px;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 72%,transparent);
          border-radius:9px;
          background:rgba(128,128,128,.035);
        }
        .router-view-switch button {
          min-height:30px;
          padding:5px 10px;
          border:0;
          border-radius:6px;
          background:transparent;
          color:var(--secondary-text-color,#aaa);
          font-size:10px;
          font-weight:800;
          cursor:pointer;
        }
        .router-view-switch button.active {
          background:color-mix(in srgb,var(--primary-color,#03a9f4) 18%,transparent);
          color:var(--primary-text-color,#fff);
          box-shadow:inset 0 0 0 1px color-mix(in srgb,var(--primary-color,#03a9f4) 45%,transparent);
        }
        .router-provider-overview {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(270px,1fr));
          gap:8px;
          align-items:start;
        }
        .router-provider-card {
          min-width:0;
          padding:9px;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 72%,transparent);
          border-left-width:4px;
          border-radius:9px;
          background:rgba(128,128,128,.025);
        }
        .router-provider-card.status-green {
          border-left-color:#35c46a;
          background:color-mix(in srgb,#35c46a 7%,transparent);
        }
        .router-provider-card.status-amber {
          border-left-color:#ffb020;
          background:color-mix(in srgb,#ffb020 8%,transparent);
        }
        .router-provider-card.status-red {
          border-left-color:var(--error-color,#f44336);
          background:color-mix(in srgb,var(--error-color,#f44336) 8%,transparent);
        }
        .router-provider-card-head {
          display:grid;
          grid-template-columns:auto minmax(0,1fr) auto;
          gap:7px;
          align-items:start;
        }
        .router-provider-card-head input {
          width:18px;
          height:18px;
          min-width:18px;
          margin:1px 0 0;
          accent-color:var(--primary-color,#03a9f4);
        }
        .router-provider-card-title {
          min-width:0;
          font-size:11px;
          font-weight:800;
          line-height:1.25;
        }
        .router-provider-state {
          display:inline-flex;
          align-items:center;
          gap:4px;
          font-size:9px;
          font-weight:800;
          white-space:nowrap;
        }
        .router-provider-state::before {
          content:"";
          width:7px;
          height:7px;
          border-radius:50%;
          background:currentColor;
          box-shadow:0 0 0 2px color-mix(in srgb,currentColor 15%,transparent);
        }
        .router-provider-state.green { color:#35c46a; }
        .router-provider-state.amber { color:#ffb020; }
        .router-provider-state.red { color:var(--error-color,#f44336); }
        .router-provider-card-badges {
          margin-top:5px;
          padding-left:25px;
        }
        .router-provider-topics {
          display:flex;
          flex-wrap:wrap;
          gap:5px;
          margin-top:8px;
          padding-top:7px;
          border-top:1px solid color-mix(in srgb,var(--divider-color,#555) 45%,transparent);
        }
        .router-topic-section {
          margin-top:8px;
          padding-top:7px;
          border-top:1px solid color-mix(in srgb,var(--divider-color,#555) 45%,transparent);
        }
        .router-topic-section-title {
          display:block;
          margin:0 0 5px;
          font-size:9px;
          font-weight:800;
          opacity:.72;
        }
        .router-topic-section-pills {
          display:flex;
          flex-wrap:wrap;
          gap:5px;
        }
        .router-service-pill {
          display:inline-block;
          margin-left:5px;
          padding:1px 4px;
          border:1px solid color-mix(in srgb,#62b9ff 55%,transparent);
          border-radius:4px;
          color:#62b9ff;
          background:color-mix(in srgb,#62b9ff 8%,transparent);
          font-size:8px;
          font-weight:800;
          vertical-align:1px;
        }
        .router-topic-pill {
          display:inline-flex;
          align-items:center;
          gap:4px;
          min-height:22px;
          padding:3px 7px;
          border:1px solid currentColor;
          border-radius:999px;
          font-size:9px;
          font-weight:800;
        }
        .router-topic-pill::before {
          content:"";
          width:6px;
          height:6px;
          border-radius:50%;
          background:currentColor;
        }
        .router-topic-pill.active {
          color:#35c46a;
          background:color-mix(in srgb,#35c46a 8%,transparent);
        }
        .router-topic-pill.blocked {
          color:var(--error-color,#f44336);
          background:color-mix(in srgb,var(--error-color,#f44336) 8%,transparent);
        }
        .router-provider-overview-summary {
          display:flex;
          flex-wrap:wrap;
          gap:7px 12px;
          margin:0 0 8px;
          font-size:10px;
          font-weight:800;
        }
        .router-provider-overview-summary .green { color:#35c46a; }
        .router-provider-overview-summary .amber { color:#ffb020; }
        .router-provider-overview-summary .red { color:var(--error-color,#f44336); }
        .router-disabled-note {
          margin:8px 0 0;
          font-size:10px;
          line-height:1.4;
          opacity:.65;
        }
        .router-save-state {
          min-height:18px;
          margin-top:7px;
          font-size:10px;
          opacity:.7;
        }
        .router-save-state.error { color:var(--error-color,#f44336); opacity:1; }
        @media(min-width:900px) {
          .router-domain-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }
        }
        @media(max-width:520px) {
          .router-domain-grid,
          .router-provider-groups,
          .router-provider-list { grid-template-columns:1fr; }
          .router-master { align-items:flex-start; }
        }
      `;
      root.appendChild(style);
    }

    if (root.getElementById("router-control-menu")) return;
    const referenceMenu = root.querySelector('[data-lab-menu-key="reference"]');
    if (!referenceMenu) return;

    const menu = document.createElement("details");
    menu.id = "router-control-menu";
    menu.className = "card lab-menu";
    menu.dataset.labMenuKey = "router-control";
    menu.open = true;
    menu.innerHTML = `
      <summary>0 · Router-Steuerung</summary>
      <div class="lab-menu-content">
        <div id="router-control-body" class="muted" style="font-size:12px">
          Lade Router-Einstellungen …
        </div>
      </div>
    `;
    referenceMenu.before(menu);

    let stored = {};
    try {
      stored = JSON.parse(localStorage.getItem(ROUTING_MENU_STATE_KEY) || "{}");
    } catch (_error) {
      stored = {};
    }
    if (Object.prototype.hasOwnProperty.call(stored, "router-control")) {
      menu.open = Boolean(stored["router-control"]);
    }
    menu.addEventListener("toggle", () => {
      let current = {};
      try {
        current = JSON.parse(localStorage.getItem(ROUTING_MENU_STATE_KEY) || "{}");
      } catch (_error) {
        current = {};
      }
      current["router-control"] = menu.open;
      try {
        localStorage.setItem(ROUTING_MENU_STATE_KEY, JSON.stringify(current));
      } catch (_error) {
        // Persistenz der Menüansicht ist optional.
      }
    });
  };

  proto._routingDomainLabel = function(domainId) {
    const labels = {
      weather: "Wetter",
      pollen: "Pollen",
      natural_hazards: "Naturgefahren",
      civil_protection: "Bevölkerungsschutz",
      security: "Öffentliche Sicherheit",
      aviation: "Luftfahrtwarnungen",
      space: "Sonne & Weltraum",
      biological_hazards: "Biologische Gefahren & Wildtiere",
    };
    return labels[domainId] || domainId;
  };

  proto._routingRender = function() {
    const root = this.shadowRoot;
    const host = root?.getElementById("router-control-body");
    if (!host) return;

    const settings = this._routingSettingsState();
    const domains = Array.isArray(settings.domains) ? settings.domains : [];
    const providers = Array.isArray(settings.providers) ? settings.providers : [];

    if (!domains.length && !providers.length) {
      host.className = "muted";
      host.textContent = "Router-Einstellungen werden geladen …";
      return;
    }

    const providerGroupsByKey = new Map();
    for (const provider of providers) {
      const primary = Array.isArray(provider.domains) && provider.domains.length
        ? provider.domains[0]
        : "weather";
      const groupKey = provider.display_group || primary;
      if (!providerGroupsByKey.has(groupKey)) providerGroupsByKey.set(groupKey, []);
      providerGroupsByKey.get(groupKey).push(provider);
    }

    // "Gewitter" is a visual provider group only. The providers remain in their
    // actual router domain (currently weather), so routing, Consumer API and
    // network-boundary semantics are unchanged.
    const providerGroupDescriptors = [];
    for (const domain of domains) {
      providerGroupDescriptors.push({
        id: domain.id,
        name: domain.name || this._routingDomainLabel(domain.id),
      });
      if (domain.id === "weather" && providerGroupsByKey.has("thunderstorm")) {
        providerGroupDescriptors.push({
          id: "thunderstorm",
          name: "Gewitter",
        });
      }
    }
    if (
      providerGroupsByKey.has("thunderstorm")
      && !providerGroupDescriptors.some(item => item.id === "thunderstorm")
    ) {
      providerGroupDescriptors.push({ id: "thunderstorm", name: "Gewitter" });
    }

    let storedFoldState = {};
    try {
      storedFoldState = JSON.parse(localStorage.getItem(ROUTING_MENU_STATE_KEY) || "{}");
    } catch (_error) {
      storedFoldState = {};
    }
    const foldOpen = (key, defaultValue=false) => (
      Object.prototype.hasOwnProperty.call(storedFoldState, key)
        ? Boolean(storedFoldState[key])
        : defaultValue
    );

    const providerView = storedFoldState["router-provider-view"] === "providers"
      ? "providers"
      : "services";
    const domainEnabled = new Map(
      domains.map(domain => [domain.id, Boolean(domain.enabled)])
    );
    const topicGroups = Array.isArray(settings.topic_groups) ? settings.topic_groups : [];
    const topicById = new Map();
    for (const group of topicGroups) {
      for (const topic of group.topics || []) {
        topicById.set(topic.id, {
          ...topic,
          group_id: group.id,
          group_name: group.name,
          domain: group.domain,
        });
      }
    }

    const providerDomains = provider => (provider.domains || []).map(domainId => ({
      id: domainId,
      label: this._routingDomainLabel(domainId),
      active: Boolean(settings.router_enabled) && Boolean(domainEnabled.get(domainId)),
    }));

    const providerHazardTopicGroups = provider => {
      const grouped = new Map();
      for (const topicId of provider.topics || []) {
        const meta = topicById.get(topicId);
        if (!meta) continue;
        if (!grouped.has(meta.group_id)) {
          grouped.set(meta.group_id, {
            id: meta.group_id,
            name: meta.group_name,
            domain: meta.domain,
            topics: [],
          });
        }
        grouped.get(meta.group_id).topics.push({
          id: topicId,
          label: meta.name,
          active: (
            Boolean(settings.router_enabled)
            && Boolean(domainEnabled.get(meta.domain))
            && Boolean(provider.enabled_by_user)
          ),
        });
      }
      return [...grouped.values()];
    };

    const providerVisualStatus = provider => {
      const providerDomainsState = providerDomains(provider);
      const activeDomains = providerDomainsState.filter(item => item.active).length;
      if (!settings.router_enabled || !provider.enabled_by_user || activeDomains === 0) {
        return { key:"red", label:"deaktiviert" };
      }
      if (activeDomains < providerDomainsState.length) {
        return { key:"amber", label:"teilweise aktiv" };
      }
      return { key:"green", label:"aktiv" };
    };

    const providerGroups = providerGroupDescriptors.map(group => {
      const entries = providerGroupsByKey.get(group.id) || [];
      if (!entries.length) return "";
      const enabledCount = entries.filter(provider => provider.enabled_by_user).length;
      const groupKey = `router-provider-group-${group.id}`;
      return `
        <details class="router-provider-group" data-router-fold-key="${this._escape(groupKey)}"
          ${foldOpen(groupKey, false) ? "open" : ""}>
          <summary>
            <span class="router-provider-group-title">
              <span>${this._escape(group.name)}</span>
            </span>
            <span class="router-fold-count">${enabledCount}/${entries.length} aktiv</span>
          </summary>
          <div class="router-provider-list">
            ${entries.map(provider => {
              const domainText = (provider.domains || [])
                .map(value => this._routingDomainLabel(value))
                .join(" · ");
              return `
                <label class="router-provider ${provider.enabled_by_user && provider.disabled_reason === "domain_disabled" ? "router-provider-domain-locked" : ""}">
                  <input type="checkbox"
                    data-router-provider="${this._escape(provider.id)}"
                    ${provider.enabled_by_user ? "checked" : ""}
                    ${!settings.router_enabled ? "disabled" : ""}>
                  <span>
                    <span class="router-provider-name">
                      ${this._escape(provider.name)}
                      ${provider.default_enabled === false
                        ? '<span class="router-provider-new">optional</span>'
                        : ""}
                      ${provider.is_extension
                        ? '<span class="router-provider-private">private Extension</span>'
                        : ""}
                    </span>
                    <span class="router-provider-meta">
                      ${this._escape(domainText)}
                      ${provider.enabled_by_user && !provider.eligible
                        ? provider.disabled_reason === "domain_disabled"
                          ? " · GESPERRT · Fachbereich deaktiviert"
                          : ` · derzeit gesperrt: ${this._escape(provider.disabled_reason || "Fachbereich aus")}`
                        : ""}
                    </span>
                  </span>
                </label>
              `;
            }).join("")}
          </div>
        </details>
      `;
    }).join("");

    const providerCards = [...providers]
      .sort((left, right) => String(left.name || left.id).localeCompare(String(right.name || right.id), "de"))
      .map(provider => {
        const status = providerVisualStatus(provider);
        const providerDomainsState = providerDomains(provider);
        const hazardGroups = providerHazardTopicGroups(provider);
        return `
          <div class="router-provider-card status-${status.key}">
            <div class="router-provider-card-head">
              <input type="checkbox"
                data-router-provider="${this._escape(provider.id)}"
                ${provider.enabled_by_user ? "checked" : ""}
                ${!settings.router_enabled ? "disabled" : ""}>
              <div class="router-provider-card-title">${this._escape(provider.name)}</div>
              <span class="router-provider-state ${status.key}">${status.label}</span>
            </div>
            <div class="router-provider-card-badges">
              ${provider.default_enabled === false
                ? '<span class="router-provider-new">optional</span>'
                : ""}
              ${provider.is_extension
                ? '<span class="router-provider-private">private Extension</span>'
                : ""}
              ${provider.display_group === "thunderstorm"
                ? '<span class="router-service-pill">Gewitter-Beobachtung</span>'
                : ""}
            </div>
            <div class="router-topic-section">
              <span class="router-topic-section-title">Fachbereiche</span>
              <div class="router-topic-section-pills">
                ${providerDomainsState.map(domain => `
                  <span class="router-topic-pill ${domain.active && provider.enabled_by_user ? "active" : "blocked"}"
                    title="${domain.active ? "Fachbereich aktiv" : "Fachbereich deaktiviert"}">
                    ${this._escape(domain.label)}
                  </span>
                `).join("")}
              </div>
            </div>
            ${hazardGroups.map(group => `
              <div class="router-topic-section">
                <span class="router-topic-section-title">
                  ${this._escape(this._routingDomainLabel(group.domain))} › ${this._escape(group.name)}
                </span>
                <div class="router-topic-section-pills">
                  ${group.topics.map(topic => `
                    <span class="router-topic-pill ${topic.active ? "active" : "blocked"}"
                      title="${topic.active ? "Thema verfügbar" : "Thema durch Fachbereich gesperrt"}">
                      ${this._escape(topic.label)}
                    </span>
                  `).join("")}
                </div>
              </div>
            `).join("")}
          </div>
        `;
      }).join("");

    const providerStatusCounts = providers.reduce((counts, provider) => {
      counts[providerVisualStatus(provider).key] += 1;
      return counts;
    }, { green:0, amber:0, red:0 });

    const enabledDomainCount = domains.filter(domain => domain.enabled).length;
    const enabledProviderCount = providers.filter(provider => provider.enabled_by_user).length;

    host.className = "";
    host.innerHTML = `
      <div class="router-master">
        <div>
          <strong>WeatherRouter aktiv</strong>
          <small>Aus = keine Provider-Abfragen über die Router-Schnittstellen.</small>
        </div>
        <label class="router-switch">
          <input id="router-master-enabled" type="checkbox"
            ${settings.router_enabled ? "checked" : ""}>
          <span>${settings.router_enabled ? "Ein" : "Aus"}</span>
        </label>
      </div>

      <details class="router-fold" data-router-fold-key="router-domains"
        ${foldOpen("router-domains", false) ? "open" : ""}>
        <summary>
          <span class="router-fold-title">Fachbereiche</span>
          <span class="router-fold-count">${enabledDomainCount}/${domains.length} aktiv</span>
        </summary>
        <div class="router-fold-body">
          <div class="router-domain-grid">
            ${domains.map(domain => `
              <label class="router-domain">
                <input type="checkbox"
                  data-router-domain="${this._escape(domain.id)}"
                  ${domain.enabled ? "checked" : ""}
                  ${!settings.router_enabled ? "disabled" : ""}>
                <span>${this._escape(domain.name || this._routingDomainLabel(domain.id))}</span>
              </label>
            `).join("")}
          </div>
        </div>
      </details>

      <details class="router-fold" data-router-fold-key="router-providers"
        ${foldOpen("router-providers", false) ? "open" : ""}>
        <summary>
          <span class="router-fold-title">Dienste / Provider</span>
          <span class="router-fold-count">${enabledProviderCount}/${providers.length} aktiv</span>
        </summary>
        <div class="router-fold-body">
          <div class="router-view-switch" role="group" aria-label="Dienste- oder Provideransicht">
            <button type="button" data-router-provider-view="services"
              class="${providerView === "services" ? "active" : ""}">Dienstansicht</button>
            <button type="button" data-router-provider-view="providers"
              class="${providerView === "providers" ? "active" : ""}">Provideransicht</button>
          </div>
          ${providerView === "services"
            ? `<div class="router-provider-groups">${providerGroups}</div>`
            : `
              <div class="router-provider-overview-summary">
                <span>${providers.length} Provider</span>
                <span class="green">● ${providerStatusCounts.green} aktiv</span>
                <span class="amber">● ${providerStatusCounts.amber} teilweise aktiv</span>
                <span class="red">● ${providerStatusCounts.red} deaktiviert</span>
              </div>
              <div class="router-provider-overview">${providerCards}</div>
            `
          }
        </div>
      </details>

      <p class="router-disabled-note">
        Deaktivierte Fachbereiche und Provider erzeugen über WeatherRouter keine Datenabrufe,
        Kartenlayer oder Provider-Diagnosen. Neue zusätzliche Gefahrenabwehr-Dienste sind
        bei bestehenden Installationen standardmäßig ausgeschaltet.
      </p>
      <div id="router-save-state" class="router-save-state"></div>
    `;

    for (const details of host.querySelectorAll("[data-router-fold-key]")) {
      details.addEventListener("toggle", () => {
        let current = {};
        try {
          current = JSON.parse(localStorage.getItem(ROUTING_MENU_STATE_KEY) || "{}");
        } catch (_error) {
          current = {};
        }
        current[details.dataset.routerFoldKey] = details.open;
        try {
          localStorage.setItem(ROUTING_MENU_STATE_KEY, JSON.stringify(current));
        } catch (_error) {
          // Die kompakte Ansicht darf auch ohne Browserpersistenz funktionieren.
        }
      });
    }

    for (const button of host.querySelectorAll("[data-router-provider-view]")) {
      button.addEventListener("click", () => {
        let current = {};
        try {
          current = JSON.parse(localStorage.getItem(ROUTING_MENU_STATE_KEY) || "{}");
        } catch (_error) {
          current = {};
        }
        current["router-provider-view"] = button.dataset.routerProviderView === "providers"
          ? "providers"
          : "services";
        try {
          localStorage.setItem(ROUTING_MENU_STATE_KEY, JSON.stringify(current));
        } catch (_error) {
          // Ansichtspersistenz ist optional.
        }
        this._routingRender();
      });
    }

    const master = host.querySelector("#router-master-enabled");
    master?.addEventListener("change", () => {
      void this._routingUpdate({ router_enabled: Boolean(master.checked) });
    });

    for (const control of host.querySelectorAll("[data-router-domain]")) {
      control.addEventListener("change", () => {
        const enabled = new Set(
          domains.filter(item => item.enabled).map(item => item.id)
        );
        if (control.checked) enabled.add(control.dataset.routerDomain);
        else enabled.delete(control.dataset.routerDomain);
        void this._routingUpdate({ enabled_domains: [...enabled] });
      });
    }

    for (const control of host.querySelectorAll("[data-router-provider]")) {
      control.addEventListener("change", () => {
        const enabled = new Set(
          providers.filter(item => item.enabled_by_user).map(item => item.id)
        );
        if (control.checked) enabled.add(control.dataset.routerProvider);
        else enabled.delete(control.dataset.routerProvider);
        void this._routingUpdate({ enabled_providers: [...enabled] });
      });
    }
  };

  proto._routingLoadSettings = async function(render=true, force=false) {
    if (!this._hass) return null;

    // Home Assistant assigns a fresh hass object for many unrelated state changes.
    // Never rebuild the routing checkboxes just because hass changed: replacing the
    // controls while pointer/click events are in flight makes selections appear
    // randomly unclickable. Reload only on first use or an explicit force refresh.
    if (!force && this._routingSettingsLoaded && this._routingSettings) {
      return this._routingSettings;
    }

    try {
      const settings = await this._hass.callWS({
        type: "weather_router/routing_settings",
      });
      this._routingSettings = settings;
      this._routingSettingsLoaded = true;
      if (render) this._routingRender();
      return settings;
    } catch (error) {
      const host = this.shadowRoot?.getElementById("router-control-body");
      if (host) {
        host.className = "error";
        host.textContent = `Router-Einstellungen nicht verfügbar: ${error?.message || String(error)}`;
      }
      this._wrLog?.("routing_settings_failed", { error }, "error");
      return null;
    }
  };

  proto._routingUpdate = async function(patch) {
    if (!this._hass || this._routingSaving) return;
    const host = this.shadowRoot?.getElementById("router-control-body");
    const status = host?.querySelector("#router-save-state");
    this._routingSaving = true;
    if (status) status.textContent = "Speichere …";

    try {
      const response = await this._hass.callWS({
        type: "weather_router/routing_settings_update",
        ...patch,
      });
      this._routingSettings = response;
      this._routingSettingsLoaded = true;
      this._routingRender();
      this._wrLog?.("routing_settings_updated", {
        router_enabled: response.router_enabled,
        enabled_domains: (response.domains || [])
          .filter(item => item.enabled)
          .map(item => item.id),
        enabled_provider_count: (response.providers || [])
          .filter(item => item.enabled_by_user)
          .length,
      });

      // Refresh the provider catalog through the final wrapped method so every
      // frontend module tears down capabilities that just became ineligible.
      this._providers = [];
      await this._ensureProviderCatalog();

      // Routing changes alter provider eligibility immediately. Refresh every UI
      // consumer that caches provider eligibility so diagnostics, counters and
      // selectors never require a browser reload to reflect the new scope.
      this._diagnosticRefreshSelectors?.();
      this._renderWeatherLayers?.();
      this._renderMedia?.();
      this._routingRender();

      const freshStatus = this.shadowRoot?.querySelector("#router-save-state");
      if (freshStatus) freshStatus.textContent = "Gespeichert.";
    } catch (error) {
      const errorStatus = this.shadowRoot?.querySelector("#router-save-state");
      if (errorStatus) {
        errorStatus.textContent = `Speichern fehlgeschlagen: ${error?.message || String(error)}`;
        errorStatus.className = "router-save-state error";
      }
      this._wrLog?.("routing_settings_update_failed", { error }, "error");
    } finally {
      this._routingSaving = false;
    }
  };

  proto._renderShell = function(...args) {
    const result = previousRenderShell?.apply(this, args);
    this._routingInstallUI();
    this._routingRender();
    return result;
  };

  proto._ensureProviderCatalog = async function(...args) {
    const result = await previousEnsureProviderCatalog?.apply(this, args);
    await this._routingLoadSettings(true, false);
    return result;
  };

  if (typeof previousEventLogSnapshot === "function") {
    proto._wrEventLogSnapshot = function(...args) {
      const snapshot = previousEventLogSnapshot.apply(this, args);
      const settings = this._routingSettingsState();
      snapshot.routing = {
        router_enabled: Boolean(settings.router_enabled),
        enabled_domains: (settings.domains || [])
          .filter(item => item.enabled)
          .map(item => item.id),
        provider_count: (settings.providers || []).length,
        enabled_provider_count: (settings.providers || [])
          .filter(item => item.enabled_by_user)
          .length,
        eligible_provider_count: (settings.providers || [])
          .filter(item => item.eligible)
          .length,
      };
      return snapshot;
    };
  }
}
