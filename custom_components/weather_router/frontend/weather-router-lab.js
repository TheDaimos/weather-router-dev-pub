import * as maplibregl from "https://unpkg.com/maplibre-gl@6.9.1/dist/maplibre-gl.mjs";

const SELECT_ENTITY = "select.weather_router_reference_location";
const MAPLIBRE_CSS = "https://unpkg.com/maplibre-gl@6.9.1/dist/maplibre-gl.css";
const WR_LAB_BUILD_VERSION = "0.10.159";
const LAB_MENU_STATE_KEY = "weather_router_lab_menu_state_v1";

const OPENFREEMAP_STYLES = {
  dark: "https://tiles.openfreemap.org/styles/dark",
  fiord: "https://tiles.openfreemap.org/styles/fiord",
  positron: "https://tiles.openfreemap.org/styles/positron",
};

const SCIENCE_STYLE = {
  version: 8,
  name: "WeatherRouter Science Fallback",
  sources: {},
  layers: [
    {
      id: "background",
      type: "background",
      paint: { "background-color": "#09111d" },
    },
  ],
};

const DEFAULT_REQUESTS = [
  { provider: "open_meteo", capability: "cloud_cover" },
  { provider: "open_meteo", capability: "cloud_cover_low" },
  { provider: "open_meteo", capability: "wind_speed" },
];

const DIAGNOSTIC_TEST_LOCATIONS = {
  "ha-reference": {
    label: "HA-Bezugsstandort verwenden",
    latitude: null,
    longitude: null,
  },
  "noaa-us-new-york": {
    label: "NOAA/NWS · New York City (USA)",
    latitude: 40.7128,
    longitude: -74.0060,
  },
  "met-nowcast-oslo": {
    label: "MET Nowcast · Oslo (Norwegen)",
    latitude: 59.9139,
    longitude: 10.7522,
  },
  "fmi-helsinki": {
    label: "FMI · Helsinki (Finnland)",
    latitude: 60.1699,
    longitude: 24.9384,
  },
  "smhi-stockholm": {
    label: "SMHI · Stockholm (Schweden)",
    latitude: 59.3293,
    longitude: 18.0686,
  },
  "eccc-toronto": {
    label: "ECCC/MSC · Toronto (Kanada)",
    latitude: 43.6532,
    longitude: -79.3832,
  },
  "jma-tokyo": {
    label: "JMA · Tokio (Japan)",
    latitude: 35.6762,
    longitude: 139.6503,
  },
};

