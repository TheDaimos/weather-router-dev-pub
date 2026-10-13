const LAB_ELEMENT = "weather-router-lab";

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Legendenmodul registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterLegendEnhanced) {
  proto.__weatherRouterLegendEnhanced = true;

  const previousRenderWeatherLayers = proto._renderWeatherLayers;
  const previousRenderShell = proto._renderShell;

  proto._legendInstallStyle = function() {
    if (this.shadowRoot?.getElementById("weather-router-legend-style")) return;
    const style = document.createElement("style");
    style.id = "weather-router-legend-style";
    style.textContent = `
      .weather-legends {
        position:absolute;
        z-index:4;
        left:12px;
        bottom:34px;
        width:min(250px,calc(100% - 24px));
        max-height:48%;
        overflow:auto;
        border:1px solid color-mix(in srgb,var(--divider-color,#555) 72%,transparent);
        border-radius:10px;
        background:rgba(18,18,18,.90);
        color:var(--primary-text-color,#eee);
        box-shadow:0 7px 24px rgba(0,0,0,.28);
        backdrop-filter:blur(5px);
      }
      .weather-legends[hidden] { display:none !important; }
      .weather-legends > summary {
        cursor:pointer;
        padding:8px 10px;
        font-size:11px;
        font-weight:750;
        user-select:none;
      }
      .weather-legends-list {
        display:grid;
        gap:7px;
        padding:0 8px 8px;
      }
      .weather-legend-item {
        border-top:1px solid rgba(128,128,128,.22);
        padding-top:6px;
      }
      .weather-legend-item summary {
        cursor:pointer;
        font-size:10px;
        line-height:1.25;
        opacity:.8;
        user-select:none;
      }
      .weather-legend-image-wrap {
        margin-top:6px;
        padding:5px;
        border-radius:6px;
        background:rgba(255,255,255,.94);
        overflow:auto;
      }
      .weather-legend-image {
        display:block;
        max-width:100%;
        max-height:240px;
        margin:auto;
      }
      .weather-legend-error {
        display:none;
        margin-top:5px;
        font-size:10px;
        color:var(--error-color,#f44336);
      }
      @media(max-width:850px) {
        .weather-legends {
          max-height:38%;
          bottom:28px;
        }
      }
    `;
    this.shadowRoot.appendChild(style);
  };

  proto._renderWeatherLegends = function() {
    const root = this.shadowRoot;
    const mapWrap = this._mapWorkspaceElement?.() || root?.querySelector(".map-wrap");
    if (!root || !mapWrap) return;

    this._legendInstallStyle();

    let panel = mapWrap.querySelector("#weather-legends") || root.getElementById("weather-legends");
    const wasOpen = panel?.open ?? true;
    if (!panel) {
      panel = document.createElement("details");
      panel.id = "weather-legends";
      panel.className = "weather-legends";
      mapWrap.appendChild(panel);
    }

    const legends = [...(this._weatherLayers?.values?.() || [])]
      .filter(state => (
        state?.enabled
        && !state?.error
        && state?.descriptor?.legend?.url
      ));

    if (!legends.length) {
      panel.hidden = true;
      panel.innerHTML = "";
      return;
    }

    panel.hidden = false;
    panel.open = wasOpen;
    panel.innerHTML = `
      <summary>Legenden · ${legends.length}</summary>
      <div class="weather-legends-list"></div>
    `;

    const list = panel.querySelector(".weather-legends-list");
    for (const [index, state] of legends.entries()) {
      const legend = state.descriptor.legend;
      const item = document.createElement("details");
      item.className = "weather-legend-item";
      item.open = legends.length <= 2 || index === 0;
      item.innerHTML = `
        <summary>${this._escape(legend.title || state.capabilityName)}</summary>
        <div class="weather-legend-image-wrap">
          <img class="weather-legend-image" alt="Legende ${this._escape(legend.title || state.capabilityName)}">
        </div>
        <div class="weather-legend-error">Legende konnte nicht geladen werden.</div>
      `;

      const image = item.querySelector(".weather-legend-image");
      const error = item.querySelector(".weather-legend-error");
      image.addEventListener("error", () => {
        image.closest(".weather-legend-image-wrap").style.display = "none";
        error.style.display = "block";
      });
      image.src = legend.url;
      list.appendChild(item);
    }
  };

  proto._renderShell = function() {
    previousRenderShell.call(this);
    this._renderWeatherLegends();
  };

  proto._renderWeatherLayers = function() {
    const result = previousRenderWeatherLayers.call(this);
    this._renderWeatherLegends();
    return result;
  };

  console.info("[WeatherRouter] generic WMS legend overlay enabled");
}
