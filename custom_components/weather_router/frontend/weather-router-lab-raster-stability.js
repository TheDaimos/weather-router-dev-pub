import * as maplibregl from "https://unpkg.com/maplibre-gl@6.9.1/dist/maplibre-gl.mjs";

const LAB_ELEMENT = "weather-router-lab";
const WEATHER_SOURCE_PREFIX = "weather-source-";
const FRAME_FADE_MS = 120;

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Raster-Stabilitätsmodul registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterRasterStabilityEnhanced) {
  proto.__weatherRouterRasterStabilityEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousAddWeatherLayerToMap = proto._addWeatherLayerToMap;
  const previousWeatherLayerStatusText = proto._weatherLayerStatusText;

  proto._renderShell = function() {
    previousRenderShell.call(this);

    const basemap = this.shadowRoot?.getElementById("basemap-provider");
    const noBasemap = basemap?.querySelector('option[value="science"]');
    if (noBasemap) noBasemap.textContent = "Keine Basiskarte · nur Wetterlayer";

    const note = this.shadowRoot?.querySelector(".basemap-note");
    if (note) {
      note.textContent =
        "Basiskarte und Wetterprovider sind getrennte Ebenen. „Keine Basiskarte“ zeigt nur die einfarbige Kartenfläche, Standortmarker und WeatherRouter-Wetterlayer; es wird kein Home-Assistant-View-Hintergrund benötigt.";
    }
  };

  proto._weatherStateForSource = function(sourceId, message = "") {
    for (const state of this._weatherLayers?.values?.() || []) {
      const ids = this._weatherLayerIds(state);
      if (sourceId && ids.source === sourceId) return state;

      const hosts = Array.isArray(state?.descriptor?.network_hosts)
        ? state.descriptor.network_hosts
        : [];
      if (message && hosts.some(host => typeof host === "string" && message.includes(host))) {
        return state;
      }
    }
    return null;
  };

  proto._handleWeatherTileError = function(event) {
    const message = event?.error?.message || String(event?.error || "Wetterkachel konnte nicht geladen werden");
    const sourceId = event?.sourceId || event?.source?.id || "";
    const state = this._weatherStateForSource(sourceId, message);
    if (!state) return false;

    const now = Date.now();
    const shouldRender = !state.tileWarningAt || now - state.tileWarningAt > 800;
    state.tileWarning = "einzelne Wetterkachel konnte nicht geladen werden";
    state.tileWarningAt = now;
    console.warn("[WeatherRouter] weather tile request failed", {
      provider: state.provider,
      capability: state.capability,
      sourceId,
      message,
    });
    this._wrLog?.("weather_tile_error", {
      source_id: sourceId || null,
      message,
    }, "warn", state);
    if (shouldRender) this._renderWeatherLayers();
    return true;
  };

  proto._clearWeatherTileWarning = function(sourceId) {
    if (!sourceId?.startsWith?.(WEATHER_SOURCE_PREFIX)) return;
    const state = this._weatherStateForSource(sourceId);
    if (!state?.tileWarning) return;
    state.tileWarning = null;
    state.tileWarningAt = null;
    this._renderWeatherLayers();
  };

  proto._weatherLayerStatusText = function(state) {
    const base = previousWeatherLayerStatusText.call(this, state);
    return state?.tileWarning ? `${base} · ⚠ ${state.tileWarning}` : base;
  };

  proto._addWeatherLayerToMap = function(state) {
    if (!this._map || !state?.enabled || !state?.descriptor || !this._map.isStyleLoaded()) return;

    const ids = this._weatherLayerIds(state);
    const existingSource = this._map.getSource(ids.source);
    const existingLayer = this._map.getLayer(ids.layer);

    if (existingSource && existingLayer && typeof existingSource.setTiles === "function") {
      existingSource.setTiles([state.descriptor.tile_url]);
      this._map.setPaintProperty(ids.layer, "raster-opacity", state.opacity / 100);
      this._map.setPaintProperty(ids.layer, "raster-fade-duration", FRAME_FADE_MS);
      return;
    }

    previousAddWeatherLayerToMap.call(this, state);
    if (this._map.getLayer(ids.layer)) {
      this._map.setPaintProperty(ids.layer, "raster-fade-duration", FRAME_FADE_MS);
    }
  };

  // The timeline module originally captured the first raster add function in a closure.
  // Override frame application after that module has loaded so every frame uses the stable
  // source-update path above instead of removing and recreating source + layer.
  proto._timelineApplyFrame = function(state, rerender = true) {
    const frames = this._timelineFrames(state);
    const index = this._timelineEnsureIndex(state);
    if (!frames.length || index < 0 || !state?.descriptor) return;

    const frame = frames[index];
    state.descriptor.tile_url = frame.tile_url;
    state.descriptor.frame_time = Number(frame.time);
    this._addWeatherLayerToMap(state);
    if (rerender) this._renderWeatherLayers();
  };

  // Replace the map bootstrap before any Lab instance exists. Weather-tile failures are
  // provider/layer warnings and must not turn the reference-location status into a global
  // "Kartenfehler". Basemap/style errors still use the normal global map status.
  proto._ensureMap = function() {
    if (this._map || !this.isConnected) return;
    this._setMapStatus("Karte lädt …");
    this._map = new maplibregl.Map({
      container: this.shadowRoot.getElementById("map"),
      center: [10, 51],
      zoom: 4.5,
      attributionControl: true,
      style: this._selectedMapStyle(),
    });
    this._map.addControl(new maplibregl.NavigationControl(), "top-right");
    this._map.on("load", () => {
      this._setMapStatus("synchron", "ok");
      this._syncFromHass(true);
      this._restoreWeatherLayers();
    });
    this._map.on("sourcedata", event => {
      if (event?.sourceId && event?.isSourceLoaded) {
        this._clearWeatherTileWarning(event.sourceId);
      }
    });
    this._map.on("error", event => {
      if (this._handleWeatherTileError(event)) return;
      const message = event?.error?.message || "unbekannter Kartenfehler";
      this._setMapStatus(`Kartenfehler: ${message}`, "error");
    });
  };

  console.info("[WeatherRouter] stable raster-frame switching and weather-tile error isolation enabled");
}
