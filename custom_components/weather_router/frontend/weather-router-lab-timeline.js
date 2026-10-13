const LAB_ELEMENT = "weather-router-lab";
const PLAYBACK_INTERVAL_MS = 900;

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Timeline-Modul registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterTimelineEnhanced) {
  proto.__weatherRouterTimelineEnhanced = true;

  const originalRenderWeatherLayers = proto._renderWeatherLayers;
  const originalLoadWeatherLayer = proto._loadWeatherLayer;
  const originalAddWeatherLayerToMap = proto._addWeatherLayerToMap;
  const originalWeatherLayerStatusText = proto._weatherLayerStatusText;
  const originalDisconnectedCallback = proto.disconnectedCallback;

  proto._timelineFrames = function(state) {
    const frames = state?.descriptor?.timeline?.frames;
    return Array.isArray(frames)
      ? frames.filter(frame => frame && Number.isFinite(Number(frame.time)) && typeof frame.tile_url === "string")
      : [];
  };

  proto._timelineEnsureIndex = function(state) {
    const frames = this._timelineFrames(state);
    if (!frames.length) return -1;
    if (!Number.isInteger(state.timelineIndex) || state.timelineIndex < 0 || state.timelineIndex >= frames.length) {
      const preferred = Number(state?.descriptor?.timeline?.default_index);
      state.timelineIndex = Number.isInteger(preferred) && preferred >= 0 && preferred < frames.length
        ? preferred
        : frames.length - 1;
    }
    return state.timelineIndex;
  };

  proto._timelineNearestIndex = function(frames, targetTime) {
    if (!Array.isArray(frames) || !frames.length) return -1;
    const target = Number(targetTime);
    if (!Number.isFinite(target)) return frames.length - 1;

    let bestIndex = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    frames.forEach((frame, index) => {
      const time = Number(frame?.time);
      if (!Number.isFinite(time)) return;
      const distance = Math.abs(time - target);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = index;
      }
    });
    return bestIndex;
  };

  proto._timelineStop = function(state) {
    if (state?.timelineTimer) clearInterval(state.timelineTimer);
    if (state) {
      state.timelineTimer = null;
      state.timelinePlaying = false;
    }
  };

  proto._timelineApplyFrame = function(state, rerender = true) {
    const frames = this._timelineFrames(state);
    const index = this._timelineEnsureIndex(state);
    if (!frames.length || index < 0 || !state.descriptor) return;

    const frame = frames[index];
    state.descriptor.tile_url = frame.tile_url;
    state.descriptor.frame_time = Number(frame.time);
    originalAddWeatherLayerToMap.call(this, state);
    if (rerender) this._renderWeatherLayers();
  };

  proto._timelineStart = function(state) {
    const frames = this._timelineFrames(state);
    if (frames.length < 2) return;
    this._timelineStop(state);
    state.timelinePlaying = true;
    state.timelineTimer = setInterval(() => {
      if (!state.enabled || !this.isConnected) {
        this._timelineStop(state);
        return;
      }
      const current = this._timelineEnsureIndex(state);
      state.timelineIndex = current >= frames.length - 1 ? 0 : current + 1;
      this._timelineApplyFrame(state, true);
    }, PLAYBACK_INTERVAL_MS);
  };

  proto._timelineAgeText = function(epoch) {
    const seconds = Number(epoch);
    if (!Number.isFinite(seconds)) return "";
    const deltaMinutes = Math.round((Date.now() - seconds * 1000) / 60000);
    if (deltaMinutes <= -120) return `in ${Math.round(Math.abs(deltaMinutes) / 60)} Std.`;
    if (deltaMinutes < -1) return `in ${Math.abs(deltaMinutes)} Min.`;
    if (deltaMinutes === -1) return "in 1 Min.";
    if (deltaMinutes < 1) return "gerade eben";
    if (deltaMinutes === 1) return "vor 1 Min.";
    if (deltaMinutes < 120) return `vor ${deltaMinutes} Min.`;
    return `vor ${Math.round(deltaMinutes / 60)} Std.`;
  };

  proto._timelineTimeGranularity = function(state) {
    return state?.descriptor?.provider_metadata?.time_granularity || "datetime";
  };

  proto._timelineDailyDateText = function(epoch) {
    const seconds = Number(epoch);
    if (!Number.isFinite(seconds)) return "";
    return new Intl.DateTimeFormat("de-DE", {
      timeZone: "UTC",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(new Date(seconds * 1000));
  };

  proto._timelineDailyAgeText = function(epoch) {
    const seconds = Number(epoch);
    if (!Number.isFinite(seconds)) return "";
    const frame = new Date(seconds * 1000);
    const now = new Date();
    const frameDay = Date.UTC(
      frame.getUTCFullYear(),
      frame.getUTCMonth(),
      frame.getUTCDate()
    );
    const today = Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate()
    );
    const deltaDays = Math.round((today - frameDay) / 86400000);
    if (deltaDays < -1) return `in ${Math.abs(deltaDays)} Tagen`;
    if (deltaDays === -1) return "morgen";
    if (deltaDays === 0) return "heute";
    if (deltaDays === 1) return "gestern";
    return `vor ${deltaDays} Tagen`;
  };

  proto._timelineFrameAgeText = function(state, frame) {
    return this._timelineTimeGranularity(state) === "day"
      ? this._timelineDailyAgeText(frame?.time)
      : this._timelineAgeText(frame?.time);
  };

  proto._timelineFrameKindLabel = function(frame) {
    if (frame?.kind === "forecast") return "Vorhersage";
    if (frame?.kind === "observation") return "Beobachtung";
    return "";
  };

  proto._timelineFrameLabel = function(state) {
    const frames = this._timelineFrames(state);
    const index = this._timelineEnsureIndex(state);
    if (!frames.length || index < 0) return "";
    const frame = frames[index];
    const daily = this._timelineTimeGranularity(state) === "day";
    const timestamp = daily
      ? this._timelineDailyDateText(frame.time)
      : this._formatEpoch(frame.time);
    const age = this._timelineFrameAgeText(state, frame);
    const kind = this._timelineFrameKindLabel(frame);
    return `${kind ? `${kind} · ` : ""}${index + 1}/${frames.length}${timestamp ? ` · ${timestamp}` : ""}${age ? ` · ${age}` : ""}`;
  };

  proto._addWeatherLayerToMap = function(state) {
    const frames = this._timelineFrames(state);
    if (frames.length && state?.descriptor) {
      const index = this._timelineEnsureIndex(state);
      const frame = frames[index];
      state.descriptor.tile_url = frame.tile_url;
      state.descriptor.frame_time = Number(frame.time);
    }
    return originalAddWeatherLayerToMap.call(this, state);
  };

  proto._loadWeatherLayer = async function(state, refresh = false) {
    const previousDescriptor = state?.descriptor;
    const previousFrames = this._timelineFrames(state);
    const previousIndex = previousFrames.length ? this._timelineEnsureIndex(state) : -1;
    const previousTime = previousIndex >= 0
      ? Number(previousFrames[previousIndex]?.time)
      : Number(state?.descriptor?.frame_time);
    const wasPlaying = Boolean(state?.timelinePlaying);

    // Freeze playback only while provider metadata is being refreshed. The playback
    // state is restored afterwards so a manual refresh does not turn into a stop command.
    if (refresh && wasPlaying) this._timelineStop(state);

    await originalLoadWeatherLayer.call(this, state, refresh);
    const frames = this._timelineFrames(state);
    if (!frames.length) return;

    if (refresh || state.descriptor !== previousDescriptor) {
      if (previousDescriptor && Number.isFinite(previousTime)) {
        state.timelineIndex = this._timelineNearestIndex(frames, previousTime);
      } else {
        state.timelineIndex = null;
        this._timelineEnsureIndex(state);
      }
      this._timelineApplyFrame(state, false);
      if (wasPlaying && state.enabled && !state.error) {
        this._timelineStart(state);
      }
    }
  };

  proto._weatherLayerStatusText = function(state) {
    const base = originalWeatherLayerStatusText.call(this, state);
    if (!state?.enabled || !state?.descriptor || state?.error) return base;
    const frames = this._timelineFrames(state);
    if (!frames.length) return base;
    const index = this._timelineEnsureIndex(state);
    const age = this._timelineFrameAgeText(state, frames[index]);
    return age && !base.includes(age) ? `${base} · ${age}` : base;
  };

  proto._renderWeatherLayers = function() {
    originalRenderWeatherLayers.call(this);

    for (const state of this._weatherLayers?.values?.() || []) {
      const frames = this._timelineFrames(state);
      if (frames.length < 2 || !state.descriptor) continue;

      const safe = this._safeId(state.key);
      const enabledInput = this.shadowRoot.getElementById(`weather-enabled-${safe}`);
      const box = enabledInput?.closest(".weather-layer");
      if (!box || box.querySelector(".weather-timeline")) continue;

      const index = this._timelineEnsureIndex(state);
      const currentIndex = Number(state?.descriptor?.timeline?.current_index);
      const hasCurrentIndex = Number.isInteger(currentIndex) && currentIndex >= 0 && currentIndex < frames.length;
      const jumpLabel = this._timelineTimeGranularity(state) === "day"
        ? "Neueste"
        : (hasCurrentIndex ? "Jetzt" : "Neueste");
      const controls = document.createElement("div");
      controls.className = "weather-timeline";
      controls.style.cssText = "margin-top:10px;padding-top:9px;border-top:1px solid rgba(128,128,128,.25);font-size:11px";
      controls.innerHTML = `
        <div style="display:grid;grid-template-columns:34px 1fr 34px;gap:6px;align-items:center">
          <button data-action="previous" title="Vorheriger Datenstand" ${state.enabled ? "" : "disabled"}>◀</button>
          <input data-action="frame" type="range" min="0" max="${frames.length - 1}" step="1" value="${index}" ${state.enabled ? "" : "disabled"}>
          <button data-action="next" title="Nächster Datenstand" ${state.enabled ? "" : "disabled"}>▶</button>
        </div>
        <div style="display:flex;align-items:center;gap:6px;margin-top:7px;flex-wrap:wrap">
          <button data-action="play" ${state.enabled ? "" : "disabled"}>${state.timelinePlaying ? "⏸ Pause" : "▶ Verlauf"}</button>
          <button data-action="latest" ${state.enabled ? "" : "disabled"}>${jumpLabel}</button>
          <span data-role="label" style="margin-left:auto;opacity:.72">${this._escape(this._timelineFrameLabel(state))}</span>
        </div>`;

      const applyIndex = (value, action = "manual") => {
        const previousIndex = this._timelineEnsureIndex(state);
        this._timelineStop(state);
        state.timelineIndex = Math.max(0, Math.min(frames.length - 1, Number(value)));
        this._wrLog?.("timeline_select", {
          action,
          from_index: previousIndex,
          to_index: state.timelineIndex,
          frame_count: frames.length,
        }, "info", state);
        this._timelineApplyFrame(state, true);
      };

      controls.querySelector('[data-action="previous"]').addEventListener("click", () => {
        applyIndex(Math.max(0, this._timelineEnsureIndex(state) - 1), "previous");
      });
      controls.querySelector('[data-action="next"]').addEventListener("click", () => {
        applyIndex(Math.min(frames.length - 1, this._timelineEnsureIndex(state) + 1), "next");
      });
      controls.querySelector('[data-action="frame"]').addEventListener("input", event => {
        applyIndex(event.target.value, "slider");
      });
      controls.querySelector('[data-action="latest"]').addEventListener("click", () => {
        applyIndex(hasCurrentIndex ? currentIndex : frames.length - 1, jumpLabel.toLowerCase());
      });
      controls.querySelector('[data-action="play"]').addEventListener("click", () => {
        const action = state.timelinePlaying ? "pause" : "start";
        this._wrLog?.("timeline_play_button", {
          action,
          index: this._timelineEnsureIndex(state),
          frame_count: frames.length,
        }, "info", state);
        if (state.timelinePlaying) this._timelineStop(state);
        else this._timelineStart(state);
        this._renderWeatherLayers();
      });

      box.appendChild(controls);
    }
  };

  proto.disconnectedCallback = function() {
    for (const state of this._weatherLayers?.values?.() || []) {
      this._timelineStop(state);
    }
    return originalDisconnectedCallback.call(this);
  };

  console.info("[WeatherRouter] generic observation/forecast timeline controls enabled");
}
