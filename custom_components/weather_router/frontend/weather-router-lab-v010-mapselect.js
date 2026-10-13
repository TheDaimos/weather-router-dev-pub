import * as maplibregl from "https://unpkg.com/maplibre-gl@6.9.1/dist/maplibre-gl.mjs";
import "./weather-router-lab.js";

const BaseLab = customElements.get("weather-router-lab");

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

class WeatherRouterLabV010MapSelect extends BaseLab {
  _renderShell() {
    super._renderShell();
    this._basemapProvider = this._basemapProvider || "openfreemap";
    this._basemapStyle = this._basemapStyle || "dark";

    const badges = this.shadowRoot.querySelector(".badges");
    if (!badges) return;

    const style = document.createElement("style");
    style.textContent = `
      .basemap-controls {
        display:grid;
        grid-template-columns:0.8fr 1.15fr 1fr;
        gap:7px;
        margin:0 0 14px;
      }
      .basemap-control label {
        display:block;
        margin:0 0 4px;
        font-size:10px;
        opacity:.62;
      }
      .basemap-control select {
        min-height:34px;
        padding:6px 8px;
      }
      .basemap-control select:disabled {
        opacity:.65;
      }
      .lab-mode-badge {
        margin:-5px 0 14px;
        font-size:10px;
        opacity:.62;
      }
      @media(max-width:520px) {
        .basemap-controls { grid-template-columns:1fr; }
      }
    `;
    this.shadowRoot.appendChild(style);

    badges.outerHTML = `
      <div class="basemap-controls">
        <div class="basemap-control">
          <label>Engine</label>
          <select id="map-engine" disabled>
            <option>MapLibre</option>
          </select>
        </div>
        <div class="basemap-control">
          <label>Kartenquelle</label>
          <select id="basemap-provider">
            <option value="openfreemap">OpenFreeMap</option>
            <option value="science">Lokaler Science-Fallback</option>
          </select>
        </div>
        <div class="basemap-control">
          <label>Kartenstil</label>
          <select id="basemap-style">
            <option value="dark">Dark · kontrastarm</option>
            <option value="fiord">Fiord</option>
            <option value="positron">Positron · hell</option>
          </select>
        </div>
      </div>
      <div class="lab-mode-badge">Multi-Provider-Diagnose · Basiskarte und Wetterprovider sind getrennte Ebenen.</div>
    `;

    const providerSelect = this.shadowRoot.getElementById("basemap-provider");
    const styleSelect = this.shadowRoot.getElementById("basemap-style");
    providerSelect.value = this._basemapProvider;
    styleSelect.value = this._basemapStyle;

    providerSelect.addEventListener("change", event => {
      this._basemapProvider = event.target.value;
      styleSelect.disabled = this._basemapProvider !== "openfreemap";
      this._applyBasemap();
    });

    styleSelect.addEventListener("change", event => {
      this._basemapStyle = event.target.value;
      this._applyBasemap();
    });
  }

  _selectedMapStyle() {
    if (this._basemapProvider === "science") return SCIENCE_STYLE;
    return OPENFREEMAP_STYLES[this._basemapStyle] || OPENFREEMAP_STYLES.dark;
  }

  _ensureMap() {
    if (this._map || !this.isConnected) return;

    this._map = new maplibregl.Map({
      container: this.shadowRoot.getElementById("map"),
      center: [10, 51],
      zoom: 4.5,
      attributionControl: true,
      style: this._selectedMapStyle(),
    });

    this._map.addControl(new maplibregl.NavigationControl(), "top-right");
    this._map.on("load", () => this._syncFromHass(true));
    this._map.on("error", event => {
      const status = this.shadowRoot.getElementById("map-status");
      if (!status) return;
      status.textContent = `Kartenfehler: ${event?.error?.message || "unbekannt"}`;
      status.className = "error";
    });
  }

  _applyBasemap() {
    if (!this._map) return;
    const center = this._map.getCenter();
    const zoom = this._map.getZoom();
    const bearing = this._map.getBearing();
    const pitch = this._map.getPitch();

    try {
      this._map.setStyle(this._selectedMapStyle());
      this._map.once("style.load", () => {
        this._map.jumpTo({ center, zoom, bearing, pitch });
        this._syncFromHass(true);
      });
    } catch (error) {
      const status = this.shadowRoot.getElementById("map-status");
      if (status) {
        status.textContent = `Kartenstil fehlgeschlagen: ${error?.message || String(error)}`;
        status.className = "error";
      }
    }
  }
}

if (!customElements.get("weather-router-lab-v010-mapselect")) {
  customElements.define("weather-router-lab-v010-mapselect", WeatherRouterLabV010MapSelect);
}
