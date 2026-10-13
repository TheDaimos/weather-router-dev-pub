const LAB_ELEMENT = "weather-router-lab";
const MAP_MODE_STORAGE_KEY = "weather_router_lab_map_mode_v1";
const MAP_WINDOW_NAME = "weather-router-map-window";

const MAP_MODES = Object.freeze({
  DOCKED: "docked",
  POPOUT: "popout",
  HIDDEN: "hidden",
});

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Karten-Workspace-Modul registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterMapWorkspaceEnhanced) {
  proto.__weatherRouterMapWorkspaceEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousEnsureMap = proto._ensureMap;
  const previousDisconnectedCallback = proto.disconnectedCallback;

  proto._mapModeLoad = function() {
    try {
      const stored = localStorage.getItem(MAP_MODE_STORAGE_KEY);
      if (stored === MAP_MODES.HIDDEN) return MAP_MODES.HIDDEN;
      if (stored === MAP_MODES.DOCKED) return MAP_MODES.DOCKED;

      // Ein separates Browserfenster darf beim Reload nicht automatisch geöffnet
      // werden. Das würde Popup-Blocker auslösen und ist ohne Benutzeraktion nicht
      // zuverlässig. Ein gespeichertes POPOUT fällt deshalb auf DOCKED zurück.
      if (stored === MAP_MODES.POPOUT) return MAP_MODES.DOCKED;
    } catch (_error) {
      // Browser-local persistence is optional.
    }
    return MAP_MODES.DOCKED;
  };

  proto._mapModePersist = function() {
    try {
      localStorage.setItem(MAP_MODE_STORAGE_KEY, this._mapMode);
    } catch (_error) {
      // Browser-local persistence is optional.
    }
  };

  proto._mapWorkspaceElement = function() {
    return (
      this._mapWorkspaceNode
      || this.shadowRoot?.getElementById("map-workspace")
      || this._mapPopupWindow?.document?.getElementById("map-workspace")
      || null
    );
  };

  proto._captureMapViewState = function() {
    const map = this._map;
    if (!map) return this._mapViewState || null;

    try {
      const center = map.getCenter();
      this._mapViewState = {
        center: [Number(center.lng), Number(center.lat)],
        zoom: Number(map.getZoom()),
        bearing: Number(map.getBearing()),
        pitch: Number(map.getPitch()),
      };
    } catch (_error) {
      // Keep the last known good state if MapLibre is currently transitioning.
    }
    return this._mapViewState || null;
  };

  proto._restoreMapViewState = function() {
    const map = this._map;
    const state = this._mapViewState;
    if (!map || !state || !Array.isArray(state.center)) return;

    const [longitude, latitude] = state.center;
    if (
      !Number.isFinite(longitude)
      || !Number.isFinite(latitude)
      || !Number.isFinite(state.zoom)
    ) return;

    map.jumpTo({
      center: [longitude, latitude],
      zoom: state.zoom,
      bearing: Number.isFinite(state.bearing) ? state.bearing : 0,
      pitch: Number.isFinite(state.pitch) ? state.pitch : 0,
    });
  };

  proto._mapWorkspaceHookMap = function() {
    const map = this._map;
    if (!map || this._mapWorkspaceHookedMap === map) return;
    this._mapWorkspaceHookedMap = map;

    const capture = () => this._captureMapViewState();
    map.on("moveend", capture);
    map.on("rotateend", capture);
    map.on("pitchend", capture);
    map.on("load", () => {
      if (this._mapMode !== MAP_MODES.HIDDEN) {
        this._mapModeRequestResize();
      }
    });
  };

  proto._mapModeRequestResize = function() {
    const expectedMap = this._map;
    if (!expectedMap || this._mapMode === MAP_MODES.HIDDEN) return;

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (
          !this.isConnected
          || this._map !== expectedMap
          || this._mapMode === MAP_MODES.HIDDEN
        ) return;
        expectedMap.resize();
        this._restoreMapViewState();
        this._captureMapViewState();
      });
    });
  };

  proto._mapModeInstallStyle = function() {
    if (this.shadowRoot?.getElementById("weather-router-map-mode-style")) return;
    const style = document.createElement("style");
    style.id = "weather-router-map-mode-style";
    style.textContent = `
      .map-mode-control {
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        min-height:54px;
        margin:0 0 12px;
        padding:9px 10px;
        border:1px solid color-mix(in srgb,var(--divider-color,#444) 78%,transparent);
        border-radius:10px;
        background:color-mix(in srgb,var(--secondary-background-color,#282828) 78%,transparent);
      }
      .map-mode-copy { min-width:0; }
      .map-mode-status {
        display:block;
        font-size:12px;
        line-height:1.25;
        font-weight:750;
      }
      .map-mode-detail {
        display:block;
        margin-top:2px;
        font-size:10px;
        line-height:1.25;
        opacity:.62;
      }
      .map-mode-actions {
        display:flex;
        align-items:center;
        justify-content:flex-end;
        gap:6px;
        flex:0 0 auto;
      }
      .map-mode-action {
        min-height:32px;
        padding:5px 9px;
        white-space:nowrap;
        font-size:11px;
      }
      .layout.map-mode-hidden,
      .layout.map-mode-popout {
        grid-template-columns:minmax(0,1fr);
      }
      .layout.map-mode-hidden .sidebar,
      .layout.map-mode-popout .sidebar {
        width:min(100%,1400px);
        justify-self:center;
        border-right:1px solid var(--divider-color,#444);
        border-left:1px solid var(--divider-color,#444);
      }
      .map-dock-anchor { display:none !important; }
      .map-wrap[hidden] { display:none !important; }

      @media(max-width:1450px) {
        .layout.map-mode-hidden .sidebar,
        .layout.map-mode-popout .sidebar {
          border-left:0;
          border-right:0;
        }
      }
      @media(max-width:850px) {
        .layout.map-mode-hidden,
        .layout.map-mode-popout {
          grid-template-rows:auto;
        }
        .layout.map-mode-hidden .sidebar,
        .layout.map-mode-popout .sidebar {
          width:100%;
        }
      }
      @media(max-width:500px) {
        .map-mode-control {
          align-items:flex-start;
          flex-direction:column;
        }
        .map-mode-actions {
          width:100%;
          display:grid;
          grid-template-columns:1fr 1fr;
        }
        .map-mode-action { width:100%; }
      }
    `;
    this.shadowRoot.appendChild(style);
  };

  proto._mapModeUpdateControl = function() {
    const status = this.shadowRoot?.getElementById("map-mode-status");
    const detail = this.shadowRoot?.getElementById("map-mode-detail");
    const primary = this.shadowRoot?.getElementById("map-mode-primary");
    const secondary = this.shadowRoot?.getElementById("map-mode-secondary");
    if (!status || !detail || !primary || !secondary) return;

    if (this._mapMode === MAP_MODES.POPOUT) {
      status.textContent = "Karte im eigenen Fenster";
      detail.textContent = "WeatherRouter bleibt im Hauptfenster vollständig nutzbar";
      primary.textContent = "Kartenfenster anzeigen";
      primary.title = "Eigenständiges Kartenfenster in den Vordergrund holen";
      secondary.textContent = "Andocken";
      secondary.title = "Karte wieder in WeatherRouter einsetzen";
      return;
    }

    if (this._mapMode === MAP_MODES.HIDDEN) {
      status.textContent = "Karte ausgeblendet";
      detail.textContent = "Kartenfläche aus dem Layout entfernt";
      primary.textContent = "Karte anzeigen";
      primary.title = "Karte wieder im WeatherRouter anzeigen";
      secondary.textContent = "In eigenem Fenster öffnen";
      secondary.title = "Karte in einem vollständig separaten Browserfenster öffnen";
      return;
    }

    status.textContent = "Karte angedockt";
    detail.textContent = "Karte im WeatherRouter eingebettet";
    primary.textContent = "In eigenem Fenster öffnen";
    primary.title = "Karte zusätzlich in einem separaten Browserfenster öffnen";
    secondary.textContent = "Karte ausblenden";
    secondary.title = "Kartenfläche aus der Analyseansicht ausblenden";
  };

  proto._mapPopupCopyTheme = function(targetDocument) {
    const computed = getComputedStyle(this);
    const names = [
      "--primary-background-color",
      "--card-background-color",
      "--secondary-background-color",
      "--primary-text-color",
      "--secondary-text-color",
      "--divider-color",
      "--primary-color",
      "--success-color",
      "--error-color",
    ];
    for (const name of names) {
      const value = computed.getPropertyValue(name);
      if (value) targetDocument.documentElement.style.setProperty(name, value);
    }
    targetDocument.documentElement.style.colorScheme = computed.colorScheme || "dark";
  };

  proto._mapPopupCloneStyles = function(targetDocument) {
    for (const source of this.shadowRoot?.querySelectorAll('style, link[rel="stylesheet"]') || []) {
      targetDocument.head.appendChild(source.cloneNode(true));
    }

    const popupStyle = targetDocument.createElement("style");
    popupStyle.textContent = `
      html, body {
        width:100%;
        height:100%;
        margin:0;
        overflow:hidden;
        background:var(--primary-background-color,#111);
        color:var(--primary-text-color,#eee);
        font-family:system-ui,sans-serif;
      }
      * { box-sizing:border-box; }
      button { font:inherit; cursor:pointer; }
      .wr-map-window {
        width:100%;
        height:100%;
        min-width:0;
        min-height:0;
        display:flex;
        flex-direction:column;
        background:var(--primary-background-color,#111);
      }
      .wr-map-window-head {
        flex:0 0 auto;
        min-height:54px;
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:12px;
        padding:9px 12px 9px 15px;
        border-bottom:1px solid var(--divider-color,#444);
        background:var(--card-background-color,#1c1c1c);
      }
      .wr-map-window-title {
        min-width:0;
        display:flex;
        flex-direction:column;
        gap:2px;
      }
      .wr-map-window-title strong { font-size:15px; line-height:1.2; }
      .wr-map-window-title small { font-size:10px; opacity:.62; }
      .wr-map-window-actions {
        flex:0 0 auto;
        display:flex;
        gap:6px;
      }
      .wr-map-window-actions button {
        min-height:34px;
        padding:5px 9px;
        white-space:nowrap;
        border:1px solid var(--divider-color,#555);
        border-radius:8px;
        background:var(--secondary-background-color,#282828);
        color:var(--primary-text-color,#eee);
      }
      .wr-map-window-body {
        position:relative;
        flex:1 1 auto;
        min-width:0;
        min-height:0;
        overflow:hidden;
        background:#09111d;
      }
      .wr-map-window-body > .map-wrap {
        position:relative !important;
        width:100% !important;
        height:100% !important;
        min-height:0 !important;
        overflow:hidden;
      }
      .wr-map-window-body #map { position:absolute; inset:0; }
      @media(max-width:650px) {
        .wr-map-window-head { padding:7px 8px; }
        .wr-map-window-title small { display:none; }
        .wr-map-window-actions button { min-height:32px; padding:4px 7px; font-size:10px; }
      }
    `;
    targetDocument.head.appendChild(popupStyle);
  };

  proto._mapPopupPrepareDocument = function(popup) {
    const popupDocument = popup.document;
    popupDocument.open();
    popupDocument.write(`<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>WeatherRouter · Karte</title>
</head>
<body>
  <main class="wr-map-window">
    <header class="wr-map-window-head">
      <div class="wr-map-window-title">
        <strong>WeatherRouter · Karte</strong>
        <small>Eigenständiges Kartenfenster · WeatherRouter bleibt im Hauptfenster</small>
      </div>
      <div class="wr-map-window-actions">
        <button id="wr-map-window-dock" type="button">Andocken</button>
        <button id="wr-map-window-hide" type="button">Ausblenden</button>
      </div>
    </header>
    <div id="wr-map-window-body" class="wr-map-window-body"></div>
  </main>
</body>
</html>`);
    popupDocument.close();

    this._mapPopupCopyTheme(popupDocument);
    this._mapPopupCloneStyles(popupDocument);

    popupDocument.getElementById("wr-map-window-dock")?.addEventListener("click", () => {
      this._setMapMode(MAP_MODES.DOCKED);
    });
    popupDocument.getElementById("wr-map-window-hide")?.addEventListener("click", () => {
      this._setMapMode(MAP_MODES.HIDDEN);
    });
  };

  proto._mapPopupReturnWorkspace = function({ closeWindow = false } = {}) {
    const root = this.shadowRoot;
    const layout = root?.querySelector(".layout");
    const dockAnchor = root?.getElementById("map-dock-anchor");
    const workspace = this._mapWorkspaceElement();
    const popup = this._mapPopupWindow;

    if (layout && dockAnchor && workspace && workspace.parentElement !== layout) {
      dockAnchor.after(workspace);
    }

    if (popup && this._mapPopupResizeHandler) {
      try {
        popup.removeEventListener("resize", this._mapPopupResizeHandler);
      } catch (_error) {
        // The popup may already be tearing down.
      }
    }
    this._mapPopupResizeHandler = null;

    if (closeWindow && popup && !popup.closed) {
      this._mapPopupSuppressUnload = true;
      try {
        popup.close();
      } finally {
        queueMicrotask(() => {
          this._mapPopupSuppressUnload = false;
        });
      }
    }

    if (!popup || popup.closed || closeWindow) {
      this._mapPopupWindow = null;
    }
  };

  proto._mapPopupHandleClosed = function() {
    if (this._mapPopupSuppressUnload) return;
    if (this._mapMode !== MAP_MODES.POPOUT) return;

    this._captureMapViewState();
    this._mapPopupReturnWorkspace({ closeWindow: false });
    this._mapPopupWindow = null;
    this._mapMode = MAP_MODES.HIDDEN;
    this._mapModePersist();
    this._applyMapMode();

    this._wrLog?.("map_window_closed", {
      next_mode: MAP_MODES.HIDDEN,
      map_initialized: Boolean(this._map),
    });
  };

  proto._openMapWindowFromGesture = function() {
    const existing = this._mapPopupWindow;
    if (existing && !existing.closed) {
      existing.focus();
      return true;
    }

    const popup = window.open(
      "",
      MAP_WINDOW_NAME,
      "popup=yes,width=1400,height=900,resizable=yes,scrollbars=no"
    );
    if (!popup) {
      this._setMapStatus?.("Eigenes Kartenfenster vom Browser blockiert");
      this._wrLog?.("map_window_blocked", { mode: this._mapMode });
      return false;
    }

    const workspace = this._mapWorkspaceElement();
    if (!workspace) {
      popup.close();
      this._wrLog?.("map_window_failed", { reason: "workspace_missing" });
      return false;
    }

    if (this._map) {
      this._map.stop?.();
      this._captureMapViewState();
    } else {
      // MapLibre muss aufgebaut werden, solange #map noch im Shadow-DOM des Labs
      // liegt; danach wird genau dieser bestehende Workspace ins neue Fenster
      // übernommen.
      workspace.hidden = false;
      this._mapPreparingPopout = true;
      try {
        this._ensureMap();
      } finally {
        this._mapPreparingPopout = false;
      }
    }

    try {
      this._mapPopupWindow = popup;
      this._mapPopupPrepareDocument(popup);

      const popupBody = popup.document.getElementById("wr-map-window-body");
      if (!popupBody) throw new Error("popup_body_missing");

      popupBody.appendChild(popup.document.adoptNode(workspace));
      workspace.hidden = false;

      this._mapPopupResizeHandler = () => this._mapModeRequestResize();
      popup.addEventListener("resize", this._mapPopupResizeHandler);
      popup.addEventListener("beforeunload", () => this._mapPopupHandleClosed(), { once: true });

      this._mapMode = MAP_MODES.POPOUT;
      this._mapModePersist();
      this._applyMapMode();
      this._mapModeRequestResize();
      popup.focus();

      this._wrLog?.("map_window_opened", {
        map_initialized: Boolean(this._map),
        reused_map_instance: true,
        main_window_preserved: true,
      });
      return true;
    } catch (error) {
      this._mapPopupSuppressUnload = true;
      try {
        popup.close();
      } catch (_closeError) {
        // Ignore close failure; the main workspace is restored below.
      }
      this._mapPopupSuppressUnload = false;
      this._mapPopupWindow = null;

      const root = this.shadowRoot;
      const anchor = root?.getElementById("map-dock-anchor");
      if (anchor && workspace.parentElement !== root?.querySelector(".layout")) {
        anchor.after(workspace);
      }
      workspace.hidden = this._mapMode === MAP_MODES.HIDDEN;
      this._setMapStatus?.("Eigenes Kartenfenster konnte nicht geöffnet werden");
      this._wrLog?.("map_window_failed", {
        reason: error?.message || String(error),
      });
      return false;
    }
  };

  proto._applyMapMode = function({ initial = false } = {}) {
    const root = this.shadowRoot;
    const layout = root?.querySelector(".layout");
    const workspace = this._mapWorkspaceElement();
    const dockAnchor = root?.getElementById("map-dock-anchor");
    if (!layout || !workspace || !dockAnchor) return;

    const hidden = this._mapMode === MAP_MODES.HIDDEN;
    const popout = this._mapMode === MAP_MODES.POPOUT;

    layout.classList.toggle("map-mode-hidden", hidden);
    layout.classList.toggle("map-mode-popout", popout);

    if (!popout && workspace.parentElement !== layout) {
      dockAnchor.after(workspace);
    }

    workspace.hidden = hidden;
    workspace.dataset.mapMode = this._mapMode;
    this._mapModeUpdateControl();

    if (hidden) {
      this._map?.stop?.();
      if (this._map) this._captureMapViewState();
      if (!initial) this._setMapStatus?.("ausgeblendet");
      return;
    }

    if (popout) {
      if (!initial) this._setMapStatus?.("eigenes Fenster");
      this._mapModeRequestResize();
      return;
    }

    if (!this._map) {
      if (!initial) this._setMapStatus?.("Karte lädt …");
      queueMicrotask(() => this._ensureMap());
      return;
    }

    this._mapModeRequestResize();
    if (!initial) this._setMapStatus?.("synchron");
  };

  proto._setMapMode = function(nextMode) {
    if (!Object.values(MAP_MODES).includes(nextMode)) return false;

    if (nextMode === MAP_MODES.POPOUT) {
      return this._openMapWindowFromGesture();
    }

    if (this._mapMode === nextMode) return true;

    const previousMode = this._mapMode;
    if (this._map) {
      this._map.stop?.();
      this._captureMapViewState();
    }

    if (previousMode === MAP_MODES.POPOUT) {
      this._mapPopupReturnWorkspace({ closeWindow: true });
    }

    this._mapMode = nextMode;
    this._mapModePersist();
    this._applyMapMode();

    this._wrLog?.("map_mode_changed", {
      from: previousMode,
      to: nextMode,
      map_initialized: Boolean(this._map),
    });
    return true;
  };

  proto._renderShell = function() {
    if (!this._mapMode) this._mapMode = this._mapModeLoad();
    if (!Object.prototype.hasOwnProperty.call(this, "_mapViewState")) {
      this._mapViewState = null;
    }

    previousRenderShell.call(this);
    this._mapModeInstallStyle();

    const root = this.shadowRoot;
    const layout = root?.querySelector(".layout");
    const workspace = root?.querySelector(".map-wrap");
    const sidebar = root?.querySelector(".sidebar");
    const basemapMenu = root?.querySelector('[data-lab-menu-key="basemap"]');
    if (!layout || !workspace || !sidebar || !basemapMenu) return;

    workspace.id = "map-workspace";
    this._mapWorkspaceNode = workspace;

    const dockAnchor = document.createElement("span");
    dockAnchor.id = "map-dock-anchor";
    dockAnchor.className = "map-dock-anchor";
    dockAnchor.setAttribute("aria-hidden", "true");
    layout.insertBefore(dockAnchor, workspace);

    const control = document.createElement("section");
    control.className = "map-mode-control";
    control.setAttribute("aria-label", "Kartenansicht");
    control.innerHTML = `
      <div class="map-mode-copy">
        <span id="map-mode-status" class="map-mode-status">Karte angedockt</span>
        <span id="map-mode-detail" class="map-mode-detail">Karte im WeatherRouter eingebettet</span>
      </div>
      <div class="map-mode-actions">
        <button id="map-mode-primary" class="map-mode-action" type="button">Karte lösen</button>
        <button id="map-mode-secondary" class="map-mode-action" type="button">Karte ausblenden</button>
      </div>
    `;
    sidebar.insertBefore(control, basemapMenu);

    root.getElementById("map-mode-primary").addEventListener("click", () => {
      if (this._mapMode === MAP_MODES.DOCKED) {
        this._openMapWindowFromGesture();
      } else if (this._mapMode === MAP_MODES.POPOUT) {
        const popup = this._mapPopupWindow;
        if (popup && !popup.closed) popup.focus();
      } else {
        this._setMapMode(MAP_MODES.DOCKED);
      }
    });

    root.getElementById("map-mode-secondary").addEventListener("click", () => {
      if (this._mapMode === MAP_MODES.HIDDEN) {
        this._openMapWindowFromGesture();
      } else if (this._mapMode === MAP_MODES.POPOUT) {
        this._setMapMode(MAP_MODES.DOCKED);
      } else {
        this._setMapMode(MAP_MODES.HIDDEN);
      }
    });

    this._applyMapMode({ initial: true });
  };

  proto._ensureMap = function() {
    if (!this._mapMode) this._mapMode = this._mapModeLoad();
    if (this._mapMode === MAP_MODES.HIDDEN && !this._mapPreparingPopout) return;

    const previousMap = this._map;
    const result = previousEnsureMap.call(this);
    if (this._map && this._map !== previousMap) {
      this._mapWorkspaceHookMap();
      this._mapModeRequestResize();
    }
    return result;
  };

  proto.disconnectedCallback = function(...args) {
    const popup = this._mapPopupWindow;
    const workspace = this._mapWorkspaceElement();
    const anchor = this.shadowRoot?.getElementById("map-dock-anchor");
    const layout = this.shadowRoot?.querySelector(".layout");

    this._mapPopupSuppressUnload = true;
    if (anchor && layout && workspace && workspace.parentElement !== layout) {
      anchor.after(workspace);
    }
    if (popup && !popup.closed) {
      try {
        popup.close();
      } catch (_error) {
        // The browser may already be closing both windows.
      }
    }
    this._mapPopupWindow = null;
    this._mapPopupResizeHandler = null;

    return previousDisconnectedCallback?.apply(this, args);
  };

  LabClass.mapModes = MAP_MODES;
  LabClass.mapModeStorageKey = MAP_MODE_STORAGE_KEY;

  console.info("[WeatherRouter] separate map window mode docked/popout/hidden enabled");
}