class WeatherRouterLab extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._map = null;
    this._marker = null;
    this._lastReference = null;
    this._diagnosticTestLocation = "ha-reference";
    this._providers = [];
    this._requests = structuredClone(DEFAULT_REQUESTS);
    this._results = null;
    this._monitorSnapshot = null;
    this._monitorSelected = null;
    this._monitorTimer = null;
    this._loading = false;
    this._basemapProvider = "openfreemap";
    this._basemapStyle = "dark";
    this._weatherLayers = new Map();
    this._weatherLayerProviderFilter = "all";
    this._weatherLayerCapabilityFilter = "all";
    this._weatherLayerOnlyActive = false;
    this._mediaSequences = new Map();
    this._liveStreams = new Map();
    this._planetaryTiles = new Map();
    this._mediaVisibilityHandler = () => {
      if (document.hidden) this._stopMediaSequencePlayback("document_hidden");
    };
    this._renderShell();
  }

  set hass(value) {
    this._hass = value;
    this._syncFromHass();
    this._ensureProviderCatalog();
  }

  set panel(_value) {}
  set narrow(_value) {}
  set route(_value) {}

  connectedCallback() {
    document.addEventListener("visibilitychange", this._mediaVisibilityHandler);
    if (!this._monitorTimer) this._monitorTimer = setInterval(() => {
      if (!document.hidden && this.shadowRoot.querySelector('[data-lab-menu-key="api-monitor"]')?.open) this._monitorRefresh();
    }, 2500);
    queueMicrotask(() => this._ensureMap());
  }

  disconnectedCallback() {
    if (this._monitorTimer) clearInterval(this._monitorTimer);
    this._monitorTimer = null;
    document.removeEventListener("visibilitychange", this._mediaVisibilityHandler);
    this._stopAllMediaPlayback("disconnect");
    if (this._map) this._map.remove();
    this._map = null;
    this._marker = null;
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${MAPLIBRE_CSS}">
      <style>
        :host { display:block; height:100%; min-height:0; overflow:hidden; color:var(--primary-text-color,#eee); background:var(--primary-background-color,#111); font-family:system-ui,sans-serif; }
        * { box-sizing:border-box; }
        button, select, input { font:inherit; }
        .layout { display:grid; grid-template-columns:minmax(330px,430px) 1fr; height:100%; min-height:0; overflow:hidden; }
        .sidebar { height:100%; min-height:0; padding:18px; overflow-y:auto; overflow-x:hidden; overscroll-behavior:contain; scrollbar-gutter:stable; border-right:1px solid var(--divider-color,#444); background:var(--card-background-color,#1c1c1c); }
        h1 { margin:0; font-size:24px; }
        .subtitle { opacity:.65; margin:4px 0 14px; }
        .basemap-controls { display:grid; grid-template-columns:.8fr 1.15fr 1fr; gap:7px; margin-bottom:8px; }
        .basemap-control label { display:block; margin:0 0 4px; font-size:10px; opacity:.62; }
        .basemap-control select { min-height:34px; padding:6px 8px; }
        .engine-status { min-height:34px; display:flex; align-items:center; padding:6px 9px; border:1px solid var(--divider-color,#555); border-radius:8px; background:var(--secondary-background-color,#282828); color:var(--primary-text-color,#eee); font-size:14px; }
        .basemap-note { margin:0; font-size:10px; opacity:.62; line-height:1.35; }
        .card { border:1px solid var(--divider-color,#444); border-radius:12px; padding:13px; margin-bottom:12px; background:color-mix(in srgb,var(--card-background-color,#222) 95%,transparent); }
        .card h2 { font-size:15px; margin:0 0 10px; }
        .lab-menu { padding:0; overflow:hidden; }
        .lab-menu > summary {
          cursor:pointer;
          list-style:none;
          user-select:none;
          display:flex;
          align-items:center;
          gap:8px;
          min-height:44px;
          padding:12px 13px;
          font-size:15px;
          font-weight:750;
        }
        .lab-menu > summary::-webkit-details-marker { display:none; }
        .lab-menu > summary::before {
          content:"▸";
          display:inline-block;
          flex:0 0 auto;
          opacity:.65;
          transition:transform .12s ease;
        }
        .lab-menu[open] > summary::before { transform:rotate(90deg); }
        .lab-menu[open] > summary { border-bottom:1px solid color-mix(in srgb,var(--divider-color,#444) 72%,transparent); }
        .lab-menu-content { padding:12px 13px 13px; }
        .lab-menu-content > :first-child { margin-top:0; }
        .lab-menu-content > :last-child { margin-bottom:0; }
        label { display:block; font-size:12px; opacity:.72; margin-bottom:5px; }
        select, button { border:1px solid var(--divider-color,#555); border-radius:8px; background:var(--secondary-background-color,#282828); color:var(--primary-text-color,#eee); padding:8px; }
        select { width:100%; }
        select:disabled { opacity:.58; }
        button { cursor:pointer; }
        button.primary { background:var(--primary-color,#03a9f4); color:#fff; border-color:transparent; font-weight:650; }
        button:disabled { opacity:.45; cursor:not-allowed; }
        .weather-layer-toolbar { display:grid; grid-template-columns:1fr 1.25fr auto; gap:7px; align-items:end; margin:10px 0 8px; }
        .weather-layer-toolbar label { margin:0; }
        .weather-layer-toolbar .compact-check { display:flex; align-items:center; gap:6px; min-height:34px; padding:0 4px; white-space:nowrap; opacity:.8; }
        .weather-layer-toolbar .compact-check input { width:16px; height:16px; margin:0; accent-color:var(--primary-color,#03a9f4); }
        .weather-layer-count { margin:0 0 8px; font-size:10px; opacity:.58; }
        .weather-provider-grid {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));
          gap:8px;
          align-items:start;
          margin-top:8px;
        }
        .weather-provider-group { position:relative; min-width:0; border:1px solid color-mix(in srgb,var(--divider-color,#555) 72%,transparent); border-radius:10px; margin:0; overflow:hidden; background:rgba(128,128,128,.035); }
        .weather-provider-group[open] { grid-column:1 / -1; }
        .weather-provider-group > summary { cursor:pointer; padding:9px 44px 9px 10px; font-size:12px; font-weight:750; list-style:none; user-select:none; display:flex; justify-content:space-between; gap:10px; align-items:center; }
        .weather-provider-group > summary::-webkit-details-marker { display:none; }
        .weather-provider-group > summary::before { content:"▸"; display:inline-block; margin-right:6px; transition:transform .12s ease; opacity:.65; }
        .weather-provider-group[open] > summary::before { transform:rotate(90deg); }
        .weather-provider-group-meta { margin-left:auto; font-size:10px; opacity:.58; font-weight:500; }
        .weather-provider-info {
          color:#d4af37;
          border-color:color-mix(in srgb,#d4af37 72%,var(--divider-color,#555));
          background:color-mix(in srgb,#d4af37 12%,var(--secondary-background-color,#282828));
          font-weight:900; line-height:1; width:28px; min-width:28px; height:28px; padding:0;
          border-radius:50%; display:inline-flex; align-items:center; justify-content:center;
        }
        .weather-provider-group > .weather-provider-info { position:absolute; top:5px; right:7px; z-index:2; }
        .provider-info-directory { margin:8px 0; border:1px solid color-mix(in srgb,#d4af37 32%,var(--divider-color,#555)); border-radius:9px; overflow:hidden; background:rgba(212,175,55,.035); }
        .provider-info-directory > summary { cursor:pointer; padding:7px 9px; list-style:none; font-size:11px; font-weight:700; }
        .provider-info-directory > summary::-webkit-details-marker { display:none; }
        .provider-info-directory-body { display:flex; gap:6px; flex-wrap:wrap; padding:0 8px 8px; }
        .provider-info-chip { display:inline-flex; align-items:center; gap:5px; min-height:30px; padding:4px 7px; font-size:10px; }
        .provider-info-chip .weather-provider-info { width:22px; min-width:22px; height:22px; font-size:11px; }
        .weather-provider-group-body {
          display:grid;
          grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));
          gap:8px;
          align-items:start;
          padding:0 8px 8px;
        }
        .provider-info-window[hidden] { display:none !important; }
        .provider-info-window { position:fixed; inset:5vh auto auto 50%; transform:translateX(-50%); z-index:10002; width:min(860px,calc(100vw - 28px)); max-height:90vh; display:flex; flex-direction:column; overflow:hidden; border:1px solid color-mix(in srgb,#d4af37 58%,var(--divider-color,#555)); border-radius:16px; background:var(--card-background-color,#1c1c1c); color:var(--primary-text-color,#eee); box-shadow:0 18px 65px rgba(0,0,0,.62); }
        .provider-info-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:13px 15px; border-bottom:1px solid var(--divider-color,#444); background:color-mix(in srgb,#d4af37 7%,var(--secondary-background-color,#282828)); }
        .provider-info-head strong { font-size:16px; }
        .provider-info-head .gold { color:#d4af37; }
        .provider-info-close { min-width:38px; min-height:34px; padding:5px 10px; font-size:18px; }
        .provider-info-body { overflow:auto; padding:14px; font-size:12px; line-height:1.45; }
        .provider-info-lead { margin:0 0 12px; opacity:.82; }
        .provider-info-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
        .provider-info-block { border:1px solid var(--divider-color,#444); border-radius:10px; padding:10px; background:rgba(128,128,128,.035); }
        .provider-info-block h3 { margin:0 0 6px; font-size:12px; color:#d4af37; }
        .provider-info-block ul { margin:5px 0 0; padding-left:18px; }
        .provider-info-capability { margin-top:8px; padding-top:8px; border-top:1px solid color-mix(in srgb,var(--divider-color,#444) 65%,transparent); }
        .provider-info-capability:first-child { margin-top:0; padding-top:0; border-top:0; }
        .provider-info-capability strong { display:block; font-size:11px; }
        .provider-info-capability small { display:block; opacity:.66; margin-top:2px; }
        .provider-info-link { color:#d4af37; }
        @media(max-width:650px) { .provider-info-window { inset:10px 8px 10px 8px; transform:none; width:auto; max-height:none; } .provider-info-grid { grid-template-columns:1fr; } }
        .weather-layer { min-width:0; border:1px solid color-mix(in srgb,var(--divider-color,#555) 75%,transparent); border-radius:9px; padding:9px; margin:0; background:rgba(128,128,128,.05); }
        .weather-layer-head { display:flex; align-items:center; gap:8px; justify-content:space-between; }
        .weather-layer-region { margin:4px 0 2px 24px; color:#d4af37; font-size:10px; line-height:1.35; font-weight:600; }
        .weather-layer-toggle { display:flex; align-items:center; gap:7px; margin:0; opacity:1; font-weight:650; }
        .weather-layer-toggle input { margin:0; width:17px; height:17px; accent-color:var(--primary-color,#03a9f4); }
        .weather-provider { font-size:11px; opacity:.6; }
        .weather-status { margin-top:5px; font-size:11px; opacity:.72; line-height:1.35; }
        .weather-opacity { display:grid; grid-template-columns:auto 1fr 42px; gap:8px; align-items:center; margin-top:8px; font-size:11px; }
        .weather-opacity input { width:100%; }
        .weather-refresh { padding:3px 7px; min-width:30px; font-size:13px; }
        .media-sequence { border:1px solid color-mix(in srgb,var(--divider-color,#555) 75%,transparent); border-radius:10px; padding:9px; margin-top:9px; background:rgba(128,128,128,.05); }
        .media-sequence-head { display:flex; align-items:center; justify-content:space-between; gap:8px; }
        .media-sequence-title { font-size:12px; font-weight:750; }
        .media-sequence-region { margin:3px 0 7px; color:#d4af37; font-size:10px; line-height:1.35; font-weight:650; }
        .media-image-wrap { display:grid; place-items:center; min-height:180px; max-height:330px; overflow:hidden; border-radius:9px; border:1px solid color-mix(in srgb,var(--divider-color,#444) 68%,transparent); background:#000; }
        .media-image-wrap img { display:block; max-width:100%; width:100%; max-height:330px; object-fit:contain; background:#000; }
        .live-stream-wrap { position:relative; width:100%; aspect-ratio:16/9; min-height:180px; overflow:hidden; border-radius:9px; border:1px solid color-mix(in srgb,var(--divider-color,#444) 68%,transparent); background:#000; display:grid; place-items:center; }
        .live-stream-wrap[hidden] { display:none !important; }
        .live-stream-wrap iframe { position:absolute; inset:0; width:100%; height:100%; border:0; background:#000; }
        .live-stream-actions { display:flex; gap:6px; margin-top:7px; }
        .live-stream-actions button { flex:1; min-height:32px; padding:5px 7px; font-size:11px; }
        .planetary-view { position:relative; width:100%; height:300px; overflow:auto; border-radius:9px; border:1px solid color-mix(in srgb,var(--divider-color,#444) 68%,transparent); background:#000; overscroll-behavior:contain; scrollbar-width:thin; cursor:grab; }
        .planetary-world { position:relative; background:#000; transform-origin:0 0; }
        .planetary-tile { position:absolute; display:block; width:256px; height:256px; object-fit:cover; user-select:none; -webkit-user-drag:none; }
        .planetary-actions { display:grid; grid-template-columns:auto auto 1fr auto auto; gap:5px; margin-top:7px; }
        .planetary-actions button { min-height:32px; padding:5px 7px; font-size:11px; }
        .planetary-meta { display:flex; justify-content:space-between; gap:8px; margin-top:5px; font-size:10px; opacity:.65; }
        .media-sequence-status { margin-top:6px; min-height:16px; font-size:10px; opacity:.72; overflow-wrap:anywhere; }
        .media-sequence-actions { display:grid; grid-template-columns:auto auto 1fr auto auto; gap:5px; margin-top:7px; }
        .media-sequence-actions button { min-height:32px; padding:5px 7px; font-size:11px; }
        .media-sequence-range { width:100%; margin-top:7px; }
        .media-sequence-meta { display:flex; justify-content:space-between; gap:8px; margin-top:4px; font-size:10px; opacity:.62; }
        .media-provider-head { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:10px; padding-top:8px; border-top:1px solid color-mix(in srgb,var(--divider-color,#444) 72%,transparent); }
        .media-provider-head:first-child { margin-top:0; padding-top:0; border-top:0; }
        .monitor-filters { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;align-items:end; }
        .monitor-filters label { display:flex;flex-direction:column;justify-content:end;gap:5px;min-width:0;font-size:12px; }
        .monitor-filters input,.monitor-filters select { width:100%;min-width:0;min-height:38px;padding:7px;box-sizing:border-box; }
        .monitor-metal { flex:1;min-height:44px;border:1px solid #997a35;border-radius:10px;font-weight:750;color:#191919;background:linear-gradient(165deg,#fff5bd 0%,#e6c66b 28%,#a98137 55%,#f2d98c 80%,#896527 100%);box-shadow:inset 0 2px 1px #fff9cc, inset 0 -3px 3px #735522,0 4px 9px #0005;text-shadow:0 1px #fff7b4;transition:transform .12s,filter .12s,box-shadow .12s; }
        .monitor-metal:active { transform:translateY(2px);box-shadow:inset 0 3px 6px #0007;filter:brightness(.88); }
        .monitor-metal.stop { border-color:#8a4147;color:#fff;background:linear-gradient(165deg,#ffa9a7,#bb4648 40%,#781c28 70%,#c55459);text-shadow:0 1px #431118;box-shadow:inset 0 1px #ffc8c8,inset 0 -3px #63151f,0 4px 9px #0005; }
        .monitor-metal:disabled { opacity:.5;cursor:wait;filter:grayscale(.4); }
        .request-row { display:grid; grid-template-columns:1fr 1.3fr auto; gap:6px; align-items:end; margin-bottom:8px; }
        .request-row button { width:38px; }
        .actions { display:flex; gap:8px; margin-top:10px; }
        .actions .primary { flex:1; }
        dl { display:grid; grid-template-columns:1fr auto; gap:6px 12px; margin:0; font-size:13px; }
        dd { margin:0; text-align:right; overflow-wrap:anywhere; }
        dt,.muted { opacity:.62; }
        .ok { color:var(--success-color,#4caf50); }
        .error { color:var(--error-color,#f44336); }
        .result { border-left:3px solid var(--primary-color,#03a9f4); padding:8px 10px; margin:8px 0; background:rgba(128,128,128,.08); border-radius:0 8px 8px 0; }
        .result strong { display:block; }
        .result small { opacity:.62; }
        .value { font-size:20px; margin-top:3px; }
        pre { max-height:240px; overflow:auto; white-space:pre-wrap; font-size:11px; background:rgba(0,0,0,.25); padding:8px; border-radius:8px; }
        .map-wrap { position:relative; min-width:0; min-height:0; height:100%; overflow:hidden; background:#09111d; }
        #map { position:absolute; inset:0; }
        .map-note { position:absolute; z-index:2; top:12px; left:12px; max-width:560px; padding:8px 10px; border-radius:8px; background:rgba(20,20,20,.84); color:white; font-size:12px; pointer-events:none; }
        @media(max-width:850px){ :host{height:auto;min-height:100vh;overflow:visible;} .layout{height:auto;min-height:100vh;overflow:visible;grid-template-columns:1fr;grid-template-rows:auto 65vh;} .sidebar{height:auto;overflow:visible;overscroll-behavior:auto;scrollbar-gutter:auto;border-right:0;border-bottom:1px solid var(--divider-color,#444);} .map-wrap{height:65vh;min-height:65vh;} }
        @media(max-width:650px){
          .weather-layer-toolbar{grid-template-columns:1fr;}
          .weather-layer-toolbar .compact-check{min-height:26px;}
          .weather-provider-grid,
          .weather-provider-group-body{grid-template-columns:1fr;}
        }
        @media(max-width:520px){ .basemap-controls{grid-template-columns:1fr;} }
      </style>
      <div class="layout">
        <aside class="sidebar">
          <h1>WeatherRouter Lab</h1>
          <div class="subtitle">WR ${WR_LAB_BUILD_VERSION} · DEV · interner Router-/Provider-Prüfstand</div>

          <details class="card lab-menu" data-lab-menu-key="basemap" open>
            <summary>Karte & Basiskarte</summary>
            <div class="lab-menu-content">
              <div class="basemap-controls">
                <div class="basemap-control">
                  <label>Engine</label>
                  <div class="engine-status" aria-label="Karten-Engine">MapLibre</div>
                </div>
                <div class="basemap-control">
                  <label for="basemap-provider">Kartenquelle</label>
                  <select id="basemap-provider">
                    <option value="openfreemap">OpenFreeMap</option>
                    <option value="science">Lokaler Hintergrund · ohne Basiskarte</option>
                  </select>
                </div>
                <div class="basemap-control">
                  <label for="basemap-style">Kartenstil</label>
                  <select id="basemap-style">
                    <option value="dark">Dark · kontrastarm</option>
                    <option value="fiord">Fiord</option>
                    <option value="positron">Positron · hell</option>
                  </select>
                </div>
              </div>
              <div class="basemap-note">Basiskarte und Wetterprovider sind getrennte Ebenen. Der lokale Hintergrund erzeugt keine externen Kartenabrufe; direkte OpenStreetMap-Standardkacheln werden nicht verwendet.</div>
            </div>
          </details>

          <details class="card lab-menu" data-lab-menu-key="reference" open>
            <summary>1 · Bezugsstandort</summary>
            <div class="lab-menu-content">
              <label for="reference">Home-Assistant-Standort</label>
              <select id="reference" disabled><option>Lade …</option></select>
              <label for="diagnostic-test-location" style="margin-top:10px">Diagnose-Teststandort</label>
              <select id="diagnostic-test-location">
                <option value="ha-reference">HA-Bezugsstandort verwenden</option>
                <option value="noaa-us-new-york">NOAA/NWS · New York City (USA)</option>
                <option value="met-nowcast-oslo">MET Nowcast · Oslo (Norwegen)</option>
                <option value="fmi-helsinki">FMI · Helsinki (Finnland)</option>
                <option value="smhi-stockholm">SMHI · Stockholm (Schweden)</option>
                <option value="eccc-toronto">ECCC/MSC · Toronto (Kanada)</option>
                <option value="jma-tokyo">JMA · Tokio (Japan)</option>
              </select>
              <div class="muted" style="font-size:10px;line-height:1.35;margin-top:5px">
                Nur für Punktabfragen in der Diagnose-Matrix. Karte und gespeicherter HA-Bezugsstandort bleiben unverändert.
              </div>
              <dl style="margin-top:10px"><dt>Koordinaten</dt><dd id="coordinates">—</dd><dt>Kartenstatus</dt><dd id="map-status">Warte</dd></dl>
            </div>
          </details>

          <details class="card lab-menu" data-lab-menu-key="weather-layers" open>
            <summary>2 · Kartenebenen</summary>
            <div class="lab-menu-content">
              <div class="muted" style="font-size:12px">Räumliche Wetter-, Satelliten-, Gefahren- und Biodiversitätslayer wie RainViewer, Copernicus GloFAS oder GBIF werden unabhängig von der Basiskarte ein- und ausgeblendet.</div>
              <div id="weather-layer-list" class="muted" style="font-size:12px;margin-top:8px">Lade verfügbare Ebenen …</div>
            </div>
          </details>

          <details class="card lab-menu" data-lab-menu-key="solar-media">
            <summary>3 · Sonne & Weltraum</summary>
            <div class="lab-menu-content">
              <div class="muted" style="font-size:12px">Bildfolgen, Livemedien und die Mondkarte laufen getrennt von der Erdkarte. Punktwerte von <strong>MET Norway · Sonne & Mond</strong> findest du unter <strong>4 · Punktwerte</strong>. Es werden keine Daten geladen, bevor du einen Dienst ausdrücklich öffnest bzw. abfragst.</div>
              <div id="media-sequence-list" class="muted" style="font-size:12px;margin-top:8px">Lade verfügbare Medien …</div>
            </div>
          </details>

          <details class="card lab-menu" data-lab-menu-key="diagnostic-matrix" open>
            <summary>4 · Punktwerte</summary>
            <div class="lab-menu-content">
              <div class="muted" style="font-size:12px;margin-bottom:10px">Hier werden Punktwerte für Wetter, Pollen sowie Sonne & Mond abgefragt. Räumliche Kartenebenen werden oben getrennt gesteuert.</div>
              <div id="request-list"></div>
              <div class="actions"><button id="add-request">+ Zeile</button><button id="run" class="primary" disabled>Abrufen</button></div>
            </div>
          </details>

          <details class="card lab-menu" data-lab-menu-key="results">
            <summary>5 · Ergebnisse</summary>
            <div class="lab-menu-content">
              <div id="results" class="muted">Noch keine Abfrage.</div>
            </div>
          </details>

          <details class="card lab-menu" data-lab-menu-key="api-monitor">
            <summary>API-Monitor · Consumer V1 / V2</summary>
            <div class="lab-menu-content">
              <div id="api-monitor-state" class="muted" role="status">Aufzeichnung AUS · noch nicht geladen</div>
              <div class="actions">
                <button id="api-monitor-start" class="monitor-metal" type="button">Aufzeichnung starten</button>
                <button id="api-monitor-stop" class="monitor-metal stop" type="button">Stopp + löschen</button>
              </div>
              <p class="muted" style="font-size:11px">Nur Administratoren. Aufzeichnung standardmäßig AUS, im Speicher begrenzt und nach Neustart AUS. Koordinaten und Zugangsdaten werden nicht aufgezeichnet.</p>
              <div class="monitor-filters">
                <label>API <select id="api-monitor-version"><option value="all">Alle</option><option value="V1">V1</option><option value="V2">V2</option></select></label>
                <label>Ergebnis <select id="api-monitor-result"><option value="all">Alle</option><option value="success">Erfolg</option><option value="no_data">Keine Daten</option><option value="rejected">Abgewiesen</option><option value="error">Fehler</option><option value="timeout">Zeitüberschreitung</option></select></label>
                <label>Befehl <input id="api-monitor-command" placeholder="alle" /></label>
                <label>Consumer <input id="api-monitor-consumer" placeholder="alle" /></label>
                <label>Provider <input id="api-monitor-provider" placeholder="alle" /></label>
                <label>Capability <input id="api-monitor-capability" placeholder="alle" /></label>
                <label>Korrelation <input id="api-monitor-correlation" placeholder="alle" /></label>
                <label>Min. Dauer (ms) <input id="api-monitor-min" type="number" min="0" step="1" /></label>
                <label>Max. Dauer (ms) <input id="api-monitor-max" type="number" min="0" step="1" /></label>
                <label>Sitzung <input id="api-monitor-session" placeholder="alle" /></label>
                <label>Anfragekennung <input id="api-monitor-request" placeholder="alle" /></label>
                <label>Ab UTC <input id="api-monitor-since" type="datetime-local" /></label>
                <label>Bis UTC <input id="api-monitor-until" type="datetime-local" /></label>
              </div>
              <label>Suche <input id="api-monitor-search" placeholder="Befehl, Kennung, Fehler ..." /></label>
              <label>Exportumfang <select id="api-monitor-export-scope"><option value="filtered">Alle gefilterten Einträge</option><option value="selected">Nur ausgewählten Eintrag</option></select></label>
              <div class="actions">
                <button id="api-monitor-refresh" type="button">Aktualisieren</button>
                <button id="api-monitor-copy" type="button">Kopieren</button>
                <button id="api-monitor-json" type="button">JSON</button>
                <button id="api-monitor-git" type="button">Export2Git</button>
              </div>
              <details style="margin:9px 0">
                <summary>Manuelles API-Prüfwerkzeug (V1 / V2)</summary>
                <label>API
                  <select id="api-monitor-manual-version"><option value="V2">Consumer V2</option><option value="V1">Consumer V1</option></select>
                </label>
                <label>Anfrage als JSON (ohne Zugangsgeheimnisse)</label>
                <textarea id="api-monitor-manual-json" rows="7" style="width:100%;font:11px monospace"></textarea>
                <div class="actions"><button id="api-monitor-manual-run" type="button">Testanfrage senden</button></div>
                <pre id="api-monitor-manual-result">Noch keine Testabfrage.</pre>
              </details>
              <div id="api-monitor-list" class="muted">Keine aufgezeichneten Anfragen.</div>
              <div id="api-monitor-detail-wrap" hidden><div class="actions"><button id="api-monitor-detail-close" type="button">Details schließen ×</button></div><pre id="api-monitor-details" aria-label="API-Monitor Anfragedetails"></pre></div>
            </div>
          </details>

          <details class="card lab-menu" data-lab-menu-key="raw-diagnostics">
            <summary>Diagnose-Rohdaten</summary>
            <div class="lab-menu-content">
              <pre id="raw">—</pre>
            </div>
          </details>
        </aside>
        <main class="map-wrap">
          <div class="map-note">Punktdaten und räumliche Kartenebenen bleiben getrennt: Wetter, Pollen sowie Sonne & Mond liefern Punktwerte; Provider wie RainViewer, Copernicus GloFAS oder GBIF liefern renderbare Kartenlayer.</div>
          <div id="map"></div>
        </main>
      </div>
      <section id="provider-info-window" class="provider-info-window" hidden>
        <div class="provider-info-head">
          <div><strong><span class="gold">ⓘ</span> <span id="provider-info-title">Anbieterinformation</span></strong></div>
          <button id="provider-info-close" class="provider-info-close" type="button" title="Schließen">×</button>
        </div>
        <div id="provider-info-body" class="provider-info-body"></div>
      </section>`;

    this.shadowRoot.getElementById("provider-info-close").addEventListener("click", () => {
      this._providerInfoClose();
    });

    let storedMenuState = {};
    try {
      storedMenuState = JSON.parse(localStorage.getItem(LAB_MENU_STATE_KEY) || "{}");
    } catch (_error) {
      storedMenuState = {};
    }

    for (const menu of this.shadowRoot.querySelectorAll("[data-lab-menu-key]")) {
      const key = menu.dataset.labMenuKey;
      if (Object.prototype.hasOwnProperty.call(storedMenuState, key)) {
        menu.open = Boolean(storedMenuState[key]);
      }
      menu.addEventListener("toggle", () => {
        let current = {};
        try {
          current = JSON.parse(localStorage.getItem(LAB_MENU_STATE_KEY) || "{}");
        } catch (_error) {
          current = {};
        }
        current[key] = menu.open;
        try {
          localStorage.setItem(LAB_MENU_STATE_KEY, JSON.stringify(current));
        } catch (_error) {
          // Persistenz ist optional; Einklappen funktioniert in der Sitzung trotzdem.
        }
        if (key === "solar-media" && !menu.open) {
          this._stopAllMediaPlayback("menu_closed");
        }
        this._wrLog?.("menu_toggle", { menu: key, open: menu.open });
      });
    }

    this.shadowRoot.getElementById("api-monitor-start").addEventListener("click", () => this._monitorConfigure(true));
    this.shadowRoot.getElementById("api-monitor-manual-run").addEventListener("click", () => this._monitorManualRun());
    this.shadowRoot.getElementById("api-monitor-manual-version").addEventListener("change", () => this._monitorManualExample());
    this._monitorManualExample();
    this.shadowRoot.getElementById("api-monitor-stop").addEventListener("click", () => this._monitorConfigure(false));
    this.shadowRoot.getElementById("api-monitor-refresh").addEventListener("click", () => this._monitorRefresh());
    this.shadowRoot.getElementById("api-monitor-copy").addEventListener("click", () => this._monitorCopy());
    this.shadowRoot.getElementById("api-monitor-json").addEventListener("click", () => this._monitorJson());
    this.shadowRoot.getElementById("api-monitor-git").addEventListener("click", () => this._monitorGit());
    this.shadowRoot.getElementById("api-monitor-detail-close").addEventListener("click", () => this._monitorCloseDetail());
    for (const id of ["api-monitor-version","api-monitor-result","api-monitor-consumer","api-monitor-provider","api-monitor-capability","api-monitor-correlation","api-monitor-min","api-monitor-max","api-monitor-search"]) {
      this.shadowRoot.getElementById(id).addEventListener("change", () => this._monitorRefresh());
    }
    this.shadowRoot.querySelector('[data-lab-menu-key="api-monitor"]').addEventListener("toggle", () => this._monitorRefresh());
    this.shadowRoot.getElementById("reference").addEventListener("change", e => this._setReference(e.target.value));
    this.shadowRoot.getElementById("diagnostic-test-location").addEventListener("change", e => {
      this._diagnosticTestLocation = e.target.value;
      const preset = DIAGNOSTIC_TEST_LOCATIONS[this._diagnosticTestLocation];
      this._wrLog?.("diagnostic_test_location_changed", {
        preset: this._diagnosticTestLocation,
        label: preset?.label || null,
      });
    });
    this.shadowRoot.getElementById("basemap-provider").addEventListener("change", e => {
      this._basemapProvider = e.target.value;
      this.shadowRoot.getElementById("basemap-style").disabled = this._basemapProvider !== "openfreemap";
      this._applyBasemap();
    });
    this.shadowRoot.getElementById("basemap-style").addEventListener("change", e => {
      this._basemapStyle = e.target.value;
      this._applyBasemap();
    });
    this.shadowRoot.getElementById("add-request").addEventListener("click", () => {
      const provider = this._valueProviders()[0];
      if (!provider) return;
      const capabilities = provider.capabilities.filter(item => item.render_mode === "value");
      this._requests.push({ provider: provider.id, capability: capabilities[0]?.id || "" });
      this._renderRequests();
    });
    this.shadowRoot.getElementById("run").addEventListener("click", () => this._runDiagnostics());
    this._renderRequests();
  }

  _monitorFilters() {
    const get = id => this.shadowRoot.getElementById("api-monitor-" + id)?.value?.trim() || "";
    const result = {};
    for (const [control, key] of [["version","api_version"],["result","result"],["command","command"],["session","session_id"],["request","request_id"],["consumer","consumer"],["provider","provider"],["capability","capability"],["correlation","correlation_id"],["search","search"]]) {
      const value = get(control);
      if (value && value !== "all") result[key] = value;
    }
    if (get("since")) result.since = get("since") + ":00+00:00";
    if (get("until")) result.until = get("until") + ":00+00:00";
    if (get("min")) result.min_duration_ms = Number(get("min"));
    if (get("max")) result.max_duration_ms = Number(get("max"));
    return result;
  }

  _monitorManualExample() {
    const version = this.shadowRoot.getElementById("api-monitor-manual-version").value;
    const example = version === "V2" ? {
      contract_version: 2,
      capability: "weather.precipitation.layer",
      context: {type:"bbox",west:-85,south:18,east:-73,north:25},
      time: {mode:"latest_coherent",max_data_age_seconds:3600},
      limits: {max_layers:4,max_tile_requests:64}
    } : {
      contract_version: 1,
      capability: "weather.radar.precipitation",
      context: {type:"bbox",west:-85,south:18,east:-73,north:25},
      time: {mode:"latest"}
    };
    this.shadowRoot.getElementById("api-monitor-manual-json").value = JSON.stringify(example, null, 2);
  }

  async _monitorManualRun() {
    const output = this.shadowRoot.getElementById("api-monitor-manual-result");
    const version = this.shadowRoot.getElementById("api-monitor-manual-version").value;
    const raw = this.shadowRoot.getElementById("api-monitor-manual-json").value.trim();
    try {
      const query = JSON.parse(raw);
      if (!query || typeof query !== "object" || Array.isArray(query)) throw Error("JSON-Objekt erwartet.");
      const command = version === "V2" ? "weather_router/consumer/resolve_mosaic" : "weather_router/consumer/resolve";
      if (query.type && query.type !== command) throw Error("API-Befehl stimmt nicht mit gewählter Version überein.");
      query.type = command;
      query.consumer_id = "weather_router_lab";
      query.correlation_id = query.correlation_id || (crypto.randomUUID?.() || ("lab-" + Date.now().toString(36)));
      output.textContent = "Anfrage läuft...";
      const result = await this._hass.callWS(query);
      output.textContent = JSON.stringify(result, null, 2);
    } catch(error) {
      output.textContent = "Anfrage abgewiesen/fehlgeschlagen: " + String(error.message || error);
    } finally {
      await this._monitorRefresh();
    }
  }

  async _monitorConfigure(enabled) {
    if (!this._hass) return;
    try {
      await this._hass.callWS({type:"weather_router/api_monitor/configure", enabled, clear:!enabled});
      await this._monitorRefresh();
    } catch(error) {
      this.shadowRoot.getElementById("api-monitor-state").textContent = "Monitor-Steuerung fehlgeschlagen: " + String(error.message || error);
    }
  }

  async _monitorRefresh() {
    if (!this._hass || !this.shadowRoot.querySelector('[data-lab-menu-key="api-monitor"]')?.open) return;
    try {
      const snapshot = await this._hass.callWS({type:"weather_router/api_monitor/query", ...this._monitorFilters()});
      this._monitorSnapshot = snapshot;
      if (this._monitorSelected && !snapshot.entries.some(item => item.request_id === this._monitorSelected.request_id)) this._monitorSelected = null;
      this.shadowRoot.getElementById("api-monitor-state").textContent =
        (snapshot.recording ? "● Aufzeichnung AKTIV" : "○ Aufzeichnung AUS") +
        " · " + snapshot.record_count + " Einträge · " + snapshot.buffer_bytes + " Bytes";
      const list = this.shadowRoot.getElementById("api-monitor-list");
      list.replaceChildren();
      for (const entry of [...snapshot.entries].reverse()) {
        const b = document.createElement("button");
        b.type = "button";
        b.style.cssText = "display:block;width:100%;text-align:left;margin:4px 0;white-space:normal;overflow-wrap:anywhere";
        b.textContent = entry.started_at + " · " + entry.api_version + " · " +
          entry.consumer + " · " + entry.capability + " · " + entry.result +
          " · " + entry.duration_ms + " ms";
        b.addEventListener("click", () => {
          if (this._monitorSelected?.request_id === entry.request_id) {
            this._monitorCloseDetail();
          } else {
            this._monitorSelected = entry;
            this.shadowRoot.getElementById("api-monitor-detail-wrap").hidden = false;
            this.shadowRoot.getElementById("api-monitor-details").textContent = JSON.stringify(entry, null, 2);
          }
        });
        list.appendChild(b);
      }
      if (!snapshot.entries.length) list.textContent = "Keine passenden Einträge.";
    } catch(error) {
      this.shadowRoot.getElementById("api-monitor-state").textContent = "API-Monitor nicht erreichbar: " + String(error.message || error);
    }
  }

  _monitorCloseDetail() {
    this._monitorSelected = null;
    this.shadowRoot.getElementById("api-monitor-detail-wrap").hidden = true;
  }

  _monitorExportSnapshot() {
    if (!this._monitorSnapshot) return null;
    const scope = this.shadowRoot.getElementById("api-monitor-export-scope").value;
    if (scope !== "selected") return this._monitorSnapshot;
    if (!this._monitorSelected) {
      this.shadowRoot.getElementById("api-monitor-state").textContent = "Bitte zuerst eine Anfrage auswählen.";
      return null;
    }
    return {...this._monitorSnapshot, record_count:1, entries:[this._monitorSelected]};
  }

  async _monitorCopy() {
    if (!this._monitorSnapshot) await this._monitorRefresh();
    if (!this._monitorSnapshot) return;
    if (!this._monitorExportSnapshot()) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(this._monitorExportSnapshot(), null, 2));
      this.shadowRoot.getElementById("api-monitor-state").textContent = "Gewählter JSON-Export in die Zwischenablage kopiert.";
    } catch(error) {
      this.shadowRoot.getElementById("api-monitor-state").textContent = "Zwischenablage nicht verfügbar: " + String(error);
    }
  }

  async _monitorJson() {
    await this._monitorRefresh();
    if (!this._monitorSnapshot) return;
    const snapshot = this._monitorExportSnapshot();
    if (!snapshot) return;
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], {type:"application/json"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "weather-router-api-monitor-" + new Date().toISOString().replace(/[:.]/g,"-") + ".json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async _monitorGit() {
    const button = this.shadowRoot.getElementById("api-monitor-git");
    const status = this.shadowRoot.getElementById("api-monitor-state");
    if (button.disabled || !this._hass) return;
    button.disabled = true;
    button.textContent = "⏳ Export läuft …";
    status.textContent = "Export2Git: Übertragung läuft …";
    try {
      await this._monitorRefresh();
      const snapshot = this._monitorExportSnapshot();
      if (!snapshot) return;
      const result = await this._hass.callWS({type:"weather_router/log_git_export",target:"archive",snapshot});
      status.textContent = "✓ Export2Git erfolgreich: " + (result.path || result.url || "Privates Archiv");
      button.textContent = "✓ Export erfolgreich";
    } catch(error) {
      status.textContent = "✕ Export2Git fehlgeschlagen: " + String(error.message || error);
      button.textContent = "✕ Export fehlgeschlagen";
    } finally {
      button.disabled = false;
      button.style.fontWeight = "bold";
    }
  }

  _providerInfoClose() {
    const panel = this.shadowRoot?.getElementById("provider-info-window");
    if (panel) panel.hidden = true;
  }

  _providerInfoOpen(providerId) {
    const provider = this._providers.find(item => item.id === providerId);
    const panel = this.shadowRoot?.getElementById("provider-info-window");
    const title = this.shadowRoot?.getElementById("provider-info-title");
    const body = this.shadowRoot?.getElementById("provider-info-body");
    if (!provider || !panel || !title || !body) return;

    const info = provider.info || {};
    const strengths = Array.isArray(info.strengths) ? info.strengths : [];
    const limitations = Array.isArray(info.limitations) ? info.limitations : [];
    const services = Array.isArray(info.services) ? info.services : [];
    const capabilities = Array.isArray(provider.capabilities) ? provider.capabilities : [];

    const renderList = values => values.length
      ? `<ul>${values.map(value => `<li>${this._escape(value)}</li>`).join("")}</ul>`
      : '<div class="muted">Keine zusätzlichen Angaben.</div>';

    const serviceHtml = services.length
      ? services.map(service => {
          const detail = [service.status, service.note].filter(Boolean).join(" · ");
          return `<div class="provider-info-capability"><strong>${this._escape(service.name || "Dienst")}</strong>${detail ? `<small>${this._escape(detail)}</small>` : ""}</div>`;
        }).join("")
      : '<div class="muted">Keine separaten Dienstangaben.</div>';

    const capabilityHtml = capabilities.length
      ? capabilities.map(capability => {
          const detail = [
            capability.coverage ? `Abdeckung: ${capability.coverage}` : null,
            capability.temporal_resolution ? `Zeitauflösung: ${capability.temporal_resolution}` : null,
            capability.typical_latency ? `Aktualität: ${capability.typical_latency}` : null,
          ].filter(Boolean).join(" · ");
          return `<div class="provider-info-capability"><strong>${this._escape(capability.name)}</strong>${capability.description ? `<div>${this._escape(capability.description)}</div>` : ""}${detail ? `<small>${this._escape(detail)}</small>` : ""}</div>`;
        }).join("")
      : '<div class="muted">Keine Fähigkeiten gemeldet.</div>';

    const doc = typeof info.documentation_url === "string" && info.documentation_url.startsWith("https://")
      ? `<p style="margin:10px 0 0"><a class="provider-info-link" href="${this._escape(info.documentation_url)}" target="_blank" rel="noopener noreferrer">Offizielle Dokumentation ↗</a></p>`
      : "";

    title.textContent = provider.name;
    body.innerHTML = `
      <p class="provider-info-lead">${this._escape(info.summary || `${provider.name} stellt WeatherRouter-Daten bereit.`)}</p>
      ${info.coverage ? `<p><strong>Abdeckung:</strong> ${this._escape(info.coverage)}</p>` : ""}
      <div class="provider-info-grid">
        <section class="provider-info-block"><h3>Stärken</h3>${renderList(strengths)}</section>
        <section class="provider-info-block"><h3>Einschränkungen</h3>${renderList(limitations)}</section>
        <section class="provider-info-block"><h3>Dienste</h3>${serviceHtml}</section>
        <section class="provider-info-block"><h3>WeatherRouter-Fähigkeiten</h3>${capabilityHtml}</section>
      </div>
      ${info.attribution ? `<p><strong>Quelle/Attribution:</strong> ${this._escape(info.attribution)}</p>` : ""}
      ${doc}
    `;
    panel.hidden = false;
    this._wrLog?.("provider_info_open", { provider: provider.id });
  }

  _selectedMapStyle() {
    if (this._basemapProvider === "science") return SCIENCE_STYLE;
    return OPENFREEMAP_STYLES[this._basemapStyle] || OPENFREEMAP_STYLES.dark;
  }

  _setMapStatus(text, className = "") {
    const status = this.shadowRoot.getElementById("map-status");
    if (!status) return;
    status.textContent = text;
    status.className = className;
  }

  _valueProviders() {
    return this._providers.filter(provider =>
      provider.eligible !== false
      && provider.capabilities?.some(
        capability => capability.render_mode === "value" && capability.eligible !== false
      )
    );
  }

  _syncWeatherLayerStates() {
    const valid = new Set();
    for (const provider of this._providers) {
      if (provider.eligible === false) continue;
      for (const capability of provider.capabilities || []) {
        if (
          capability.render_mode !== "raster_tile"
          || capability.eligible === false
        ) continue;
        const key = `${provider.id}/${capability.id}`;
        valid.add(key);
        if (!this._weatherLayers.has(key)) {
          this._weatherLayers.set(key, {
            key,
            provider: provider.id,
            providerName: provider.name,
            capability: capability.id,
            capabilityName: capability.name,
            coverage: capability.coverage || null,
            enabled: false,
            loading: false,
            opacity: 65,
            descriptor: null,
            error: null,
          });
        }
      }
    }
    for (const [key, state] of this._weatherLayers.entries()) {
      if (valid.has(key)) continue;
      state.enabled = false;
      this._removeWeatherLayerFromMap(state);
      this._weatherLayers.delete(key);
    }
  }

  _syncMediaSequenceStates() {
    const valid = new Set();
    for (const provider of this._providers) {
      if (provider.eligible === false) continue;
      for (const capability of provider.capabilities || []) {
        if (
          capability.render_mode !== "image_sequence"
          || capability.eligible === false
        ) continue;
        const key = `${provider.id}/${capability.id}`;
        valid.add(key);
        if (!this._mediaSequences.has(key)) {
          this._mediaSequences.set(key, {
            key,
            provider: provider.id,
            providerName: provider.name,
            capability: capability.id,
            capabilityName: capability.name,
            coverage: capability.coverage || null,
            descriptor: null,
            loading: false,
            error: null,
            index: 0,
            playing: false,
            timer: null,
          });
        }
      }
    }
    for (const [key, state] of this._mediaSequences.entries()) {
      if (valid.has(key)) continue;
      this._stopMediaPlayback(state, "router_disabled");
      this._mediaSequences.delete(key);
    }
  }

  _syncLiveStreamStates() {
    const valid = new Set();
    for (const provider of this._providers) {
      if (provider.eligible === false) continue;
      for (const capability of provider.capabilities || []) {
        if (
          capability.render_mode !== "live_stream"
          || capability.eligible === false
        ) continue;
        const key = `${provider.id}/${capability.id}`;
        valid.add(key);
        if (!this._liveStreams.has(key)) {
          this._liveStreams.set(key, {
            key,
            provider: provider.id,
            providerName: provider.name,
            capability: capability.id,
            capabilityName: capability.name,
            coverage: capability.coverage || null,
            descriptor: null,
            loading: false,
            active: false,
            error: null,
          });
        }
      }
    }
    for (const [key, state] of this._liveStreams.entries()) {
      if (valid.has(key)) continue;
      this._stopLiveStream(state, "router_disabled");
      this._liveStreams.delete(key);
    }
  }

  _syncPlanetaryTileStates() {
    const valid = new Set();
    for (const provider of this._providers) {
      if (provider.eligible === false) continue;
      for (const capability of provider.capabilities || []) {
        if (
          capability.render_mode !== "planetary_tile"
          || capability.eligible === false
        ) continue;
        const key = `${provider.id}/${capability.id}`;
        valid.add(key);
        if (!this._planetaryTiles.has(key)) {
          this._planetaryTiles.set(key, {
            key,
            provider: provider.id,
            providerName: provider.name,
            capability: capability.id,
            capabilityName: capability.name,
            coverage: capability.coverage || null,
            descriptor: null,
            loading: false,
            active: false,
            error: null,
            zoom: 1,
            needsCenter: true,
            tiles: new Map(),
          });
        }
      }
    }
    for (const [key, state] of this._planetaryTiles.entries()) {
      if (valid.has(key)) continue;
      this._stopPlanetaryView(state, "router_disabled");
      this._planetaryTiles.delete(key);
    }
  }

  async _loadPlanetaryTile(state, force=false) {
    if (!this._hass || state.loading) return;
    if (state.descriptor && !force) {
      state.active = true;
      this._updatePlanetaryCard(state);
      return;
    }

    this._stopPlanetaryView(state, "reload");
    state.loading = true;
    state.error = null;
    this._updatePlanetaryCard(state);
    this._wrLog?.("planetary_tile_load_start", {
      provider: state.provider,
      capability: state.capability,
    });

    try {
      const response = await this._hass.callWS({
        type: "weather_router/map_layer",
        provider: state.provider,
        capability: state.capability,
      });
      const descriptor = response?.layer;
      const planetary = descriptor?.planetary;
      const template = planetary?.tile_url_template;
      const allowedHosts = Array.isArray(descriptor?.network_hosts)
        ? descriptor.network_hosts.filter(host => typeof host === "string" && host)
        : [];
      let templateUrl = null;
      if (typeof template === "string") {
        try {
          templateUrl = new URL(
            template
              .replace("{z}", "0")
              .replace("{y}", "0")
              .replace("{x}", "0")
          );
        } catch (_error) {
          templateUrl = null;
        }
      }
      if (
        descriptor?.render_mode !== "planetary_tile"
        || typeof template !== "string"
        || templateUrl?.protocol !== "https:"
        || !allowedHosts.includes(templateUrl?.hostname)
        || !template.includes("{z}")
        || !template.includes("{y}")
        || !template.includes("{x}")
      ) {
        throw new Error("Provider lieferte keinen unterstützten planetaren Kachelvertrag");
      }
      state.descriptor = descriptor;
      state.zoom = Math.min(
        Math.max(
          Number(planetary.min_zoom ?? 0),
          Number(planetary.initial_zoom ?? 1),
        ),
        Number(planetary.max_zoom ?? 8),
      );
      state.active = true;
      state.needsCenter = true;
      this._wrLog?.("planetary_tile_loaded", {
        provider: state.provider,
        capability: state.capability,
        body: planetary.body,
        zoom: state.zoom,
      });
    } catch (error) {
      state.descriptor = null;
      state.active = false;
      state.error = error?.message || String(error);
      this._wrLog?.("planetary_tile_load_failed", {
        provider: state.provider,
        capability: state.capability,
        error,
      }, "error");
    } finally {
      state.loading = false;
      this._updatePlanetaryCard(state);
    }
  }

  _planetaryDimensions(state, zoom=state.zoom) {
    const planetary = state.descriptor?.planetary;
    const tileSize = Number(planetary?.tile_size || 256);
    const scale = 2 ** Number(zoom || 0);
    const columns = Number(planetary?.columns_at_zoom0 || 1) * scale;
    const rows = Number(planetary?.rows_at_zoom0 || 1) * scale;
    return {
      tileSize,
      columns,
      rows,
      width: columns * tileSize,
      height: rows * tileSize,
    };
  }

  _planetaryTileUrl(state, z, y, x) {
    const template = state.descriptor?.planetary?.tile_url_template;
    if (typeof template !== "string") return null;
    return template
      .replace("{z}", String(z))
      .replace("{y}", String(y))
      .replace("{x}", String(x));
  }

  _renderPlanetaryVisibleTiles(state) {
    if (!state.active || document.hidden || !this.isConnected) return;
    const safe = this._safeId(state.key);
    const view = this.shadowRoot.getElementById(`planetary-view-${safe}`);
    const world = this.shadowRoot.getElementById(`planetary-world-${safe}`);
    if (!view || !world) return;

    const { tileSize, columns, rows } = this._planetaryDimensions(state);
    const startX = Math.max(0, Math.floor(view.scrollLeft / tileSize) - 1);
    const endX = Math.min(
      columns - 1,
      Math.floor((view.scrollLeft + view.clientWidth) / tileSize) + 1,
    );
    const startY = Math.max(0, Math.floor(view.scrollTop / tileSize) - 1);
    const endY = Math.min(
      rows - 1,
      Math.floor((view.scrollTop + view.clientHeight) / tileSize) + 1,
    );

    const wanted = new Set();
    for (let y = startY; y <= endY; y += 1) {
      for (let x = startX; x <= endX; x += 1) {
        const key = `${state.zoom}/${y}/${x}`;
        wanted.add(key);
        if (state.tiles.has(key)) continue;
        const url = this._planetaryTileUrl(state, state.zoom, y, x);
        if (!url) continue;
        const image = document.createElement("img");
        image.className = "planetary-tile";
        image.alt = "";
        image.loading = "eager";
        image.decoding = "async";
        image.draggable = false;
        image.dataset.tileKey = key;
        image.style.left = `${x * tileSize}px`;
        image.style.top = `${y * tileSize}px`;
        image.style.width = `${tileSize}px`;
        image.style.height = `${tileSize}px`;
        image.src = url;
        world.appendChild(image);
        state.tiles.set(key, image);
      }
    }

    for (const [key, image] of state.tiles.entries()) {
      if (wanted.has(key)) continue;
      image.remove();
      state.tiles.delete(key);
    }
  }

  _centerPlanetaryView(state) {
    const safe = this._safeId(state.key);
    const view = this.shadowRoot.getElementById(`planetary-view-${safe}`);
    if (!view) return;
    const { width, height } = this._planetaryDimensions(state);
    view.scrollLeft = Math.max(0, (width - view.clientWidth) / 2);
    view.scrollTop = Math.max(0, (height - view.clientHeight) / 2);
    this._renderPlanetaryVisibleTiles(state);
  }

  _changePlanetaryZoom(state, delta) {
    if (!state.active) return;
    const planetary = state.descriptor?.planetary;
    const minZoom = Number(planetary?.min_zoom ?? 0);
    const maxZoom = Number(planetary?.max_zoom ?? 8);
    const nextZoom = Math.min(maxZoom, Math.max(minZoom, state.zoom + delta));
    if (nextZoom === state.zoom) return;

    const safe = this._safeId(state.key);
    const view = this.shadowRoot.getElementById(`planetary-view-${safe}`);
    const world = this.shadowRoot.getElementById(`planetary-world-${safe}`);
    if (!view || !world) return;

    const old = this._planetaryDimensions(state);
    const centerX = (view.scrollLeft + view.clientWidth / 2) / old.width;
    const centerY = (view.scrollTop + view.clientHeight / 2) / old.height;

    for (const image of state.tiles.values()) image.remove();
    state.tiles.clear();
    state.zoom = nextZoom;

    const next = this._planetaryDimensions(state);
    world.style.width = `${next.width}px`;
    world.style.height = `${next.height}px`;

    requestAnimationFrame(() => {
      view.scrollLeft = Math.max(0, centerX * next.width - view.clientWidth / 2);
      view.scrollTop = Math.max(0, centerY * next.height - view.clientHeight / 2);
      this._updatePlanetaryCard(state);
      this._renderPlanetaryVisibleTiles(state);
    });
  }

  _stopPlanetaryView(state, reason="stop") {
    const wasActive = state.active;
    state.active = false;
    for (const image of state.tiles.values()) image.remove();
    state.tiles.clear();
    this._updatePlanetaryCard(state);
    if (wasActive) {
      this._wrLog?.("planetary_tile_stop", {
        provider: state.provider,
        capability: state.capability,
        reason,
      });
    }
  }

  _updatePlanetaryCard(state) {
    const safe = this._safeId(state.key);
    const view = this.shadowRoot.getElementById(`planetary-view-${safe}`);
    if (!view) return;
    const world = this.shadowRoot.getElementById(`planetary-world-${safe}`);
    const placeholder = this.shadowRoot.getElementById(`planetary-placeholder-${safe}`);
    const status = this.shadowRoot.getElementById(`planetary-status-${safe}`);
    const open = this.shadowRoot.getElementById(`planetary-open-${safe}`);
    const stop = this.shadowRoot.getElementById(`planetary-stop-${safe}`);
    const zoomOut = this.shadowRoot.getElementById(`planetary-zoom-out-${safe}`);
    const zoomIn = this.shadowRoot.getElementById(`planetary-zoom-in-${safe}`);
    const zoom = this.shadowRoot.getElementById(`planetary-zoom-${safe}`);
    const attribution = this.shadowRoot.getElementById(`planetary-attribution-${safe}`);
    const planetary = state.descriptor?.planetary;

    open.disabled = state.loading || state.active;
    stop.disabled = state.loading || !state.active;
    zoomOut.disabled = state.loading || !state.active || state.zoom <= Number(planetary?.min_zoom ?? 0);
    zoomIn.disabled = state.loading || !state.active || state.zoom >= Number(planetary?.max_zoom ?? 8);
    zoom.textContent = `Zoom ${state.zoom}`;
    attribution.textContent = state.descriptor?.attribution || state.providerName;

    if (state.loading) {
      status.textContent = "Mondkarte wird vorbereitet …";
      status.className = "media-sequence-status";
    } else if (state.error) {
      status.textContent = state.error;
      status.className = "media-sequence-status error";
    } else if (state.active) {
      status.textContent = "Mondkarte aktiv · ziehen/scrollen zum Verschieben.";
      status.className = "media-sequence-status ok";
    } else if (state.descriptor) {
      status.textContent = "Mondkarte bereit · derzeit geschlossen.";
      status.className = "media-sequence-status";
    } else {
      status.textContent = "Noch nicht geöffnet.";
      status.className = "media-sequence-status";
    }

    if (state.active && planetary) {
      placeholder.hidden = true;
      view.hidden = false;
      const dims = this._planetaryDimensions(state);
      world.style.width = `${dims.width}px`;
      world.style.height = `${dims.height}px`;
      requestAnimationFrame(() => {
        if (state.needsCenter) {
          state.needsCenter = false;
          this._centerPlanetaryView(state);
        } else {
          this._renderPlanetaryVisibleTiles(state);
        }
      });
    } else {
      view.hidden = true;
      placeholder.hidden = false;
      placeholder.textContent = state.error ? "Mondkarte nicht verfügbar" : "Mondkarte geschlossen";
    }
  }

  async _loadLiveStream(state, force=false) {
    if (!this._hass || state.loading) return;
    if (state.descriptor && !force) {
      state.active = true;
      this._updateLiveStreamCard(state);
      return;
    }

    this._stopLiveStream(state, "reload");
    state.loading = true;
    state.error = null;
    this._updateLiveStreamCard(state);
    this._wrLog?.("live_stream_load_start", {
      provider: state.provider,
      capability: state.capability,
    });

    try {
      const response = await this._hass.callWS({
        type: "weather_router/map_layer",
        provider: state.provider,
        capability: state.capability,
      });
      const descriptor = response?.layer;
      const embedUrl = descriptor?.stream?.embed_url;
      if (
        descriptor?.render_mode !== "live_stream"
        || typeof embedUrl !== "string"
        || !embedUrl.startsWith("https://www.youtube-nocookie.com/embed/")
      ) {
        throw new Error("Provider lieferte keinen unterstützten Livestream");
      }
      state.descriptor = descriptor;
      state.active = true;
      this._wrLog?.("live_stream_loaded", {
        provider: state.provider,
        capability: state.capability,
      });
    } catch (error) {
      state.descriptor = null;
      state.active = false;
      state.error = error?.message || String(error);
      this._wrLog?.("live_stream_load_failed", {
        provider: state.provider,
        capability: state.capability,
        error,
      }, "error");
    } finally {
      state.loading = false;
      this._updateLiveStreamCard(state);
    }
  }

  _stopLiveStream(state, reason="stop") {
    const wasActive = state.active;
    state.active = false;
    this._updateLiveStreamCard(state);
    if (wasActive) {
      this._wrLog?.("live_stream_stop", {
        provider: state.provider,
        capability: state.capability,
        reason,
      });
    }
  }

  _updateLiveStreamCard(state) {
    const safe = this._safeId(state.key);
    const iframe = this.shadowRoot.getElementById(`live-frame-${safe}`);
    if (!iframe) return;
    const placeholder = this.shadowRoot.getElementById(`live-placeholder-${safe}`);
    const status = this.shadowRoot.getElementById(`live-status-${safe}`);
    const open = this.shadowRoot.getElementById(`live-open-${safe}`);
    const stop = this.shadowRoot.getElementById(`live-stop-${safe}`);
    const refresh = this.shadowRoot.getElementById(`live-refresh-${safe}`);
    const embedUrl = state.descriptor?.stream?.embed_url;

    open.disabled = state.loading || state.active;
    stop.disabled = state.loading || !state.active;
    refresh.disabled = state.loading;

    if (state.loading) {
      status.textContent = "NASA-Livestream wird aufgelöst …";
      status.className = "media-sequence-status";
    } else if (state.error) {
      status.textContent = state.error;
      status.className = "media-sequence-status error";
    } else if (state.active) {
      status.textContent = state.descriptor?.attribution || state.providerName;
      status.className = "media-sequence-status ok";
    } else if (state.descriptor) {
      status.textContent = "Stream bereit · derzeit gestoppt.";
      status.className = "media-sequence-status";
    } else {
      status.textContent = "Noch nicht geöffnet.";
      status.className = "media-sequence-status";
    }

    if (state.active && typeof embedUrl === "string") {
      placeholder.hidden = true;
      iframe.hidden = false;
      if (iframe.dataset.embedUrl !== embedUrl) {
        iframe.dataset.embedUrl = embedUrl;
        iframe.src = embedUrl;
      }
    } else {
      iframe.hidden = true;
      iframe.removeAttribute("src");
      delete iframe.dataset.embedUrl;
      placeholder.hidden = false;
      placeholder.textContent = state.error ? "Livestream nicht verfügbar" : "Livestream gestoppt";
    }
  }

  _renderMediaSequences() {
    const host = this.shadowRoot.getElementById("media-sequence-list");
    if (!host) return;
    host.innerHTML = "";

    const states = [...this._mediaSequences.values()];
    const liveStates = [...this._liveStreams.values()];
    const planetaryStates = [...this._planetaryTiles.values()];
    if (!states.length && !liveStates.length && !planetaryStates.length) {
      host.className = "muted";
      host.textContent = "Noch keine Sonnen-/Weltraummedien verfügbar.";
      return;
    }
    host.className = "";

    const grouped = new Map();
    for (const state of states) {
      if (!grouped.has(state.provider)) grouped.set(state.provider, []);
      grouped.get(state.provider).push(state);
    }

    for (const [providerId, providerStates] of grouped.entries()) {
      const providerName = providerStates[0]?.providerName || providerId;
      const head = document.createElement("div");
      head.className = "media-provider-head";
      head.innerHTML = `
        <strong>${this._escape(providerName)}</strong>
        <button class="weather-provider-info" type="button" data-media-provider-info="${this._escape(providerId)}" title="Informationen zu ${this._escape(providerName)}">i</button>
      `;
      head.querySelector("[data-media-provider-info]").addEventListener("click", event => {
        event.preventDefault();
        this._providerInfoOpen(providerId);
      });
      host.appendChild(head);

      for (const state of providerStates) {
        const safe = this._safeId(state.key);
        const box = document.createElement("div");
        box.className = "media-sequence";
        box.innerHTML = `
          <div class="media-sequence-head">
            <span class="media-sequence-title">${this._escape(state.capabilityName)}</span>
            <button id="media-refresh-${safe}" type="button" title="Bildfolge neu laden">↻</button>
          </div>
          ${state.coverage ? `<div class="media-sequence-region">Region · ${this._escape(state.coverage)}</div>` : ""}
          <div class="media-image-wrap">
            <img id="media-image-${safe}" alt="${this._escape(state.capabilityName)}" hidden>
            <span id="media-placeholder-${safe}" class="muted">Noch nicht geladen</span>
          </div>
          <div id="media-status-${safe}" class="media-sequence-status"></div>
          <div class="media-sequence-actions">
            <button id="media-prev-${safe}" type="button" title="Vorheriger Frame">◀</button>
            <button id="media-play-${safe}" type="button">▶ Wiedergabe</button>
            <button id="media-load-${safe}" type="button" class="primary">Laden</button>
            <button id="media-next-${safe}" type="button" title="Nächster Frame">▶</button>
            <button id="media-latest-${safe}" type="button">Neueste</button>
          </div>
          <input id="media-range-${safe}" class="media-sequence-range" type="range" min="0" max="0" value="0" step="1" disabled>
          <div class="media-sequence-meta">
            <span id="media-index-${safe}">0/0</span>
            <span id="media-time-${safe}">—</span>
          </div>
        `;

        box.querySelector(`#media-load-${safe}`).addEventListener("click", () => this._loadMediaSequence(state, false));
        box.querySelector(`#media-refresh-${safe}`).addEventListener("click", () => this._loadMediaSequence(state, true));
        box.querySelector(`#media-prev-${safe}`).addEventListener("click", () => {
          this._stopMediaPlayback(state, "manual_navigation");
          this._setMediaFrame(state, state.index - 1);
        });
        box.querySelector(`#media-next-${safe}`).addEventListener("click", () => {
          this._stopMediaPlayback(state, "manual_navigation");
          this._setMediaFrame(state, state.index + 1);
        });
        box.querySelector(`#media-latest-${safe}`).addEventListener("click", () => {
          this._stopMediaPlayback(state, "latest");
          const frames = state.descriptor?.timeline?.frames || [];
          this._setMediaFrame(state, Math.max(0, frames.length - 1));
        });
        box.querySelector(`#media-play-${safe}`).addEventListener("click", () => {
          if (state.playing) this._stopMediaPlayback(state, "user");
          else this._startMediaPlayback(state);
        });
        box.querySelector(`#media-range-${safe}`).addEventListener("input", event => {
          this._stopMediaPlayback(state, "range");
          this._setMediaFrame(state, Number(event.target.value));
        });

        host.appendChild(box);
        this._updateMediaSequenceCard(state);
      }
    }

    const groupedLive = new Map();
    for (const state of liveStates) {
      if (!groupedLive.has(state.provider)) groupedLive.set(state.provider, []);
      groupedLive.get(state.provider).push(state);
    }

    for (const [providerId, providerStates] of groupedLive.entries()) {
      const providerName = providerStates[0]?.providerName || providerId;
      const head = document.createElement("div");
      head.className = "media-provider-head";
      head.innerHTML = `
        <strong>${this._escape(providerName)}</strong>
        <button class="weather-provider-info" type="button" data-live-provider-info="${this._escape(providerId)}" title="Informationen zu ${this._escape(providerName)}">i</button>
      `;
      head.querySelector("[data-live-provider-info]").addEventListener("click", event => {
        event.preventDefault();
        this._providerInfoOpen(providerId);
      });
      host.appendChild(head);

      for (const state of providerStates) {
        const safe = this._safeId(state.key);
        const box = document.createElement("div");
        box.className = "media-sequence";
        box.innerHTML = `
          <div class="media-sequence-head">
            <span class="media-sequence-title">${this._escape(state.capabilityName)}</span>
          </div>
          ${state.coverage ? `<div class="media-sequence-region">Region · ${this._escape(state.coverage)}</div>` : ""}
          <div class="live-stream-wrap">
            <iframe
              id="live-frame-${safe}"
              title="${this._escape(state.capabilityName)}"
              allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
              referrerpolicy="strict-origin-when-cross-origin"
              allowfullscreen
              hidden></iframe>
            <span id="live-placeholder-${safe}" class="muted">Noch nicht geöffnet</span>
          </div>
          <div id="live-status-${safe}" class="media-sequence-status"></div>
          <div class="live-stream-actions">
            <button id="live-open-${safe}" type="button" class="primary">Live öffnen</button>
            <button id="live-stop-${safe}" type="button">Stoppen</button>
            <button id="live-refresh-${safe}" type="button">Neu auflösen</button>
          </div>
        `;
        box.querySelector(`#live-open-${safe}`).addEventListener("click", () => this._loadLiveStream(state, false));
        box.querySelector(`#live-stop-${safe}`).addEventListener("click", () => this._stopLiveStream(state, "user"));
        box.querySelector(`#live-refresh-${safe}`).addEventListener("click", () => this._loadLiveStream(state, true));
        host.appendChild(box);
        this._updateLiveStreamCard(state);
      }
    }

    const groupedPlanetary = new Map();
    for (const state of planetaryStates) {
      if (!groupedPlanetary.has(state.provider)) groupedPlanetary.set(state.provider, []);
      groupedPlanetary.get(state.provider).push(state);
    }

    for (const [providerId, providerStates] of groupedPlanetary.entries()) {
      const providerName = providerStates[0]?.providerName || providerId;
      const head = document.createElement("div");
      head.className = "media-provider-head";
      head.innerHTML = `
        <strong>${this._escape(providerName)}</strong>
        <button class="weather-provider-info" type="button" data-planetary-provider-info="${this._escape(providerId)}" title="Informationen zu ${this._escape(providerName)}">i</button>
      `;
      head.querySelector("[data-planetary-provider-info]").addEventListener("click", event => {
        event.preventDefault();
        this._providerInfoOpen(providerId);
      });
      host.appendChild(head);

      for (const state of providerStates) {
        const safe = this._safeId(state.key);
        const box = document.createElement("div");
        box.className = "media-sequence";
        box.innerHTML = `
          <div class="media-sequence-head">
            <span class="media-sequence-title">${this._escape(state.capabilityName)}</span>
          </div>
          ${state.coverage ? `<div class="media-sequence-region">Region · ${this._escape(state.coverage)}</div>` : ""}
          <div id="planetary-placeholder-${safe}" class="live-stream-wrap"><span class="muted">Mondkarte geschlossen</span></div>
          <div id="planetary-view-${safe}" class="planetary-view" hidden>
            <div id="planetary-world-${safe}" class="planetary-world"></div>
          </div>
          <div id="planetary-status-${safe}" class="media-sequence-status"></div>
          <div class="planetary-actions">
            <button id="planetary-zoom-out-${safe}" type="button" title="Herauszoomen">−</button>
            <button id="planetary-stop-${safe}" type="button">Schließen</button>
            <button id="planetary-open-${safe}" type="button" class="primary">Mond öffnen</button>
            <button id="planetary-center-${safe}" type="button">Zentrieren</button>
            <button id="planetary-zoom-in-${safe}" type="button" title="Hineinzoomen">+</button>
          </div>
          <div class="planetary-meta">
            <span id="planetary-zoom-${safe}">Zoom ${state.zoom}</span>
            <span id="planetary-attribution-${safe}">${this._escape(state.providerName)}</span>
          </div>
        `;

        const view = box.querySelector(`#planetary-view-${safe}`);
        view.addEventListener("scroll", () => {
          if (!state.active) return;
          requestAnimationFrame(() => this._renderPlanetaryVisibleTiles(state));
        }, { passive: true });
        box.querySelector(`#planetary-open-${safe}`).addEventListener("click", () => this._loadPlanetaryTile(state, false));
        box.querySelector(`#planetary-stop-${safe}`).addEventListener("click", () => this._stopPlanetaryView(state, "user"));
        box.querySelector(`#planetary-center-${safe}`).addEventListener("click", () => this._centerPlanetaryView(state));
        box.querySelector(`#planetary-zoom-out-${safe}`).addEventListener("click", () => this._changePlanetaryZoom(state, -1));
        box.querySelector(`#planetary-zoom-in-${safe}`).addEventListener("click", () => this._changePlanetaryZoom(state, 1));
        host.appendChild(box);
        this._updatePlanetaryCard(state);
      }
    }
  }

  async _loadMediaSequence(state, force=false) {
    if (!this._hass || state.loading) return;
    if (state.descriptor && !force) {
      this._updateMediaSequenceCard(state);
      return;
    }
    this._stopMediaPlayback(state, "reload");
    state.loading = true;
    state.error = null;
    this._updateMediaSequenceCard(state);
    this._wrLog?.("media_sequence_load_start", {
      provider: state.provider,
      capability: state.capability,
    });

    try {
      const response = await this._hass.callWS({
        type: "weather_router/map_layer",
        provider: state.provider,
        capability: state.capability,
      });
      const descriptor = response?.layer;
      const frames = descriptor?.timeline?.frames;
      if (
        descriptor?.render_mode !== "image_sequence"
        || !Array.isArray(frames)
        || !frames.length
      ) {
        throw new Error("Provider lieferte keine nutzbare Bildfolge");
      }
      const safeFrames = frames.filter(frame => (
        frame
        && typeof frame.time === "string"
        && typeof frame.image_url === "string"
        && frame.image_url.startsWith("https://")
      ));
      if (!safeFrames.length) throw new Error("Bildfolge enthält keine sicheren Frames");
      descriptor.timeline.frames = safeFrames;
      state.descriptor = descriptor;
      state.index = Math.min(
        Math.max(0, Number(descriptor.timeline.default_index ?? safeFrames.length - 1)),
        safeFrames.length - 1,
      );
      this._wrLog?.("media_sequence_loaded", {
        provider: state.provider,
        capability: state.capability,
        frame_count: safeFrames.length,
      });
      this._preloadNextMediaFrame(state);
    } catch (error) {
      state.descriptor = null;
      state.error = error?.message || String(error);
      this._wrLog?.("media_sequence_load_failed", {
        provider: state.provider,
        capability: state.capability,
        error,
      }, "error");
    } finally {
      state.loading = false;
      this._updateMediaSequenceCard(state);
    }
  }

  _mediaFrames(state) {
    const frames = state.descriptor?.timeline?.frames;
    return Array.isArray(frames) ? frames : [];
  }

  _setMediaFrame(state, index) {
    const frames = this._mediaFrames(state);
    if (!frames.length) return;
    const next = Math.min(Math.max(0, Number(index) || 0), frames.length - 1);
    state.index = next;
    this._updateMediaSequenceCard(state);
    this._preloadNextMediaFrame(state);
  }

  _preloadNextMediaFrame(state) {
    if (!state.playing && !state.descriptor) return;
    const frames = this._mediaFrames(state);
    if (frames.length < 2) return;
    const nextIndex = (state.index + 1) % frames.length;
    const url = frames[nextIndex]?.image_url;
    if (typeof url !== "string") return;
    const image = new Image();
    image.decoding = "async";
    image.src = url;
  }

  _startMediaPlayback(state) {
    const frames = this._mediaFrames(state);
    if (frames.length < 2 || state.playing) return;
    this._stopMediaSequencePlayback("switch_sequence");
    state.playing = true;
    state.timer = window.setInterval(() => {
      if (!state.playing || document.hidden || !this.isConnected) {
        this._stopMediaPlayback(state, "inactive");
        return;
      }
      const currentFrames = this._mediaFrames(state);
      if (!currentFrames.length) {
        this._stopMediaPlayback(state, "empty");
        return;
      }
      state.index = (state.index + 1) % currentFrames.length;
      this._updateMediaSequenceCard(state);
      this._preloadNextMediaFrame(state);
    }, 700);
    this._wrLog?.("media_sequence_playback_start", {
      provider: state.provider,
      capability: state.capability,
      frame_count: frames.length,
    });
    this._updateMediaSequenceCard(state);
  }

  _stopMediaPlayback(state, reason="stop") {
    if (state.timer !== null) {
      window.clearInterval(state.timer);
      state.timer = null;
    }
    if (!state.playing) return;
    state.playing = false;
    this._wrLog?.("media_sequence_playback_stop", {
      provider: state.provider,
      capability: state.capability,
      reason,
    });
    this._updateMediaSequenceCard(state);
  }

  _stopMediaSequencePlayback(reason="stop_sequences") {
    for (const state of this._mediaSequences.values()) {
      this._stopMediaPlayback(state, reason);
    }
  }

  _stopAllMediaPlayback(reason="stop_all") {
    this._stopMediaSequencePlayback(reason);
    for (const state of this._liveStreams.values()) {
      this._stopLiveStream(state, reason);
    }
    for (const state of this._planetaryTiles.values()) {
      this._stopPlanetaryView(state, reason);
    }
  }

  _updateMediaSequenceCard(state) {
    const safe = this._safeId(state.key);
    const image = this.shadowRoot.getElementById(`media-image-${safe}`);
    if (!image) return;
    const placeholder = this.shadowRoot.getElementById(`media-placeholder-${safe}`);
    const status = this.shadowRoot.getElementById(`media-status-${safe}`);
    const load = this.shadowRoot.getElementById(`media-load-${safe}`);
    const refresh = this.shadowRoot.getElementById(`media-refresh-${safe}`);
    const prev = this.shadowRoot.getElementById(`media-prev-${safe}`);
    const play = this.shadowRoot.getElementById(`media-play-${safe}`);
    const next = this.shadowRoot.getElementById(`media-next-${safe}`);
    const latest = this.shadowRoot.getElementById(`media-latest-${safe}`);
    const range = this.shadowRoot.getElementById(`media-range-${safe}`);
    const index = this.shadowRoot.getElementById(`media-index-${safe}`);
    const time = this.shadowRoot.getElementById(`media-time-${safe}`);

    const frames = this._mediaFrames(state);
    const frame = frames[state.index];

    load.hidden = Boolean(frames.length);
    load.disabled = state.loading;
    refresh.disabled = state.loading;
    prev.disabled = !frames.length || state.index <= 0 || state.loading;
    next.disabled = !frames.length || state.index >= frames.length - 1 || state.loading;
    latest.disabled = !frames.length || state.index >= frames.length - 1 || state.loading;
    play.disabled = frames.length < 2 || state.loading;
    play.textContent = state.playing ? "⏸ Pause" : "▶ Wiedergabe";

    if (state.loading) {
      status.textContent = "Bildfolge wird geladen …";
      status.className = "media-sequence-status";
    } else if (state.error) {
      status.textContent = state.error;
      status.className = "media-sequence-status error";
    } else if (frames.length) {
      status.textContent = `${frames.length} Frames · ${this._escape(state.descriptor?.attribution || state.providerName)}`;
      status.className = "media-sequence-status ok";
    } else {
      status.textContent = "Noch keine Daten abgerufen.";
      status.className = "media-sequence-status";
    }

    range.disabled = !frames.length || state.loading;
    range.max = String(Math.max(0, frames.length - 1));
    range.value = String(Math.min(state.index, Math.max(0, frames.length - 1)));
    index.textContent = frames.length ? `${state.index + 1}/${frames.length}` : "0/0";
    time.textContent = frame?.time ? this._formatMediaTime(frame.time) : "—";

    if (frame?.image_url) {
      image.hidden = false;
      placeholder.hidden = true;
      if (image.dataset.frameUrl !== frame.image_url) {
        image.dataset.frameUrl = frame.image_url;
        image.src = frame.image_url;
      }
    } else {
      image.hidden = true;
      image.removeAttribute("src");
      delete image.dataset.frameUrl;
      placeholder.hidden = false;
      placeholder.textContent = state.error ? "Bildfolge nicht verfügbar" : "Noch nicht geladen";
    }
  }

  _formatMediaTime(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value || "—");
    return parsed.toLocaleString("de-DE", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  _renderWeatherLayers() {
    const host = this.shadowRoot.getElementById("weather-layer-list");
    if (!host) return;
    host.innerHTML = "";

    const layers = [...this._weatherLayers.values()];
    if (!layers.length) {
      host.className = "muted";
      host.textContent = "Noch keine räumlichen Kartenebenen verfügbar.";
      return;
    }
    host.className = "";

    if (this._providers.length) {
      const directory = document.createElement("details");
      directory.className = "provider-info-directory";
      directory.innerHTML = `
        <summary>Anbieterinformationen · <span style="color:#d4af37">ⓘ</span></summary>
        <div class="provider-info-directory-body">
          ${[...this._providers]
            .sort((a, b) => a.name.localeCompare(b.name, "de"))
            .map(provider => `
              <span class="provider-info-chip">
                <span>${this._escape(provider.name)}</span>
                <button class="weather-provider-info" type="button" data-provider-info="${this._escape(provider.id)}" title="Informationen zu ${this._escape(provider.name)}">i</button>
              </span>
            `).join("")}
        </div>
      `;
      directory.querySelectorAll("[data-provider-info]").forEach(button => {
        button.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          this._providerInfoOpen(button.dataset.providerInfo);
        });
      });
      host.appendChild(directory);
    }

    const providers = [...new Map(
      layers.map(state => [state.provider, state.providerName])
    ).entries()].sort((a, b) => a[1].localeCompare(b[1], "de"));

    if (
      this._weatherLayerProviderFilter !== "all"
      && !providers.some(([id]) => id === this._weatherLayerProviderFilter)
    ) {
      this._weatherLayerProviderFilter = "all";
    }

    const providerScoped = this._weatherLayerProviderFilter === "all"
      ? layers
      : layers.filter(state => state.provider === this._weatherLayerProviderFilter);

    const capabilityNames = [...new Set(
      providerScoped.map(state => state.capabilityName)
    )].sort((a, b) => a.localeCompare(b, "de"));

    if (
      this._weatherLayerCapabilityFilter !== "all"
      && !capabilityNames.includes(this._weatherLayerCapabilityFilter)
    ) {
      this._weatherLayerCapabilityFilter = "all";
    }

    const toolbar = document.createElement("div");
    toolbar.className = "weather-layer-toolbar";
    toolbar.innerHTML = `
      <div>
        <label for="weather-provider-filter">Anbieter</label>
        <select id="weather-provider-filter">
          <option value="all">Alle Anbieter</option>
          ${providers.map(([id, name]) =>
            `<option value="${this._escape(id)}" ${this._weatherLayerProviderFilter === id ? "selected" : ""}>${this._escape(name)}</option>`
          ).join("")}
        </select>
      </div>
      <div>
        <label for="weather-capability-filter">Kartenebene</label>
        <select id="weather-capability-filter">
          <option value="all">Alle Ebenen</option>
          ${capabilityNames.map(name =>
            `<option value="${this._escape(name)}" ${this._weatherLayerCapabilityFilter === name ? "selected" : ""}>${this._escape(name)}</option>`
          ).join("")}
        </select>
      </div>
      <label class="compact-check">
        <input id="weather-active-filter" type="checkbox" ${this._weatherLayerOnlyActive ? "checked" : ""}>
        Nur aktive
      </label>
    `;
    host.appendChild(toolbar);

    toolbar.querySelector("#weather-provider-filter").addEventListener("change", event => {
      this._weatherLayerProviderFilter = event.target.value;
      this._weatherLayerCapabilityFilter = "all";
      this._renderWeatherLayers();
    });
    toolbar.querySelector("#weather-capability-filter").addEventListener("change", event => {
      this._weatherLayerCapabilityFilter = event.target.value;
      this._renderWeatherLayers();
    });
    toolbar.querySelector("#weather-active-filter").addEventListener("change", event => {
      this._weatherLayerOnlyActive = event.target.checked;
      this._renderWeatherLayers();
    });

    let visible = providerScoped;
    if (this._weatherLayerCapabilityFilter !== "all") {
      visible = visible.filter(
        state => state.capabilityName === this._weatherLayerCapabilityFilter
      );
    }
    if (this._weatherLayerOnlyActive) {
      visible = visible.filter(
        state => state.enabled || state.loading
      );
    }

    const activeCount = layers.filter(state => state.enabled).length;
    const count = document.createElement("div");
    count.className = "weather-layer-count";
    count.textContent = `${activeCount} aktiv · ${visible.length} angezeigt · ${layers.length} verfügbar`;
    host.appendChild(count);

    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "muted";
      empty.style.fontSize = "12px";
      empty.textContent = "Für diese Filterauswahl sind keine Wetterebenen sichtbar.";
      host.appendChild(empty);
      return;
    }

    const grouped = new Map();
    for (const state of visible) {
      if (!grouped.has(state.provider)) grouped.set(state.provider, []);
      grouped.get(state.provider).push(state);
    }

    const providerGrid = document.createElement("div");
    providerGrid.className = "weather-provider-grid";
    host.appendChild(providerGrid);

    for (const [providerId, states] of grouped.entries()) {
      const providerName = states[0]?.providerName || providerId;
      const providerActive = states.filter(state => state.enabled).length;
      const providerNeedsAttention = states.some(
        state => state.enabled || state.loading || state.error
      );

      const group = document.createElement("details");
      group.className = "weather-provider-group";
      group.open = (
        this._weatherLayerProviderFilter !== "all"
        || providerNeedsAttention
        || grouped.size === 1
      );

      const summary = document.createElement("summary");
      summary.innerHTML = `
        <span>${this._escape(providerName)}</span>
        <span class="weather-provider-group-meta">${providerActive} aktiv · ${states.length} Ebenen</span>
      `;
      group.appendChild(summary);

      const infoButton = document.createElement("button");
      infoButton.className = "weather-provider-info";
      infoButton.type = "button";
      infoButton.textContent = "i";
      infoButton.title = `Informationen zu ${providerName}`;
      infoButton.addEventListener("click", event => {
        event.preventDefault();
        event.stopPropagation();
        this._providerInfoOpen(providerId);
      });
      group.appendChild(infoButton);

      const body = document.createElement("div");
      body.className = "weather-provider-group-body";

      for (const state of states) {
        const safe = this._safeId(state.key);
        const box = document.createElement("div");
        box.className = "weather-layer";
        box.innerHTML = `
          <div class="weather-layer-head">
            <label class="weather-layer-toggle">
              <input id="weather-enabled-${safe}" type="checkbox" ${state.enabled ? "checked" : ""} ${state.loading ? "disabled" : ""}>
              <span>${this._escape(state.capabilityName)}</span>
            </label>
            <div style="display:flex;align-items:center;gap:6px">
              <button id="weather-refresh-${safe}" class="weather-refresh" title="Layer aktualisieren" ${state.loading ? "disabled" : ""}>↻</button>
            </div>
          </div>
          ${state.coverage ? `<div class="weather-layer-region">Region · ${this._escape(state.coverage)}</div>` : ""}
          <div id="weather-status-${safe}" class="weather-status ${state.error ? "error" : state.enabled && state.descriptor ? "ok" : ""}">${this._weatherLayerStatusText(state)}</div>
          <div class="weather-opacity">
            <span>Deckkraft</span>
            <input id="weather-opacity-${safe}" type="range" min="10" max="100" step="5" value="${state.opacity}" ${state.enabled ? "" : "disabled"}>
            <span id="weather-opacity-value-${safe}">${state.opacity}%</span>
          </div>`;

        const enabled = box.querySelector(`#weather-enabled-${safe}`);
        const opacity = box.querySelector(`#weather-opacity-${safe}`);
        const refresh = box.querySelector(`#weather-refresh-${safe}`);

        enabled.addEventListener("change", async event => {
          state.enabled = event.target.checked;
          state.error = null;
          this._wrLog?.("layer_toggle", {
            enabled: state.enabled,
          }, "info", state);
          if (state.enabled) await this._loadWeatherLayer(state, true);
          else this._removeWeatherLayerFromMap(state);
          this._renderWeatherLayers();
        });

        opacity.addEventListener("input", event => {
          state.opacity = Number(event.target.value);
          box.querySelector(`#weather-opacity-value-${safe}`).textContent = `${state.opacity}%`;
          const ids = this._weatherLayerIds(state);
          if (this._map?.getLayer(ids.layer)) {
            this._map.setPaintProperty(ids.layer, "raster-opacity", state.opacity / 100);
          }
        });
        opacity.addEventListener("change", () => {
          this._wrLog?.("opacity_changed", {
            opacity: state.opacity,
          }, "info", state);
        });

        refresh.addEventListener("click", async () => {
          this._wrLog?.("layer_refresh_requested", {
            enabled_before: Boolean(state.enabled),
          }, "info", state);
          if (!state.enabled) state.enabled = true;
          await this._loadWeatherLayer(state, true);
          this._renderWeatherLayers();
        });

        body.appendChild(box);
      }

      group.appendChild(body);
      providerGrid.appendChild(group);
    }
  }

  _weatherLayerStatusText(state) {
    if (state.loading) return "Layerdaten werden geladen …";
    if (state.error) return `Fehler: ${state.error}`;
    if (!state.enabled) return "Aus";
    if (!state.descriptor) return "Bereit zum Laden";
    const time = this._formatEpoch(state.descriptor.frame_time);
    return time ? `Aktiv · Datenstand ${time}` : "Aktiv";
  }

  _weatherLayerIds(state) {
    const safe = this._safeId(state.key);
    return {
      source: `weather-source-${safe}`,
      layer: `weather-layer-${safe}`,
    };
  }

  async _loadWeatherLayer(state, refresh = false) {
    if (!this._hass || !this._map || state.loading) return;
    if (state.descriptor && !refresh) {
      this._addWeatherLayerToMap(state);
      return;
    }

    state.loading = true;
    state.error = null;
    this._renderWeatherLayers();
    try {
      const response = await this._hass.callWS({
        type: "weather_router/map_layer",
        provider: state.provider,
        capability: state.capability,
      });
      const descriptor = response?.layer;
      if (!descriptor?.tile_url || descriptor.render_mode !== "raster_tile") {
        throw new Error("ungültige Layerdefinition");
      }
      state.descriptor = descriptor;
      if (Number.isFinite(Number(descriptor.default_opacity)) && state.opacity === 65) {
        state.opacity = Math.round(Number(descriptor.default_opacity) * 100);
      }
      this._addWeatherLayerToMap(state);
    } catch (error) {
      state.error = error?.message || String(error);
      state.enabled = false;
      this._removeWeatherLayerFromMap(state);
    } finally {
      state.loading = false;
    }
  }

  _addWeatherLayerToMap(state) {
    if (!this._map || !state.enabled || !state.descriptor || !this._map.isStyleLoaded()) return;
    const ids = this._weatherLayerIds(state);
    if (this._map.getLayer(ids.layer)) this._map.removeLayer(ids.layer);
    if (this._map.getSource(ids.source)) this._map.removeSource(ids.source);

    this._map.addSource(ids.source, {
      type: "raster",
      tiles: [state.descriptor.tile_url],
      tileSize: Number(state.descriptor.tile_size) || 256,
      maxzoom: Number(state.descriptor.max_zoom) || 7,
      attribution: state.descriptor.attribution || state.providerName,
    });
    this._map.addLayer({
      id: ids.layer,
      type: "raster",
      source: ids.source,
      paint: {
        "raster-opacity": state.opacity / 100,
        "raster-fade-duration": 0,
      },
    });
  }

  _removeWeatherLayerFromMap(state) {
    if (!this._map) return;
    const ids = this._weatherLayerIds(state);
    if (this._map.getLayer(ids.layer)) this._map.removeLayer(ids.layer);
    if (this._map.getSource(ids.source)) this._map.removeSource(ids.source);
  }

  _restoreWeatherLayers() {
    for (const state of this._weatherLayers.values()) {
      if (state.enabled && state.descriptor) this._addWeatherLayerToMap(state);
    }
  }

  async _ensureProviderCatalog() {
    if (!this._hass || this._providers.length) return;
    try {
      const response = await this._hass.callWS({ type: "weather_router/providers" });
      this._providers = response.providers || [];
      this._wrLog?.("provider_catalog_loaded", {
        provider_count: this._providers.length,
        eligible_provider_count: this._providers.filter(provider => provider.eligible !== false).length,
        router_enabled: response.router_enabled !== false,
        raster_capability_count: this._providers.reduce(
          (sum, provider) => sum + (provider.capabilities || []).filter(
            capability => capability.render_mode === "raster_tile"
          ).length,
          0
        ),
        image_sequence_capability_count: this._providers.reduce(
          (sum, provider) => sum + (provider.capabilities || []).filter(
            capability => capability.render_mode === "image_sequence"
          ).length,
          0
        ),
        live_stream_capability_count: this._providers.reduce(
          (sum, provider) => sum + (provider.capabilities || []).filter(
            capability => capability.render_mode === "live_stream"
          ).length,
          0
        ),
        planetary_tile_capability_count: this._providers.reduce(
          (sum, provider) => sum + (provider.capabilities || []).filter(
            capability => capability.render_mode === "planetary_tile"
          ).length,
          0
        ),
        hazard_feed_capability_count: this._providers.reduce(
          (sum, provider) => sum + (provider.capabilities || []).filter(
            capability => capability.render_mode === "hazard_feed"
          ).length,
          0
        ),
      });
      this._syncWeatherLayerStates();
      this._syncMediaSequenceStates();
      this._syncLiveStreamStates();
      this._syncPlanetaryTileStates();
      this._renderWeatherLayers();
      this._renderMediaSequences();
      this._renderRequests();
      this.shadowRoot.getElementById("run").disabled = !this._valueProviders().length;
    } catch (error) {
      this._wrLog?.("provider_catalog_failed", { error }, "error");
      this.shadowRoot.getElementById("results").innerHTML = `<span class="error">Provider-Katalog nicht verfügbar: ${this._escape(error?.message || String(error))}</span>`;
      const layerHost = this.shadowRoot.getElementById("weather-layer-list");
      if (layerHost) layerHost.innerHTML = `<span class="error">Wetterebenen nicht verfügbar: ${this._escape(error?.message || String(error))}</span>`;
      const mediaHost = this.shadowRoot.getElementById("media-sequence-list");
      if (mediaHost) mediaHost.innerHTML = `<span class="error">Medien nicht verfügbar: ${this._escape(error?.message || String(error))}</span>`;
    }
  }

  _renderRequests() {
    const host = this.shadowRoot.getElementById("request-list");
    if (!host) return;
    host.innerHTML = "";
    const providers = this._valueProviders();
    this._requests.forEach((request, index) => {
      const provider = providers.find(item => item.id === request.provider) || providers[0];
      if (provider && !providers.find(item => item.id === request.provider)) request.provider = provider.id;
      const capabilities = (provider?.capabilities || []).filter(
        item => item.render_mode === "value" && item.eligible !== false
      );
      if (capabilities.length && !capabilities.find(item => item.id === request.capability)) request.capability = capabilities[0].id;

      const row = document.createElement("div");
      row.className = "request-row";
      row.innerHTML = `<div><label>Provider</label><select class="provider"></select></div><div><label>Information</label><select class="capability"></select></div><button title="Entfernen">×</button>`;
      const providerSelect = row.querySelector(".provider");
      for (const item of providers) providerSelect.add(new Option(item.name, item.id, false, item.id === request.provider));
      const capabilitySelect = row.querySelector(".capability");
      for (const item of capabilities) capabilitySelect.add(new Option(item.name, item.id, false, item.id === request.capability));

      providerSelect.addEventListener("change", e => {
        request.provider = e.target.value;
        const selected = providers.find(item => item.id === request.provider);
        request.capability = selected?.capabilities?.find(
          item => item.render_mode === "value" && item.eligible !== false
        )?.id || "";
        this._renderRequests();
      });
      capabilitySelect.addEventListener("change", e => request.capability = e.target.value);
      row.querySelector("button").addEventListener("click", () => { this._requests.splice(index,1); this._renderRequests(); });
      host.appendChild(row);
    });
  }

  async _runDiagnostics() {
    if (!this._hass || this._loading) return;
    const point = this._diagnosticPoint();
    if (!point) {
      this.shadowRoot.getElementById("results").innerHTML = '<span class="error">Der gewählte Diagnose-Standort hat keine nutzbaren Koordinaten.</span>';
      return;
    }
    const grouped = new Map();
    for (const row of this._requests) {
      if (!row.provider || !row.capability) continue;
      if (!grouped.has(row.provider)) grouped.set(row.provider, new Set());
      grouped.get(row.provider).add(row.capability);
    }
    const requests = [...grouped].map(([provider, capabilities]) => ({ provider, capabilities:[...capabilities] }));
    this._loading = true;
    const button = this.shadowRoot.getElementById("run");
    button.disabled = true; button.textContent = "Lade …";
    try {
      this._results = await this._hass.callWS({ type:"weather_router/diagnostic_query", latitude:point.latitude, longitude:point.longitude, requests });
      this._renderResults();
    } catch (error) {
      this.shadowRoot.getElementById("results").innerHTML = `<span class="error">Abfrage fehlgeschlagen: ${this._escape(error?.message || String(error))}</span>`;
    } finally {
      this._loading = false; button.disabled = false; button.textContent = "Abrufen";
    }
  }

  _renderResults() {
    const host = this.shadowRoot.getElementById("results");
    host.innerHTML = "";
    const byProvider = new Map((this._results?.results || []).map(item => [item.provider,item]));
    for (const request of this._requests) {
      const providerMeta = this._providers.find(item => item.id === request.provider);
      const capabilityMeta = providerMeta?.capabilities.find(item => item.id === request.capability);
      const result = byProvider.get(request.provider);
      const box = document.createElement("div"); box.className = "result";
      if (!result?.ok) {
        box.innerHTML = `<strong>${this._escape(capabilityMeta?.name || request.capability)}</strong><small>${this._escape(providerMeta?.name || request.provider)}</small><div class="error">${this._escape(result?.error || "kein Ergebnis")}</div>`;
      } else if (result.coverage_status === "outside_coverage" || result.available === false) {
        box.innerHTML = `<strong>${this._escape(capabilityMeta?.name || request.capability)}</strong><small>${this._escape(result.provider_name || providerMeta?.name || request.provider)} · ${this._escape(result.source_class || capabilityMeta?.source_class || "")}</small><div class="muted" style="margin-top:5px">${this._escape(result.reason || "Außerhalb der Provider-Abdeckung.")}</div>`;
      } else {
        const value = result.values?.[request.capability];
        box.innerHTML = `<strong>${this._escape(capabilityMeta?.name || request.capability)}</strong><small>${this._escape(result.provider_name)} · ${this._escape(result.source_class)} · ${this._escape(result.data_time || "Zeit unbekannt")}</small><div class="value">${this._escape(value?.value ?? "—")} ${this._escape(value?.unit || capabilityMeta?.unit || "")}</div>`;
      }
      host.appendChild(box);
    }
    this.shadowRoot.getElementById("raw").textContent = JSON.stringify(this._results,null,2);
  }

  _ensureMap() {
    if (this._map || !this.isConnected) return;
    this._setMapStatus("Karte lädt …");
    this._map = new maplibregl.Map({
      container: this.shadowRoot.getElementById("map"),
      center: [10,51],
      zoom: 4.5,
      attributionControl: true,
      style: this._selectedMapStyle(),
    });
    this._map.addControl(new maplibregl.NavigationControl(),"top-right");
    this._map.on("load",() => {
      this._setMapStatus("synchron", "ok");
      this._syncFromHass(true);
      this._restoreWeatherLayers();
    });
    this._map.on("error", event => {
      const message = event?.error?.message || "unbekannter Kartenfehler";
      this._setMapStatus(`Kartenfehler: ${message}`, "error");
    });
  }

  _applyBasemap() {
    if (!this._map) return;
    const center = this._map.getCenter();
    const zoom = this._map.getZoom();
    const bearing = this._map.getBearing();
    const pitch = this._map.getPitch();
    this._setMapStatus("Kartenstil lädt …");
    const onStyleLoad = () => {
      this._map.jumpTo({ center, zoom, bearing, pitch });
      this._setMapStatus("synchron", "ok");

      // A basemap change must not be treated as a reference-location change.
      // Preserve the exact viewport; forcing the reference sync here used to
      // start a second 650 ms easeTo() while timeline staging was rebuilding.
      this._syncFromHass(false);
      this._restoreWeatherLayers();
    };

    try {
      // Register before setStyle(). Very small/local styles can finish quickly,
      // and the restore hook must never miss their style.load event.
      this._map.once("style.load", onStyleLoad);
      this._map.setStyle(this._selectedMapStyle());
    } catch (error) {
      this._map.off("style.load", onStyleLoad);
      this._setMapStatus(`Kartenstil fehlgeschlagen: ${error?.message || String(error)}`, "error");
    }
  }

  async _setReference(option) {
    if (!this._hass) return;
    try { await this._hass.callService("select","select_option",{ entity_id:SELECT_ENTITY, option }); }
    catch (error) { console.error("WeatherRouter Lab reference selection failed",error); }
  }

  _syncFromHass(force=false) {
    if (!this._hass) return;
    const selectState=this._hass.states[SELECT_ENTITY]; const select=this.shadowRoot.getElementById("reference");
    if (!selectState) { select.innerHTML="<option>WeatherRouter-Select nicht gefunden</option>"; select.disabled=true; return; }
    const options=Array.isArray(selectState.attributes.options)?selectState.attributes.options:[];
    const signature=`${selectState.state}|${options.join("|")}`;
    if (force || select.dataset.signature!==signature) {
      select.innerHTML="";
      for (const option of options) select.add(new Option(this._friendlyLocationName(option),option,false,option===selectState.state));
      select.disabled=false; select.dataset.signature=signature;
    }
    const point=this._currentPoint();
    this.shadowRoot.getElementById("coordinates").textContent=point?`${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`:"nicht verfügbar";
    if (point && this._map) {
      const key=`${selectState.state}:${point.latitude}:${point.longitude}`;
      if (force || this._lastReference!==key) {
        this._lastReference=key; this._map.easeTo({center:[point.longitude,point.latitude],zoom:Math.max(this._map.getZoom(),8),duration:650});
        if (!this._marker) this._marker=new maplibregl.Marker({color:"#ff9800"}).setLngLat([point.longitude,point.latitude]).addTo(this._map); else this._marker.setLngLat([point.longitude,point.latitude]);
      }
      this._setMapStatus("synchron", "ok");
    }
  }

  _currentPoint() {
    const selected=this._hass?.states?.[SELECT_ENTITY]?.state; const state=selected?this._hass.states[selected]:null;
    const latitude=Number(state?.attributes?.latitude); const longitude=Number(state?.attributes?.longitude);
    return Number.isFinite(latitude)&&Number.isFinite(longitude)?{latitude,longitude}:null;
  }

  _diagnosticPoint() {
    const preset = DIAGNOSTIC_TEST_LOCATIONS[this._diagnosticTestLocation];
    if (preset && preset.latitude !== null && preset.longitude !== null && Number.isFinite(Number(preset.latitude)) && Number.isFinite(Number(preset.longitude))) {
      return { latitude:Number(preset.latitude), longitude:Number(preset.longitude) };
    }
    return this._currentPoint();
  }

  _formatEpoch(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) return "";
    return new Date(seconds * 1000).toLocaleString("de-DE", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  _safeId(value) { return String(value).replace(/[^a-zA-Z0-9_-]/g,"-"); }
  _friendlyLocationName(entityId) { const state=this._hass?.states?.[entityId]; const name=state?.attributes?.friendly_name; return name?`${name} · ${entityId}`:entityId; }
  _escape(value) { return String(value).replace(/[&<>'\"]/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'\"':"&quot;"}[ch])); }
}

WeatherRouterLab.buildVersion = WR_LAB_BUILD_VERSION;

if (!customElements.get("weather-router-lab")) customElements.define("weather-router-lab",WeatherRouterLab);
