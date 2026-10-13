const LAB_ELEMENT = "weather-router-lab";
const HAZARD_MENU_STATE_KEY = "weather_router_lab_menu_state_v1";
const HAZARD_PROXIMITY_KEY = "weather_router_hazard_proximity_v1";
const HAZARD_PROXIMITY_DEFAULT_KM = 100;
const HAZARD_VIEW_FILTER_KEY = "weather_router_hazard_view_filter_v1";
const HAZARD_TARGET_SYMBOL_URL = new URL("./gewitterradar_target_symbol.svg", import.meta.url).href;

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Gefahrenmodul registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterHazardsEnhanced) {
  proto.__weatherRouterHazardsEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousEnsureProviderCatalog = proto._ensureProviderCatalog;
  const previousRestoreWeatherLayers = proto._restoreWeatherLayers;
  const previousEventLogSnapshot = proto._wrEventLogSnapshot;

  proto._hazardStates = function() {
    if (!this._hazardFeeds) this._hazardFeeds = new Map();
    return this._hazardFeeds;
  };

  proto._hazardInstallUI = function() {
    const root = this.shadowRoot;
    if (!root) return;

    if (!root.getElementById("weather-router-hazard-style")) {
      const style = document.createElement("style");
      style.id = "weather-router-hazard-style";
      style.textContent = `
        .hazard-overview {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
          gap:6px;
          margin:0 0 8px;
        }
        .hazard-overview-card {
          min-width:0;
          padding:7px 9px;
          border:1px solid color-mix(in srgb,#d4af37 24%,var(--divider-color,#555));
          border-radius:8px;
          background:rgba(128,128,128,.035);
        }
        .hazard-overview-card small {
          display:block;
          margin-bottom:2px;
          font-size:9px;
          opacity:.58;
        }
        .hazard-overview-card strong {
          display:block;
          font-size:12px;
          line-height:1.25;
        }
        .hazard-filter-controls {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
          gap:7px;
          margin:0 0 8px;
        }
        .hazard-filter-controls label { margin:0; }
        .hazard-filter-controls select { min-height:34px; padding:5px 7px; }
        .hazard-group-list {
          display:grid;
          gap:8px;
        }
        .hazard-group {
          min-width:0;
          border:1px solid color-mix(in srgb,var(--divider-color,#555) 74%,transparent);
          border-radius:10px;
          overflow:hidden;
          background:rgba(128,128,128,.02);
        }
        .hazard-group > summary {
          cursor:pointer;
          list-style:none;
          user-select:none;
          display:flex;
          align-items:center;
          gap:7px;
          min-height:38px;
          padding:8px 10px;
          color:#d4af37;
          font-size:11px;
          font-weight:800;
          background:rgba(128,128,128,.04);
        }
        .hazard-group > summary::-webkit-details-marker { display:none; }
        .hazard-group > summary::before {
          content:"▸";
          flex:0 0 auto;
          opacity:.7;
          transition:transform .12s ease;
        }
        .hazard-group[open] > summary::before { transform:rotate(90deg); }
        .hazard-group-title { margin-right:auto; min-width:0; }
        .hazard-group-meta {
          flex:0 0 auto;
          font-size:9px;
          font-weight:600;
          color:var(--primary-text-color,#eee);
          opacity:.6;
        }
        .hazard-group-body {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));
          gap:7px;
          align-items:start;
          padding:8px;
        }
        .hazard-feed {
          min-width:0;
          border:1px solid color-mix(in srgb,#d4af37 38%,var(--divider-color,#555));
          border-radius:10px;
          padding:0;
          margin:0;
          overflow:hidden;
          background:color-mix(in srgb,#d4af37 4%,transparent);
        }
        .hazard-feed.hazard-feed-open { grid-column:1 / -1; }
        .hazard-feed.hazard-feed-has-events {
          border-color:color-mix(in srgb,#d4af37 62%,var(--divider-color,#555));
        }
        .hazard-feed-body {
          padding:0 9px 9px;
          border-top:1px solid color-mix(in srgb,var(--divider-color,#555) 58%,transparent);
        }
        .hazard-feed-body[hidden] { display:none !important; }
        .hazard-feed-head {
          display:grid;
          grid-template-columns:auto minmax(0,1fr) auto auto;
          align-items:center;
          gap:6px;
          min-height:42px;
          padding:5px 7px;
        }
        .hazard-feed-expand {
          width:30px;
          min-width:30px;
          height:30px;
          padding:0;
          display:grid;
          place-items:center;
          border:0;
          background:transparent;
          opacity:.68;
          transition:transform .12s ease;
        }
        .hazard-feed-expand[aria-expanded="true"] { transform:rotate(90deg); }
        .hazard-feed-summary {
          display:flex;
          min-width:0;
          flex-direction:column;
          gap:2px;
        }
        .hazard-feed-summary-meta {
          font-size:9px;
          line-height:1.25;
          opacity:.62;
        }
        .hazard-feed-actions {
          display:flex;
          gap:5px;
          align-items:center;
        }
        .hazard-feed-toggle {
          display:flex;
          align-items:center;
          gap:7px;
          margin:0;
          padding:2px 0;
          min-height:28px;
          flex:1 1 auto;
          min-width:0;
          opacity:1;
          font-weight:750;
          cursor:pointer;
          user-select:none;
          touch-action:manipulation;
        }
        .hazard-feed-toggle input {
          width:18px;
          height:18px;
          min-width:18px;
          min-height:18px;
          margin:0;
          accent-color:var(--primary-color,#03a9f4);
          cursor:pointer;
          touch-action:manipulation;
        }
        .hazard-feed-region {
          margin:7px 0 0;
          color:#d4af37;
          font-size:10px;
          line-height:1.35;
        }
        .hazard-feed-status {
          margin:5px 0 0;
          font-size:11px;
          line-height:1.4;
          opacity:.76;
        }
        .hazard-feed-events {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));
          gap:6px;
          margin:8px 0 0;
          align-items:start;
        }
        .hazard-event {
          min-width:0;
          border:1px solid color-mix(in srgb,#d4af37 38%,var(--divider-color,#555));
          border-left:3px solid #d4af37;
          border-radius:7px;
          padding:6px 7px;
          background:rgba(128,128,128,.055);
          font-size:10px;
          line-height:1.35;
        }
        .hazard-event-head {
          display:flex;
          align-items:flex-start;
          gap:7px;
        }
        .hazard-event strong {
          display:block;
          flex:1 1 auto;
          min-width:0;
          font-size:11px;
        }
        .hazard-event small { display:block; opacity:.65; margin-top:2px; }
        .hazard-event-meta {
          display:flex;
          flex-wrap:wrap;
          gap:4px 8px;
          margin-top:4px;
          font-size:10px;
          opacity:.78;
        }
        .hazard-event-near {
          border-left-color:#ffb300;
          background:color-mix(in srgb,#ffb300 8%,rgba(128,128,128,.055));
        }
        .hazard-proximity {
          margin:5px 0 0;
          padding:5px 7px;
          border:1px solid color-mix(in srgb,#ffb300 52%,transparent);
          border-radius:8px;
          background:color-mix(in srgb,#ffb300 8%,transparent);
          color:#ffca28;
          font-size:10px;
          line-height:1.35;
        }
        .hazard-proximity-controls {
          display:grid;
          grid-template-columns:minmax(0,1fr) minmax(110px,145px);
          gap:8px;
          align-items:end;
          margin:0 0 10px;
          padding:8px;
          border:1px solid color-mix(in srgb,#d4af37 28%,var(--divider-color,#555));
          border-radius:9px;
          background:rgba(128,128,128,.035);
        }
        .hazard-proximity-controls label {
          margin:0;
          font-size:10px;
          opacity:.72;
        }
        .hazard-proximity-controls select {
          min-height:34px;
          padding:5px 7px;
        }
        .hazard-proximity-note {
          grid-column:1 / -1;
          margin:0;
          font-size:9px;
          line-height:1.35;
          opacity:.62;
        }
        .hazard-event-focus {
          flex:0 0 auto;
          width:36px;
          height:36px;
          padding:0;
          border:0;
          border-radius:10px;
          background:transparent;
          line-height:0;
          cursor:pointer;
          touch-action:manipulation;
        }
        .hazard-event-focus img {
          display:block;
          width:36px;
          height:36px;
          pointer-events:none;
        }
        .hazard-event-focus:hover img,
        .hazard-event-focus:focus-visible img {
          filter:brightness(1.08);
        }
        .hazard-event-focus:focus-visible {
          outline:1px solid #62B9FF;
          outline-offset:1px;
        }
        .hazard-feed-refresh { min-width:32px; min-height:32px; padding:4px 7px; touch-action:manipulation; }
        .hazard-feed-note { margin:0 0 8px; font-size:11px; opacity:.68; line-height:1.4; }
        @media(max-width:620px) {
          .hazard-overview,
          .hazard-filter-controls,
          .hazard-group-body,
          .hazard-feed-events { grid-template-columns:1fr; }
          .hazard-feed-head { grid-template-columns:auto minmax(0,1fr) auto; }
          .hazard-feed-summary-meta { grid-column:2; }
        }
      `;
      root.appendChild(style);
    }

    if (root.getElementById("hazard-feed-list")) return;
    const weatherMenu = root.querySelector('[data-lab-menu-key="weather-layers"]');
    if (!weatherMenu) return;

    const menu = document.createElement("details");
    menu.className = "card lab-menu";
    menu.dataset.labMenuKey = "hazards";
    menu.innerHTML = `
      <summary>3 · Gefahren & Warnungen</summary>
      <div class="lab-menu-content">
        <p class="hazard-feed-note">
          Amtliche Warnungen und Ereignisse. Beim Einschalten werden alle vom Provider
          gelieferten Ereignisse seiner Abdeckung geladen – unabhängig vom aktuellen
          Kartenausschnitt. Keine Hintergrundabfrage nur durch Registrierung eines Providers.
        </p>
        <div id="hazard-overview" class="hazard-overview"></div>
        <div class="hazard-filter-controls">
          <label>
            Anzeige
            <select id="hazard-view-filter">
              <option value="all">Alle Feeds</option>
              <option value="active">Nur aktive Feeds</option>
              <option value="events">Nur Feeds mit Ereignissen</option>
              <option value="errors">Nur Feeds mit Fehlern</option>
            </select>
          </label>
          <label>
            Gruppe
            <select id="hazard-group-filter">
              <option value="all">Alle Gruppen</option>
            </select>
          </label>
        </div>
        <div class="hazard-proximity-controls">
          <label for="hazard-proximity-threshold">Nähehinweis zum Bezugsstandort</label>
          <select id="hazard-proximity-threshold">
            <option value="0">Aus</option>
            <option value="25">bis 25 km</option>
            <option value="50">bis 50 km</option>
            <option value="100">bis 100 km</option>
            <option value="250">bis 250 km</option>
            <option value="500">bis 500 km</option>
          </select>
          <p class="hazard-proximity-note">
            Rein informativer WeatherRouter-Hinweis für Punkt-Ereignisse – keine amtliche Warnung.
          </p>
        </div>
        <div id="hazard-feed-list" class="hazard-group-list muted" style="font-size:12px">
          Lade verfügbare Gefahrenfeeds …
        </div>
      </div>
    `;
    weatherMenu.after(menu);

    const solar = root.querySelector('[data-lab-menu-key="solar-media"] > summary');
    const diagnostic = root.querySelector('[data-lab-menu-key="diagnostic-matrix"] > summary');
    const results = root.querySelector('[data-lab-menu-key="results"] > summary');
    if (solar) solar.textContent = "4 · Sonne & Weltraum";
    if (diagnostic) diagnostic.textContent = "5 · Diagnose-Matrix";
    if (results) results.textContent = "6 · Ergebnisse";

    let stored = {};
    try {
      stored = JSON.parse(localStorage.getItem(HAZARD_MENU_STATE_KEY) || "{}");
    } catch (_error) {
      stored = {};
    }
    if (Object.prototype.hasOwnProperty.call(stored, "hazards")) {
      menu.open = Boolean(stored.hazards);
    }

    let storedView = {};
    try {
      storedView = JSON.parse(localStorage.getItem(HAZARD_VIEW_FILTER_KEY) || "{}");
    } catch (_error) {
      storedView = {};
    }
    this._hazardViewFilter = ["all", "active", "events", "errors"].includes(storedView.view)
      ? storedView.view
      : "all";
    this._hazardGroupFilter = typeof storedView.group === "string"
      ? storedView.group
      : "all";

    const persistView = () => {
      try {
        localStorage.setItem(HAZARD_VIEW_FILTER_KEY, JSON.stringify({
          view: this._hazardViewFilter || "all",
          group: this._hazardGroupFilter || "all",
        }));
      } catch (_error) {
        // Filter bleiben auch ohne Browserpersistenz nutzbar.
      }
    };

    const viewFilter = root.getElementById("hazard-view-filter");
    if (viewFilter) {
      viewFilter.value = this._hazardViewFilter;
      viewFilter.addEventListener("change", () => {
        this._hazardViewFilter = viewFilter.value;
        persistView();
        this._hazardRender();
      });
    }

    const groupFilter = root.getElementById("hazard-group-filter");
    if (groupFilter) {
      groupFilter.addEventListener("change", () => {
        this._hazardGroupFilter = groupFilter.value;
        persistView();
        this._hazardRender();
      });
    }

    const proximitySelect = root.getElementById("hazard-proximity-threshold");
    if (proximitySelect) {
      const configured = Number(localStorage.getItem(HAZARD_PROXIMITY_KEY));
      const threshold = [0, 25, 50, 100, 250, 500].includes(configured)
        ? configured
        : HAZARD_PROXIMITY_DEFAULT_KM;
      proximitySelect.value = String(threshold);
      proximitySelect.addEventListener("change", () => {
        const next = Number(proximitySelect.value);
        localStorage.setItem(HAZARD_PROXIMITY_KEY, String(next));
        this._hazardRender();
        this._wrLog?.("hazard_proximity_threshold_changed", {
          threshold_km: next,
        });
      });
    }

    menu.addEventListener("toggle", () => {
      let current = {};
      try {
        current = JSON.parse(localStorage.getItem(HAZARD_MENU_STATE_KEY) || "{}");
      } catch (_error) {
        current = {};
      }
      current.hazards = menu.open;
      localStorage.setItem(HAZARD_MENU_STATE_KEY, JSON.stringify(current));
      this._wrLog?.("lab_menu_toggle", {
        menu: "hazards",
        open: menu.open,
      });
    });
  };

  proto._hazardSyncStates = function() {
    const states = this._hazardStates();
    const valid = new Set();

    for (const provider of this._providers || []) {
      if (provider.eligible === false) continue;
      for (const capability of provider.capabilities || []) {
        if (
          capability.render_mode !== "hazard_feed"
          || capability.eligible === false
        ) continue;
        const key = `${provider.id}/${capability.id}`;
        valid.add(key);
        if (!states.has(key)) {
          states.set(key, {
            key,
            provider: provider.id,
            providerName: provider.name,
            capability: capability.id,
            capabilityName: capability.name,
            coverage: capability.coverage || null,
            enabled: false,
            loading: false,
            error: null,
            feed: null,
          });
        }
      }
    }

    for (const [key, state] of states) {
      if (valid.has(key)) continue;
      this._hazardRemoveFromMap(state);
      states.delete(key);
    }
  };

  proto._hazardLayerIds = function(state) {
    const safe = this._safeId(state.key);
    return {
      source: `hazard-source-${safe}`,
      fill: `hazard-fill-${safe}`,
      line: `hazard-line-${safe}`,
      point: `hazard-point-${safe}`,
    };
  };

  proto._hazardRemoveFromMap = function(state) {
    if (!this._map) return;
    const ids = this._hazardLayerIds(state);
    for (const id of [ids.point, ids.line, ids.fill]) {
      if (this._map.getLayer(id)) this._map.removeLayer(id);
    }
    if (this._map.getSource(ids.source)) this._map.removeSource(ids.source);
  };

  proto._hazardGeoJSON = function(state) {
    const events = Array.isArray(state.feed?.events) ? state.feed.events : [];
    return {
      type: "FeatureCollection",
      features: events
        .filter(item => item?.geometry && typeof item.geometry === "object")
        .map(item => ({
          type: "Feature",
          id: item.id || undefined,
          geometry: item.geometry,
          properties: {
            id: item.id || "",
            hazard_type: item.hazard_type || "weather_warning",
            event: item.event || "",
            headline: item.headline || item.event || "Warnung",
            severity: item.severity || "unknown",
            expires: item.expires || "",
            provider: state.providerName,
          },
        })),
    };
  };

  proto._hazardApplyToMap = function(state) {
    if (!this._map || !this._map.isStyleLoaded() || !state.enabled || !state.feed) return;
    const ids = this._hazardLayerIds(state);
    const data = this._hazardGeoJSON(state);

    if (this._map.getSource(ids.source)) {
      this._map.getSource(ids.source).setData(data);
      return;
    }

    this._map.addSource(ids.source, {
      type: "geojson",
      data,
      attribution: state.feed.attribution || state.providerName,
    });

    const severityColor = [
      "match",
      ["get", "severity"],
      "extreme", "#aa00aa",
      "severe", "#d32f2f",
      "moderate", "#f57c00",
      "minor", "#fbc02d",
      "#d4af37",
    ];

    this._map.addLayer({
      id: ids.fill,
      type: "fill",
      source: ids.source,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: {
        "fill-color": severityColor,
        "fill-opacity": 0.22,
      },
    });
    this._map.addLayer({
      id: ids.line,
      type: "line",
      source: ids.source,
      filter: ["==", ["geometry-type"], "Polygon"],
      paint: {
        "line-color": severityColor,
        "line-width": 2,
        "line-opacity": 0.9,
      },
    });
    this._map.addLayer({
      id: ids.point,
      type: "circle",
      source: ids.source,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": 6,
        "circle-color": severityColor,
        "circle-stroke-width": 2,
        "circle-stroke-color": "#111",
        "circle-opacity": 0.92,
      },
    });
  };

  proto._hazardLoad = async function(state) {
    if (!this._hass || state.loading) return;
    state.loading = true;
    state.error = null;
    this._hazardRender();
    this._wrLog?.("hazard_feed_load_start", {}, "info", state);

    try {
      const request = {
        type: "weather_router/hazard_feed",
        provider: state.provider,
        capability: state.capability,
        // Hazard feeds are provider-scoped, not viewport-scoped. This avoids
        // fragile world-wrap bboxes and ensures global feeds really show all
        // available events regardless of the current map position.
        limit: 1000,
      };

      const response = await this._hass.callWS(request);
      state.feed = response?.feed || null;
      if (!state.feed || !Array.isArray(state.feed.events)) {
        throw new Error("ungültiger Gefahrenfeed");
      }
      this._hazardApplyToMap(state);
      this._wrLog?.("hazard_feed_loaded", {
        event_count: state.feed.event_count ?? state.feed.events.length,
        hazard_types: [...new Set(
          state.feed.events.map(item => item?.hazard_type).filter(Boolean)
        )],
      }, "info", state);
    } catch (error) {
      state.error = error?.message || String(error);
      state.enabled = false;
      this._hazardRemoveFromMap(state);
      this._wrLog?.("hazard_feed_load_failed", { error }, "error", state);
    } finally {
      state.loading = false;
      this._hazardRender();
    }
  };

  proto._hazardIcon = function(type) {
    const icons = {
      tsunami: "🌊",
      tsunami_potential: "🌊?",
      earthquake: "🌎",
      volcanic_activity: "🌋",
      tornado: "🌪️",
      waterspout: "🌪️",
      tropical_cyclone: "🌀",
      severe_thunderstorm: "⛈️",
      supercell: "⛈️",
      downburst: "💨",
      hail: "🌨️",
      windstorm: "💨",
      storm_surge: "🌊",
      flash_flood: "🌊",
      surface_water_flood: "🌧️",
      flood: "🌊",
      debris_flow: "🪨",
      levee_failure: "🧱",
      dam_failure: "🏗️",
      glacial_lake_outburst_flood: "🏔️",
      ice_jam_flood: "🧊",
      heavy_rain: "🌧️",
      lightning: "⚡",
      wildfire: "🔥",
      avalanche: "🏔️",
      civil_protection: "🛡️",
      public_safety: "🚨",
      explosive_ordnance: "💣",
      fire: "🔥",
      infrastructure_outage: "⚡",
      contamination: "☣️",
      cbrn: "☢️",
      evacuation: "🚨",
      seismic_explosion: "💥",
      seismic_non_earthquake: "📈",
      collapse: "🏚️",
      landslide: "⛰️",
      meteor: "☄️",
      acoustic_event: "🔊",
      drought: "☀️",
      natural_hazard: "⚠️",
      volcanic_ash: "🌋",
      aviation_icing: "🧊",
      aviation_turbulence: "✈️",
      mountain_wave: "〰️",
      dust_storm: "🌫️",
      aviation_ifr: "✈️",
      aviation_warning: "✈️",
    };
    return icons[type] || "⚠️";
  };

  proto._hazardTaxonomyLabel = function(type) {
    const labels = {
      severe_thunderstorm: "Naturgefahren › Unwetter / Konvektive Gefahren › Gewitter",
      tornado: "Naturgefahren › Unwetter / Konvektive Gefahren › Tornado / Windhose",
      waterspout: "Naturgefahren › Unwetter / Konvektive Gefahren › Tornado / Windhose",
      hail: "Naturgefahren › Unwetter / Konvektive Gefahren › Hagel",
      lightning: "Naturgefahren › Unwetter / Konvektive Gefahren › Gewitter",
      downburst: "Naturgefahren › Unwetter / Konvektive Gefahren › Starkwind / Downburst",
      supercell: "Naturgefahren › Unwetter / Konvektive Gefahren › Superzelle",
    };
    return labels[type] || type || "weather_warning";
  };

  proto._hazardStatusText = function(state) {
    if (state.loading) return "Amtliche Daten werden geladen …";
    if (state.error) return `Fehler: ${state.error}`;
    if (!state.enabled) return "Aus";
    if (!state.feed) return "Bereit";
    const count = Number(state.feed.event_count ?? state.feed.events?.length ?? 0);
    return `Aktiv · ${count} Ereignis${count === 1 ? "" : "se"}`;
  };

  proto._hazardBindEvents = function(host) {
    if (!host || host.__weatherRouterHazardEventsBound) return;
    host.__weatherRouterHazardEventsBound = true;

    host.addEventListener("change", event => {
      const toggle = event.target?.closest?.("[data-hazard-toggle]");
      if (!toggle) return;
      const state = this._hazardStates().get(toggle.dataset.hazardToggle);
      if (!state || state.loading) return;

      state.enabled = Boolean(toggle.checked);
      state.error = null;
      this._wrLog?.("hazard_feed_toggle", { enabled: state.enabled }, "info", state);

      if (state.enabled) {
        void this._hazardLoad(state);
      } else {
        this._hazardRemoveFromMap(state);
        this._hazardRender();
      }
    });

    host.addEventListener("click", event => {
      const expand = event.target?.closest?.("[data-hazard-expand]");
      if (expand) {
        const card = expand.closest(".hazard-feed");
        const body = card?.querySelector(".hazard-feed-body");
        if (!card || !body) return;
        const nextOpen = body.hasAttribute("hidden");
        body.toggleAttribute("hidden", !nextOpen);
        card.classList.toggle("hazard-feed-open", nextOpen);
        expand.setAttribute("aria-expanded", nextOpen ? "true" : "false");
        try {
          const current = JSON.parse(localStorage.getItem(HAZARD_MENU_STATE_KEY) || "{}");
          current[`hazard-feed:${expand.dataset.hazardExpand}`] = nextOpen;
          localStorage.setItem(HAZARD_MENU_STATE_KEY, JSON.stringify(current));
        } catch (_error) {
          // Feed bleibt auch ohne Browserpersistenz bedienbar.
        }
        return;
      }

      const refresh = event.target?.closest?.("[data-hazard-refresh]");
      if (refresh) {
        event.preventDefault();
        event.stopPropagation();
        const state = this._hazardStates().get(refresh.dataset.hazardRefresh);
        if (!state || state.loading) return;
        state.enabled = true;
        void this._hazardLoad(state);
        return;
      }

      const focus = event.target?.closest?.("[data-hazard-focus]");
      if (focus) {
        const state = this._hazardStates().get(focus.dataset.hazardFocus);
        const eventIndex = Number.parseInt(focus.dataset.hazardEventIndex || "", 10);
        if (state && Number.isInteger(eventIndex)) {
          this._hazardFocusEvent(state, eventIndex);
        }
        return;
      }

      const info = event.target?.closest?.("[data-hazard-info]");
      if (info) {
        event.preventDefault();
        event.stopPropagation();
        this._providerInfoOpen?.(info.dataset.hazardInfo);
      }
    });
  };

  proto._hazardProximityThresholdKm = function() {
    const configured = Number(localStorage.getItem(HAZARD_PROXIMITY_KEY));
    return [0, 25, 50, 100, 250, 500].includes(configured)
      ? configured
      : HAZARD_PROXIMITY_DEFAULT_KM;
  };

  proto._hazardPointCoordinates = function(item) {
    const geometry = item?.geometry;
    if (!geometry || geometry.type !== "Point" || !Array.isArray(geometry.coordinates)) {
      return null;
    }
    const longitude = Number(geometry.coordinates[0]);
    const latitude = Number(geometry.coordinates[1]);
    if (
      !Number.isFinite(latitude) || !Number.isFinite(longitude)
      || latitude < -90 || latitude > 90
      || longitude < -180 || longitude > 180
    ) {
      return null;
    }
    return { latitude, longitude };
  };

  proto._hazardDistanceKm = function(point, reference=this._currentPoint?.()) {
    if (!point || !reference) return null;
    const toRad = value => Number(value) * Math.PI / 180;
    const lat1 = toRad(reference.latitude);
    const lat2 = toRad(point.latitude);
    const deltaLat = lat2 - lat1;
    const deltaLon = toRad(point.longitude - reference.longitude);
    const a = (
      Math.sin(deltaLat / 2) ** 2
      + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2
    );
    const clamped = Math.min(1, Math.max(0, a));
    return 6371.0088 * 2 * Math.atan2(Math.sqrt(clamped), Math.sqrt(1 - clamped));
  };

  proto._hazardEventGeoMeta = function(item) {
    const point = this._hazardPointCoordinates(item);
    if (!point) return {
      point: null,
      distanceKm: null,
      isNear: false,
      coordinateText: null,
    };

    const distanceKm = this._hazardDistanceKm(point);
    const thresholdKm = this._hazardProximityThresholdKm();
    return {
      point,
      distanceKm,
      isNear: (
        thresholdKm > 0
        && Number.isFinite(distanceKm)
        && distanceKm <= thresholdKm
      ),
      coordinateText: `${point.latitude.toFixed(5)}°, ${point.longitude.toFixed(5)}°`,
    };
  };

  proto._hazardEventCount = function(state) {
    if (!state?.enabled || !state.feed) return 0;
    return Number(state.feed.event_count ?? state.feed.events?.length ?? 0) || 0;
  };

  proto._hazardGroupMeta = function(state) {
    const text = [
      state?.provider,
      state?.providerName,
      state?.capability,
      state?.capabilityName,
    ].filter(Boolean).join(" ").toLowerCase();

    if (/aviation|sigmet|airmet|luftfahrt/.test(text)) {
      return { id: "aviation", label: "Luftfahrtwarnungen", order: 60 };
    }
    if (/tropical|cyclone|hurricane|wirbelsturm|nhc/.test(text)) {
      return { id: "tropical", label: "Tropische Systeme", order: 20 };
    }
    if (/tsunami/.test(text)) {
      return { id: "tsunami", label: "Tsunami & Küste", order: 30 };
    }
    if (/flood|hochwas|storm.?surge|coastal|hydrolog|debris|mud|mure|deich|levee|dam|damm|glof|ice.?jam|eisstau/.test(text)) {
      return { id: "hydrology", label: "Hochwasser & Hydrologie", order: 40 };
    }
    if (/earthquake|erdbeben|seismic|seism|volcan|vulkan/.test(text)) {
      return { id: "geophysical", label: "Erdbeben & Vulkanismus", order: 50 };
    }
    if (/civil|bevölkerung|mowas|katwarn|biwapp|polizei|public.?safety|bbk|nina/.test(text)) {
      return { id: "civil", label: "Bevölkerungsschutz & Sicherheit", order: 55 };
    }
    if (/weather|wetterwarn|dwd|nws|warning|warnung/.test(text)) {
      return { id: "official", label: "Amtliche Wetterwarnungen", order: 10 };
    }
    return { id: "other", label: "Weitere Gefahrenfeeds", order: 70 };
  };

  proto._hazardRelevance = function(state) {
    const count = this._hazardEventCount(state);
    if (state?.enabled && count > 0) return 4;
    if (state?.enabled && state?.loading) return 3;
    if (state?.enabled) return 2;
    if (state?.error) return 1;
    return 0;
  };

  proto._hazardOpenPreference = function(key, fallback=false) {
    try {
      const stored = JSON.parse(localStorage.getItem(HAZARD_MENU_STATE_KEY) || "{}");
      if (Object.prototype.hasOwnProperty.call(stored, key)) return Boolean(stored[key]);
    } catch (_error) {
      // Fallback verwenden.
    }
    return fallback;
  };

  proto._hazardPersistOpen = function(key, value) {
    try {
      const stored = JSON.parse(localStorage.getItem(HAZARD_MENU_STATE_KEY) || "{}");
      stored[key] = Boolean(value);
      localStorage.setItem(HAZARD_MENU_STATE_KEY, JSON.stringify(stored));
    } catch (_error) {
      // Offen-/Zu-Zustand bleibt trotzdem im aktuellen DOM erhalten.
    }
  };

  proto._hazardDisplayEvents = function(state) {
    const source = Array.isArray(state.feed?.events) ? state.feed.events : [];
    const enriched = source.map((item, index) => ({
      item,
      index,
      meta: this._hazardEventGeoMeta(item),
    }));
    return enriched
      .sort((a, b) => {
        if (a.meta.isNear !== b.meta.isNear) return a.meta.isNear ? -1 : 1;
        if (a.meta.isNear && b.meta.isNear) {
          return (a.meta.distanceKm ?? Infinity) - (b.meta.distanceKm ?? Infinity);
        }
        return a.index - b.index;
      })
      .slice(0, 12);
  };

  proto._hazardNearbySummary = function(state) {
    const thresholdKm = this._hazardProximityThresholdKm();
    if (thresholdKm <= 0) return null;
    const events = Array.isArray(state.feed?.events) ? state.feed.events : [];
    const nearby = events
      .map(item => this._hazardEventGeoMeta(item))
      .filter(meta => meta.isNear);
    if (!nearby.length) return null;
    const nearest = Math.min(...nearby.map(meta => meta.distanceKm));
    return {
      count: nearby.length,
      thresholdKm,
      nearestKm: nearest,
    };
  };

  proto._hazardGeometryPoints = function(geometry) {
    const points = [];
    const visit = value => {
      if (!Array.isArray(value)) return;
      if (
        value.length >= 2
        && Number.isFinite(Number(value[0]))
        && Number.isFinite(Number(value[1]))
      ) {
        const longitude = Number(value[0]);
        const latitude = Number(value[1]);
        if (
          longitude >= -180 && longitude <= 180
          && latitude >= -90 && latitude <= 90
        ) {
          points.push([longitude, latitude]);
        }
        return;
      }
      for (const child of value) visit(child);
    };
    visit(geometry?.coordinates);
    return points;
  };

  proto._hazardFocusEvent = function(state, eventIndex) {
    if (!this._map || !state?.feed?.events) return;
    const item = state.feed.events[eventIndex];
    const geometry = item?.geometry;
    if (!geometry || typeof geometry !== "object") return;

    const points = this._hazardGeometryPoints(geometry);
    if (!points.length) return;

    if (geometry.type === "Point") {
      const [longitude, latitude] = points[0];
      const currentZoom = Number(this._map.getZoom?.() ?? 0);
      const zoom = Math.max(6.5, Math.min(currentZoom, 9));
      this._map.easeTo({
        center: [longitude, latitude],
        zoom,
        duration: 850,
        essential: true,
      });
    } else {
      let west = points[0][0];
      let east = points[0][0];
      let south = points[0][1];
      let north = points[0][1];
      for (const [longitude, latitude] of points.slice(1)) {
        west = Math.min(west, longitude);
        east = Math.max(east, longitude);
        south = Math.min(south, latitude);
        north = Math.max(north, latitude);
      }

      if (west === east && south === north) {
        this._map.easeTo({
          center: [west, south],
          zoom: 7,
          duration: 850,
          essential: true,
        });
      } else {
        this._map.fitBounds(
          [[west, south], [east, north]],
          {
            padding: 64,
            maxZoom: 8,
            duration: 850,
            essential: true,
          },
        );
      }
    }

    this._wrLog?.("hazard_event_focus", {
      event_id: item.id || null,
      geometry_type: geometry.type || null,
    }, "info", state);
  };

  proto._hazardRender = function() {
    const root = this.shadowRoot;
    const host = root?.getElementById("hazard-feed-list");
    if (!host) return;

    const states = [...this._hazardStates().values()];
    const overview = root?.getElementById("hazard-overview");
    const viewFilter = root?.getElementById("hazard-view-filter");
    const groupFilter = root?.getElementById("hazard-group-filter");

    if (!states.length) {
      if (overview) overview.innerHTML = "";
      host.className = "muted";
      host.textContent = "Noch keine Gefahrenfeeds verfügbar.";
      return;
    }

    const activeFeeds = states.filter(state => state.enabled).length;
    const feedsWithEvents = states.filter(state => this._hazardEventCount(state) > 0).length;
    const totalEvents = states.reduce((sum, state) => sum + this._hazardEventCount(state), 0);
    const errorFeeds = states.filter(state => state.error).length;

    if (overview) {
      const markup = `
        <div class="hazard-overview-card"><small>Feeds</small><strong>${activeFeeds}/${states.length} aktiv</strong></div>
        <div class="hazard-overview-card"><small>Mit Ereignissen</small><strong>${feedsWithEvents} Feeds</strong></div>
        <div class="hazard-overview-card"><small>Ereignisse</small><strong>${totalEvents} aktiv</strong></div>
        <div class="hazard-overview-card"><small>Status</small><strong>${errorFeeds ? `${errorFeeds} Fehler` : "ohne Fehler"}</strong></div>
      `;
      if (overview.innerHTML !== markup) overview.innerHTML = markup;
    }

    const groupMetaById = new Map();
    for (const state of states) {
      const meta = this._hazardGroupMeta(state);
      groupMetaById.set(meta.id, meta);
    }
    const groupOptions = [
      '<option value="all">Alle Gruppen</option>',
      ...[...groupMetaById.values()]
        .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label, "de"))
        .map(meta => `<option value="${this._escape(meta.id)}">${this._escape(meta.label)}</option>`),
    ].join("");
    if (groupFilter && groupFilter.innerHTML !== groupOptions) {
      groupFilter.innerHTML = groupOptions;
    }

    this._hazardViewFilter = ["all", "active", "events", "errors"].includes(this._hazardViewFilter)
      ? this._hazardViewFilter
      : "all";
    if (!groupMetaById.has(this._hazardGroupFilter) && this._hazardGroupFilter !== "all") {
      this._hazardGroupFilter = "all";
    }
    if (viewFilter && viewFilter.value !== this._hazardViewFilter) {
      viewFilter.value = this._hazardViewFilter;
    }
    if (groupFilter && groupFilter.value !== this._hazardGroupFilter) {
      groupFilter.value = this._hazardGroupFilter;
    }

    let visibleStates = states.filter(state => {
      const count = this._hazardEventCount(state);
      if (this._hazardViewFilter === "active" && !state.enabled) return false;
      if (this._hazardViewFilter === "events" && count <= 0) return false;
      if (this._hazardViewFilter === "errors" && !state.error) return false;
      const group = this._hazardGroupMeta(state);
      return this._hazardGroupFilter === "all" || group.id === this._hazardGroupFilter;
    });

    visibleStates = visibleStates.sort((a, b) => (
      this._hazardRelevance(b) - this._hazardRelevance(a)
      || this._hazardGroupMeta(a).order - this._hazardGroupMeta(b).order
      || String(a.capabilityName).localeCompare(String(b.capabilityName), "de")
    ));

    host.className = "hazard-group-list";
    this._hazardBindEvents(host);

    if (!visibleStates.length) {
      host.innerHTML = '<div class="muted" style="font-size:11px">Für diese Filterauswahl sind keine Gefahrenfeeds sichtbar.</div>';
      return;
    }

    const grouped = new Map();
    for (const state of visibleStates) {
      const meta = this._hazardGroupMeta(state);
      if (!grouped.has(meta.id)) grouped.set(meta.id, { meta, states: [] });
      grouped.get(meta.id).states.push(state);
    }

    const groups = [...grouped.values()].sort((a, b) => {
      const aScore = Math.max(...a.states.map(state => this._hazardRelevance(state)));
      const bScore = Math.max(...b.states.map(state => this._hazardRelevance(state)));
      return bScore - aScore || a.meta.order - b.meta.order;
    });

    const validCards = new Set();
    const validGroups = new Set();

    for (const { meta, states: groupStates } of groups) {
      const groupId = `hazard-group-${meta.id}`;
      validGroups.add(groupId);
      let group = host.querySelector(`#${groupId}`);
      if (!group) {
        group = document.createElement("details");
        group.id = groupId;
        group.className = "hazard-group";
        group.innerHTML = '<summary></summary><div class="hazard-group-body"></div>';
        host.appendChild(group);
        group.addEventListener("toggle", () => {
          this._hazardPersistOpen(`hazard-group:${meta.id}`, group.open);
        });
      }

      const groupActive = groupStates.filter(state => state.enabled).length;
      const groupEventFeeds = groupStates.filter(state => this._hazardEventCount(state) > 0).length;
      const groupEvents = groupStates.reduce((sum, state) => sum + this._hazardEventCount(state), 0);
      const summaryMarkup = `
        <span class="hazard-group-title">${this._escape(meta.label)}</span>
        <span class="hazard-group-meta">${groupActive}/${groupStates.length} aktiv · ${groupEventFeeds} mit Ereignissen · ${groupEvents} Ereignisse</span>
      `;
      const summary = group.querySelector("summary");
      if (summary.innerHTML !== summaryMarkup) summary.innerHTML = summaryMarkup;

      const defaultGroupOpen = groupEventFeeds > 0;
      const desiredGroupOpen = this._hazardOpenPreference(
        `hazard-group:${meta.id}`,
        defaultGroupOpen,
      );
      if (group.open !== desiredGroupOpen) group.open = desiredGroupOpen;

      const body = group.querySelector(".hazard-group-body");

      for (const state of groupStates) {
      const safe = this._safeId(state.key);
      const cardId = `hazard-card-${safe}`;
      validCards.add(cardId);

      let box = host.querySelector(`#${cardId}`);
      if (!box) {
        box = document.createElement("div");
        box.id = cardId;
        box.className = "hazard-feed";
        host.appendChild(box);
      }

      const events = state.enabled ? this._hazardDisplayEvents(state) : [];
      const nearby = state.enabled ? this._hazardNearbySummary(state) : null;
      const totalCount = this._hazardEventCount(state);
      const feedOpen = this._hazardOpenPreference(
        `hazard-feed:${state.key}`,
        state.enabled && totalCount > 0,
      );
      box.classList.toggle("hazard-feed-open", feedOpen);
      box.classList.toggle("hazard-feed-has-events", totalCount > 0);
      const statusSummary = state.loading
        ? "lädt …"
        : state.error
          ? "Fehler"
          : state.enabled
            ? totalCount
              ? `aktiv · ${totalCount} Ereignis${totalCount === 1 ? "" : "se"}`
              : "aktiv · keine Ereignisse"
            : "aus";
      const markup = `
        <div class="hazard-feed-head">
          <button class="hazard-feed-expand" type="button"
            data-hazard-expand="${this._escape(state.key)}"
            aria-expanded="${feedOpen ? "true" : "false"}"
            title="${feedOpen ? "Details einklappen" : "Details aufklappen"}">▸</button>
          <div class="hazard-feed-summary">
            <label class="hazard-feed-toggle">
              <input type="checkbox"
                data-hazard-toggle="${this._escape(state.key)}"
                ${state.enabled ? "checked" : ""}
                ${state.loading ? "disabled" : ""}>
              <span>${this._escape(state.capabilityName)}</span>
            </label>
            <span class="hazard-feed-summary-meta">${this._escape(statusSummary)}</span>
          </div>
          <div class="hazard-feed-actions">
            <button class="weather-provider-info" type="button"
              data-hazard-info="${this._escape(state.provider)}"
              title="Informationen zu ${this._escape(state.providerName)}">i</button>
            <button class="hazard-feed-refresh"
              data-hazard-refresh="${this._escape(state.key)}"
              type="button" title="Gefahrenfeed aktualisieren"
              ${state.loading ? "disabled" : ""}>↻</button>
          </div>
        </div>
        <div class="hazard-feed-body" ${feedOpen ? "" : "hidden"}>
          ${state.coverage ? `<div class="hazard-feed-region">Region · ${this._escape(state.coverage)}</div>` : ""}
          <div class="hazard-feed-status ${state.error ? "error" : state.enabled && state.feed ? "ok" : ""}">
            ${this._escape(this._hazardStatusText(state))}
          </div>
          ${nearby ? `<div class="hazard-proximity">
            Nähehinweis · ${nearby.count} Ereignis${nearby.count === 1 ? "" : "se"} innerhalb
            ${nearby.thresholdKm} km · nächstes ${nearby.nearestKm.toFixed(1)} km
          </div>` : ""}
          ${events.length ? `
            <div class="hazard-feed-events">
            ${events.map(({ item, index: eventIndex, meta }) => `
              <div class="hazard-event ${meta.isNear ? "hazard-event-near" : ""}">
                <div class="hazard-event-head">
                  <strong>${this._escape(this._hazardIcon(item.hazard_type))} ${this._escape(item.headline || item.event || item.hazard_type || "Warnung")}</strong>
                  ${item?.geometry && typeof item.geometry === "object"
                    ? `<button class="hazard-event-focus" type="button"
                        data-hazard-focus="${this._escape(state.key)}"
                        data-hazard-event-index="${eventIndex}"
                        title="Ereignis auf der Karte anzeigen"
                        aria-label="Ereignis auf der Karte anzeigen">
                          <img src="${HAZARD_TARGET_SYMBOL_URL}" alt="">
                        </button>`
                    : ""}
                </div>
                <small>
                  ${this._escape(this._hazardTaxonomyLabel(item.hazard_type))}
                  · ${this._escape(item.parameters?.alert_level || item.severity || "unknown")}
                  · ${this._escape(item.severity || "unknown")}
                  ${item.area_desc ? ` · ${this._escape(item.area_desc)}` : ""}
                </small>
                ${meta.coordinateText ? `
                  <div class="hazard-event-meta">
                    <span>Koordinaten · ${this._escape(meta.coordinateText)}</span>
                    ${Number.isFinite(meta.distanceKm)
                      ? `<span>Entfernung · ${meta.distanceKm.toFixed(1)} km</span>`
                      : ""}
                    ${meta.isNear
                      ? `<span>⚑ Nähehinweis · zum Bezugsstandort</span>`
                      : ""}
                  </div>
                ` : ""}
              </div>
            `).join("")}
            ${totalCount > events.length
              ? `<div class="muted" style="font-size:10px">Karte enthält alle ${totalCount} Ereignisse; hier werden die ersten ${events.length} gezeigt.</div>`
              : ""}
            </div>
          ` : ""}
        </div>
      `;

      // Do not tear down controls of unrelated feeds while another request
      // completes. This prevents lost taps/clicks during parallel interaction.
      if (box.innerHTML !== markup) box.innerHTML = markup;

      const desiredIndex = groupStates.indexOf(state);
      const atIndex = body.children[desiredIndex];
      if (atIndex !== box) body.insertBefore(box, atIndex || null);
      }

      if (group.parentElement !== host) host.appendChild(group);
    }

    for (const card of [...host.querySelectorAll("[id^='hazard-card-']")]) {
      if (!validCards.has(card.id)) card.remove();
    }
    for (const group of [...host.querySelectorAll(".hazard-group")]) {
      if (!validGroups.has(group.id)) group.remove();
    }

    groups.forEach(({ meta }, index) => {
      const group = host.querySelector(`#hazard-group-${meta.id}`);
      if (!group) return;
      const atIndex = host.children[index];
      if (atIndex !== group) host.insertBefore(group, atIndex || null);
    });
  };

  proto._hazardRestore = function() {
    for (const state of this._hazardStates().values()) {
      if (state.enabled && state.feed) this._hazardApplyToMap(state);
    }
  };

  proto._renderShell = function(...args) {
    const result = previousRenderShell?.apply(this, args);
    this._hazardInstallUI();
    this._hazardRender();
    return result;
  };

  proto._ensureProviderCatalog = async function(...args) {
    const result = await previousEnsureProviderCatalog?.apply(this, args);
    this._hazardSyncStates();
    this._hazardRender();
    const signature = [...this._hazardStates().keys()].sort().join("|");
    if (signature !== this._hazardCatalogLogSignature) {
      this._hazardCatalogLogSignature = signature;
      this._wrLog?.("hazard_catalog_ready", {
        feed_count: this._hazardStates().size,
      });
    }
    return result;
  };

  proto._restoreWeatherLayers = function(...args) {
    const result = previousRestoreWeatherLayers?.apply(this, args);
    this._hazardRestore();
    return result;
  };

  if (typeof previousEventLogSnapshot === "function") {
    proto._wrEventLogSnapshot = function(...args) {
      const snapshot = previousEventLogSnapshot.apply(this, args);
      snapshot.hazards = [...this._hazardStates().values()]
        .filter(state => state.enabled || state.error || state.feed)
        .map(state => this._wrEventSanitize?.({
          provider: state.provider,
          provider_name: state.providerName,
          capability: state.capability,
          capability_name: state.capabilityName,
          enabled: state.enabled,
          loading: state.loading,
          error: state.error,
          event_count: state.feed?.event_count ?? state.feed?.events?.length ?? 0,
          hazard_types: [...new Set(
            (state.feed?.events || []).map(item => item?.hazard_type).filter(Boolean)
          )],
        }) || {});
      return snapshot;
    };
  }
}
