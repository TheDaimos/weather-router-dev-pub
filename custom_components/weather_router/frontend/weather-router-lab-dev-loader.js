const TARGET_ELEMENT = "weather-router-lab";
const WR_LAB_BUILD_VERSION = "0.10.148";
const LOADER_REV = "0.10-loader-151"

class WeatherRouterLabDevLoader extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._panel = null;
    this._narrow = false;
    this._child = null;
    this._loadPromise = null;
  }

  set hass(value) {
    this._hass = value;
    if (this._child) this._child.hass = value;
  }

  set panel(value) {
    this._panel = value;
    if (this._child) this._child.panel = value;
  }

  set narrow(value) {
    this._narrow = value;
    if (this._child) this._child.narrow = value;
  }

  set route(value) {
    this._route = value;
    if (this._child) this._child.route = value;
  }

  connectedCallback() {
    // Do not mutate attributes/children in the custom-element constructor.
    // Home Assistant creates the panel element via document.createElement().
    this.style.display = "block";
    this.style.height = "100%";
    this.style.minHeight = "100vh";
    this.style.background = "var(--primary-background-color, #111)";
    this.style.color = "var(--primary-text-color, #eee)";

    console.info(`[WeatherRouter] dev loader ${LOADER_REV} connected`);
    this._load();
  }

  async _load() {
    if (this._loadPromise) return this._loadPromise;

    const loading = document.createElement("div");
    loading.style.cssText = "padding:20px;font:14px system-ui,sans-serif;color:var(--primary-text-color,#eee)";
    loading.textContent = `WeatherRouter Lab WR ${WR_LAB_BUILD_VERSION} · DEV wird geladen … (${LOADER_REV})`;
    this.replaceChildren(loading);

    const token = `${Date.now()}-${Math.random().toString(36).slice(2)}`;

    this._loadPromise = (async () => {
      try {
        const moduleUrl = new URL("./weather-router-lab.js", import.meta.url);
        moduleUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading Lab module", moduleUrl.href);
        await import(moduleUrl.href);

        const brandingUrl = new URL("./weather-router-lab-branding.js", import.meta.url);
        brandingUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading branding module", brandingUrl.href);
        await import(brandingUrl.href);

        const eventLogUrl = new URL("./weather-router-lab-event-log.js", import.meta.url);
        eventLogUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading event log module", eventLogUrl.href);
        await import(eventLogUrl.href);

        const logExportUrl = new URL("./weather-router-lab-log-export.js", import.meta.url);
        logExportUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading log export module", logExportUrl.href);
        await import(logExportUrl.href);

        const timelineUrl = new URL("./weather-router-lab-timeline.js", import.meta.url);
        timelineUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading timeline module", timelineUrl.href);
        await import(timelineUrl.href);

        const rasterStabilityUrl = new URL("./weather-router-lab-raster-stability.js", import.meta.url);
        rasterStabilityUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading raster stability module", rasterStabilityUrl.href);
        await import(rasterStabilityUrl.href);

        const frameBufferUrl = new URL("./weather-router-lab-frame-buffer.js", import.meta.url);
        frameBufferUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading frame buffer module", frameBufferUrl.href);
        await import(frameBufferUrl.href);

        const legendsUrl = new URL("./weather-router-lab-legends.js", import.meta.url);
        legendsUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading map legends module", legendsUrl.href);
        await import(legendsUrl.href);

        const diagnosticsUrl = new URL("./weather-router-lab-diagnostics.js", import.meta.url);
        diagnosticsUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading provider diagnostics module", diagnosticsUrl.href);
        await import(diagnosticsUrl.href);

        const routingUrl = new URL("./weather-router-lab-routing.js", import.meta.url);
        routingUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading router control module", routingUrl.href);
        await import(routingUrl.href);

        const consumerApiUrl = new URL("./weather-router-lab-consumer-api.js", import.meta.url);
        consumerApiUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading Consumer API V1 test module", consumerApiUrl.href);
        await import(consumerApiUrl.href);

        const routingDiagnosticsUrl = new URL("./weather-router-lab-routing-diagnostics.js", import.meta.url);
        routingDiagnosticsUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading routing diagnostics cockpit", routingDiagnosticsUrl.href);
        await import(routingDiagnosticsUrl.href);

        const biologicalUrl = new URL("./weather-router-lab-biological.js", import.meta.url);
        biologicalUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading biological taxon search module", biologicalUrl.href);
        await import(biologicalUrl.href);

        const hazardsUrl = new URL("./weather-router-lab-hazards.js", import.meta.url);
        hazardsUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading hazard feed module", hazardsUrl.href);
        await import(hazardsUrl.href);

        const mapWorkspaceUrl = new URL("./weather-router-lab-map-workspace.js", import.meta.url);
        mapWorkspaceUrl.searchParams.set("dev", token);
        console.info("[WeatherRouter] loading map workspace module", mapWorkspaceUrl.href);
        await import(mapWorkspaceUrl.href);

        if (!customElements.get(TARGET_ELEMENT)) {
          throw new Error(`Custom element ${TARGET_ELEMENT} wurde nicht registriert.`);
        }
        if (!this.isConnected) return;

        const child = document.createElement(TARGET_ELEMENT);
        this._child = child;
        child.hass = this._hass;
        child.panel = this._panel;
        child.narrow = this._narrow;
        child.route = this._route;
        this.replaceChildren(child);
      } catch (error) {
        console.error("WeatherRouter Lab development loader failed", error);
        if (!this.isConnected) return;
        const message = document.createElement("div");
        message.style.cssText = "padding:20px;color:var(--error-color,#f44336);background:var(--primary-background-color,#111);font:14px system-ui,sans-serif;white-space:pre-wrap";
        message.textContent = `WeatherRouter Lab konnte nicht geladen werden (${LOADER_REV}):\n${error?.message || String(error)}`;
        this.replaceChildren(message);
      }
    })();

    return this._loadPromise;
  }
}

if (!customElements.get("weather-router-lab-dev-loader")) {
  customElements.define("weather-router-lab-dev-loader", WeatherRouterLabDevLoader);
}
