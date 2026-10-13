import * as maplibregl from "https://unpkg.com/maplibre-gl@6.9.1/dist/maplibre-gl.mjs";

const LAB_ELEMENT = "weather-router-lab";

const BUFFER_DEFAULT_TARGET = 3;
const BUFFER_MIN_TARGET = 2;
const BUFFER_MAX_TARGET = 4;
const BUFFER_TILE_CONCURRENCY = 6;
const BUFFER_TILE_TIMEOUT_MS = 12000;
const BUFFER_SOURCE_TIMEOUT_MS = 10000;
const BUFFER_RENDER_SETTLE_TIMEOUT_MS = 1500;
const BUFFER_STAGE_OPACITY = 0.001;
const BUFFER_RETRY_AFTER_MS = 15000;
const BUFFER_MIN_PARTIAL_RATIO = 0.75;
const BUFFER_ENTRY_LIMIT = 16;
const BUFFER_MANUAL_MAX_TARGET = 24;
const BUFFER_MANUAL_MAX_CONCURRENCY = 8;
const BUFFER_SETTINGS_KEY = "weather_router_lab_buffer_settings_v1";
const BUFFER_PROTOCOL = "wrbuffer";
const BUFFER_PROTOCOL_GLOBAL_KEY = "__weatherRouterRasterTileProtocolV1";
const BUFFER_BYTE_CACHE_MAX_BYTES = 128 * 1024 * 1024;
const PLAYBACK_BASE_DWELL_MS = 900;

const WEB_MERCATOR_LIMIT = 85.05112878;
const WEB_MERCATOR_EXTENT = 20037508.342789244;

const bufferProtocolState = globalThis[BUFFER_PROTOCOL_GLOBAL_KEY] || {
  registered: false,
  templateSequence: 0,
  templateIds: new Map(),
  templates: new Map(),
  tileCache: new Map(),
  cacheBytes: 0,
  stats: {
    networkRequests: 0,
    cacheHits: 0,
    sharedPending: 0,
    canonicalBboxHits: 0,
    errors: 0,
  },
};
globalThis[BUFFER_PROTOCOL_GLOBAL_KEY] = bufferProtocolState;

const protocolTemplate = template => {
  if (typeof template !== "string" || !template) return template;

  let id = bufferProtocolState.templateIds.get(template);
  if (!id) {
    bufferProtocolState.templateSequence += 1;
    id = bufferProtocolState.templateSequence.toString(36);
    bufferProtocolState.templateIds.set(template, id);
    bufferProtocolState.templates.set(id, template);
  }

  if (template.includes("{bbox-epsg-3857}")) {
    return `${BUFFER_PROTOCOL}://tile/${id}/bbox/{bbox-epsg-3857}`;
  }
  if (
    template.includes("{z}")
    && template.includes("{x}")
    && template.includes("{y}")
  ) {
    return `${BUFFER_PROTOCOL}://tile/${id}/xyz/{z}/{x}/{y}`;
  }
  return template;
};

const protocolActualUrl = protocolUrl => {
  const parsed = new URL(protocolUrl);
  const parts = parsed.pathname.split("/").filter(Boolean);
  const id = parts[0];
  const mode = parts[1];
  const template = bufferProtocolState.templates.get(id);
  if (!template) {
    throw new Error(`Unbekannte WeatherRouter-Puffervorlage: ${id || "leer"}`);
  }

  if (mode === "bbox") {
    const bbox = decodeURIComponent(parts.slice(2).join("/"));
    if (!bbox) throw new Error("WeatherRouter-Puffer: BBOX fehlt");
    return template.replaceAll("{bbox-epsg-3857}", bbox);
  }

  if (mode === "xyz") {
    const [z, x, y] = parts.slice(2, 5).map(value => decodeURIComponent(value || ""));
    if (!z || !x || !y) {
      throw new Error("WeatherRouter-Puffer: XYZ-Koordinaten unvollständig");
    }
    return template
      .replaceAll("{z}", z)
      .replaceAll("{x}", x)
      .replaceAll("{y}", y);
  }

  throw new Error(`WeatherRouter-Puffer: unbekannter Tile-Modus ${mode || "leer"}`);
};

const protocolCacheKey = actualUrl => {
  const source = String(actualUrl || "");
  return source.replace(/([?&]bbox=)([^&]+)/i, (match, prefix, rawValue) => {
    let decoded;
    try {
      decoded = decodeURIComponent(rawValue);
    } catch (_error) {
      decoded = rawValue;
    }

    const values = decoded.split(",").map(value => Number(value));
    if (values.length !== 4 || !values.every(Number.isFinite)) {
      return match;
    }

    // MapLibre and WeatherRouter can serialize the same Web-Mercator tile
    // with microscopic floating-point differences in the final decimals.
    // Six decimal places are far below any visible map resolution while
    // making semantically identical WMS BBOX requests share one cache key.
    return `${prefix}${values.map(value => value.toFixed(6)).join(",")}`;
  });
};

const pruneProtocolCache = () => {
  if (bufferProtocolState.cacheBytes <= BUFFER_BYTE_CACHE_MAX_BYTES) return;

  const removable = [...bufferProtocolState.tileCache.entries()]
    .filter(([, entry]) => entry?.bytes && !entry?.promise)
    .sort((a, b) => Number(a[1].touchedAt || 0) - Number(b[1].touchedAt || 0));

  while (
    bufferProtocolState.cacheBytes > BUFFER_BYTE_CACHE_MAX_BYTES
    && removable.length
  ) {
    const [key, entry] = removable.shift();
    if (!bufferProtocolState.tileCache.delete(key)) continue;
    bufferProtocolState.cacheBytes = Math.max(
      0,
      bufferProtocolState.cacheBytes - Number(entry.size || 0)
    );
  }
};

