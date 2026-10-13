const LAB_ELEMENT = "weather-router-lab";
const EVENT_LOG_SCHEMA = "weather_router.event_log.v1";
const EVENT_LOG_LIMIT = 500;
const EVENT_LOG_MAX_STRING = 500;

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Ereignislog registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterEventLogEnhanced) {
  proto.__weatherRouterEventLogEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousSetMapStatus = proto._setMapStatus;
  const previousApplyBasemap = proto._applyBasemap;
  const previousLoadWeatherLayer = proto._loadWeatherLayer;
  const previousDisconnectedCallback = proto.disconnectedCallback;

  const sensitiveKey = key => /(?:url|uri|token|secret|password|authorization|api.?key|latitude|longitude|coordinate|bbox)/i.test(String(key || ""));

  const redactString = value => {
    const text = String(value ?? "");
    return text
      .replace(/https?:\/\/[^\s"'<>]+/gi, "<url-redacted>")
      .replace(/([?&](?:api[_-]?key|apikey|access[_-]?token|token|key|password|secret)=)[^&#\s]+/gi, "$1<redacted>")
      .slice(0, EVENT_LOG_MAX_STRING);
  };

  proto._wrEventLogStore = function() {
    if (!this._wrEventLogState) {
      this._wrEventLogState = {
        started_at: new Date().toISOString(),
        sequence: 0,
        events: [],
      };
    }
    return this._wrEventLogState;
  };

  proto._wrEventSanitize = function(value, depth = 0, key = "") {
    if (sensitiveKey(key)) return "<redacted>";
    if (depth > 5) return "<max-depth>";

    if (value === null || value === undefined) return value ?? null;
    if (typeof value === "string") return redactString(value);
    if (typeof value === "number") return Number.isFinite(value) ? value : String(value);
    if (typeof value === "boolean") return value;

    if (Array.isArray(value)) {
      return value.slice(0, 30).map(item => this._wrEventSanitize(item, depth + 1));
    }

    if (value instanceof Error) {
      return {
        name: redactString(value.name),
        message: redactString(value.message),
      };
    }

    if (typeof value === "object") {
      const result = {};
      for (const [childKey, childValue] of Object.entries(value).slice(0, 60)) {
        result[childKey] = sensitiveKey(childKey)
          ? "<redacted>"
          : this._wrEventSanitize(childValue, depth + 1, childKey);
      }
      return result;
    }

    return redactString(value);
  };

  proto._wrEventLogBadge = function() {
    const button = this.shadowRoot?.getElementById("wr-event-log-open");
    if (!button) return;
    const count = this._wrEventLogStore().events.length;
    button.textContent = `📋 Ereignislog · ${count}`;
  };

  proto._wrLog = function(event, details = {}, level = "info", state = null) {
    const store = this._wrEventLogStore();
    store.sequence += 1;

    const record = {
      seq: store.sequence,
      time: new Date().toISOString(),
      level,
      event: String(event || "event"),
    };

    if (state) {
      record.provider = state.provider || null;
      record.capability = state.capability || null;
    }

    const safe = this._wrEventSanitize(details);
    if (safe && typeof safe === "object" && Object.keys(safe).length) {
      record.details = safe;
    }

    store.events.push(record);
    if (store.events.length > EVENT_LOG_LIMIT) {
      store.events.splice(0, store.events.length - EVENT_LOG_LIMIT);
    }

    this._wrEventLogBadge();
    return record;
  };

  proto._wrEventLogLayerSnapshot = function(state) {
    let frames = [];
    let buffer = null;

    try {
      frames = this._timelineFrames?.(state) || [];
    } catch (_error) {
      frames = [];
    }

    try {
      if (typeof this._timelineBufferStats === "function") {
        const stats = this._timelineBufferStats(state);
        const entry = stats?.nextEntry;
        buffer = {
          target: Number(stats?.target || 0),
          ready: Number(stats?.ready || 0),
          next: entry ? {
            index: Number(entry.index),
            status: entry.status || null,
            total: Number(entry.total || 0),
            loaded: Number(entry.loaded || 0),
            failed: Number(entry.failed || 0),
            completed: Number(entry.completed || 0),
            duration_ms: Number(entry.durationMs || 0) || null,
          } : null,
        };
      }
    } catch (_error) {
      buffer = { error: "snapshot_failed" };
    }

    return this._wrEventSanitize({
      provider: state?.provider || null,
      provider_name: state?.providerName || null,
      capability: state?.capability || null,
      capability_name: state?.capabilityName || null,
      enabled: Boolean(state?.enabled),
      loading: Boolean(state?.loading),
      error: state?.error || null,
      opacity: Number(state?.opacity),
      timeline: {
        frame_count: frames.length,
        index: Number.isInteger(state?.timelineIndex) ? state.timelineIndex : null,
        frame_time: Number(state?.descriptor?.frame_time) || null,
        playing: Boolean(state?.timelinePlaying),
        playback_token: Number(state?.timelinePlaybackToken || 0),
        viewport_suspended: Boolean(state?.timelineViewportSuspended),
        style_recovery_active: Boolean(state?.timelineStyleRecoveryActive),
        warning: state?.timelinePlaybackWarning || null,
      },
      buffer,
      stage: {
        staged_index: Number.isInteger(state?.timelineStagedIndex) ? state.timelineStagedIndex : null,
        staged_slot: state?.timelineStagedSlot || null,
        loading_index: Number.isInteger(state?.timelineStageLoadingIndex)
          ? state.timelineStageLoadingIndex
          : null,
        loading: Boolean(state?.timelineMapStageLoading),
        failure_reason: state?.timelineStageFailureReason || null,
        source_wait: state?.timelineStageSourceWaitDetail || null,
      },
      tile_warning: state?.tileWarning || null,
    });
  };

  proto._wrEventLogSnapshot = function() {
    const map = this._map;
    let protocolCache = null;

    try {
      protocolCache = typeof this._timelineProtocolCacheStats === "function"
        ? this._timelineProtocolCacheStats()
        : null;
    } catch (_error) {
      protocolCache = { error: "snapshot_failed" };
    }

    let mapStatus = null;
    try {
      mapStatus = {
        mode: this._mapMode || "docked",
        basemap_provider: this._basemapProvider || null,
        basemap_style: this._basemapStyle || null,
        style_loaded: Boolean(map?.isStyleLoaded?.()),
        moving: Boolean(map?.isMoving?.()),
        zooming: Boolean(map?.isZooming?.()),
        rotating: Boolean(map?.isRotating?.()),
        zoom: Number.isFinite(Number(map?.getZoom?.()))
          ? Math.round(Number(map.getZoom()) * 100) / 100
          : null,
        ui_status: this.shadowRoot?.getElementById("map-status")?.textContent || null,
      };
    } catch (_error) {
      mapStatus = { error: "snapshot_failed" };
    }

    const store = this._wrEventLogStore();
    return this._wrEventSanitize({
      schema: EVENT_LOG_SCHEMA,
      generated_at: new Date().toISOString(),
      session_started_at: store.started_at,
      build: LabClass.buildVersion || "unknown",
      browser: {
        user_agent: navigator.userAgent,
        visibility: document.visibilityState,
        online: navigator.onLine,
      },
      map: mapStatus,
      buffer_settings: typeof this._timelineBufferSettings === "function"
        ? this._timelineBufferSettings()
        : null,
      protocol_cache: protocolCache,
      layers: [...(this._weatherLayers?.values?.() || [])]
        .filter(state => state?.enabled || state?.error || state?.descriptor)
        .map(state => this._wrEventLogLayerSnapshot(state)),
      events: store.events,
    });
  };

  proto._wrEventLogText = function() {
    return JSON.stringify(this._wrEventLogSnapshot(), null, 2);
  };

  proto._wrEventLogCopyText = async function(text) {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_error) {
        // Fall through to the legacy copy path below.
      }
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
    document.body.appendChild(textarea);
    textarea.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch (_error) {
      copied = false;
    }
    textarea.remove();
    return copied;
  };

  proto._wrEventLogRefreshOutput = function() {
    const output = this.shadowRoot?.getElementById("wr-event-log-output");
    if (!output) return;
    output.textContent = this._wrEventLogText();
  };

  proto._wrEventLogOpen = function() {
    const panel = this.shadowRoot?.getElementById("wr-event-log-window");
    if (!panel) return;
    this._wrLog("event_log_opened");
    this._wrEventLogRefreshOutput();
    panel.hidden = false;
  };

  proto._wrEventLogClose = function() {
    const panel = this.shadowRoot?.getElementById("wr-event-log-window");
    if (panel) panel.hidden = true;
  };

  proto._wrEventLogCopy = async function() {
    const status = this.shadowRoot?.getElementById("wr-event-log-status");
    const text = this._wrEventLogText();
    const copied = await this._wrEventLogCopyText(text);
    if (status) {
      status.textContent = copied
        ? "Ereignislog kopiert · kann direkt in den Chat eingefügt werden."
        : "Kopieren nicht möglich · JSON unten markieren und manuell kopieren.";
      status.className = copied ? "wr-event-log-status ok" : "wr-event-log-status error";
    }
    this._wrLog("event_log_copy", { copied });
    this._wrEventLogRefreshOutput();
  };

  proto._wrEventLogClear = function() {
    const store = this._wrEventLogStore();
    store.events = [];
    store.started_at = new Date().toISOString();
    store.sequence = 0;
    this._wrEventLogBadge();
    this._wrEventLogRefreshOutput();
    const status = this.shadowRoot?.getElementById("wr-event-log-status");
    if (status) {
      status.textContent = "Ereignislog geleert.";
      status.className = "wr-event-log-status muted";
    }
  };

  proto._wrEventLogInstallGlobalHandlers = function() {
    if (this._wrEventLogGlobalHandlers) return;

    const onError = event => {
      this._wrLog("browser_error", {
        message: event?.message || event?.error?.message || "unbekannter Browserfehler",
        line: Number(event?.lineno || 0) || null,
        column: Number(event?.colno || 0) || null,
      }, "error");
    };

    const onUnhandled = event => {
      this._wrLog("unhandled_rejection", {
        reason: event?.reason instanceof Error
          ? { name: event.reason.name, message: event.reason.message }
          : String(event?.reason || "unbekannte Promise-Ablehnung"),
      }, "error");
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandled);
    this._wrEventLogGlobalHandlers = { onError, onUnhandled };
  };

  proto._wrEventLogRemoveGlobalHandlers = function() {
    const handlers = this._wrEventLogGlobalHandlers;
    if (!handlers) return;
    window.removeEventListener("error", handlers.onError);
    window.removeEventListener("unhandledrejection", handlers.onUnhandled);
    this._wrEventLogGlobalHandlers = null;
  };

  proto._wrEventLogInstallUI = function() {
    const root = this.shadowRoot;
    const sidebar = root?.querySelector(".sidebar");
    if (!root || !sidebar) return;

    if (!root.getElementById("wr-event-log-style")) {
      const style = document.createElement("style");
      style.id = "wr-event-log-style";
      style.textContent = `
        .wr-event-log-launch-wrap { display:flex; gap:8px; margin:0 0 12px; }
        .wr-event-log-launch {
          width:100%; min-height:38px; font-weight:750;
          border-color:color-mix(in srgb,var(--warning-color,#ff9800) 55%,var(--divider-color,#555));
          background:color-mix(in srgb,var(--warning-color,#ff9800) 11%,var(--secondary-background-color,#282828));
        }
        .wr-event-log-window[hidden] { display:none !important; }
        .wr-event-log-window {
          position:fixed; inset:6vh auto auto 50%; transform:translateX(-50%);
          z-index:10001; width:min(980px,calc(100vw - 28px)); max-height:88vh;
          display:flex; flex-direction:column; overflow:hidden;
          border:1px solid color-mix(in srgb,var(--warning-color,#ff9800) 45%,var(--divider-color,#555));
          border-radius:16px; background:var(--card-background-color,#1c1c1c);
          color:var(--primary-text-color,#eee); box-shadow:0 18px 65px rgba(0,0,0,.58);
        }
        .wr-event-log-head {
          display:flex; align-items:center; gap:12px; justify-content:space-between;
          padding:13px 15px; border-bottom:1px solid var(--divider-color,#444);
          background:color-mix(in srgb,var(--secondary-background-color,#282828) 88%,transparent);
        }
        .wr-event-log-head strong { font-size:16px; }
        .wr-event-log-head small { display:block; margin-top:2px; opacity:.62; }
        .wr-event-log-close { min-width:38px; min-height:34px; padding:5px 10px; font-size:18px; }
        .wr-event-log-body { overflow:auto; padding:14px; }
        .wr-event-log-help {
          margin:0 0 10px; padding:10px 12px; border-radius:10px;
          border:1px solid var(--divider-color,#444); font-size:11px; line-height:1.45; opacity:.78;
        }
        .wr-event-log-actions { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
        .wr-event-log-actions button { min-height:36px; }
        .wr-event-log-status { min-height:20px; margin:0 0 8px; font-size:11px; }
        .wr-event-log-output {
          display:block; width:100%; max-height:56vh; margin:0; white-space:pre;
          overflow:auto; font-size:10px; line-height:1.35;
        }
        @media(max-width:650px) {
          .wr-event-log-window {
            inset:10px 8px 10px 8px; transform:none; width:auto; max-height:none;
          }
          .wr-event-log-actions button { flex:1 1 auto; }
        }
      `;
      root.appendChild(style);
    }

    if (!root.getElementById("wr-event-log-launch-wrap")) {
      const wrap = document.createElement("div");
      wrap.className = "wr-event-log-launch-wrap";
      wrap.id = "wr-event-log-launch-wrap";
      wrap.innerHTML = `
        <button id="wr-event-log-open" class="wr-event-log-launch" type="button">📋 Ereignislog · 0</button>
      `;
      const hero = root.getElementById("weather-router-brand-hero");
      if (hero?.nextSibling) sidebar.insertBefore(wrap, hero.nextSibling);
      else if (hero) hero.after(wrap);
      else sidebar.prepend(wrap);
      root.getElementById("wr-event-log-open").addEventListener("click", () => {
        this._wrEventLogOpen();
      });
    }

    if (!root.getElementById("wr-event-log-window")) {
      const panel = document.createElement("section");
      panel.className = "wr-event-log-window";
      panel.id = "wr-event-log-window";
      panel.hidden = true;
      panel.innerHTML = `
        <div class="wr-event-log-head">
          <div>
            <strong>WeatherRouter · Ereignislog</strong>
            <small>lokaler Ringpuffer · redigiertes JSON · keine Koordinaten/URLs/Secrets</small>
          </div>
          <button id="wr-event-log-close" class="wr-event-log-close" type="button" title="Schließen">×</button>
        </div>
        <div class="wr-event-log-body">
          <div class="wr-event-log-help">
            Bei einem Fehler nichts zurücksetzen: Ereignislog öffnen, <strong>Log kopieren</strong>
            drücken und den JSON-Block direkt in den Chat einfügen. Enthalten sind Build,
            Karten-/Wiedergabe-/Pufferzustand und die letzten relevanten Ereignisse.
          </div>
          <div class="wr-event-log-actions">
            <button id="wr-event-log-copy" class="primary" type="button">Log kopieren</button>
            <button id="wr-event-log-refresh" type="button">Ansicht aktualisieren</button>
            <button id="wr-event-log-clear" type="button">Log leeren</button>
          </div>
          <div id="wr-event-log-status" class="wr-event-log-status muted">
            Noch nicht kopiert.
          </div>
          <pre id="wr-event-log-output" class="wr-event-log-output">—</pre>
        </div>
      `;
      root.appendChild(panel);

      root.getElementById("wr-event-log-close").addEventListener("click", () => this._wrEventLogClose());
      root.getElementById("wr-event-log-copy").addEventListener("click", () => this._wrEventLogCopy());
      root.getElementById("wr-event-log-refresh").addEventListener("click", () => this._wrEventLogRefreshOutput());
      root.getElementById("wr-event-log-clear").addEventListener("click", () => this._wrEventLogClear());
    }

    this._wrEventLogBadge();
    this._wrEventLogInstallGlobalHandlers();
  };

  proto._renderShell = function() {
    previousRenderShell.call(this);
    this._wrEventLogInstallUI();
    this._wrLog("lab_shell_ready", {
      build: LabClass.buildVersion || "unknown",
    });
  };

  proto._setMapStatus = function(text, className = "") {
    const signature = `${text}|${className}`;
    previousSetMapStatus.call(this, text, className);
    if (signature !== this._wrLastMapStatusSignature) {
      this._wrLastMapStatusSignature = signature;
      this._wrLog("map_status", { text, class_name: className || null });
    }
  };

  proto._applyBasemap = function() {
    this._wrLog("basemap_change_requested", {
      provider: this._basemapProvider || null,
      style: this._basemapStyle || null,
    });
    return previousApplyBasemap.call(this);
  };

  proto._loadWeatherLayer = async function(state, refresh = false) {
    this._wrLog("layer_load_start", {
      refresh: Boolean(refresh),
      enabled: Boolean(state?.enabled),
    }, "info", state);

    try {
      const result = await previousLoadWeatherLayer.call(this, state, refresh);
      this._wrLog("layer_load_complete", {
        refresh: Boolean(refresh),
        enabled: Boolean(state?.enabled),
        error: state?.error || null,
        frame_count: Array.isArray(state?.descriptor?.timeline?.frames)
          ? state.descriptor.timeline.frames.length
          : 0,
      }, state?.error ? "error" : "info", state);
      return result;
    } catch (error) {
      this._wrLog("layer_load_exception", { error }, "error", state);
      throw error;
    }
  };

  proto.disconnectedCallback = function() {
    this._wrLog("lab_disconnected");
    this._wrEventLogRemoveGlobalHandlers();
    return previousDisconnectedCallback.call(this);
  };

  console.info("[WeatherRouter] structured local event log enabled");
}
