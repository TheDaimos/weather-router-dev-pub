const LAB_ELEMENT = "weather-router-lab";

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor der biologischen Taxonsuche registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterBiologicalSearchEnhanced) {
  proto.__weatherRouterBiologicalSearchEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousRestoreWeatherLayers = proto._restoreWeatherLayers;
  const previousSyncWeatherLayerStates = proto._syncWeatherLayerStates;

  proto._renderShell = function() {
    previousRenderShell.call(this);
    this._biologicalInstallSearchUI();
  };

  proto._biologicalDynamicState = function() {
    if (!this._biologicalDynamicLayers) this._biologicalDynamicLayers = new Map();
    return this._biologicalDynamicLayers;
  };

  proto._biologicalInstallSearchUI = function() {
    const root = this.shadowRoot;
    const sidebar = root?.querySelector(".sidebar");
    const weatherMenu = root?.querySelector('[data-lab-menu-key="weather-layers"]');
    if (!sidebar || !weatherMenu || root.getElementById("biological-taxon-search-menu")) return;

    const menu = document.createElement("details");
    menu.id = "biological-taxon-search-menu";
    menu.className = "card lab-menu";
    menu.dataset.labMenuKey = "biological-taxon-search";
    menu.innerHTML = `
      <summary>2a · Biologische Taxonsuche</summary>
      <div class="lab-menu-content">
        <style>
          .bio-search-grid{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;align-items:end}
          .bio-search-grid input{width:100%;min-height:36px;border:1px solid var(--divider-color,#555);border-radius:8px;background:var(--secondary-background-color,#282828);color:var(--primary-text-color,#eee);padding:8px}
          .bio-search-note{font-size:10px;line-height:1.4;opacity:.66;margin:7px 0}
          .bio-search-status{font-size:11px;margin:7px 0 0}
          .bio-search-status.ok{color:var(--success-color,#4caf50)}
          .bio-search-status.error{color:var(--error-color,#f44336)}
          .bio-dynamic-list{display:grid;gap:6px;margin-top:9px}
          .bio-dynamic-row{border:1px solid color-mix(in srgb,var(--divider-color,#555) 72%,transparent);border-radius:8px;padding:7px 8px;background:rgba(128,128,128,.035)}
          .bio-dynamic-head{display:flex;gap:7px;justify-content:space-between;align-items:center}
          .bio-dynamic-head strong{font-size:11px}
          .bio-dynamic-head button{padding:4px 7px;min-width:32px}
          .bio-dynamic-meta{font-size:9px;opacity:.62;margin-top:3px}
          .bio-dynamic-opacity{display:grid;grid-template-columns:auto 1fr auto;gap:7px;align-items:center;margin-top:6px;font-size:9px;opacity:.8}
          .bio-dynamic-opacity input{width:100%}
          .bio-clear{margin-top:8px}
        </style>
        <div class="muted" style="font-size:12px">
          Freie GBIF-Suche zusätzlich zu den 88 vorbereiteten Layern. Gib einen
          <strong>wissenschaftlichen Namen</strong> oder ein höheres Taxon ein.
        </div>
        <div class="bio-search-grid" style="margin-top:8px">
          <label style="margin:0">
            Taxon
            <input id="biological-taxon-search-input" type="text"
              maxlength="200" placeholder="z. B. Panthera leo, Crocodylia, Viperidae">
          </label>
          <button id="biological-taxon-search-run" class="primary" type="button">Auf Karte</button>
        </div>
        <div class="bio-search-note">
          Die Ebene zeigt die Dichte veröffentlichter GBIF-Vorkommensnachweise ab 2000.
          Sie ist <strong>keine Populationsdichte</strong> und
          <strong>keine Gefahrenwahrscheinlichkeit</strong>. Fachbereich und Provider
          müssen in der Router-Steuerung aktiviert sein.
        </div>
        <div id="biological-taxon-search-status" class="bio-search-status muted">Noch keine freie Taxonsuche.</div>
        <div id="biological-taxon-dynamic-list" class="bio-dynamic-list"></div>
        <button id="biological-taxon-clear" class="secondary bio-clear" type="button">Freie Layer entfernen</button>
      </div>
    `;

    weatherMenu.after(menu);

    const input = menu.querySelector("#biological-taxon-search-input");
    const run = menu.querySelector("#biological-taxon-search-run");
    const clear = menu.querySelector("#biological-taxon-clear");

    run.addEventListener("click", () => this._biologicalSearchTaxon());
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        this._biologicalSearchTaxon();
      }
    });
    clear.addEventListener("click", () => this._biologicalClearDynamicLayers());
    this._biologicalRenderDynamicLayers();
  };

  proto._biologicalSearchTaxon = async function() {
    const root = this.shadowRoot;
    const input = root?.getElementById("biological-taxon-search-input");
    const button = root?.getElementById("biological-taxon-search-run");
    const status = root?.getElementById("biological-taxon-search-status");
    const scientificName = String(input?.value || "").trim();
    if (!scientificName) {
      if (status) {
        status.className = "bio-search-status error";
        status.textContent = "Bitte einen wissenschaftlichen Namen oder ein höheres Taxon eingeben.";
      }
      return;
    }
    if (!this._hass) return;

    const gbif = (this._providers || []).find(provider => provider.id === "gbif_biodiversity");
    if (gbif?.eligible === false) {
      if (status) {
        status.className = "bio-search-status error";
        status.textContent = "GBIF ist aktuell nicht freigegeben. Aktiviere zuerst den Fachbereich und den Provider in der Router-Steuerung.";
      }
      return;
    }

    if (button) {
      button.disabled = true;
      button.textContent = "Lade …";
    }
    if (status) {
      status.className = "bio-search-status muted";
      status.textContent = `GBIF löst „${scientificName}“ taxonomisch auf …`;
    }

    try {
      const response = await this._hass.callWS({
        type: "weather_router/biological_taxon_layer",
        scientific_name: scientificName,
      });
      const descriptor = response?.layer;
      if (!descriptor?.tile_url || descriptor.render_mode !== "raster_tile") {
        throw new Error("GBIF lieferte keine gültige Rasterebene.");
      }

      const meta = descriptor.provider_metadata || {};
      const taxonKey = meta.taxon_key;
      if (taxonKey == null) throw new Error("GBIF-Antwort enthält keinen taxonKey.");
      const matched = meta.canonical_name || meta.scientific_name_matched || scientificName;
      const key = `gbif_biodiversity/dynamic_${taxonKey}`;
      const states = this._biologicalDynamicState();

      const existing = states.get(key);
      if (existing) this._removeWeatherLayerFromMap(existing);

      const opacity = Math.round(
        (Number.isFinite(Number(descriptor.default_opacity))
          ? Number(descriptor.default_opacity)
          : 0.78) * 100
      );
      const state = {
        key,
        provider: "gbif_biodiversity",
        providerName: "GBIF · Biologische Vorkommen",
        capability: `dynamic_${taxonKey}`,
        capabilityName: `GBIF · Freie Suche · ${matched}`,
        coverage: "Global · abhängig von veröffentlichten GBIF-Nachweisen",
        enabled: true,
        loading: false,
        opacity,
        descriptor,
        error: null,
        dynamicTaxon: true,
        requestedName: scientificName,
        matchedName: matched,
        taxonKey,
      };
      states.set(key, state);
      this._addWeatherLayerToMap(state);
      this._biologicalRenderDynamicLayers();

      if (status) {
        status.className = "bio-search-status ok";
        status.textContent = `Aktiv: ${matched} · GBIF taxonKey ${taxonKey} · Vorkommensdichte`;
      }
      this._wrLog?.("biological_taxon_layer_loaded", {
        requested_name: scientificName,
        matched_name: matched,
        taxon_key: taxonKey,
        semantics: "occurrence_density",
      });
    } catch (error) {
      if (status) {
        status.className = "bio-search-status error";
        status.textContent = `Taxonsuche fehlgeschlagen: ${error?.message || String(error)}`;
      }
      this._wrLog?.("biological_taxon_layer_failed", {
        requested_name: scientificName,
        error,
      }, "error");
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "Auf Karte";
      }
    }
  };

  proto._biologicalRenderDynamicLayers = function() {
    const root = this.shadowRoot;
    const host = root?.getElementById("biological-taxon-dynamic-list");
    const clear = root?.getElementById("biological-taxon-clear");
    if (!host) return;

    const states = [...this._biologicalDynamicState().values()];
    if (clear) clear.disabled = !states.length;
    if (!states.length) {
      host.innerHTML = "";
      return;
    }

    host.innerHTML = states.map(state => `
      <div class="bio-dynamic-row" data-bio-dynamic="${this._escape(state.key)}">
        <div class="bio-dynamic-head">
          <strong>${this._escape(state.matchedName || state.requestedName)}</strong>
          <button type="button" data-bio-remove="${this._escape(state.key)}" title="Layer entfernen">×</button>
        </div>
        <div class="bio-dynamic-meta">
          gesucht: ${this._escape(state.requestedName)} · taxonKey ${this._escape(state.taxonKey)}
        </div>
        <div class="bio-dynamic-opacity">
          <span>Deckkraft</span>
          <input type="range" min="10" max="100" step="5"
            value="${this._escape(state.opacity)}" data-bio-opacity="${this._escape(state.key)}">
          <span>${this._escape(state.opacity)}%</span>
        </div>
      </div>
    `).join("");

    host.querySelectorAll("[data-bio-remove]").forEach(button => {
      button.addEventListener("click", () => this._biologicalRemoveDynamicLayer(button.dataset.bioRemove));
    });
    host.querySelectorAll("[data-bio-opacity]").forEach(input => {
      input.addEventListener("input", event => {
        const state = this._biologicalDynamicState().get(input.dataset.bioOpacity);
        if (!state) return;
        state.opacity = Number(event.target.value);
        event.target.nextElementSibling.textContent = `${state.opacity}%`;
        const ids = this._weatherLayerIds(state);
        if (this._map?.getLayer(ids.layer)) {
          this._map.setPaintProperty(ids.layer, "raster-opacity", state.opacity / 100);
        }
      });
    });
  };

  proto._biologicalRemoveDynamicLayer = function(key) {
    const states = this._biologicalDynamicState();
    const state = states.get(key);
    if (!state) return;
    state.enabled = false;
    this._removeWeatherLayerFromMap(state);
    states.delete(key);
    this._biologicalRenderDynamicLayers();
  };

  proto._biologicalClearDynamicLayers = function() {
    const states = this._biologicalDynamicState();
    for (const state of states.values()) {
      state.enabled = false;
      this._removeWeatherLayerFromMap(state);
    }
    states.clear();
    this._biologicalRenderDynamicLayers();
    const status = this.shadowRoot?.getElementById("biological-taxon-search-status");
    if (status) {
      status.className = "bio-search-status muted";
      status.textContent = "Freie GBIF-Layer entfernt.";
    }
  };

  proto._restoreWeatherLayers = function() {
    previousRestoreWeatherLayers.call(this);
    for (const state of this._biologicalDynamicState().values()) {
      if (state.enabled && state.descriptor) this._addWeatherLayerToMap(state);
    }
  };

  proto._syncWeatherLayerStates = function() {
    previousSyncWeatherLayerStates.call(this);
    const gbif = (this._providers || []).find(provider => provider.id === "gbif_biodiversity");
    if (!gbif || gbif.eligible === false) {
      this._biologicalClearDynamicLayers();
    }
  };
}