const loadProtocolTile = async actualUrl => {
  const cacheKey = protocolCacheKey(actualUrl);
  const existing = bufferProtocolState.tileCache.get(cacheKey);
  if (existing?.bytes) {
    existing.touchedAt = Date.now();
    bufferProtocolState.stats.cacheHits += 1;
    if (existing.firstUrl && existing.firstUrl !== actualUrl) {
      bufferProtocolState.stats.canonicalBboxHits += 1;
    }
    return existing.bytes;
  }
  if (existing?.promise) {
    existing.touchedAt = Date.now();
    bufferProtocolState.stats.sharedPending += 1;
    if (existing.firstUrl && existing.firstUrl !== actualUrl) {
      bufferProtocolState.stats.canonicalBboxHits += 1;
    }
    return existing.promise;
  }

  const entry = {
    bytes: null,
    promise: null,
    size: 0,
    touchedAt: Date.now(),
    firstUrl: actualUrl,
  };

  entry.promise = (async () => {
    bufferProtocolState.stats.networkRequests += 1;
    try {
      const response = await fetch(actualUrl, {
        method: "GET",
        mode: "cors",
        cache: "no-store",
        credentials: "omit",
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} ${response.statusText}`);
      }

      const contentType = String(response.headers.get("content-type") || "").toLowerCase();
      const buffer = await response.arrayBuffer();
      const bytes = new Uint8Array(buffer);

      if (
        contentType.includes("xml")
        || contentType.includes("text/")
        || (bytes.length >= 5
          && String.fromCharCode(...bytes.slice(0, 5)).toLowerCase().includes("<?xml"))
      ) {
        throw new Error(`Tile-Antwort ist kein Rasterbild (${contentType || "unbekannter Inhaltstyp"})`);
      }

      entry.bytes = bytes;
      entry.size = bytes.byteLength;
      entry.touchedAt = Date.now();
      bufferProtocolState.cacheBytes += entry.size;
      pruneProtocolCache();
      return bytes;
    } catch (error) {
      bufferProtocolState.stats.errors += 1;
      bufferProtocolState.tileCache.delete(cacheKey);
      throw error;
    } finally {
      entry.promise = null;
    }
  })();

  bufferProtocolState.tileCache.set(cacheKey, entry);
  return entry.promise;
};

if (!bufferProtocolState.registered) {
  maplibregl.addProtocol(BUFFER_PROTOCOL, async params => {
    const actualUrl = protocolActualUrl(params.url);
    const bytes = await loadProtocolTile(actualUrl);

    // Return a copy. MapLibre may transfer/detach ArrayBuffers internally;
    // keeping the cached Uint8Array intact allows the same tile to be reused
    // by later frames, loops and double-buffer slots without another HTTP GET.
    return { data: bytes.slice().buffer };
  });
  bufferProtocolState.registered = true;
}

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Frame-Puffer registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterFrameBufferEnhanced) {
  proto.__weatherRouterFrameBufferEnhanced = true;

  const previousTimelineStart = proto._timelineStart;
  const previousTimelineStop = proto._timelineStop;
  const previousRenderWeatherLayers = proto._renderWeatherLayers;
  const previousLoadWeatherLayer = proto._loadWeatherLayer;
  const previousEnsureMap = proto._ensureMap;
  const previousApplyBasemap = proto._applyBasemap;
  const previousAddWeatherLayerToMap = proto._addWeatherLayerToMap;
  const previousRemoveWeatherLayerFromMap = proto._removeWeatherLayerFromMap;
  const previousWeatherLayerIds = proto._weatherLayerIds;

  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

  proto._timelineBufferedTileTemplate = function(template) {
    return protocolTemplate(template);
  };

  proto._timelineProtocolCacheStats = function() {
    return {
      entries: bufferProtocolState.tileCache.size,
      bytes: bufferProtocolState.cacheBytes,
      ...bufferProtocolState.stats,
    };
  };

  proto._addWeatherLayerToMap = function(state) {
    const original = state?.descriptor?.tile_url;
    const frames = state ? this._timelineFrames?.(state) : [];
    if (
      !original
      || !Array.isArray(frames)
      || frames.length < 2
      || (!original.includes("{bbox-epsg-3857}")
        && !(original.includes("{z}") && original.includes("{x}") && original.includes("{y}")))
    ) {
      return previousAddWeatherLayerToMap.call(this, state);
    }

    state.descriptor.tile_url = this._timelineBufferedTileTemplate(original);
    try {
      return previousAddWeatherLayerToMap.call(this, state);
    } finally {
      state.descriptor.tile_url = original;
    }
  };


  proto._timelineBufferSettings = function() {
    if (this._timelineBufferSettingsCache) return this._timelineBufferSettingsCache;

    const defaults = {
      mode: "auto",
      target: 6,
      concurrency: 4,
      startReady: 6,
    };
    let stored = null;
    try {
      stored = JSON.parse(localStorage.getItem(BUFFER_SETTINGS_KEY) || "null");
    } catch (_error) {
      stored = null;
    }

    const mode = ["auto", "off", "manual"].includes(stored?.mode)
      ? stored.mode
      : defaults.mode;
    const target = clamp(
      Number(stored?.target) || defaults.target,
      1,
      BUFFER_MANUAL_MAX_TARGET
    );
    const concurrency = clamp(
      Number(stored?.concurrency) || defaults.concurrency,
      1,
      BUFFER_MANUAL_MAX_CONCURRENCY
    );
    const startReady = clamp(
      Number(stored?.startReady) || Math.min(defaults.startReady, target),
      1,
      target
    );

    this._timelineBufferSettingsCache = {
      mode,
      target,
      concurrency,
      startReady,
    };
    return this._timelineBufferSettingsCache;
  };

  proto._timelineSaveBufferSettings = function(next) {
    const current = this._timelineBufferSettings();
    const target = clamp(
      Number(next?.target ?? current.target),
      1,
      BUFFER_MANUAL_MAX_TARGET
    );
    const value = {
      mode: ["auto", "off", "manual"].includes(next?.mode)
        ? next.mode
        : current.mode,
      target,
      concurrency: clamp(
        Number(next?.concurrency ?? current.concurrency),
        1,
        BUFFER_MANUAL_MAX_CONCURRENCY
      ),
      startReady: clamp(
        Number(next?.startReady ?? current.startReady),
        1,
        target
      ),
    };
    this._timelineBufferSettingsCache = value;
    try {
      localStorage.setItem(BUFFER_SETTINGS_KEY, JSON.stringify(value));
    } catch (_error) {
      // Browser storage is optional; the current session still uses the selected values.
    }
    return value;
  };

  proto._timelineEffectiveTarget = function(state) {
    const frames = this._timelineFrames(state);
    if (frames.length < 2) return 0;
    const settings = this._timelineBufferSettings();
    if (settings.mode === "off") return 0;
    if (settings.mode === "manual") {
      return clamp(settings.target, 1, Math.min(BUFFER_MANUAL_MAX_TARGET, frames.length - 1));
    }
    return clamp(
      Number(state.timelineBufferTarget) || BUFFER_DEFAULT_TARGET,
      BUFFER_MIN_TARGET,
      Math.min(BUFFER_MAX_TARGET, frames.length - 1)
    );
  };

  proto._timelineEffectiveConcurrency = function() {
    const settings = this._timelineBufferSettings();
    return settings.mode === "manual"
      ? clamp(settings.concurrency, 1, BUFFER_MANUAL_MAX_CONCURRENCY)
      : BUFFER_TILE_CONCURRENCY;
  };

  proto._timelineStartReadyTarget = function(state) {
    const settings = this._timelineBufferSettings();
    if (settings.mode === "off") return 0;
    const target = this._timelineEffectiveTarget(state);
    if (!target) return 0;
    if (settings.mode === "manual") {
      return clamp(settings.startReady, 1, target);
    }
    return 1;
  };

  proto._timelineBufferModeLabel = function() {
    const mode = this._timelineBufferSettings().mode;
    if (mode === "off") return "Aus";
    if (mode === "manual") return "Manuell";
    return "Automatisch";
  };

  proto._timelineDropHiddenStage = function(state) {
    if (!this._map || !state) return;
    const hiddenSlot = this._timelineOppositeSlot(state);
    const ids = this._timelineLayerIdsForSlot(state, hiddenSlot);
    if (this._map.getLayer(ids.layer)) this._map.removeLayer(ids.layer);
    if (this._map.getSource(ids.source)) this._map.removeSource(ids.source);
    state.timelineStagedIndex = null;
    state.timelineStagedSlot = null;
    state.timelineStageLoadingIndex = null;
    state.timelineMapStageLoading = false;
  };

  proto._timelineApplyBufferSettings = function() {
    for (const state of this._weatherLayers?.values?.() || []) {
      this._timelineStop(state);
      state.timelineBufferPrimeToken = Number(state.timelineBufferPrimeToken || 0) + 1;
      state.timelinePrimePromise = null;
      state.timelineStageToken = Number(state.timelineStageToken || 0) + 1;
      state.timelineStagePromise = null;
      if (state.timelineBufferEntries instanceof Map) state.timelineBufferEntries.clear();
      state.timelineLoadDurations = [];
      state.timelineWaitingForStartBuffer = false;
      this._timelineDropHiddenStage(state);

      if (
        state.enabled
        && state.descriptor
        && this._timelineBufferSettings().mode !== "off"
        && this._timelineFrames(state).length >= 2
      ) {
        this._timelinePrimeBuffer(state);
        this._timelinePrimeMapStage(state);
      }
    }
    this._renderWeatherLayers();
  };


  const tileX = (longitude, zoom) => {
    const n = 2 ** zoom;
    return Math.floor(((longitude + 180) / 360) * n);
  };

  const tileY = (latitude, zoom) => {
    const lat = clamp(latitude, -WEB_MERCATOR_LIMIT, WEB_MERCATOR_LIMIT);
    const radians = lat * Math.PI / 180;
    const n = 2 ** zoom;
    return Math.floor(
      (1 - Math.log(Math.tan(radians) + (1 / Math.cos(radians))) / Math.PI) / 2 * n
    );
  };

  const normalizedX = (value, zoom) => {
    const n = 2 ** zoom;
    return ((value % n) + n) % n;
  };

  const tileBbox3857 = (x, y, zoom) => {
    const n = 2 ** zoom;
    const span = (WEB_MERCATOR_EXTENT * 2) / n;
    const minX = -WEB_MERCATOR_EXTENT + x * span;
    const maxX = minX + span;
    const maxY = WEB_MERCATOR_EXTENT - y * span;
    const minY = maxY - span;
    return [minX, minY, maxX, maxY].join(",");
  };

  proto._timelineBaseLayerIds = function(state) {
    return previousWeatherLayerIds.call(this, state);
  };

  proto._timelineLayerIdsForSlot = function(state, slot) {
    const base = this._timelineBaseLayerIds(state);
    if (slot === "b") {
      return {
        source: `${base.source}-buffer-b`,
        layer: `${base.layer}-buffer-b`,
      };
    }
    return base;
  };

  proto._weatherLayerIds = function(state) {
    if (state?.timelineDoubleBufferActive && state.timelineVisibleSlot === "b") {
      return this._timelineLayerIdsForSlot(state, "b");
    }
    return this._timelineLayerIdsForSlot(state, "a");
  };

  proto._timelineCurrentSlot = function(state) {
    return state?.timelineDoubleBufferActive && state.timelineVisibleSlot === "b"
      ? "b"
      : "a";
  };

  proto._timelineOppositeSlot = function(state) {
    return this._timelineCurrentSlot(state) === "a" ? "b" : "a";
  };

  proto._timelineWaitForSpecificSource = function(sourceId, state = null) {
    const map = this._map;
    if (!map || !sourceId || !map.getSource(sourceId)) return Promise.resolve(false);

    return new Promise(resolve => {
      let settled = false;
      let timeout = null;
      let poll = null;
      const detail = {
        sourceEvents: 0,
        abortEvents: 0,
        lastSourceDataType: null,
        lastEventLoaded: false,
        elapsedMs: 0,
        timedOut: false,
      };
      const startedAt = performance.now();

      const sourceIsLoaded = () => {
        try {
          return Boolean(map.getSource(sourceId) && map.isSourceLoaded(sourceId));
        } catch (_error) {
          return false;
        }
      };

      const finish = (loaded, timedOut = false) => {
        if (settled) return;
        settled = true;
        if (timeout) clearTimeout(timeout);
        if (poll) clearInterval(poll);
        map.off("sourcedata", onSourceData);
        map.off("sourcedataabort", onSourceAbort);
        detail.elapsedMs = Math.max(0, performance.now() - startedAt);
        detail.timedOut = Boolean(timedOut);
        if (state) state.timelineStageSourceWaitDetail = detail;
        resolve(loaded);
      };

      const onSourceData = event => {
        if (event?.sourceId !== sourceId) return;
        detail.sourceEvents += 1;
        detail.lastSourceDataType = event?.sourceDataType || null;
        detail.lastEventLoaded = Boolean(event?.isSourceLoaded);

        // MapLibre documents sourceDataType=idle as a source-local
        // completion signal. Accept it in addition to isSourceLoaded().
        if (
          event?.isSourceLoaded
          || event?.sourceDataType === "idle"
          || sourceIsLoaded()
        ) {
          finish(true);
        }
      };

      const onSourceAbort = event => {
        if (event?.sourceId !== sourceId) return;
        detail.abortEvents += 1;
        detail.lastSourceDataType = "abort";
      };

      // Register listeners before checking the state. With a warm wrbuffer
      // cache MapLibre can finish a raster source between an early status
      // check and listener registration.
      map.on("sourcedata", onSourceData);
      map.on("sourcedataabort", onSourceAbort);

      if (sourceIsLoaded()) {
        finish(true);
        return;
      }

      // Keep a lightweight state check as a second safety net. Some MapLibre
      // paths can complete without another sourcedata event after cached bytes
      // have been handed to the source.
      poll = setInterval(() => {
        if (sourceIsLoaded()) finish(true);
      }, 100);

      timeout = setTimeout(() => {
        finish(sourceIsLoaded(), true);
      }, BUFFER_SOURCE_TIMEOUT_MS);
    });
  };

  proto._timelineStageWarningText = function(state) {
    const reason = state?.timelineStageFailureReason;
    if (reason === "source_timeout") {
      const detail = state?.timelineStageSourceWaitDetail;
      if (detail) {
        const seconds = (Number(detail.elapsedMs || BUFFER_SOURCE_TIMEOUT_MS) / 1000)
          .toFixed(1)
          .replace(".", ",");
        const lastStatus = detail.lastSourceDataType || "—";
        return `Kartenpuffer: MapLibre-Quelle nach ${seconds} s nicht vollständig geladen · Quellereignisse ${Number(detail.sourceEvents || 0)} · Abbrüche ${Number(detail.abortEvents || 0)} · letzter Status ${lastStatus}`;
      }
      return "Kartenpuffer: MapLibre-Quelle wurde nicht rechtzeitig vollständig geladen";
    }
    if (reason === "render_timeout") {
      return "Kartenpuffer: vorbereiteter Frame wurde nicht rechtzeitig gerendert";
    }
    return "Kartenpuffer konnte den nächsten Frame nicht vollständig vorbereiten";
  };

  proto._timelineWaitForMapStable = function(timeoutMs = 5000) {
    const map = this._map;
    if (!map) return Promise.resolve(false);

    return new Promise(resolve => {
      let settled = false;
      let poll = null;
      let timeout = null;

      const stable = () => {
        try {
          return Boolean(
            map.isStyleLoaded()
            && !(map.isMoving?.() || map.isZooming?.() || map.isRotating?.())
          );
        } catch (_error) {
          return false;
        }
      };

      const finish = result => {
        if (settled) return;
        settled = true;
        if (poll) clearInterval(poll);
        if (timeout) clearTimeout(timeout);
        resolve(Boolean(result));
      };

      if (stable()) {
        // Let one browser task pass so the style.load restore callbacks and
        // their layer additions are committed before staging begins.
        setTimeout(() => finish(stable()), 0);
        return;
      }

      poll = setInterval(() => {
        if (stable()) finish(true);
      }, 50);
      timeout = setTimeout(() => finish(stable()), timeoutMs);
    });
  };

  proto._timelineWaitForRenderCycles = function(count = 1) {
    const map = this._map;
    if (!map) return Promise.resolve(false);

    return new Promise(resolve => {
      let remaining = Math.max(1, Number(count) || 1);
      let settled = false;
      const finish = rendered => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        map.off("render", onRender);
        resolve(rendered);
      };
      const onRender = () => {
        remaining -= 1;
        if (remaining <= 0) finish(true);
      };
      const timeout = setTimeout(() => finish(false), BUFFER_RENDER_SETTLE_TIMEOUT_MS);
      map.on("render", onRender);
      map.triggerRepaint();
    });
  };

  proto._timelineCreateStageSlot = async function(state, slot, frame, token) {
    const map = this._map;
    if (
      !map
      || !state?.enabled
      || !state?.descriptor
      || !frame?.tile_url
      || !map.isStyleLoaded()
    ) {
      return false;
    }

    const ids = this._timelineLayerIdsForSlot(state, slot);
    const currentIds = this._weatherLayerIds(state);

    if (map.getLayer(ids.layer)) map.removeLayer(ids.layer);
    if (map.getSource(ids.source)) map.removeSource(ids.source);

    map.addSource(ids.source, {
      type: "raster",
      tiles: [this._timelineBufferedTileTemplate(frame.tile_url)],
      tileSize: Number(state.descriptor.tile_size) || 256,
      maxzoom: Number(state.descriptor.max_zoom) || 7,
      attribution: state.descriptor.attribution || state.providerName,
    });

    const layerDefinition = {
      id: ids.layer,
      type: "raster",
      source: ids.source,
      paint: {
        // A tiny non-zero opacity forces MapLibre to render/decode the staged
        // raster while remaining visually imperceptible. A fully transparent
        // raster can be source-loaded but still not have a ready GPU frame.
        "raster-opacity": BUFFER_STAGE_OPACITY,
        "raster-fade-duration": 0,
      },
    };

    const beforeId = currentIds?.layer && map.getLayer(currentIds.layer)
      ? currentIds.layer
      : undefined;
    if (beforeId) map.addLayer(layerDefinition, beforeId);
    else map.addLayer(layerDefinition);

    const loaded = await this._timelineWaitForSpecificSource(ids.source, state);
    if (!loaded) {
      if (token === state.timelineStageToken) {
        state.timelineStageFailureReason = "source_timeout";
      }
      return false;
    }
    if (
      token !== state.timelineStageToken
      || !state.enabled
      || !this.isConnected
    ) {
      return false;
    }

    // Source-loaded alone is not sufficient for a seamless swap: wait until
    // MapLibre has actually rendered the hidden staging layer at least once.
    const rendered = await this._timelineWaitForRenderCycles(1);
    if (!rendered) {
      if (token === state.timelineStageToken) {
        state.timelineStageFailureReason = "render_timeout";
      }
      return false;
    }
    if (
      token !== state.timelineStageToken
      || !state.enabled
      || !this.isConnected
    ) {
      return false;
    }

    state.timelineStageFailureReason = null;
    return true;
  };

  proto._timelinePrimeMapStage = function(state, frameIndex = null) {
    const frames = this._timelineFrames(state);
    if (!state?.enabled || frames.length < 2 || !this._map) return Promise.resolve(false);

    const current = this._timelineEnsureIndex(state);
    const index = frameIndex === null
      ? (current >= frames.length - 1 ? 0 : current + 1)
      : ((Number(frameIndex) % frames.length) + frames.length) % frames.length;

    if (
      state.timelineStagedIndex === index
      && state.timelineStagedSlot
      && this._map.getSource(this._timelineLayerIdsForSlot(state, state.timelineStagedSlot).source)
    ) {
      return Promise.resolve(true);
    }

    if (
      state.timelineStagePromise
      && state.timelineStageLoadingIndex === index
    ) {
      return state.timelineStagePromise;
    }

    const token = Number(state.timelineStageToken || 0) + 1;
    state.timelineStageToken = token;
    state.timelineStageFailureReason = null;
    state.timelineStageSourceWaitDetail = null;
    const slot = this._timelineOppositeSlot(state);
    const frame = frames[index];
    state.timelineMapStageLoading = true;
    state.timelineStageLoadingIndex = index;
    this._timelineUpdateBufferUi(state);

    state.timelineStagePromise = this._timelineCreateStageSlot(
      state,
      slot,
      frame,
      token
    ).then(loaded => {
      if (token !== state.timelineStageToken) return false;
      state.timelineMapStageLoading = false;
      if (loaded) {
        state.timelineStagedIndex = index;
        state.timelineStagedSlot = slot;
        if (state.timelineStyleRecoveryActive || state.timelineViewportSuspended) {
          this._wrLog?.("map_stage_ready", {
            index,
            slot,
            style_recovery: Boolean(state.timelineStyleRecoveryActive),
            viewport_suspended: Boolean(state.timelineViewportSuspended),
          }, "info", state);
        }
      } else {
        state.timelineStagedIndex = null;
        state.timelineStagedSlot = null;
        this._wrLog?.("map_stage_failed", {
          index,
          slot,
          reason: state.timelineStageFailureReason || null,
          source_wait: state.timelineStageSourceWaitDetail || null,
        }, "error", state);
      }
      this._timelineUpdateBufferUi(state);
      return loaded;
    }).finally(() => {
      if (token === state.timelineStageToken) {
        state.timelineStagePromise = null;
        state.timelineStageLoadingIndex = null;
      }
    });

    return state.timelineStagePromise;
  };

  proto._timelineSwapToFrame = async function(state, frameIndex, rerender = true) {
    const frames = this._timelineFrames(state);
    if (!frames.length || !state?.enabled || !this._map) return false;
    const index = ((Number(frameIndex) % frames.length) + frames.length) % frames.length;

    const staged = (
      state.timelineStagedIndex === index
      && state.timelineStagedSlot
    )
      ? true
      : await this._timelinePrimeMapStage(state, index);

    if (!staged || state.timelineStagedIndex !== index || !state.timelineStagedSlot) {
      state.timelinePlaybackWarning = this._timelineStageWarningText(state);
      if (rerender) this._renderWeatherLayers();
      return false;
    }

    const oldSlot = this._timelineCurrentSlot(state);
    const newSlot = state.timelineStagedSlot;
    const oldIds = this._timelineLayerIdsForSlot(state, oldSlot);
    const newIds = this._timelineLayerIdsForSlot(state, newSlot);
    const opacity = state.opacity / 100;

    if (!this._map.getLayer(newIds.layer)) return false;

    // Keep the old frame fully visible while the staged frame becomes visible
    // underneath it. Only after MapLibre has painted the new frame do we hide
    // the old slot. This avoids the bright basemap flash between frames.
    this._map.setPaintProperty(newIds.layer, "raster-opacity", opacity);
    await this._timelineWaitForRenderCycles(2);

    if (!state.enabled || !this.isConnected || !this._map.getLayer(newIds.layer)) {
      return false;
    }

    if (this._map.getLayer(oldIds.layer)) {
      this._map.setPaintProperty(oldIds.layer, "raster-opacity", 0);
    }
    this._map.triggerRepaint();

    state.timelineDoubleBufferActive = true;
    state.timelineVisibleSlot = newSlot;
    state.timelineIndex = index;
    state.descriptor.tile_url = frames[index].tile_url;
    state.descriptor.frame_time = Number(frames[index].time);
    state.timelineStagedIndex = null;
    state.timelineStagedSlot = null;
    state.timelinePlaybackWarning = null;
    state.timelineDisplayLoading = false;

    if (rerender) this._renderWeatherLayers();

    // Prepare the next MapLibre source immediately while the just-swapped frame
    // remains completely visible.
    queueMicrotask(() => {
      if (
        state.enabled
        && this.isConnected
        && this._timelineBufferSettings().mode !== "off"
      ) {
        this._timelinePrimeMapStage(state);
        this._timelinePrimeBuffer(state);
      }
    });
    return true;
  };

  proto._timelineApplyFrame = function(state, rerender = true) {
    const index = this._timelineEnsureIndex(state);
    if (index < 0) return Promise.resolve(false);
    return this._timelineSwapToFrame(state, index, rerender);
  };

  proto._timelineBufferStore = function(state) {
    if (!(state.timelineBufferEntries instanceof Map)) {
      state.timelineBufferEntries = new Map();
    }
    if (!Array.isArray(state.timelineLoadDurations)) {
      state.timelineLoadDurations = [];
    }
    if (!Number.isInteger(state.timelineBufferTarget)) {
      state.timelineBufferTarget = BUFFER_DEFAULT_TARGET;
    }
    return state.timelineBufferEntries;
  };

  proto._timelineViewportTiles = function(state) {
    if (!this._map || !state?.descriptor) return null;

    const template = String(state.descriptor.tile_url || "");
    if (
      !template.includes("{bbox-epsg-3857}")
      && !(template.includes("{z}") && template.includes("{x}") && template.includes("{y}"))
    ) {
      return null;
    }

    const descriptorMaxZoom = Number(state.descriptor.max_zoom);
    const mapZoom = Number(this._map.getZoom()) || 0;
    const tileSize = Number(state.descriptor.tile_size) || 256;

    // MapLibre's transform uses a 512 px reference tile. Raster sources with
    // 256 px tiles therefore request one source zoom level above the visible
    // map zoom. Match that source-zoom calculation so the browser preloader
    // warms exactly the same tile URLs MapLibre will request.
    const sourceZoomOffset = Math.log2(512 / tileSize);
    const requestedSourceZoom = Math.floor(mapZoom + sourceZoomOffset);
    const zoom = clamp(
      requestedSourceZoom,
      0,
      Number.isFinite(descriptorMaxZoom) ? Math.floor(descriptorMaxZoom) : 22
    );
    const bounds = this._map.getBounds?.();
    if (!bounds) return null;

    let west = Number(bounds.getWest());
    let east = Number(bounds.getEast());
    const north = clamp(Number(bounds.getNorth()), -WEB_MERCATOR_LIMIT, WEB_MERCATOR_LIMIT);
    const south = clamp(Number(bounds.getSouth()), -WEB_MERCATOR_LIMIT, WEB_MERCATOR_LIMIT);
    if (![west, east, north, south].every(Number.isFinite)) return null;

    while (west < -180) west += 360;
    while (west >= 180) west -= 360;
    while (east < -180) east += 360;
    while (east >= 180) east -= 360;

    const n = 2 ** zoom;
    const yStart = clamp(tileY(north, zoom), 0, n - 1);
    const yEnd = clamp(tileY(south, zoom), 0, n - 1);

    const xValues = [];
    const addRange = (startLng, endLng) => {
      const start = tileX(startLng, zoom);
      const end = tileX(endLng, zoom);
      for (let x = start; x <= end; x += 1) {
        xValues.push(normalizedX(x, zoom));
      }
    };

    if (east >= west) {
      addRange(west, east);
    } else {
      addRange(west, 179.999999);
      addRange(-180, east);
    }

    const uniqueX = [...new Set(xValues)];
    const tiles = [];
    for (let y = yStart; y <= yEnd; y += 1) {
      for (const x of uniqueX) {
        tiles.push({ x, y, z: zoom });
      }
    }

    if (!tiles.length) return null;

    const signature = `${zoom}:${uniqueX.join(",")}:${yStart}-${yEnd}`;
    return {
      zoom,
      mapZoom,
      tileSize,
      sourceZoomOffset,
      tiles,
      signature,
    };
  };

  proto._timelineFrameTileUrls = function(state, frame) {
    const viewport = this._timelineViewportTiles(state);
    if (!viewport || typeof frame?.tile_url !== "string") {
      return { signature: "unsupported", urls: [] };
    }

    const urls = viewport.tiles.map(tile => {
      let url = frame.tile_url;
      url = url.replaceAll("{z}", String(tile.z));
      url = url.replaceAll("{x}", String(tile.x));
      url = url.replaceAll("{y}", String(tile.y));
      url = url.replaceAll(
        "{bbox-epsg-3857}",
        tileBbox3857(tile.x, tile.y, tile.z)
      );
      return url;
    });

    return {
      signature: viewport.signature,
      urls: [...new Set(urls)],
    };
  };

  proto._timelineBufferKey = function(state, frame, viewportSignature) {
    return `${viewportSignature}|${Number(frame?.time)}`;
  };

  proto._timelinePruneBuffer = function(state) {
    const store = this._timelineBufferStore(state);
    const limit = Math.max(BUFFER_ENTRY_LIMIT, this._timelineEffectiveTarget(state) + 6);
    if (store.size <= limit) return;

    const removable = [...store.entries()]
      .filter(([, entry]) => entry.status !== "loading")
      .sort((a, b) => Number(a[1].touchedAt || 0) - Number(b[1].touchedAt || 0));

    while (store.size > limit && removable.length) {
      const [key] = removable.shift();
      store.delete(key);
    }
  };

  proto._timelineRecordLoadDuration = function(state, durationMs) {
    if (!Number.isFinite(Number(durationMs))) return;
    this._timelineBufferStore(state);
    state.timelineLoadDurations.push(Number(durationMs));
    if (state.timelineLoadDurations.length > 6) {
      state.timelineLoadDurations.splice(0, state.timelineLoadDurations.length - 6);
    }

    const average = state.timelineLoadDurations.reduce((sum, value) => sum + value, 0)
      / state.timelineLoadDurations.length;

    if (this._timelineBufferSettings().mode !== "auto") return;

    if (state.timelineLoadDurations.length >= 2 && average <= 1400) {
      state.timelineBufferTarget = BUFFER_MAX_TARGET;
    } else if (state.timelineLoadDurations.length >= 2 && average >= 3500) {
      state.timelineBufferTarget = BUFFER_MIN_TARGET;
    } else {
      state.timelineBufferTarget = BUFFER_DEFAULT_TARGET;
    }
  };

  proto._timelineLoadImage = async function(url) {
    const started = performance.now();
    let timeout = null;

    try {
      const result = await Promise.race([
        loadProtocolTile(url).then(() => true),
        new Promise(resolve => {
          timeout = setTimeout(() => resolve(false), BUFFER_TILE_TIMEOUT_MS);
        }),
      ]);
      return {
        ok: result === true,
        durationMs: Math.max(0, performance.now() - started),
      };
    } catch (_error) {
      return {
        ok: false,
        durationMs: Math.max(0, performance.now() - started),
      };
    } finally {
      if (timeout) clearTimeout(timeout);
    }
  };

  proto._timelineRunTileQueue = async function(state, entry, urls) {
    let cursor = 0;

    const worker = async () => {
      while (cursor < urls.length && state.enabled) {
        const index = cursor;
        cursor += 1;
        const result = await this._timelineLoadImage(urls[index]);
        if (result.ok) entry.loaded += 1;
        else entry.failed += 1;
        entry.completed = entry.loaded + entry.failed;
        entry.touchedAt = Date.now();
        this._timelineUpdateBufferUi(state);
      }
    };

    const workers = Array.from(
      { length: Math.min(this._timelineEffectiveConcurrency(), urls.length) },
      () => worker()
    );
    await Promise.all(workers);
  };

  proto._timelineEnsureBuffered = function(state, frameIndex) {
    const frames = this._timelineFrames(state);
    if (!frames.length) return Promise.resolve(null);
    const index = ((Number(frameIndex) % frames.length) + frames.length) % frames.length;
    const frame = frames[index];
    const preload = this._timelineFrameTileUrls(state, frame);
    if (!preload.urls.length) return Promise.resolve(null);

    const store = this._timelineBufferStore(state);
    const key = this._timelineBufferKey(state, frame, preload.signature);
    const existing = store.get(key);
    if (existing) {
      existing.touchedAt = Date.now();
      if (
        existing.status !== "failed"
        || Date.now() - Number(existing.finishedAt || 0) < BUFFER_RETRY_AFTER_MS
      ) {
        return existing.promise || Promise.resolve(existing);
      }
      store.delete(key);
    }

    const entry = {
      key,
      index,
      frameTime: Number(frame.time),
      viewportSignature: preload.signature,
      status: "loading",
      total: preload.urls.length,
      loaded: 0,
      failed: 0,
      completed: 0,
      startedAt: Date.now(),
      finishedAt: null,
      durationMs: null,
      touchedAt: Date.now(),
      promise: null,
    };
    store.set(key, entry);
    this._timelinePruneBuffer(state);
    this._timelineUpdateBufferUi(state);

    entry.promise = (async () => {
      await this._timelineRunTileQueue(state, entry, preload.urls);
      entry.durationMs = Date.now() - entry.startedAt;
      entry.finishedAt = Date.now();
      entry.touchedAt = Date.now();

      const ratio = entry.total > 0 ? entry.loaded / entry.total : 0;
      if (ratio >= 0.999) {
        entry.status = "ready";
      } else if (ratio >= BUFFER_MIN_PARTIAL_RATIO) {
        entry.status = "partial";
      } else {
        entry.status = "failed";
      }

      if (entry.status !== "ready") {
        this._wrLog?.("buffer_frame_degraded", {
          index: entry.index,
          status: entry.status,
          total: entry.total,
          loaded: entry.loaded,
          failed: entry.failed,
          duration_ms: entry.durationMs,
        }, entry.status === "failed" ? "error" : "warn", state);
      }

      this._timelineRecordLoadDuration(state, entry.durationMs);
      this._timelineUpdateBufferUi(state);
      return entry;
    })();

    return entry.promise;
  };

  proto._timelineLookAheadIndices = function(state) {
    const frames = this._timelineFrames(state);
    if (frames.length < 2) return [];
    const target = this._timelineEffectiveTarget(state);
    if (!target) return [];
    const current = this._timelineEnsureIndex(state);
    return Array.from({ length: target }, (_, offset) => (
      current + offset + 1
    ) % frames.length);
  };

  proto._timelineBufferEntryForIndex = function(state, frameIndex) {
    const frames = this._timelineFrames(state);
    const frame = frames[frameIndex];
    if (!frame) return null;
    const preload = this._timelineFrameTileUrls(state, frame);
    if (!preload.urls.length) return null;
    const key = this._timelineBufferKey(state, frame, preload.signature);
    return this._timelineBufferStore(state).get(key) || null;
  };

  proto._timelineBufferStats = function(state) {
    const lookAhead = this._timelineLookAheadIndices(state);
    const entries = lookAhead.map(index => this._timelineBufferEntryForIndex(state, index));
    const ready = entries.filter(
      entry => entry && (entry.status === "ready" || entry.status === "partial")
    ).length;
    const nextEntry = entries[0] || null;
    return {
      target: lookAhead.length,
      ready,
      nextEntry,
    };
  };

  proto._timelinePrimeBuffer = function(state) {
    if (
      this._timelineBufferSettings().mode === "off"
      || !state?.enabled
      || !state?.descriptor
      || this._timelineFrames(state).length < 2
    ) {
      return Promise.resolve();
    }
    if (state.timelinePrimePromise) return state.timelinePrimePromise;

    const token = Number(state.timelineBufferPrimeToken || 0) + 1;
    state.timelineBufferPrimeToken = token;

    state.timelinePrimePromise = (async () => {
      while (
        state.enabled
        && token === state.timelineBufferPrimeToken
        && this.isConnected
      ) {
        const indices = this._timelineLookAheadIndices(state);
        let candidate = null;

        for (const index of indices) {
          const entry = this._timelineBufferEntryForIndex(state, index);
          if (!entry) {
            candidate = index;
            break;
          }
          if (entry.status === "failed") {
            const retryAge = Date.now() - Number(entry.finishedAt || 0);
            if (retryAge >= BUFFER_RETRY_AFTER_MS) {
              candidate = index;
              break;
            }
          }
        }

        if (candidate === null) break;
        const entry = await this._timelineEnsureBuffered(state, candidate);
        if (entry?.status === "failed") break;
      }
    })().finally(() => {
      if (state.timelineBufferPrimeToken === token) {
        state.timelinePrimePromise = null;
      }
      this._timelineUpdateBufferUi(state);
    });

    state.timelinePrimePromise.then(() => {
      if (state.enabled && this.isConnected) this._timelinePrimeMapStage(state);
    });

    return state.timelinePrimePromise;
  };

  proto._timelineBufferStatusText = function(state) {
    const settings = this._timelineBufferSettings();
    const stats = this._timelineBufferStats(state);
    if (settings.mode === "off") {
      return "Vorpuffer aus · nächster Frame wird bei Bedarf geladen";
    }
    if (!stats.target) return "";

    const entry = stats.nextEntry;
    const startTarget = this._timelineStartReadyTarget(state);
    const prefix = state.timelineWaitingForStartBuffer
      ? `Startpuffer ${stats.ready}/${startTarget}`
      : `Puffer ${stats.ready}/${stats.target}`;
    const bufferText = prefix;
    if (!entry) return `${bufferText} · wartet`;

    if (entry.status === "loading") {
      return `${bufferText} · nächster Frame ${entry.completed}/${entry.total} Kacheln`;
    }
    if (entry.status === "ready") {
      const mapReady = (
        state.timelineStagedIndex === this._timelineLookAheadIndices(state)[0]
        && state.timelineStagedSlot
      );
      return mapReady
        ? `${bufferText} · nächster Frame im Kartenpuffer bereit`
        : `${bufferText} · nächster Frame vorgeladen${state.timelineMapStageLoading ? " · Kartenpuffer lädt …" : ""}`;
    }
    if (entry.status === "partial") {
      return `${bufferText} · nächster Frame teilweise bereit (${entry.loaded}/${entry.total})`;
    }
    return `${bufferText} · ⚠ nächster Frame konnte nicht gepuffert werden`;
  };

  proto._timelineUpdateBufferUi = function(state) {
    const safe = this._safeId?.(state?.key);
    if (!safe) return;
    const enabledInput = this.shadowRoot?.getElementById(`weather-enabled-${safe}`);
    const box = enabledInput?.closest(".weather-layer");
    const buffer = box?.querySelector(".weather-frame-buffer");
    if (!buffer) return;

    const stats = this._timelineBufferStats(state);
    const entry = stats.nextEntry;
    const text = buffer.querySelector('[data-role="buffer-text"]');
    const fill = buffer.querySelector('[data-role="buffer-fill"]');

    if (text) text.textContent = this._timelineBufferStatusText(state);

    let ratio = 0;
    if (this._timelineBufferSettings().mode === "off") {
      ratio = 0;
    } else if (entry?.total) {
      ratio = clamp(entry.completed / entry.total, 0, 1);
    } else if (stats.target && stats.ready) {
      ratio = clamp(stats.ready / stats.target, 0, 1);
    }
    if (fill) fill.style.width = `${Math.round(ratio * 100)}%`;
  };

  proto._timelinePlaybackDelay = function(state) {
    const stats = this._timelineBufferStats(state);
    const durations = Array.isArray(state.timelineLoadDurations)
      ? state.timelineLoadDurations
      : [];
    const average = durations.length
      ? durations.reduce((sum, value) => sum + value, 0) / durations.length
      : 0;

    let delay = PLAYBACK_BASE_DWELL_MS;
    if (stats.ready <= 1) delay = 1500;
    else if (stats.ready === 2) delay = 1150;

    if (average >= 4500) delay = Math.max(delay, 1900);
    else if (average >= 3000) delay = Math.max(delay, 1500);
    else if (average >= 1800) delay = Math.max(delay, 1200);

    return delay;
  };

  proto._timelineWaitForStartBuffer = async function(state, token) {
    const target = this._timelineStartReadyTarget(state);
    if (!target) return true;

    state.timelineWaitingForStartBuffer = true;
    state.timelineStartBufferThreshold = target;
    this._timelineUpdateBufferUi(state);

    const indices = this._timelineLookAheadIndices(state).slice(0, target);
    for (const index of indices) {
      if (
        !state.timelinePlaying
        || token !== state.timelinePlaybackToken
        || !state.enabled
      ) {
        state.timelineWaitingForStartBuffer = false;
        return false;
      }
      const entry = await this._timelineEnsureBuffered(state, index);
      if (!entry || entry.status === "failed") {
        state.timelineWaitingForStartBuffer = false;
        return false;
      }
      this._timelineUpdateBufferUi(state);
    }

    state.timelineWaitingForStartBuffer = false;
    this._timelineUpdateBufferUi(state);
    return true;
  };

  proto._timelineStop = function(state) {
    const wasPlaying = Boolean(state?.timelinePlaying);
    const previousToken = Number(state?.timelinePlaybackToken || 0);
    previousTimelineStop.call(this, state);
    if (!state) return;
    state.timelinePlaying = false;
    state.timelinePlaybackToken = Number(state.timelinePlaybackToken || 0) + 1;
    state.timelineDisplayLoading = false;
    state.timelineWaitingForStartBuffer = false;
    state.timelineResumeAfterViewport = false;
    state.timelineViewportSuspended = false;
    if (wasPlaying) {
      this._wrLog?.("playback_stop", {
        previous_token: previousToken,
        next_token: state.timelinePlaybackToken,
        warning: state.timelinePlaybackWarning || null,
      }, state.timelinePlaybackWarning ? "warn" : "info", state);
    }
    this._timelineUpdateBufferUi(state);
  };

  proto._timelineStart = function(state) {
    const frames = this._timelineFrames(state);
    if (frames.length < 2 || !state?.enabled) return;

    this._timelineStop(state);
    state.timelinePlaying = true;
    const token = Number(state.timelinePlaybackToken || 0) + 1;
    state.timelinePlaybackToken = token;

    const mode = this._timelineBufferSettings().mode;
    this._wrLog?.("playback_start", {
      token,
      index: this._timelineEnsureIndex(state),
      frame_count: frames.length,
      buffer_mode: mode,
      buffer_settings: this._timelineBufferSettings(),
    }, "info", state);
    if (mode !== "off") {
      this._timelinePrimeBuffer(state);
      this._timelinePrimeMapStage(state);
    }
    this._timelineUpdateBufferUi(state);

    state.timelinePlaybackPromise = (async () => {
      if (mode !== "off") {
        const startReady = await this._timelineWaitForStartBuffer(state, token);
        if (!startReady) {
          if (state.timelinePlaying && token === state.timelinePlaybackToken) {
            state.timelinePlaybackWarning = "Startpuffer konnte nicht vollständig aufgebaut werden";
            this._wrLog?.("start_buffer_failed", {
              token,
              buffer: this._timelineBufferStats(state),
            }, "error", state);
            this._timelineStop(state);
            this._renderWeatherLayers();
          }
          return;
        }
      }

      while (
        state.timelinePlaying
        && state.enabled
        && this.isConnected
        && token === state.timelinePlaybackToken
      ) {
        // A pan/zoom does not end the user's playback request. It temporarily
        // suspends this same playback loop until the exact new viewport has
        // been prebuffered and staged. Keeping one owner token avoids the
        // stop/restart race that could leave the UI on "Pause" with no active
        // frame progression.
        if (state.timelineViewportSuspended) {
          const recovery = state.timelineViewportRecoveryPromise;
          if (recovery) await recovery;
          if (
            !state.timelinePlaying
            || token !== state.timelinePlaybackToken
            || !state.enabled
          ) {
            break;
          }
          continue;
        }

        const current = this._timelineEnsureIndex(state);
        const next = current >= frames.length - 1 ? 0 : current + 1;

        if (mode !== "off") {
          const bufferEntry = await this._timelineEnsureBuffered(state, next);

          if (
            !state.timelinePlaying
            || token !== state.timelinePlaybackToken
            || !state.enabled
          ) {
            break;
          }

          if (state.timelineViewportSuspended) {
            const recovery = state.timelineViewportRecoveryPromise;
            if (recovery) await recovery;
            if (
              !state.timelinePlaying
              || token !== state.timelinePlaybackToken
              || !state.enabled
            ) {
              break;
            }
            continue;
          }

          if (bufferEntry?.status === "failed") {
            state.timelinePlaybackWarning = "Puffer konnte den nächsten Frame nicht laden";
            this._wrLog?.("playback_buffer_failed", {
              token,
              next_index: next,
              entry: bufferEntry,
            }, "error", state);
            this._timelineStop(state);
            this._renderWeatherLayers();
            break;
          }
        }

        state.timelineDisplayLoading = true;
        this._timelineUpdateBufferUi(state);
        const swapped = await this._timelineSwapToFrame(state, next, true);

        if (
          !swapped
          || !state.timelinePlaying
          || token !== state.timelinePlaybackToken
          || !state.enabled
        ) {
          if (
            !swapped
            && state.timelineViewportSuspended
            && state.timelinePlaying
            && token === state.timelinePlaybackToken
          ) {
            const recovery = state.timelineViewportRecoveryPromise;
            if (recovery) await recovery;
            if (
              state.timelinePlaying
              && token === state.timelinePlaybackToken
              && state.enabled
            ) {
              continue;
            }
          }

          if (
            !swapped
            && state.timelinePlaying
            && token === state.timelinePlaybackToken
          ) {
            this._wrLog?.("frame_swap_failed", {
              token,
              next_index: next,
              stage_reason: state.timelineStageFailureReason || null,
              stage_detail: state.timelineStageSourceWaitDetail || null,
              style_recovery: Boolean(state.timelineStyleRecoveryActive),
              viewport_suspended: Boolean(state.timelineViewportSuspended),
            }, "error", state);
            this._timelineStop(state);
            this._renderWeatherLayers();
          }
          break;
        }

        if (mode !== "off") {
          this._timelinePrimeBuffer(state);
          this._timelinePrimeMapStage(state);
        }
        this._timelineUpdateBufferUi(state);

        const delay = mode === "off"
          ? PLAYBACK_BASE_DWELL_MS
          : this._timelinePlaybackDelay(state);
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    })().finally(() => {
      if (state.timelinePlaybackToken === token) {
        state.timelinePlaybackPromise = null;
      }
      this._timelineUpdateBufferUi(state);
    });
  };

  proto._loadWeatherLayer = async function(state, refresh = false) {
    await previousLoadWeatherLayer.call(this, state, refresh);
    if (state?.enabled && !state?.error && this._timelineFrames(state).length >= 2) {
      this._timelinePrimeBuffer(state);
    }
  };

  proto._removeWeatherLayerFromMap = function(state) {
    if (state) {
      this._timelineStop(state);
      state.timelineBufferPrimeToken = Number(state.timelineBufferPrimeToken || 0) + 1;
      state.timelinePrimePromise = null;
      if (state.timelineBufferEntries instanceof Map) state.timelineBufferEntries.clear();
      state.timelineStageToken = Number(state.timelineStageToken || 0) + 1;
      state.timelineStagePromise = null;
      state.timelineStagedIndex = null;
      state.timelineStagedSlot = null;
      state.timelineStageLoadingIndex = null;
      state.timelineMapStageLoading = false;
      state.timelineDoubleBufferActive = false;
      state.timelineVisibleSlot = "a";
    }

    const map = this._map;
    const base = state ? this._timelineLayerIdsForSlot(state, "a") : null;
    const buffer = state ? this._timelineLayerIdsForSlot(state, "b") : null;
    const result = previousRemoveWeatherLayerFromMap.call(this, state);
    if (map && buffer) {
      if (map.getLayer(buffer.layer)) map.removeLayer(buffer.layer);
      if (map.getSource(buffer.source)) map.removeSource(buffer.source);
    }
    if (map && base) {
      if (map.getLayer(base.layer)) map.removeLayer(base.layer);
      if (map.getSource(base.source)) map.removeSource(base.source);
    }
    return result;
  };

  proto._timelineResetViewportBuffer = function(state) {
    if (!state?.enabled || !state?.descriptor || this._timelineFrames(state).length < 2) {
      return;
    }

    // Preserve one playback owner across a viewport change. The timeline loop
    // stays logically active but waits on timelineViewportRecoveryPromise.
    // This avoids stop -> restart token races and makes "Pause" truthful:
    // playback is requested, temporarily suspended for buffering, then resumes
    // automatically on the same loop.
    const resumeAfterViewport = Boolean(state.timelinePlaying);
    const viewportToken = Number(state.timelineViewportToken || 0) + 1;
    state.timelineViewportToken = viewportToken;
    state.timelineResumeAfterViewport = resumeAfterViewport;
    state.timelineViewportSuspended = resumeAfterViewport;
    this._wrLog?.("viewport_recovery_start", {
      viewport_token: viewportToken,
      playback_was_running: resumeAfterViewport,
      index: this._timelineEnsureIndex(state),
    }, "info", state);

    // A map move changes the exact set of source tiles. Any preloaded entries
    // and hidden MapLibre staging source belong to the previous viewport and
    // must not survive into the next playback cycle.
    state.timelineBufferPrimeToken = Number(state.timelineBufferPrimeToken || 0) + 1;
    state.timelinePrimePromise = null;
    if (state.timelineBufferEntries instanceof Map) {
      state.timelineBufferEntries.clear();
    }
    state.timelineLoadDurations = [];

    state.timelineStageToken = Number(state.timelineStageToken || 0) + 1;
    state.timelineStagePromise = null;
    state.timelineStagedIndex = null;
    state.timelineStagedSlot = null;
    state.timelineStageLoadingIndex = null;
    state.timelineMapStageLoading = false;
    state.timelineStageFailureReason = null;
    state.timelineStageSourceWaitDetail = null;
    state.timelinePlaybackWarning = null;

    const map = this._map;
    const staleSlot = this._timelineOppositeSlot(state);
    const staleIds = this._timelineLayerIdsForSlot(state, staleSlot);
    if (map?.getLayer(staleIds.layer)) map.removeLayer(staleIds.layer);
    if (map?.getSource(staleIds.source)) map.removeSource(staleIds.source);

    const stillCurrent = () => (
      state.enabled
      && this.isConnected
      && Number(state.timelineViewportToken || 0) === viewportToken
    );

    if (this._timelineBufferSettings().mode === "off") {
      state.timelineViewportSuspended = false;
      state.timelineResumeAfterViewport = false;
      this._timelineUpdateBufferUi(state);
      return;
    }

    // New viewport is rebuilt in one strict order:
    // prebuffer -> hidden MapLibre stage -> release the existing playback loop.
    const recovery = Promise.resolve(this._timelinePrimeBuffer(state))
      .then(() => {
        if (!stillCurrent()) return false;
        return this._timelinePrimeMapStage(state);
      })
      .then(stageReady => {
        if (!stillCurrent()) return false;

        if (!stageReady) {
          state.timelinePlaybackWarning = this._timelineStageWarningText(state);
          this._wrLog?.("viewport_recovery_failed", {
            viewport_token: viewportToken,
            warning: state.timelinePlaybackWarning,
            stage_reason: state.timelineStageFailureReason || null,
            stage_detail: state.timelineStageSourceWaitDetail || null,
          }, "error", state);
          state.timelineResumeAfterViewport = false;
          state.timelineViewportSuspended = false;
          if (resumeAfterViewport && state.timelinePlaying) {
            this._timelineStop(state);
          }
          this._renderWeatherLayers();
          return false;
        }

        // No new playback loop is created here. The already running loop owns
        // the playback token and continues as soon as this barrier is released.
        state.timelineResumeAfterViewport = false;
        state.timelineViewportSuspended = false;
        this._wrLog?.("viewport_recovery_complete", {
          viewport_token: viewportToken,
          playback_continues: Boolean(state.timelinePlaying),
          index: this._timelineEnsureIndex(state),
        }, "info", state);
        this._timelineUpdateBufferUi(state);
        return true;
      })
      .finally(() => {
        if (Number(state.timelineViewportToken || 0) === viewportToken) {
          state.timelineViewportRecoveryPromise = null;
          if (!state.timelinePlaying) {
            state.timelineViewportSuspended = false;
            state.timelineResumeAfterViewport = false;
          }
        }
        this._timelineUpdateBufferUi(state);
      });

    state.timelineViewportRecoveryPromise = recovery;
  };

  proto._applyBasemap = function() {
    const map = this._map;
    if (!map) return previousApplyBasemap.call(this);

    const affected = [...(this._weatherLayers?.values?.() || [])].filter(
      state => (
        state?.enabled
        && state?.descriptor
        && this._timelineFrames(state).length >= 2
      )
    );

    if (!affected.length) {
      return previousApplyBasemap.call(this);
    }

    const styleToken = Number(this._timelineStyleRecoveryToken || 0) + 1;
    this._timelineStyleRecoveryToken = styleToken;

    let finishStyleLoad = null;
    const styleLoaded = new Promise(resolve => {
      let settled = false;
      let timeout = null;

      const finish = loaded => {
        if (settled) return;
        settled = true;
        if (timeout) clearTimeout(timeout);
        map.off("style.load", onStyleLoad);
        resolve(Boolean(loaded));
      };
      const onStyleLoad = () => finish(true);

      map.on("style.load", onStyleLoad);
      timeout = setTimeout(() => finish(false), BUFFER_SOURCE_TIMEOUT_MS + 5000);
      finishStyleLoad = finish;
    });

    for (const state of affected) {
      const wasPlaying = Boolean(state.timelinePlaying);
      state.timelineStyleRecoveryActive = true;
      state.timelineStyleRecoveryToken = styleToken;
      state.timelineResumeAfterStyle = wasPlaying;
      this._wrLog?.("style_recovery_start", {
        style_token: styleToken,
        playback_was_running: wasPlaying,
        basemap_provider: this._basemapProvider || null,
        basemap_style: this._basemapStyle || null,
        index: this._timelineEnsureIndex(state),
      }, "info", state);

      // Keep the existing playback loop alive. It waits on the same recovery
      // barrier already used for viewport changes while setStyle() destroys
      // and rebuilds all MapLibre sources/layers.
      if (wasPlaying) {
        state.timelineViewportSuspended = true;
      }

      // Only MapLibre staging is style-bound. The wrbuffer byte cache and its
      // viewport entries stay valid because a basemap change does not change
      // the geographic viewport.
      state.timelineStageToken = Number(state.timelineStageToken || 0) + 1;
      state.timelineStagePromise = null;
      state.timelineStagedIndex = null;
      state.timelineStagedSlot = null;
      state.timelineStageLoadingIndex = null;
      state.timelineMapStageLoading = false;
      state.timelineStageFailureReason = null;
      state.timelineStageSourceWaitDetail = null;
      state.timelinePlaybackWarning = null;

      const recovery = styleLoaded
        .then(async loaded => {
          if (
            !loaded
            || !state.enabled
            || !this.isConnected
            || state.timelineStyleRecoveryToken !== styleToken
            || this._timelineStyleRecoveryToken !== styleToken
          ) {
            return false;
          }

          // The normal style.load handler restores the visible weather layer.
          // Wait until any style-induced camera work is fully settled before
          // creating the hidden stage. Building it while MapLibre is moving can
          // abort/remove the new raster source immediately.
          const mapStable = await this._timelineWaitForMapStable();
          if (
            !mapStable
            || !state.enabled
            || !this.isConnected
            || state.timelineStyleRecoveryToken !== styleToken
            || this._timelineStyleRecoveryToken !== styleToken
            || !this._map?.isStyleLoaded()
          ) {
            return false;
          }

          // Give the restored visible slot two paints before adding the hidden
          // staging slot. This keeps source/layer ordering deterministic across
          // light, dark and local/no-basemap styles.
          const restoredRendered = await this._timelineWaitForRenderCycles(2);
          if (!restoredRendered) return false;

          return this._timelinePrimeMapStage(state);
        })
        .then(stageReady => {
          if (
            state.timelineStyleRecoveryToken !== styleToken
            || this._timelineStyleRecoveryToken !== styleToken
          ) {
            return false;
          }

          state.timelineStyleRecoveryActive = false;
          state.timelineResumeAfterStyle = false;
          state.timelineViewportSuspended = false;

          if (!stageReady) {
            const stageDetail = this._timelineStageWarningText(state);
            state.timelinePlaybackWarning = (
              "Kartenstil: Wetterlayer/Kartenpuffer konnte nach dem Stilwechsel "
              + `nicht vollständig wiederhergestellt werden · ${stageDetail}`
            );
            this._wrLog?.("style_recovery_failed", {
              style_token: styleToken,
              warning: state.timelinePlaybackWarning,
              stage_reason: state.timelineStageFailureReason || null,
              stage_detail: state.timelineStageSourceWaitDetail || null,
              map_stable: Boolean(this._map?.isStyleLoaded?.())
                && !(this._map?.isMoving?.() || this._map?.isZooming?.() || this._map?.isRotating?.()),
            }, "error", state);
            if (wasPlaying && state.timelinePlaying) {
              this._timelineStop(state);
            }
            this._renderWeatherLayers();
            return false;
          }

          // Do not create a new playback loop. If playback was active, the
          // existing loop is released from its recovery barrier here.
          state.timelinePlaybackWarning = null;
          this._wrLog?.("style_recovery_complete", {
            style_token: styleToken,
            playback_continues: Boolean(state.timelinePlaying),
            basemap_provider: this._basemapProvider || null,
            basemap_style: this._basemapStyle || null,
            index: this._timelineEnsureIndex(state),
          }, "info", state);
          this._timelineUpdateBufferUi(state);
          return true;
        })
        .finally(() => {
          if (state.timelineStyleRecoveryToken === styleToken) {
            state.timelineStyleRecoveryActive = false;
            state.timelineResumeAfterStyle = false;
            if (!state.timelinePlaying) {
              state.timelineViewportSuspended = false;
            }
            if (state.timelineViewportRecoveryPromise === recovery) {
              state.timelineViewportRecoveryPromise = null;
            }
          }
          this._timelineUpdateBufferUi(state);
        });

      state.timelineViewportRecoveryPromise = recovery;
    }

    try {
      return previousApplyBasemap.call(this);
    } catch (error) {
      finishStyleLoad?.(false);
      this._wrLog?.("style_recovery_exception", {
        error,
        style_token: styleToken,
        basemap_provider: this._basemapProvider || null,
        basemap_style: this._basemapStyle || null,
      }, "error");
      throw error;
    }
  };

  proto._ensureMap = function() {
    const result = previousEnsureMap.call(this);
    if (this._map && !this._timelineBufferMapHooked) {
      this._timelineBufferMapHooked = true;
      const reprimeForViewport = () => {
        for (const state of this._weatherLayers?.values?.() || []) {
          // setStyle() restores the same viewport through its own dedicated
          // recovery barrier. Its jumpTo() may emit moveend; do not start a
          // second competing viewport rebuild for that synthetic move.
          if (state?.timelineStyleRecoveryActive) continue;
          this._timelineResetViewportBuffer(state);
        }
      };

      // MapLibre emits moveend after pans and zooms. Listening to zoomend as
      // well caused the same viewport change to invalidate/restart staging
      // twice; the second token could cancel the first otherwise valid stage.
      this._map.on("moveend", reprimeForViewport);
    }
    return result;
  };

  proto._timelineInstallBufferSettingsStyle = function() {
    if (this.shadowRoot?.getElementById("weather-router-buffer-settings-style")) return;
    const style = document.createElement("style");
    style.id = "weather-router-buffer-settings-style";
    style.textContent = `
      .weather-buffer-settings {
        margin:0 0 9px;
        border:1px solid color-mix(in srgb,var(--divider-color,#555) 68%,transparent);
        border-radius:9px;
        background:rgba(128,128,128,.035);
        overflow:hidden;
      }
      .weather-buffer-settings > summary {
        cursor:pointer;
        padding:8px 9px;
        font-size:11px;
        font-weight:700;
        user-select:none;
      }
      .weather-buffer-settings-body {
        padding:0 9px 9px;
        display:grid;
        gap:8px;
      }
      .weather-buffer-settings-grid {
        display:grid;
        grid-template-columns:1fr 1fr;
        gap:7px;
      }
      .weather-buffer-settings-grid label {
        margin:0;
        font-size:10px;
      }
      .weather-buffer-settings-note {
        font-size:10px;
        line-height:1.35;
        opacity:.62;
      }
      @media(max-width:520px) {
        .weather-buffer-settings-grid { grid-template-columns:1fr; }
      }
    `;
    this.shadowRoot.appendChild(style);
  };

  proto._timelineRenderBufferSettings = function() {
    const host = this.shadowRoot?.getElementById("weather-layer-list");
    if (!host) return;
    this._timelineInstallBufferSettingsStyle();

    const settings = this._timelineBufferSettings();
    const panel = document.createElement("details");
    panel.className = "weather-buffer-settings";
    panel.open = Boolean(this._timelineBufferSettingsOpen);

    const targetOptions = Array.from(
      { length: BUFFER_MANUAL_MAX_TARGET },
      (_, index) => index + 1
    ).map(value => `<option value="${value}" ${settings.target === value ? "selected" : ""}>${value} Frame${value === 1 ? "" : "s"}</option>`).join("");

    const concurrencyOptions = Array.from(
      { length: BUFFER_MANUAL_MAX_CONCURRENCY },
      (_, index) => index + 1
    ).map(value => `<option value="${value}" ${settings.concurrency === value ? "selected" : ""}>${value}</option>`).join("");

    const startOptions = Array.from(
      { length: settings.target },
      (_, index) => index + 1
    ).map(value => `<option value="${value}" ${settings.startReady === value ? "selected" : ""}>${value} Frame${value === 1 ? "" : "s"}</option>`).join("");

    panel.innerHTML = `
      <summary>Wiedergabepuffer · ${this._timelineBufferModeLabel()}</summary>
      <div class="weather-buffer-settings-body">
        <div>
          <label>Modus</label>
          <select data-buffer-setting="mode">
            <option value="auto" ${settings.mode === "auto" ? "selected" : ""}>Automatisch</option>
            <option value="off" ${settings.mode === "off" ? "selected" : ""}>Aus · nur bei Bedarf laden</option>
            <option value="manual" ${settings.mode === "manual" ? "selected" : ""}>Manuell</option>
          </select>
        </div>
        <div class="weather-buffer-settings-grid" data-buffer-manual ${settings.mode === "manual" ? "" : "hidden"}>
          <div>
            <label>Vorladen</label>
            <select data-buffer-setting="target">${targetOptions}</select>
          </div>
          <div>
            <label>Parallele Kacheln</label>
            <select data-buffer-setting="concurrency">${concurrencyOptions}</select>
          </div>
          <div>
            <label>Wiedergabe starten ab</label>
            <select data-buffer-setting="startReady">${startOptions}</select>
          </div>
        </div>
        <div class="weather-buffer-settings-note">
          Diese Einstellung gilt nur für diesen Browser. Mehr Vorlauf kann eine langsame Verbindung glätten,
          benötigt dafür bewusst mehr Ladezeit, Browsercache und Netzwerkverkehr.
        </div>
      </div>
    `;

    panel.addEventListener("toggle", () => {
      this._timelineBufferSettingsOpen = panel.open;
    });

    const saveFromControls = () => {
      const mode = panel.querySelector('[data-buffer-setting="mode"]').value;
      const target = Number(panel.querySelector('[data-buffer-setting="target"]')?.value || settings.target);
      const concurrency = Number(panel.querySelector('[data-buffer-setting="concurrency"]')?.value || settings.concurrency);
      const startSelect = panel.querySelector('[data-buffer-setting="startReady"]');
      const startReady = Number(startSelect?.value || Math.min(settings.startReady, target));
      this._timelineSaveBufferSettings({
        mode,
        target,
        concurrency,
        startReady: Math.min(startReady, target),
      });
      this._timelineApplyBufferSettings();
    };

    panel.querySelectorAll("[data-buffer-setting]").forEach(control => {
      control.addEventListener("change", saveFromControls);
    });

    host.prepend(panel);
  };

  proto._renderWeatherLayers = function() {
    previousRenderWeatherLayers.call(this);
    this._timelineRenderBufferSettings();

    for (const state of this._weatherLayers?.values?.() || []) {
      const frames = this._timelineFrames(state);
      if (frames.length < 2 || !state.descriptor) continue;

      const safe = this._safeId(state.key);
      const enabledInput = this.shadowRoot.getElementById(`weather-enabled-${safe}`);
      const box = enabledInput?.closest(".weather-layer");
      const timeline = box?.querySelector(".weather-timeline");
      if (!box || !timeline || timeline.querySelector(".weather-frame-buffer")) continue;

      const buffer = document.createElement("div");
      buffer.className = "weather-frame-buffer";
      buffer.style.cssText = "margin-top:7px;min-height:31px;display:grid;gap:4px";
      buffer.innerHTML = `
        <div data-role="buffer-text" style="font-size:10px;opacity:.66;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
          Puffer wird vorbereitet …
        </div>
        <div style="height:4px;border-radius:999px;background:rgba(128,128,128,.18);overflow:hidden">
          <div data-role="buffer-fill" style="height:100%;width:0%;background:var(--primary-color,#03a9f4);transition:width .16s linear"></div>
        </div>
      `;
      timeline.appendChild(buffer);

      if (state.timelinePlaybackWarning) {
        const warning = document.createElement("div");
        warning.className = "error";
        warning.style.cssText = "margin-top:5px;font-size:10px";
        warning.textContent = state.timelinePlaybackWarning;
        timeline.appendChild(warning);
      }

      this._timelineUpdateBufferUi(state);
      if (state.enabled) this._timelinePrimeBuffer(state);
    }
  };

  console.info("[WeatherRouter] adaptive multi-frame raster buffer + shared byte-cache protocol + render-settled MapLibre double buffer enabled");
}
