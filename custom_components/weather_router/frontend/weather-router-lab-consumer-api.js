const LAB_ELEMENT = "weather-router-lab";
const CONSUMER_CONTRACT_VERSION = 1;

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Consumer-API-Testmodul registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterConsumerApiEnhanced) {
  proto.__weatherRouterConsumerApiEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousEnsureProviderCatalog = proto._ensureProviderCatalog;

  proto._consumerApiState = function() {
    if (!this._consumerApi) {
      this._consumerApi = {
        discovery: null,
        capabilities: null,
        baseCapabilities: null,
        selected: "",
        phenomenon: "",
        family: "",
        hazardType: "",
        severity: "",
        profiles: null,
        profileId: "",
        profileEditorOpen: false,
        profileSections: {
          status: false,
          profile: true,
          identity: true,
          scope: false,
          providers: false,
          query: true,
          output: false,
        },
        lastResolution: null,
        loading: false,
        error: null,
        catalogFeedback: null,
      };
    }
    return this._consumerApi;
  };

  proto._consumerApiInstallUI = function() {
    const root = this.shadowRoot;
    if (!root) return;

    if (!root.getElementById("weather-router-consumer-api-style")) {
      const style = document.createElement("style");
      style.id = "weather-router-consumer-api-style";
      style.textContent = `
        .consumer-api-top-grid {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));
          gap:7px;
          align-items:start;
          margin-bottom:7px;
        }
        .consumer-api-top-grid .consumer-api-wide {
          grid-column:1 / -1;
        }
        .consumer-api-status-grid {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(105px,1fr));
          gap:6px;
          margin-bottom:10px;
        }
        .consumer-api-status {
          padding:7px 8px;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 70%,transparent);
          border-radius:8px;
          background:rgba(128,128,128,.035);
        }
        .consumer-api-status small {
          display:block;
          font-size:8px;
          opacity:.58;
          text-transform:uppercase;
          letter-spacing:.04em;
        }
        .consumer-api-status strong {
          display:block;
          margin-top:2px;
          font-size:11px;
        }
        .consumer-api-status .ok { color:var(--success-color,#43a047); }
        .consumer-api-status .warn { color:#d4af37; }
        .consumer-api-status .error { color:var(--error-color,#f44336); }
        .consumer-api-filter-grid {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
          gap:6px;
          margin:0 0 6px;
        }
        .consumer-api-filter-grid select {
          min-height:36px;
        }
        .consumer-api-event-filter {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));
          gap:6px;
          margin:6px 0 8px;
          padding:8px;
          border:1px solid color-mix(in srgb,#d4af37 38%,var(--divider-color,#555));
          border-radius:8px;
          background:rgba(212,175,55,.045);
        }
        .consumer-api-event-filter select {
          min-height:36px;
        }
        .consumer-api-event-filter-note {
          grid-column:1 / -1;
          font-size:10px;
          line-height:1.35;
          opacity:.68;
        }
        .consumer-api-controls {
          display:flex;
          flex-wrap:wrap;
          gap:6px;
          align-items:center;
        }
        .consumer-api-controls select {
          flex:1 1 380px;
          min-width:min(100%,280px);
          min-height:36px;
        }
        .consumer-api-controls button {
          flex:0 0 auto;
          min-height:36px;
        }
        .consumer-api-note {
          margin:8px 0 0;
          font-size:10px;
          line-height:1.4;
          opacity:.64;
        }
        .consumer-api-profile-bar {
          display:flex;
          flex-wrap:wrap;
          gap:6px;
          align-items:center;
          margin:8px 0;
          padding:8px;
          border:1px solid color-mix(in srgb,#d4af37 42%,var(--divider-color,#555));
          border-radius:9px;
          background:rgba(212,175,55,.045);
        }
        .consumer-api-profile-bar select {
          flex:1 1 320px;
          min-width:min(100%,250px);
          min-height:36px;
        }
        .consumer-api-profile-bar button {
          flex:0 0 auto;
          min-height:36px;
        }
        .consumer-api-profile-editor input,
        .consumer-api-profile-editor textarea {
          min-height:36px;
        }
        .consumer-api-profile-editor {
          margin:0 0 9px;
          padding:8px;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 76%,transparent);
          border-radius:9px;
          background:rgba(128,128,128,.035);
        }
        .consumer-api-profile-sections {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
          gap:7px;
          align-items:start;
        }
        .consumer-api-fold {
          min-width:0;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 72%,transparent);
          border-radius:8px;
          overflow:hidden;
          background:rgba(128,128,128,.025);
        }
        .consumer-api-fold > summary {
          cursor:pointer;
          list-style:none;
          user-select:none;
          display:flex;
          align-items:center;
          gap:7px;
          min-height:36px;
          padding:7px 9px;
          font-size:10px;
          font-weight:800;
          color:#d4af37;
          background:rgba(128,128,128,.04);
        }
        .consumer-api-fold > summary::-webkit-details-marker { display:none; }
        .consumer-api-fold > summary::before {
          content:"▸";
          flex:0 0 auto;
          opacity:.7;
          transition:transform .12s ease;
        }
        .consumer-api-fold[open] > summary::before { transform:rotate(90deg); }
        .consumer-api-fold-summary {
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:8px;
          min-width:0;
          width:100%;
        }
        .consumer-api-fold-meta {
          flex:0 0 auto;
          color:var(--primary-text-color,#eee);
          font-size:9px;
          font-weight:600;
          opacity:.6;
        }
        .consumer-api-fold-body { padding:8px; }
        .consumer-api-profile-editor-grid {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
          gap:6px;
        }
        .consumer-api-profile-editor-grid .wide { grid-column:1 / -1; }
        .consumer-api-profile-editor label {
          display:grid;
          gap:3px;
          font-size:10px;
          opacity:.9;
        }
        .consumer-api-policy-grid,
        .consumer-api-profile-provider-list {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(205px,1fr));
          gap:4px 10px;
          max-height:240px;
          overflow:auto;
          padding:7px;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 70%,transparent);
          border-radius:7px;
        }
        .consumer-api-policy-block {
          min-width:0;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 70%,transparent);
          border-radius:8px;
          padding:7px;
          background:rgba(128,128,128,.025);
        }
        .consumer-api-policy-head {
          display:flex;
          align-items:center;
          justify-content:space-between;
          gap:8px;
          margin-bottom:6px;
        }
        .consumer-api-policy-head strong {
          color:#d4af37;
          font-size:10px;
        }
        .consumer-api-policy-head label {
          display:flex;
          align-items:center;
          gap:5px;
          margin:0;
          font-size:9px;
          opacity:.78;
          white-space:nowrap;
        }
        .consumer-api-policy-grid.is-disabled {
          opacity:.42;
          pointer-events:none;
        }
        .consumer-api-policy-grid label,
        .consumer-api-profile-provider-list label {
          display:flex;
          align-items:flex-start;
          gap:6px;
          min-width:0;
          margin:0;
          padding:4px 3px;
          border-radius:6px;
        }
        .consumer-api-policy-grid label:hover,
        .consumer-api-profile-provider-list label:hover {
          background:rgba(128,128,128,.055);
        }
        .consumer-api-policy-grid input[type="checkbox"],
        .consumer-api-profile-provider-list input[type="checkbox"] {
          flex:0 0 auto;
          margin-top:1px;
        }
        .consumer-api-policy-grid span,
        .consumer-api-profile-provider-list span {
          min-width:0;
          overflow-wrap:anywhere;
        }
        .consumer-api-profile-actions {
          display:flex;
          flex-wrap:wrap;
          gap:6px;
          margin-top:4px;
        }
        .consumer-api-refresh-feedback {
          margin:8px 0 0;
          padding:10px 12px;
          border:1px solid color-mix(in srgb,#d4af37 45%,var(--divider-color,#555));
          border-radius:9px;
          background:rgba(212,175,55,.075);
          color:var(--primary-text-color,#eee);
          font-size:12px;
          font-weight:650;
          line-height:1.4;
          overflow-wrap:anywhere;
        }
        .consumer-api-refresh-feedback.loading { border-color:#d4af37;color:#ffe4a0; }
        .consumer-api-refresh-feedback.ok { border-color:#2d8f66;background:rgba(45,143,102,.12);color:#a6f5ca; }
        .consumer-api-refresh-feedback.error { border-color:var(--error-color,#f44336);background:rgba(244,67,54,.09);color:#ffa9a9; }
        .consumer-api-output {
          max-height:300px;
          overflow:auto;
          margin:0;
          padding:8px;
          border-radius:8px;
          background:rgba(0,0,0,.18);
          font:10px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
          white-space:pre-wrap;
          overflow-wrap:anywhere;
        }
        @media(max-width:760px) {
          .consumer-api-top-grid { grid-template-columns:1fr; }
          .consumer-api-top-grid .consumer-api-wide { grid-column:1; }
        }
        @media(max-width:620px) {
          .consumer-api-status-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
          .consumer-api-filter-grid { grid-template-columns:1fr; }
          .consumer-api-event-filter { grid-template-columns:1fr; }
          .consumer-api-event-filter-note { grid-column:1; }
          .consumer-api-controls { grid-template-columns:1fr; }
          .consumer-api-profile-bar { grid-template-columns:1fr; }
          .consumer-api-profile-sections,
          .consumer-api-profile-editor-grid,
          .consumer-api-profile-provider-list { grid-template-columns:1fr; }
          .consumer-api-profile-editor-grid .wide { grid-column:1; }
        }
      `;
      root.appendChild(style);
    }

    if (root.getElementById("consumer-api-menu")) return;

    const referenceMenu = root.querySelector('[data-lab-menu-key="reference"]');
    if (!referenceMenu) return;

    const menu = document.createElement("details");
    menu.id = "consumer-api-menu";
    menu.className = "card lab-menu";
    menu.dataset.labMenuKey = "consumer-api-v1";
    menu.innerHTML = `
      <summary>Consumer API V1 · Schnittstellentest</summary>
      <div class="lab-menu-content">
        <div id="consumer-api-body" class="muted" style="font-size:12px">
          Consumer-Vertrag wird geladen …
        </div>
      </div>
    `;

    const routerMenu = root.getElementById("router-control-menu");
    if (routerMenu?.nextSibling) routerMenu.parentNode.insertBefore(menu, routerMenu.nextSibling);
    else referenceMenu.before(menu);
  };

  proto._consumerApiStatusClass = function(value, expected=true) {
    return value === expected ? "ok" : value == null ? "warn" : "error";
  };

  proto._consumerApiFamilyLabel = function(value) {
    const labels = {
      point:"Punktwerte",
      radar:"Radar",
      satellite:"Satellit",
      nowcast:"Nowcast",
      model:"Modell",
      warning:"Warnungen",
      convection:"Gewitter / Konvektion",
      lightning:"Blitze",
      lightning_observation:"Live-Blitzbeobachtungen",
      lightning_density:"Beobachtete Blitzdichte",
      lightning_satellite:"Satelliten-Blitze",
      earthquake:"Erdbeben",
      volcano:"Vulkane",
      tsunami:"Tsunami",
      tropical_cyclone:"Tropische Wirbelstürme",
      disaster_awareness:"Katastrophenlage",
      flood:"Hochwasser",
      public_warning:"Öffentliche Warnungen",
      sigmet:"SIGMET",
      airmet:"AIRMET",
      gairmet:"G-AIRMET",
      solar:"Sonnenaktivität",
      sun:"Sonne",
      pollen:"Pollen",
      iss:"ISS",
      moon:"Mond",
      biological_occurrence_density:"Biologische Vorkommensdichte",
    };
    return labels[value] || value;
  };

  proto._consumerApiDomainLabel = function(value) {
    const labels = {
      weather:"Wetter",
      pollen:"Pollen",
      natural_hazards:"Naturgefahren",
      civil_protection:"Bevölkerungsschutz",
      security:"Öffentliche Sicherheit",
      aviation:"Luftfahrt",
      space:"Sonne & Weltraum",
      biological_hazards:"Biologische Gefahren & Wildtiere",
    };
    return labels[value] || value;
  };

  proto._consumerApiSeverityLabel = function(value) {
    const labels = {
      unknown:"Unbekannt",
      minor:"Gering",
      moderate:"Mittel",
      severe:"Schwer",
      extreme:"Extrem",
    };
    return labels[value] || value;
  };

  proto._consumerApiRender = function() {
    const root = this.shadowRoot;
    const host = root?.getElementById("consumer-api-body");
    if (!host) return;

    const state = this._consumerApiState();
    const discovery = state.discovery;
    const catalog = state.capabilities;
    const allRows = catalog?.capabilities || [];
    const baseCatalog = state.baseCapabilities || catalog;
    const baseRows = baseCatalog?.capabilities || [];
    const filterOptions = catalog?.filter_options || {};
    const baseFilterOptions = baseCatalog?.filter_options || filterOptions;
    const phenomena = filterOptions.phenomena || [];
    const families = filterOptions.families || [];
    const profilePhenomena = baseFilterOptions.phenomena || [];
    const profileFamilies = baseFilterOptions.families || [];
    const profileDomains = baseFilterOptions.domains || [];
    const hazardTypeMap = new Map();
    const severityMap = new Map();
    for (const row of baseRows) {
      for (const item of row.event_filter_options?.hazard_types || []) {
        if (item?.id) hazardTypeMap.set(item.id, item.name || item.id);
      }
      for (const item of row.event_filter_options?.severities || []) {
        if (item?.id) severityMap.set(item.id, item.name || item.id);
      }
    }
    const profileHazardTypes = [...hazardTypeMap.entries()]
      .map(([id,name]) => ({ id, name }))
      .sort((a,b) => String(a.name).localeCompare(String(b.name), "de"));
    const profileSeverities = [...severityMap.keys()]
      .map(id => ({ id, name:this._consumerApiSeverityLabel(id) }));
    const rows = allRows.filter(item => (
      (!state.phenomenon || (item.phenomena || []).includes(state.phenomenon))
      && (!state.family || item.family === state.family)
    ));
    const available = rows.filter(item => item.available).length;
    const enabled = rows.filter(item => item.enabled).length;
    const compatible = discovery?.contract?.supported_versions?.includes(CONSUMER_CONTRACT_VERSION) ?? null;
    const ready = discovery?.router?.ready ?? null;
    const routerEnabled = discovery?.router?.enabled ?? null;
    const profiles = state.profiles?.profiles || [];
    const selectedProfile = profiles.find(item => item.id === state.profileId) || null;
    const providerRows = [...(this._providers || [])]
      .sort((a,b) => String(a.name || a.id).localeCompare(String(b.name || b.id), "de"));
    const excludedProviderCount = (selectedProfile?.excluded_providers || []).length;
    const excludedCandidateClassCount = [
      ...(selectedProfile?.excluded_data_origins || []),
      ...(selectedProfile?.excluded_measurement_methods || []),
      ...(selectedProfile?.excluded_observation_kinds || []),
    ].length;
    const csv = value => Array.isArray(value) ? value.join(", ") : "";
    const selectedSet = key => new Set(selectedProfile?.[key] || []);
    const policyEnabled = key => Array.isArray(selectedProfile?.[key]) && selectedProfile[key].length > 0;
    const policyGrid = (field, title, values, labeler=value => value) => {
      const enabled = policyEnabled(field);
      const selected = selectedSet(field);
      return `
        <div class="consumer-api-policy-block">
          <div class="consumer-api-policy-head">
            <strong>${this._escape(title)}</strong>
            <label>
              <input type="checkbox" data-profile-policy-toggle="${this._escape(field)}"
                ${enabled ? "checked" : ""}>
              einschränken
            </label>
          </div>
          <div class="consumer-api-policy-grid ${enabled ? "" : "is-disabled"}"
            data-profile-policy-grid="${this._escape(field)}">
            ${values.map(item => {
              const id = typeof item === "string" ? item : item.id;
              const name = typeof item === "string" ? labeler(item) : (item.name || labeler(item.id));
              return `
                <label title="${this._escape(id)}">
                  <input type="checkbox"
                    data-profile-policy-value="${this._escape(field)}"
                    value="${this._escape(id)}"
                    ${selected.has(id) ? "checked" : ""}>
                  <span>${this._escape(name)}</span>
                </label>
              `;
            }).join("") || '<span style="font-size:9px;opacity:.62">Keine Werte im Basiskatalog.</span>'}
          </div>
        </div>
      `;
    };
    const sectionOpen = key => state.profileSections?.[key] !== false;

    if (!discovery && state.loading) {
      host.className = "muted";
      host.textContent = "Consumer-Vertrag wird geladen …";
      return;
    }

    const selectedExists = rows.some(item => item.id === state.selected);
    if (!selectedExists) {
      state.selected = rows.find(item => item.id === "weather.precipitation.layer" && item.available)?.id
        || rows.find(item => item.available)?.id
        || rows[0]?.id
        || "";
      state.hazardType = "";
      state.severity = "";
    }

    const selectedCapability = allRows.find(item => item.id === state.selected) || null;
    const eventFilterOptions = selectedCapability?.event_filter_options || null;
    const hazardTypes = eventFilterOptions?.hazard_types || [];
    const severities = eventFilterOptions?.severities || [];
    if (state.hazardType && !hazardTypes.some(item => item.id === state.hazardType)) {
      state.hazardType = "";
    }
    if (state.severity && !severities.some(item => item.id === state.severity)) {
      state.severity = "";
    }

    host.className = "";
    host.innerHTML = `
      <div class="consumer-api-top-grid">
        <details class="consumer-api-fold" data-consumer-section="status"
          ${sectionOpen("status") ? "open" : ""}>
          <summary>
            <span class="consumer-api-fold-summary">
              <span>Schnittstellenstatus</span>
              <span class="consumer-api-fold-meta">
                V1 · ${ready ? "bereit" : "nicht bereit"} · Router ${routerEnabled ? "aktiv" : "aus"}
              </span>
            </span>
          </summary>
          <div class="consumer-api-fold-body">
            <div class="consumer-api-status-grid">
              <div class="consumer-api-status">
                <small>PRESENT</small>
                <strong class="${this._consumerApiStatusClass(Boolean(discovery))}">
                  ${discovery ? "ja" : "nein"}
                </strong>
              </div>
              <div class="consumer-api-status">
                <small>COMPATIBLE</small>
                <strong class="${this._consumerApiStatusClass(compatible)}">
                  ${compatible == null ? "—" : compatible ? "V1" : "nein"}
                </strong>
              </div>
              <div class="consumer-api-status">
                <small>READY</small>
                <strong class="${this._consumerApiStatusClass(ready)}">
                  ${ready == null ? "—" : ready ? "ja" : "nein"}
                </strong>
              </div>
              <div class="consumer-api-status">
                <small>Router</small>
                <strong class="${this._consumerApiStatusClass(routerEnabled)}">
                  ${routerEnabled == null ? "—" : routerEnabled ? "aktiv" : "aus"}
                </strong>
              </div>
            </div>
            <div style="font-size:10px;opacity:.7">
              Öffentliche Capabilities: <strong>${rows.length}</strong>
              ${rows.length !== allRows.length ? ` von ${allRows.length}` : ""} ·
              aktiviert: <strong>${enabled}</strong> ·
              auflösbar: <strong>${available}</strong>
            </div>
          </div>
        </details>

        <details class="consumer-api-fold ${state.profileEditorOpen ? "consumer-api-wide" : ""}"
          data-consumer-section="profile" ${sectionOpen("profile") ? "open" : ""}>
          <summary>
            <span class="consumer-api-fold-summary">
              <span>Profil & Richtlinien</span>
              <span class="consumer-api-fold-meta">
                ${selectedProfile
                  ? `${this._escape(selectedProfile.name)} · r${Number(selectedProfile.revision || 0)}`
                  : "normale API"}
              </span>
            </span>
          </summary>
          <div class="consumer-api-fold-body">
            <div class="consumer-api-profile-bar" style="margin:0">
              <select id="consumer-api-profile" aria-label="Consumer-Profil">
                <option value="">Kein Profil · normale API</option>
                ${profiles.map(item => `
                  <option value="${this._escape(item.id)}"
                    ${item.id === state.profileId ? "selected" : ""}>
                    ${this._escape(item.name)} · r${Number(item.revision || 0)}
                  </option>
                `).join("")}
              </select>
              <button id="consumer-api-profile-new" class="secondary" type="button">Neues Profil</button>
              <button id="consumer-api-profile-edit" class="secondary" type="button"
                ${!state.profiles ? "disabled" : ""}>Profile verwalten</button>
            </div>

            ${state.profileEditorOpen && state.profiles ? `
              <div class="consumer-api-profile-editor" style="margin-top:7px;margin-bottom:0">
          <div class="consumer-api-profile-sections">
            <details class="consumer-api-fold" data-consumer-section="identity"
              ${sectionOpen("identity") ? "open" : ""}>
              <summary>
                <span class="consumer-api-fold-summary">
                  <span>Profilgrunddaten</span>
                  <span class="consumer-api-fold-meta">${selectedProfile ? `r${Number(selectedProfile.revision || 0)}` : "neu"}</span>
                </span>
              </summary>
              <div class="consumer-api-fold-body">
                <div class="consumer-api-profile-editor-grid">
                  <label>
                    Profil-ID
                    <input id="consumer-profile-id" value="${this._escape(selectedProfile?.id || "")}"
                      placeholder="z. B. gewitterradar" ${selectedProfile ? "readonly" : ""}>
                  </label>
                  <label>
                    Name
                    <input id="consumer-profile-name" value="${this._escape(selectedProfile?.name || "")}"
                      placeholder="Anzeigename">
                  </label>
                  <label>
                    Profil aktiv
                    <input id="consumer-profile-enabled" type="checkbox"
                      ${selectedProfile?.enabled !== false ? "checked" : ""}>
                  </label>
                  <label class="wide">
                    Beschreibung
                    <textarea id="consumer-profile-description" rows="2"
                      placeholder="Optional">${this._escape(selectedProfile?.description || "")}</textarea>
                  </label>
                </div>
              </div>
            </details>

            <details class="consumer-api-fold" data-consumer-section="scope"
              ${sectionOpen("scope") ? "open" : ""}>
              <summary>
                <span class="consumer-api-fold-summary">
                  <span>Fachliche Auswahl</span>
                  <span class="consumer-api-fold-meta">6 Filtergruppen</span>
                </span>
              </summary>
              <div class="consumer-api-fold-body">
                <div class="consumer-api-profile-editor-grid">
                  ${policyGrid(
                    "allowed_domains",
                    "Fachbereiche",
                    profileDomains,
                    value => this._consumerApiDomainLabel(value),
                  )}
                  ${policyGrid(
                    "allowed_families",
                    "Familien / Ebenen",
                    profileFamilies,
                    value => this._consumerApiFamilyLabel(value),
                  )}
                  ${policyGrid(
                    "allowed_phenomena",
                    "Themen",
                    profilePhenomena,
                    value => value,
                  )}
                  ${policyGrid(
                    "allowed_hazard_types",
                    "Ereignistypen",
                    profileHazardTypes,
                    value => value,
                  )}
                  ${policyGrid(
                    "allowed_severities",
                    "Warnstufen",
                    profileSeverities,
                    value => this._consumerApiSeverityLabel(value),
                  )}
                  <label class="wide">
                    Erweiterte Capability-Positivliste
                    <input id="consumer-profile-capabilities"
                      value="${this._escape(csv(selectedProfile?.allowed_capabilities))}"
                      placeholder="optional · öffentliche Capability-IDs">
                    <small style="display:block;margin-top:3px;opacity:.62">
                      Leer = keine zusätzliche Capability-Einschränkung. Diese Expertenoption
                      bleibt textuell, weil der öffentliche Katalog sehr groß werden kann.
                    </small>
                  </label>
                </div>
              </div>
            </details>

            <details class="consumer-api-fold consumer-api-profile-providers"
              data-consumer-section="providers"
              ${sectionOpen("providers") ? "open" : ""}>
              <summary>
                <span class="consumer-api-fold-summary">
                  <span>Provider-Ausschlüsse</span>
                  <span class="consumer-api-fold-meta">${excludedProviderCount} Provider · ${excludedCandidateClassCount} Klassen ausgeschlossen</span>
                </span>
              </summary>
              <div class="consumer-api-fold-body">
                <div style="margin-bottom:7px;font-size:10px;opacity:.72">
                  Provider dürfen hier nur zusätzlich ausgeschlossen werden. Ein global
                  deaktivierter Provider bleibt immer deaktiviert; Profile können ihn niemals
                  wieder einschalten oder priorisieren. „global aus“ ist nur eine Information.
                </div>
                <div class="consumer-api-profile-provider-list">
                  ${providerRows.map(provider => `
                    <label title="${this._escape(provider.id)}">
                      <input type="checkbox" data-profile-excluded-provider="${this._escape(provider.id)}"
                        ${(selectedProfile?.excluded_providers || []).includes(provider.id) ? "checked" : ""}>
                      <span>${this._escape(provider.name || provider.id)}${provider.eligible === false ? " · global aus" : ""}</span>
                    </label>
                  `).join("")}
                </div>
                <div class="consumer-api-profile-editor-grid" style="margin-top:8px">
                  <label>
                    Datenursprünge ausschließen
                    <input id="consumer-profile-excluded-origins"
                      value="${this._escape(csv(selectedProfile?.excluded_data_origins))}"
                      placeholder="z. B. satellite, model, nowcast">
                  </label>
                  <label>
                    Beobachtungsarten ausschließen
                    <input id="consumer-profile-excluded-kinds"
                      value="${this._escape(csv(selectedProfile?.excluded_observation_kinds))}"
                      placeholder="z. B. estimate, nowcast, forecast">
                  </label>
                  <label class="wide">
                    Messmethoden ausschließen
                    <input id="consumer-profile-excluded-methods"
                      value="${this._escape(csv(selectedProfile?.excluded_measurement_methods))}"
                      placeholder="z. B. radar_reflectivity">
                    <small style="display:block;margin-top:3px;opacity:.62">
                      Rein restriktiv: Diese Felder priorisieren nichts. Routing-Reihenfolge und
                      Fallback bleiben ausschließlich Aufgabe des WeatherRouter-Core.
                    </small>
                  </label>
                </div>
              </div>
            </details>
          </div>

                <div class="consumer-api-profile-actions" style="margin-top:7px">
                  <button id="consumer-profile-save" type="button">Profil speichern</button>
                  <button id="consumer-profile-template-storm" class="secondary" type="button">Vorlage Gewitterradar</button>
                  <button id="consumer-profile-template-aurora" class="secondary" type="button">Vorlage Aurora</button>
                  <button id="consumer-profile-template-bio" class="secondary" type="button">Vorlage Biologische Gefahren</button>
                  <button id="consumer-profile-delete" class="secondary" type="button"
                    ${!selectedProfile ? "disabled" : ""}>Profil löschen</button>
                </div>
              </div>
            ` : ""}
          </div>
        </details>
      </div>

      <details class="consumer-api-fold" data-consumer-section="query"
        ${sectionOpen("query") ? "open" : ""}>
        <summary>
          <span class="consumer-api-fold-summary">
            <span>Filter & Auflösung</span>
            <span class="consumer-api-fold-meta">${rows.length} Capabilities</span>
          </span>
        </summary>
        <div class="consumer-api-fold-body">
          <div class="consumer-api-filter-grid">
            <select id="consumer-api-phenomenon" aria-label="Thema filtern">
              <option value="">Alle Themen</option>
              ${phenomena.map(item => `
                <option value="${this._escape(item.id)}"
                  ${item.id === state.phenomenon ? "selected" : ""}>
                  ${this._escape(item.name)}
                </option>
              `).join("")}
            </select>
            <select id="consumer-api-family" aria-label="Capability-Familie filtern">
              <option value="">Alle Ebenen</option>
              ${families.map(item => `
                <option value="${this._escape(item)}"
                  ${item === state.family ? "selected" : ""}>
                  ${this._escape(this._consumerApiFamilyLabel(item))}
                </option>
              `).join("")}
            </select>
          </div>

          <div class="consumer-api-controls">
            <select id="consumer-api-capability" aria-label="Öffentliche Consumer-Capability">
              ${rows.map(item => `
                <option value="${this._escape(item.id)}"
                  ${item.id === state.selected ? "selected" : ""}>
                  ${this._escape(item.name || item.id)} · ${this._escape(item.id)}${item.available ? "" : " · nicht auflösbar"}
                </option>
              `).join("")}
            </select>
            <button id="consumer-api-refresh" class="secondary" type="button"
              ${state.loading ? "disabled" : ""}>${state.loading ? "Katalog wird geladen …" : "Discovery/Katalog"}</button>
            <button id="consumer-api-resolve" type="button"
              ${state.loading || !state.selected ? "disabled" : ""}>Resolve testen</button>
          </div>
          ${state.catalogFeedback ? `
            <div class="consumer-api-refresh-feedback ${this._escape(state.catalogFeedback.kind)}"
                 role="status" aria-live="polite">${this._escape(state.catalogFeedback.message)}</div>
          ` : ""}

          ${hazardTypes.length ? `
            <div class="consumer-api-event-filter">
              <select id="consumer-api-hazard-type" aria-label="Ereignistyp filtern">
                <option value="">Alle Ereignistypen</option>
                ${hazardTypes.map(item => `
                  <option value="${this._escape(item.id)}"
                    ${item.id === state.hazardType ? "selected" : ""}>
                    ${this._escape(item.name)} · ${this._escape(item.id)}
                  </option>
                `).join("")}
              </select>
              <select id="consumer-api-severity" aria-label="Warnstufe filtern">
                <option value="">Alle Warnstufen</option>
                ${severities.map(item => `
                  <option value="${this._escape(item.id)}"
                    ${item.id === state.severity ? "selected" : ""}>
                    ${this._escape(item.name)} · ${this._escape(item.id)}
                  </option>
                `).join("")}
              </select>
              <div class="consumer-api-event-filter-note">
                Ereignisfilter wirken erst nach dem Abruf auf normalisierte Warnereignisse.
                Sie wählen keinen Provider und ändern keine amtliche Einstufung.
              </div>
            </div>
          ` : ""}

          <p class="consumer-api-note">
            Discovery/Katalog erzeugt keine Provider-Netzwerkabfragen. „Resolve testen“
            verwendet nur die öffentliche Capability-ID; den Provider wählt WeatherRouter.
          </p>
        </div>
      </details>

      <details class="consumer-api-fold" data-consumer-section="output"
        style="margin-top:7px" ${sectionOpen("output") ? "open" : ""}>
        <summary>
          <span class="consumer-api-fold-summary">
            <span>Antwort / Diagnose</span>
            <span class="consumer-api-fold-meta">${state.error ? "Fehler" : state.lastResolution ? "Resolve" : "Katalog"}</span>
          </span>
        </summary>
        <div class="consumer-api-fold-body">
          <div id="consumer-api-result" class="consumer-api-output">${this._escape(
            state.error
              ? `Fehler: ${state.error}`
              : state.lastResolution
                ? JSON.stringify(state.lastResolution, null, 2)
                : discovery
                  ? JSON.stringify({
                      discovery,
                      capability_summary: {
                        total: allRows.length,
                        visible: rows.length,
                        enabled,
                        available,
                        phenomenon: state.phenomenon || null,
                        family: state.family || null,
                      },
                    }, null, 2)
                  : "Noch kein Schnittstellentest ausgeführt."
          )}</div>
        </div>
      </details>
    `;

    host.querySelectorAll("[data-consumer-section]").forEach(details => {
      details.addEventListener("toggle", () => {
        state.profileSections = {
          ...(state.profileSections || {}),
          [details.dataset.consumerSection]: details.open,
        };
      });
    });

    host.querySelectorAll("[data-profile-policy-toggle]").forEach(toggle => {
      toggle.addEventListener("change", () => {
        const field = toggle.dataset.profilePolicyToggle;
        const grid = host.querySelector(`[data-profile-policy-grid="${field}"]`);
        grid?.classList.toggle("is-disabled", !toggle.checked);
      });
    });

    host.querySelector("#consumer-api-profile")?.addEventListener("change", event => {
      state.profileId = event.target.value;
      state.selected = "";
      state.hazardType = "";
      state.severity = "";
      void this._consumerApiLoad(true);
    });
    host.querySelector("#consumer-api-profile-edit")?.addEventListener("click", () => {
      state.profileEditorOpen = !state.profileEditorOpen;
      this._consumerApiRender();
    });
    host.querySelector("#consumer-api-profile-new")?.addEventListener("click", () => {
      state.profileId = "";
      state.profileEditorOpen = true;
      this._consumerApiRender();
    });
    host.querySelector("#consumer-profile-save")?.addEventListener("click", () => {
      void this._consumerApiSaveProfile();
    });
    host.querySelector("#consumer-profile-delete")?.addEventListener("click", () => {
      void this._consumerApiDeleteProfile();
    });
    host.querySelector("#consumer-profile-template-storm")?.addEventListener("click", () => {
      this._consumerApiApplyProfileTemplate("gewitterradar");
    });
    host.querySelector("#consumer-profile-template-aurora")?.addEventListener("click", () => {
    root?.getElementById("consumer-profile-template-bio")?.addEventListener("click", () => this._consumerApiApplyProfileTemplate("biologische_gefahren"));
      this._consumerApiApplyProfileTemplate("aurora_borealis");
    });
    host.querySelector("#consumer-api-phenomenon")?.addEventListener("change", event => {
      state.phenomenon = event.target.value;
      state.selected = "";
      this._consumerApiRender();
    });
    host.querySelector("#consumer-api-family")?.addEventListener("change", event => {
      state.family = event.target.value;
      state.selected = "";
      this._consumerApiRender();
    });
    host.querySelector("#consumer-api-capability")?.addEventListener("change", event => {
      state.selected = event.target.value;
      state.hazardType = "";
      state.severity = "";
      this._consumerApiRender();
    });
    host.querySelector("#consumer-api-hazard-type")?.addEventListener("change", event => {
      state.hazardType = event.target.value;
    });
    host.querySelector("#consumer-api-severity")?.addEventListener("change", event => {
      state.severity = event.target.value;
    });
    host.querySelector("#consumer-api-refresh")?.addEventListener("click", () => {
      void this._consumerApiLoad(true);
    });
    host.querySelector("#consumer-api-resolve")?.addEventListener("click", () => {
      void this._consumerApiResolve();
    });
  };

  proto._consumerApiCsvList = function(value) {
    return String(value || "")
      .split(",")
      .map(item => item.trim())
      .filter(Boolean)
      .filter((item,index,array) => array.indexOf(item) === index);
  };

  proto._consumerApiReadProfileForm = function() {
    const root = this.shadowRoot;
    const id = root?.getElementById("consumer-profile-id")?.value?.trim() || "";
    const name = root?.getElementById("consumer-profile-name")?.value?.trim() || "";

    const policyLabels = {
      allowed_domains:"Fachbereiche",
      allowed_families:"Familien / Ebenen",
      allowed_phenomena:"Themen",
      allowed_hazard_types:"Ereignistypen",
      allowed_severities:"Warnstufen",
    };
    const readPolicy = field => {
      const toggle = root?.querySelector(`[data-profile-policy-toggle="${field}"]`);
      if (!toggle?.checked) return null;
      const values = [...(root?.querySelectorAll(
        `[data-profile-policy-value="${field}"]:checked`
      ) || [])].map(node => node.value).filter(Boolean);
      if (!values.length) {
        throw new Error(`${policyLabels[field] || field}: Bei aktiver Einschränkung muss mindestens ein Wert ausgewählt sein.`);
      }
      return values;
    };

    const profile = {
      id,
      name,
      description: root?.getElementById("consumer-profile-description")?.value?.trim() || "",
      enabled: root?.getElementById("consumer-profile-enabled")?.checked !== false,
      excluded_providers: [...(root?.querySelectorAll("[data-profile-excluded-provider]:checked") || [])]
        .map(node => node.dataset.profileExcludedProvider)
        .filter(Boolean),
      excluded_data_origins: this._consumerApiCsvList(
        root?.getElementById("consumer-profile-excluded-origins")?.value
      ),
      excluded_measurement_methods: this._consumerApiCsvList(
        root?.getElementById("consumer-profile-excluded-methods")?.value
      ),
      excluded_observation_kinds: this._consumerApiCsvList(
        root?.getElementById("consumer-profile-excluded-kinds")?.value
      ),
    };

    for (const field of Object.keys(policyLabels)) {
      const values = readPolicy(field);
      if (values) profile[field] = values;
    }

    const capabilities = this._consumerApiCsvList(
      root?.getElementById("consumer-profile-capabilities")?.value
    );
    if (capabilities.length) profile.allowed_capabilities = capabilities;

    return profile;
  };

  proto._consumerApiApplyProfileTemplate = function(templateId) {
    const root = this.shadowRoot;
    const templates = {
      gewitterradar: {
        id:"gewitterradar",
        name:"Gewitterradar",
        description:"Gewitter-, Niederschlags- und warnungsbezogene WeatherRouter-Sicht.",
        domains:"weather, natural_hazards",
        families:"warning, convection, lightning, radar, nowcast, point, satellite",
        phenomena:"thunderstorm, precipitation, rain, wind, clouds",
        hazards:"severe_thunderstorm, tornado, waterspout, hail, downburst, supercell, heavy_rain, windstorm, lightning, flash_flood, flood",
        severities:"",
      },
      biologische_gefahren: {
        id:"biologische_gefahren",
        name:"Biologische Gefahren",
        description:"Wildtiere, giftige Arten, toxische Pflanzen/Pilze und biologische Vektoren.",
        domains:"biological_hazards",
        families:"biological_occurrence_density",
        phenomena:"wildlife, predator, crocodilian, marine, venomous, snake, toxic, toxic_plant, toxic_fungus, vector",
        hazards:"",
        severities:"",
      },
      aurora_borealis: {
        id:"aurora_borealis",
        name:"Aurora Borealis",
        description:"Sichtbedingungen und Weltraumdaten für Polarlichtbeobachtung.",
        domains:"weather, space",
        families:"point, satellite, solar",
        phenomena:"clouds, visibility, fog, precipitation, weather_condition",
        hazards:"",
        severities:"",
      },
    };
    const t = templates[templateId];
    if (!t || !root) return;
    const assign = (id,value) => {
      const node = root.getElementById(id);
      if (node) node.value = value;
    };
    const setPolicy = (field, csvValue) => {
      const values = new Set(this._consumerApiCsvList(csvValue));
      const toggle = root.querySelector(`[data-profile-policy-toggle="${field}"]`);
      const grid = root.querySelector(`[data-profile-policy-grid="${field}"]`);
      if (toggle) toggle.checked = values.size > 0;
      grid?.classList.toggle("is-disabled", values.size === 0);
      root.querySelectorAll(`[data-profile-policy-value="${field}"]`).forEach(node => {
        node.checked = values.has(node.value);
      });
    };

    assign("consumer-profile-id", t.id);
    assign("consumer-profile-name", t.name);
    assign("consumer-profile-description", t.description);
    const enabledNode = root.getElementById("consumer-profile-enabled");
    if (enabledNode) enabledNode.checked = true;

    setPolicy("allowed_domains", t.domains);
    setPolicy("allowed_families", t.families);
    setPolicy("allowed_phenomena", t.phenomena);
    setPolicy("allowed_hazard_types", t.hazards);
    setPolicy("allowed_severities", t.severities);
    assign("consumer-profile-capabilities", "");

    root.querySelectorAll("[data-profile-excluded-provider]").forEach(node => {
      node.checked = false;
    });
    assign("consumer-profile-excluded-origins", "");
    assign("consumer-profile-excluded-methods", "");
    assign("consumer-profile-excluded-kinds", "");
  };

  proto._consumerApiSaveProfile = async function() {
    if (!this._hass) return;
    const state = this._consumerApiState();
    try {
      const profile = this._consumerApiReadProfileForm();
      if (!profile.id || !profile.name) {
        throw new Error("Profil-ID und Name sind erforderlich.");
      }
      const response = await this._hass.callWS({
        type:"weather_router/consumer_profile_upsert",
        profile,
      });
      state.profiles = response;
      state.profileId = profile.id;
      state.profileEditorOpen = true;
      state.error = null;
      state.selected = "";
      await this._consumerApiLoad(true);
      this._wrLog?.("consumer_profile_saved", {
        profile_id:profile.id,
        excluded_provider_count:profile.excluded_providers?.length || 0,
      });
    } catch (error) {
      state.error = error?.message || String(error);
      this._wrLog?.("consumer_profile_save_failed", { error }, "error");
      this._consumerApiRender();
    }
  };

  proto._consumerApiDeleteProfile = async function() {
    if (!this._hass) return;
    const state = this._consumerApiState();
    if (!state.profileId) return;
    try {
      const deletedId = state.profileId;
      const response = await this._hass.callWS({
        type:"weather_router/consumer_profile_delete",
        profile_id:deletedId,
      });
      state.profiles = response;
      state.profileId = "";
      state.profileEditorOpen = false;
      state.selected = "";
      state.error = null;
      await this._consumerApiLoad(true);
      this._wrLog?.("consumer_profile_deleted", { profile_id:deletedId });
    } catch (error) {
      state.error = error?.message || String(error);
      this._wrLog?.("consumer_profile_delete_failed", { error }, "error");
      this._consumerApiRender();
    }
  };

  proto._consumerApiLoad = async function(force=false) {
    if (!this._hass) return null;
    const state = this._consumerApiState();
    if (state.loading) return null;
    if (!force && state.discovery && state.capabilities) {
      // Do not rebuild an already rendered Consumer API/profile editor on every
      // unrelated Home Assistant state update. Replacing active inputs/checkboxes
      // while a click is in flight causes missed selections and also discards
      // unsaved form edits.
      return state;
    }

    const startedAt = Date.now();
    state.loading = true;
    state.error = null;
    state.catalogFeedback = { kind:"loading", message:"Katalog wird geladen …" };
    this._consumerApiRender();
    try {
      state.discovery = await this._hass.callWS({
        type: "weather_router/consumer/discovery",
      });
      try {
        state.profiles = await this._hass.callWS({
          type:"weather_router/consumer_profiles",
        });
      } catch (_profileError) {
        state.profiles = null;
        state.profileId = "";
      }
      const baseCapabilityRequest = {
        type:"weather_router/consumer/capabilities",
        contract_version:CONSUMER_CONTRACT_VERSION,
      };
      state.baseCapabilities = await this._hass.callWS(baseCapabilityRequest);
      if (state.profileId) {
        state.capabilities = await this._hass.callWS({
          ...baseCapabilityRequest,
          profile_id:state.profileId,
        });
      } else {
        state.capabilities = state.baseCapabilities;
      }
      const durationMs = Math.max(0, Date.now() - startedAt);
      const total = state.capabilities?.capabilities?.length || 0;
      const available = (state.capabilities?.capabilities || []).filter(item => item.available).length;
      state.catalogFeedback = {
        kind:"ok",
        message:`Katalog geladen · ${available} von ${total} verfügbar · ${durationMs} ms · ${new Date().toLocaleTimeString("de-DE")}`,
      };
      this._wrLog?.("consumer_api_catalog_ready", {
        duration_ms: durationMs,
        contract_version: CONSUMER_CONTRACT_VERSION,
        ready: state.discovery?.router?.ready ?? null,
        router_enabled: state.discovery?.router?.enabled ?? null,
        capability_count: state.capabilities?.capabilities?.length || 0,
        available_count: (state.capabilities?.capabilities || []).filter(item => item.available).length,
      });
    } catch (error) {
      state.error = error?.message || String(error);
      state.catalogFeedback = { kind:"error", message:"Katalog konnte nicht geladen werden: " + state.error };
      this._wrLog?.("consumer_api_catalog_failed", { error }, "error");
    } finally {
      state.loading = false;
      this._consumerApiRender();
    }
    return state;
  };

  proto._consumerApiBbox = function() {
    if (!this._map) return null;
    const bounds = this._map.getBounds?.();
    if (!bounds) return null;
    const rawWest = Number(bounds.getWest?.());
    const rawEast = Number(bounds.getEast?.());
    const south = Math.max(-90, Math.min(90, Number(bounds.getSouth?.())));
    const north = Math.max(-90, Math.min(90, Number(bounds.getNorth?.())));
    if (![rawWest, rawEast, south, north].every(Number.isFinite)) return null;

    const span = rawEast - rawWest;
    if (span >= 360) {
      return { type:"bbox", west:-180, south, east:180, north };
    }
    const wrap = value => ((value + 180) % 360 + 360) % 360 - 180;
    return {
      type:"bbox",
      west:wrap(rawWest),
      south,
      east:wrap(rawEast),
      north,
    };
  };

  proto._consumerApiContext = function(capability) {
    const contexts = capability?.spatial_contexts || [];
    const point = this._currentPoint?.();
    if (contexts.includes("point") && point) {
      return {
        type:"point",
        latitude:Number(point.latitude),
        longitude:Number(point.longitude),
      };
    }
    if (contexts.includes("bbox")) {
      const bbox = this._consumerApiBbox();
      if (bbox) return bbox;
    }
    if (contexts.includes("global")) return { type:"global" };
    if (contexts.includes("point")) {
      throw new Error("Für diese Capability fehlt ein gültiger expliziter Testpunkt.");
    }
    throw new Error("Für diese Capability steht kein unterstützter Testkontext bereit.");
  };

  proto._consumerApiResolve = async function() {
    if (!this._hass) return;
    const state = this._consumerApiState();
    if (state.loading) return;

    const capability = (state.capabilities?.capabilities || [])
      .find(item => item.id === state.selected);
    if (!capability) return;

    state.loading = true;
    state.error = null;
    state.lastResolution = null;
    this._consumerApiRender();

    try {
      const context = this._consumerApiContext(capability);
      const started = performance.now();
      const request = {
        type:"weather_router/consumer/resolve",
        contract_version:CONSUMER_CONTRACT_VERSION,
        capability:capability.id,
        context,
        time:{ mode:"latest" },
      };
      if (state.profileId) request.profile_id = state.profileId;
      const eventFilter = {};
      if (state.hazardType) eventFilter.hazard_types = [state.hazardType];
      if (state.severity) eventFilter.severities = [state.severity];
      if (Object.keys(eventFilter).length) request.event_filter = eventFilter;
      const result = await this._hass.callWS(request);
      const durationMs = Math.round(performance.now() - started);
      state.lastResolution = result;
      this._wrLog?.("consumer_api_resolve", {
        capability:capability.id,
        context_type:context.type,
        status:result?.status || null,
        resource_type:result?.resource?.type || null,
        reason_code:result?.routing?.reason_code || result?.unavailable?.code || null,
        hazard_type_filter:state.hazardType || null,
        severity_filter:state.severity || null,
        profile_id:state.profileId || null,
        duration_ms:durationMs,
      }, result?.status === "ready" ? "info" : "warning");
    } catch (error) {
      state.error = error?.message || String(error);
      this._wrLog?.("consumer_api_resolve_failed", {
        capability:capability.id,
        error,
      }, "error");
    } finally {
      state.loading = false;
      this._consumerApiRender();
    }
  };

  proto._renderShell = function(...args) {
    const result = previousRenderShell?.apply(this, args);
    this._consumerApiInstallUI();
    this._consumerApiRender();
    return result;
  };

  proto._ensureProviderCatalog = async function(...args) {
    const result = await previousEnsureProviderCatalog?.apply(this, args);
    await this._consumerApiLoad(false);
    return result;
  };
}
