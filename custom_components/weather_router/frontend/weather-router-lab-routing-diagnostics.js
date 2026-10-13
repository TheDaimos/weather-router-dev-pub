const LAB_ELEMENT = "weather-router-lab";
const ROUTING_DIAGNOSTIC_SCHEMA = "weather_router.routing_diagnostic.v1";
const ROUTING_DIAGNOSTIC_LIMIT = 50;

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Routing-Diagnosemodul registriert sein.`);
}

const proto = LabClass.prototype;

const PRESETS = {
  germany: { label:"Deutschland", type:"bbox", west:5.0, south:47.0, east:16.0, north:56.0 },
  europe: { label:"Europa", type:"bbox", west:-12.0, south:34.0, east:35.0, north:72.0 },
  usa: { label:"USA", type:"bbox", west:-125.0, south:24.0, east:-66.0, north:50.0 },
  cuba: { label:"Kuba / Karibik", type:"bbox", west:-86.0, south:18.0, east:-73.0, north:24.5 },
  somalia: { label:"Puntland / Somalia", type:"bbox", west:47.0, south:7.0, east:52.0, north:12.0 },
  australia: { label:"Australien", type:"bbox", west:112.0, south:-44.0, east:154.0, north:-10.0 },
  japan: { label:"Japan", type:"bbox", west:128.0, south:30.0, east:146.0, north:46.0 },
  antimeridian: { label:"Antimeridian", type:"bbox", west:170.0, south:-12.0, east:-170.0, north:12.0 },
  northpole: { label:"Nordpol", type:"point", latitude:89.0, longitude:0.0 },
  southpole: { label:"Südpol", type:"point", latitude:-89.0, longitude:0.0 },
};

if (!proto.__weatherRouterRoutingDiagnosticsEnhanced) {
  proto.__weatherRouterRoutingDiagnosticsEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousDisconnectedCallback = proto.disconnectedCallback;

  proto._rdEsc = function(value) {
    if (typeof this._escape === "function") return this._escape(String(value ?? ""));
    return String(value ?? "")
      .replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;")
      .replaceAll('"',"&quot;");
  };

  proto._rdJson = function(value) {
    return this._rdEsc(JSON.stringify(value ?? null, null, 2));
  };

  proto._rdState = function() {
    if (!this._routingDiagnosticState) {
      this._routingDiagnosticState = {
        index: [],
        trace: null,
        selectedId: "",
        compareA: "",
        compareB: "",
        compareResult: null,
        capabilities: [],
        profiles: [],
        loading: false,
        live: false,
        liveUnsub: null,
        liveRefreshTimer: null,
        manualResult: null,
        message: "",
        messageKind: "muted",
        exportMessage: "Noch kein Export ausgeführt.",
        exportKind: "muted",
        exportBusy: false,
        gitExportResult: null,
        manual: {
          capability: "",
          capabilityFilter: "",
          preset: "",
          context: { type:"bbox", west:5.0, south:47.0, east:16.0, north:56.0 },
          resourceType: "",
          sourceClass: "",
          maxAgeSeconds: "",
          timelineRequired: false,
          profileId: "",
          faultMode: "resource_temporarily_unavailable",
        },
      };
    }
    return this._routingDiagnosticState;
  };

  proto._rdInstall = function() {
    const root = this.shadowRoot;
    const sidebar = root?.querySelector(".sidebar");
    if (!root || !sidebar) return;

    if (!root.getElementById("wr-routing-diagnostic-style")) {
      const style = document.createElement("style");
      style.id = "wr-routing-diagnostic-style";
      style.textContent = `
        .wr-rd-launch-wrap{display:flex;gap:8px;margin:0 0 12px}
        .wr-rd-launch{width:100%;min-height:40px;font-weight:800;border-color:#8b6d2c!important;
          background:linear-gradient(135deg,color-mix(in srgb,#d9aa45 18%,var(--secondary-background-color,#282828)),
          color-mix(in srgb,var(--primary-color,#03a9f4) 11%,var(--secondary-background-color,#282828)))!important}
        .wr-rd-window[hidden]{display:none!important}
        .wr-rd-window{position:fixed;z-index:10020;inset:3vh 2.5vw;width:95vw;max-width:1500px;
          margin:auto;display:flex;flex-direction:column;overflow:hidden;border:1px solid #79622e;
          border-radius:18px;background:var(--card-background-color,#171a20);box-shadow:0 24px 90px #000b}
        .wr-rd-window,.wr-rd-window *{box-sizing:border-box}
        .wr-rd-window,.wr-rd-head,.wr-rd-head-main,.wr-rd-head-actions,.wr-rd-body,
        .wr-rd-toolbar,.wr-rd-manual-grid,.wr-rd-summary-grid,.wr-rd-compare-grid,
        .wr-rd-card,.wr-rd-fold,.wr-rd-fold-body,.wr-rd-actions,.wr-rd-context-grid,
        .wr-rd-table-wrap,.wr-rd-candidate-cards,.wr-rd-profile-testbox{min-width:0;max-width:100%}
        .wr-rd-body>*,
        .wr-rd-toolbar>*,.wr-rd-manual-grid>*,.wr-rd-summary-grid>*,.wr-rd-compare-grid>*,
        .wr-rd-context-grid>*,.wr-rd-actions>*{min-width:0;max-width:100%}
        .wr-rd-head{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:13px 16px;
          border-bottom:1px solid var(--divider-color,#444);background:linear-gradient(90deg,#5a431b33,#18364a33)}
        .wr-rd-head h2{font-size:17px;margin:0}.wr-rd-head small{display:block;opacity:.62;margin-top:2px}
        .wr-rd-head-main{min-width:220px;flex:1 1 auto}
        .wr-rd-head-actions{display:flex;justify-content:flex-end;align-items:center;gap:6px;flex-wrap:wrap}
        .wr-rd-head-actions button{min-height:32px;padding:5px 9px;font-size:11px}
        .wr-rd-head-actions button.wr-rd-git-exported{border-color:#3e7d59!important;color:#8ce0a8!important;
          background:color-mix(in srgb,#3e7d59 18%,var(--secondary-background-color,#282828))!important}
        .wr-rd-head-status{max-width:420px;font-size:10px;line-height:1.25;opacity:.75;overflow-wrap:anywhere}
        .wr-rd-head-status.ok{color:#8ce0a8;opacity:1}.wr-rd-head-status.error{color:#ff9090;opacity:1}
        .wr-rd-close{font-size:20px;min-width:40px}
        .wr-diagnostic-hub{margin:0 0 12px;padding:10px;border:1px solid color-mix(in srgb,#d4af37 34%,var(--divider-color,#444));
          border-radius:12px;background:color-mix(in srgb,#d4af37 3%,var(--card-background-color,#1c1c1c))}
        .wr-diagnostic-hub-title{display:flex;justify-content:space-between;gap:10px;align-items:center;margin:0 0 8px;
          font-size:12px;font-weight:800}
        .wr-diagnostic-hub-title small{font-weight:500;opacity:.58}
        .wr-diagnostic-hub-tools{display:grid;grid-template-columns:1fr 1fr;gap:8px}
        .wr-diagnostic-hub-tools>#wr-log-menu{grid-column:1/-1;margin:0}
        .wr-diagnostic-hub-tools>.wr-diagnostic-launch-wrap,.wr-diagnostic-hub-tools>.wr-rd-launch-wrap{margin:0}
        .wr-rd-cap-search{width:100%;min-height:34px;border:1px solid var(--divider-color,#555);border-radius:8px;
          background:var(--secondary-background-color,#282828);color:inherit;padding:7px}
        .wr-rd-body{overflow-y:auto;overflow-x:hidden;padding:13px;display:grid;gap:12px}
        .wr-rd-toolbar,.wr-rd-manual-grid,.wr-rd-summary-grid,.wr-rd-compare-grid{display:grid;gap:8px}
        .wr-rd-toolbar{grid-template-columns:minmax(220px,2fr) auto auto auto;align-items:end}
        .wr-rd-manual-grid{grid-template-columns:repeat(auto-fit,minmax(165px,1fr))}
        .wr-rd-summary-grid{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
        .wr-rd-compare-grid{grid-template-columns:1fr 1fr auto}
        .wr-rd-card,.wr-rd-fold{border:1px solid var(--divider-color,#444);border-radius:12px;background:#00000012}
        .wr-rd-card{padding:10px}.wr-rd-card small{display:block;opacity:.58}.wr-rd-card strong{display:block;margin-top:3px}
        .wr-rd-fold>summary{cursor:pointer;padding:10px 12px;font-weight:750;display:flex;justify-content:space-between;gap:10px}
        .wr-rd-fold-body{padding:0 12px 12px}
        .wr-rd-actions{display:flex;flex-wrap:wrap;gap:7px}
        .wr-rd-context-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}
        .wr-rd-context-grid.point{grid-template-columns:repeat(2,1fr)}
        .wr-rd-context-grid input{width:100%;min-height:34px;border:1px solid var(--divider-color,#555);
          border-radius:8px;background:var(--secondary-background-color,#282828);color:inherit;padding:7px}
        .wr-rd-manual-grid label,.wr-rd-toolbar label,.wr-rd-compare-grid label,.wr-rd-context-grid label{min-width:0;max-width:100%}
        .wr-rd-manual-grid input:not([type="checkbox"]):not([type="radio"]),.wr-rd-manual-grid select,
        .wr-rd-toolbar input:not([type="checkbox"]):not([type="radio"]),.wr-rd-toolbar select,
        .wr-rd-compare-grid select,.wr-rd-context-grid input:not([type="checkbox"]):not([type="radio"]){
          width:100%;min-width:0;max-width:100%}
        .wr-rd-window input[type="checkbox"],.wr-rd-window input[type="radio"]{
          width:18px;height:18px;min-width:18px;max-width:18px;min-height:18px;max-height:18px;
          flex:0 0 18px;margin:0}
        .wr-rd-table-wrap{overflow:auto;max-width:100%}.wr-rd-table{width:100%;border-collapse:collapse;font-size:11px;min-width:1040px}
        .wr-rd-table th,.wr-rd-table td{padding:7px 6px;border-bottom:1px solid #ffffff14;text-align:left;vertical-align:top}
        .wr-rd-table th{position:sticky;top:0;background:var(--card-background-color,#202020);z-index:1}
        .wr-rd-pass{color:#75d69a}.wr-rd-fail{color:#ff8585}.wr-rd-warn{color:#f4c56a}.wr-rd-muted{opacity:.58}
        .wr-rd-pre{width:100%;max-width:100%;min-width:0;max-height:38vh;overflow:auto;white-space:pre-wrap;
          overflow-wrap:anywhere;word-break:break-word;background:#080b10;border:1px solid #ffffff18;
          border-radius:9px;padding:10px;font:11px ui-monospace,Consolas,monospace}
        .wr-rd-message{font-size:11px;padding:7px 9px;border-radius:8px;background:#ffffff09}
        .wr-rd-message.ok{color:#8ce0a8}.wr-rd-message.error{color:#ff9090}.wr-rd-message.muted{opacity:.7}
        .wr-rd-export-status{margin-top:9px;font-size:11px;padding:8px 10px;border-radius:8px;background:#ffffff09;overflow-wrap:anywhere}
        .wr-rd-export-status.ok{color:#8ce0a8}.wr-rd-export-status.error{color:#ff9090}.wr-rd-export-status.muted{opacity:.7}
        .wr-rd-export-link{display:inline-block;margin-left:8px;color:#d9aa45}
        .wr-rd-badge{display:inline-flex;padding:3px 7px;border:1px solid #ffffff2a;border-radius:999px;font-size:10px;margin:2px}
        .wr-rd-badge.ready{border-color:#3e7d59;color:#8ce0a8}.wr-rd-badge.unavailable{border-color:#8a6b2f;color:#f0c56a}
        .wr-rd-badge.error{border-color:#8c4141;color:#ff9a9a}
        .wr-rd-section-title{font-size:11px;opacity:.62;margin-bottom:5px}
        .wr-rd-candidate-cards{display:none}
        @media(max-width:1200px){
          .wr-rd-window{inset:1.5vh 1.5vw;width:97vw;max-width:none}
          .wr-rd-head{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:start;gap:8px;padding:10px 12px}
          .wr-rd-head-main{min-width:0}
          .wr-rd-close{grid-column:2;grid-row:1;min-width:44px;min-height:44px}
          .wr-rd-head-actions{grid-column:1/-1;grid-row:2;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
            width:100%;min-width:0;max-width:100%;justify-content:stretch;align-items:stretch;overflow:visible}
          .wr-rd-head-actions button{width:100%;min-width:0;max-width:100%;white-space:normal}
          .wr-rd-head-status{grid-column:1/-1;min-width:0;max-width:100%}
          .wr-rd-toolbar{grid-template-columns:repeat(2,minmax(0,1fr))}
          .wr-rd-manual-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
          .wr-rd-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
          .wr-rd-compare-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
          .wr-rd-compare-grid button{grid-column:1/-1}
          .wr-rd-context-grid,.wr-rd-context-grid.point{grid-template-columns:repeat(2,minmax(0,1fr))}
          .wr-rd-fold>summary{min-width:0;max-width:100%;overflow-wrap:anywhere}
          .wr-rd-table-wrap{min-width:0;max-width:100%;overflow-x:auto;overscroll-behavior-inline:contain}
        }
        @media(max-width:900px){
          .wr-rd-window{inset:0;width:100vw;height:100dvh;max-width:none;max-height:none;border-radius:0;border-left:0;border-right:0}
          .wr-rd-head{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-rows:auto auto;align-items:start;align-content:start;gap:8px;padding:10px 10px 8px;position:sticky;top:0;z-index:8;flex:0 0 auto;height:auto;min-height:0}
          .wr-rd-head-main{min-width:0}.wr-rd-head h2{font-size:15px;line-height:1.2}.wr-rd-head small{font-size:10px}
          .wr-rd-close{grid-column:2;grid-row:1;min-width:44px;min-height:44px;padding:0;font-size:24px}
          .wr-rd-head-actions{grid-column:1/-1;grid-row:2;display:flex;gap:6px;flex-wrap:nowrap;
            justify-content:flex-start;align-items:center;align-self:start;width:100%;height:42px;min-height:42px;max-height:42px;
            overflow-x:auto;overflow-y:hidden;padding:2px 0 4px;scrollbar-width:thin;
            overscroll-behavior-inline:contain}
          .wr-rd-head-actions button{flex:0 0 auto;width:auto;min-width:max-content;max-width:none;height:36px;min-height:36px;max-height:36px;
            align-self:center;font-size:11px;padding:6px 9px;white-space:nowrap}
          .wr-rd-head-status{grid-column:1/-1;display:block;min-width:0;max-width:100%;font-size:10px}
          .wr-rd-body{padding:8px;gap:9px;overscroll-behavior:contain}
          .wr-rd-toolbar,.wr-rd-manual-grid,.wr-rd-compare-grid{grid-template-columns:1fr}
          .wr-rd-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
          .wr-rd-toolbar button,.wr-rd-actions button,
          .wr-rd-manual-grid input:not([type="checkbox"]):not([type="radio"]),.wr-rd-manual-grid select,
          .wr-rd-toolbar select,.wr-rd-toolbar input:not([type="checkbox"]):not([type="radio"]),
          .wr-rd-context-grid input:not([type="checkbox"]):not([type="radio"]),.wr-rd-compare-grid select{min-height:44px}
          .wr-rd-toolbar input[type="checkbox"],.wr-rd-manual-grid input[type="checkbox"]{
            width:20px;height:20px;min-width:20px;max-width:20px;min-height:20px;max-height:20px;flex-basis:20px}
          .wr-rd-actions{display:grid;grid-template-columns:1fr;gap:8px}
          .wr-rd-fold>summary{min-height:44px;align-items:center;padding:10px}
          .wr-rd-fold-body{padding:0 9px 9px}
          .wr-rd-card{padding:9px;min-width:0}.wr-rd-card strong{overflow-wrap:anywhere;font-size:12px}
          .wr-rd-pre{max-height:48vh;font-size:10px;padding:8px}
          .wr-rd-table-wrap{display:none}
          .wr-rd-candidate-cards{display:grid;gap:8px}
          .wr-rd-candidate-card{border:1px solid var(--divider-color,#444);border-radius:10px;padding:9px;background:#00000016}
          .wr-rd-candidate-card-head{display:flex;justify-content:space-between;gap:8px;align-items:flex-start}
          .wr-rd-candidate-card-head strong{overflow-wrap:anywhere}
          .wr-rd-candidate-card-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;font-size:11px}
          .wr-rd-candidate-card-grid>div{min-width:0;padding:5px 6px;border-radius:7px;background:#ffffff07;overflow-wrap:anywhere}
          .wr-rd-candidate-card-grid small{display:block;opacity:.58;margin-bottom:2px}
          .wr-diagnostic-hub-tools{grid-template-columns:1fr}
          .wr-diagnostic-hub-tools>#wr-log-menu{grid-column:auto}
          .wr-rd-context-grid,.wr-rd-context-grid.point{grid-template-columns:1fr 1fr}
          .wr-rd-profile-testbox{padding:9px;border:1px dashed color-mix(in srgb,#d4af37 45%,var(--divider-color,#444));border-radius:10px}
          .wr-rd-profile-testbox button{width:100%;min-height:44px}
        }
        @media(max-width:520px){
          .wr-rd-context-grid,.wr-rd-context-grid.point{grid-template-columns:1fr}
          .wr-rd-summary-grid{grid-template-columns:1fr}
          .wr-rd-candidate-card-grid{grid-template-columns:1fr}
        }
      `;
      root.appendChild(style);
    }

    if (!root.getElementById("wr-routing-diagnostic-launch")) {
      const wrap = document.createElement("div");
      wrap.className = "wr-rd-launch-wrap";
      wrap.id = "wr-routing-diagnostic-launch";
      wrap.innerHTML = '<button class="wr-rd-launch" type="button">🧭 Routing & Consumer-Diagnose</button>';
      const providerDiagnostics = root.getElementById("provider-diagnostics-launch");
      if (providerDiagnostics) providerDiagnostics.after(wrap);
      else sidebar.prepend(wrap);
      wrap.querySelector("button")?.addEventListener("click",()=>this._rdOpen());
    }

    if (!root.getElementById("wr-routing-diagnostic-window")) {
      const panel = document.createElement("section");
      panel.className = "wr-rd-window";
      panel.id = "wr-routing-diagnostic-window";
      panel.hidden = true;
      panel.innerHTML = `
        <div class="wr-rd-head">
          <div class="wr-rd-head-main"><h2>WeatherRouter · Routing & Consumer-Diagnose</h2>
            <small>providerneutral · admin-only · Ringpuffer ${ROUTING_DIAGNOSTIC_LIMIT} · keine zusätzlichen Providerabfragen im Live-Modus</small></div>
          <div class="wr-rd-head-actions" aria-label="Schnellaktionen">
            <button id="wr-rd-head-git" type="button" disabled>Nach Git übertragen</button>
            <button id="wr-rd-head-copy" type="button" disabled>Diagnose kopieren</button>
            <button id="wr-rd-head-json" type="button" disabled>JSON kopieren</button>
            <button id="wr-rd-head-report" type="button" disabled>Routingreport</button>
            <button id="wr-rd-head-csv" type="button" disabled>Kandidaten CSV</button>
            <span id="wr-rd-head-status" class="wr-rd-head-status muted">Noch kein Export ausgeführt.</span>
          </div>
          <button id="wr-rd-close" class="wr-rd-close" type="button" title="Schließen">×</button>
        </div>
        <div id="wr-rd-body" class="wr-rd-body"></div>
      `;
      root.appendChild(panel);
      root.getElementById("wr-rd-close")?.addEventListener("click",()=>this._rdClose());
      root.getElementById("wr-rd-head-copy")?.addEventListener("click",()=>void this._rdCopy(true));
      root.getElementById("wr-rd-head-json")?.addEventListener("click",()=>void this._rdCopy(false));
      root.getElementById("wr-rd-head-report")?.addEventListener("click",()=>this._rdDownload("json"));
      root.getElementById("wr-rd-head-csv")?.addEventListener("click",()=>this._rdDownload("csv"));
      root.getElementById("wr-rd-head-git")?.addEventListener("click",()=>void this._rdGitExport());
    }
    this._rdOrganizeDiagnosticHub();
    this._rdUpdateHeaderActions();
  };

  proto._rdOpen = async function() {
    const panel=this.shadowRoot?.getElementById("wr-routing-diagnostic-window");
    if (!panel) return;
    panel.hidden=false;
    await this._rdRefresh(true);
    await this._rdLoadCapabilities();
    await this._rdLoadProfiles();
  };

  proto._rdClose = function() {
    const panel=this.shadowRoot?.getElementById("wr-routing-diagnostic-window");
    if(panel) panel.hidden=true;
  };

  proto._rdLoadCapabilities = async function() {
    const state=this._rdState();
    if(!this._hass || state.capabilities.length) return;
    try{
      const result=await this._hass.callWS({
        type:"weather_router/consumer/capabilities",
        contract_version:1,
      });
      state.capabilities=Array.isArray(result?.capabilities)?result.capabilities:[];
      this._rdRender();
    }catch(error){
      state.message=`Capability-Katalog: ${error?.message||String(error)}`;
      state.messageKind="error";this._rdRender();
    }
  };

  proto._rdLoadProfiles = async function() {
    const state=this._rdState();
    if(!this._hass)return;
    try{
      const result=await this._hass.callWS({type:"weather_router/consumer_profiles"});
      state.profiles=Array.isArray(result?.profiles)?result.profiles:[];
      this._rdRender();
    }catch(error){
      state.profiles=[];
      state.message=`Consumer-Profile: ${error?.message||String(error)}`;
      state.messageKind="error";this._rdRender();
    }
  };
  proto._rdEnsureP0060Profiles = async function() {
    const state=this._rdState();
    if(!this._hass)return;
    const profiles=[
      {id:"p0060_no_satellite",name:"P0-060 · Kein Satellit",description:"Testprofil: satellitenbasierte Candidates ausschließen.",enabled:true,excluded_data_origins:["satellite"]},
      {id:"p0060_no_model",name:"P0-060 · Kein Modell",description:"Testprofil: modellbasierte Candidates ausschließen.",enabled:true,excluded_data_origins:["model"]},
      {id:"p0060_no_dwd",name:"P0-060 · Kein DWD",description:"Testprofil: Provider DWD ausschließen.",enabled:true,excluded_providers:["dwd"]},
      {id:"p0060_no_reflectivity",name:"P0-060 · Keine Radarreflektivität",description:"Testprofil: radar_reflectivity als Messmethode ausschließen.",enabled:true,excluded_measurement_methods:["radar_reflectivity"]},
      {id:"p0060_no_forecast_model",name:"P0-060 · Kein Forecast/Modell",description:"Testprofil: Modelle und Forecast-Beobachtungsart ausschließen.",enabled:true,excluded_data_origins:["model"],excluded_observation_kinds:["forecast"]},
    ];
    state.message="P0-060-Testprofile werden angelegt/aktualisiert …";state.messageKind="muted";this._rdRenderMessageOnly();
    try{
      let result=null;
      for(const profile of profiles){
        result=await this._hass.callWS({type:"weather_router/consumer_profile_upsert",profile});
      }
      state.profiles=Array.isArray(result?.profiles)?result.profiles:state.profiles;
      state.message="5 P0-060-Testprofile sind bereit. Wähle jetzt eines im Feld Profil aus.";state.messageKind="ok";
      this._rdRender();
    }catch(error){
      state.message=`P0-060-Testprofile konnten nicht angelegt werden: ${error?.message||String(error)}`;state.messageKind="error";this._rdRender();
    }
  };
  proto._rdRefresh = async function(selectLatest=false, preferredId="") {
    const state=this._rdState();
    if(!this._hass) return;
    state.loading=true;this._rdRender();
    try{
      const index=await this._hass.callWS({type:"weather_router/routing_diagnostics",limit:50});
      state.index=Array.isArray(index?.traces)?index.traces:[];
      const desired=preferredId || (selectLatest?state.index[0]?.trace_id:"") || state.selectedId || state.index[0]?.trace_id || "";
      state.selectedId=state.index.some(item=>item.trace_id===desired)?desired:(state.index[0]?.trace_id||"");
      if(!state.compareA) state.compareA=state.index[0]?.trace_id||"";
      if(!state.compareB) state.compareB=state.index[1]?.trace_id||state.index[0]?.trace_id||"";
      state.trace=state.selectedId?await this._hass.callWS({type:"weather_router/routing_diagnostics",trace_id:state.selectedId}):null;
      state.message=`${state.index.length} Routing-Entscheidungen im Ringpuffer.`;
      state.messageKind="ok";
    }catch(error){
      state.message=error?.message||String(error);state.messageKind="error";
    }finally{state.loading=false;this._rdRender();}
  };

  proto._rdLoadTrace = async function(id) {
    const state=this._rdState();state.selectedId=id;
    if(!id){state.trace=null;this._rdRender();return;}
    try{
      state.trace=await this._hass.callWS({type:"weather_router/routing_diagnostics",trace_id:id});
      state.message="Trace geladen.";state.messageKind="ok";
    }catch(error){state.message=error?.message||String(error);state.messageKind="error";}
    this._rdRender();
  };

  proto._rdSetLive = async function(enabled) {
    const state=this._rdState();
    if(!this._hass) return;
    if(!enabled){
      if(typeof state.liveUnsub==="function") await state.liveUnsub();
      state.liveUnsub=null;state.live=false;this._rdRender();return;
    }
    if(state.liveUnsub){state.live=true;this._rdRender();return;}
    try{
      state.liveUnsub=await this._hass.connection.subscribeMessage(event=>{
        const traceId=event?.summary?.trace_id||event?.trace?.meta?.trace_id||"";
        clearTimeout(state.liveRefreshTimer);
        state.liveRefreshTimer=setTimeout(()=>{void this._rdRefresh(true,traceId);},350);
      },{type:"weather_router/routing_diagnostics_subscribe"});
      state.live=true;state.message="Live Routing beobachten ist aktiv.";state.messageKind="ok";
    }catch(error){state.live=false;state.message=error?.message||String(error);state.messageKind="error";}
    this._rdRender();
  };

  proto._rdCaptureManual = function() {
    const root=this.shadowRoot;const state=this._rdState();const manual=state.manual;
    const capability=root?.getElementById("wr-rd-capability");if(capability?.value)manual.capability=capability.value;
    const filter=root?.getElementById("wr-rd-capability-filter");if(filter)manual.capabilityFilter=filter.value;
    const preset=root?.getElementById("wr-rd-preset");if(preset)manual.preset=preset.value;
    const type=root?.getElementById("wr-rd-context-type")?.value;const number=id=>Number(root?.getElementById(id)?.value);
    if(type==="global")manual.context={type:"global"};
    else if(type==="point"&&root?.getElementById("wr-rd-lat"))manual.context={type:"point",latitude:number("wr-rd-lat"),longitude:number("wr-rd-lon")};
    else if(type==="bbox"&&root?.getElementById("wr-rd-west"))manual.context={type:"bbox",west:number("wr-rd-west"),south:number("wr-rd-south"),east:number("wr-rd-east"),north:number("wr-rd-north")};
    const resource=root?.getElementById("wr-rd-resource-type");if(resource)manual.resourceType=resource.value;
    const source=root?.getElementById("wr-rd-source-class");if(source)manual.sourceClass=source.value;
    const age=root?.getElementById("wr-rd-max-age");if(age)manual.maxAgeSeconds=age.value;
    const timeline=root?.getElementById("wr-rd-timeline-required");if(timeline)manual.timelineRequired=timeline.checked;
    const profile=root?.getElementById("wr-rd-profile");if(profile)manual.profileId=profile.value;
    return manual;
  };

  proto._rdPreset = function(key) {
    const preset=PRESETS[key];if(!preset)return;
    const state=this._rdState();state.manual.preset=key;state.manual.context={...preset};
    const type=this.shadowRoot?.getElementById("wr-rd-context-type");if(type)type.value=preset.type;
    this._rdRenderManualContext(preset);
  };

  proto._rdRenderManualContext = function(values=null) {
    const host=this.shadowRoot?.getElementById("wr-rd-context-fields");if(!host)return;
    const state=this._rdState();
    let context=values?{...values}:{...(state.manual.context||{type:"bbox",west:5,south:47,east:16,north:56})};
    const selectedType=this.shadowRoot?.getElementById("wr-rd-context-type")?.value;
    if(!values&&selectedType&&selectedType!==context.type){
      context=selectedType==="global"?{type:"global"}:selectedType==="point"?{type:"point",latitude:53.5,longitude:10.0}:{type:"bbox",west:5,south:47,east:16,north:56};
      state.manual.preset="";
    }
    const type=context.type||"bbox";state.manual.context={...context};
    const typeSelect=this.shadowRoot?.getElementById("wr-rd-context-type");if(typeSelect)typeSelect.value=type;
    if(type==="global"){host.className="wr-rd-context-grid";host.innerHTML='<div class="wr-rd-muted">global=true</div>';return;}
    if(type==="point"){
      host.className="wr-rd-context-grid point";
      host.innerHTML=`
        <label>Latitude<input id="wr-rd-lat" type="number" step="any" value="${context.latitude??53.5}"></label>
        <label>Longitude<input id="wr-rd-lon" type="number" step="any" value="${context.longitude??10.0}"></label>`;
      return;
    }
    host.className="wr-rd-context-grid";
    host.innerHTML=`
      <label>west<input id="wr-rd-west" type="number" step="any" value="${context.west??5}"></label>
      <label>south<input id="wr-rd-south" type="number" step="any" value="${context.south??47}"></label>
      <label>east<input id="wr-rd-east" type="number" step="any" value="${context.east??16}"></label>
      <label>north<input id="wr-rd-north" type="number" step="any" value="${context.north??56}"></label>`;
  };

  proto._rdUseTraceContext = function() {
    const state=this._rdState();const context=state.trace?.context;if(!context)return;
    let next=null;
    if(context.type==="bbox")next={type:"bbox",west:Number(context.west),south:Number(context.south),east:Number(context.east),north:Number(context.north)};
    else if(context.type==="point")next={type:"point",latitude:Number(context.latitude??context.center?.latitude),longitude:Number(context.longitude??context.center?.longitude)};
    else if(context.type==="global")next={type:"global"};
    if(!next)return;
    state.manual.context=next;state.manual.preset="";
    const preset=this.shadowRoot?.getElementById("wr-rd-preset");if(preset)preset.value="";
    this._rdRenderManualContext(next);
    state.message="Räumlicher Kontext des ausgewählten Traces wurde in die manuelle Testanfrage übernommen.";
    state.messageKind="ok";this._rdRenderMessageOnly();
  };

  proto._rdCapabilityEntries = function() {
    return [...this._rdState().capabilities].sort((a,b)=>String(a.id).localeCompare(String(b.id)))
      .map((item,index)=>({...item,uiNumber:String(index+1).padStart(3,"0")}));
  };

  proto._rdApplyCapabilityFilter = function() {
    const state=this._rdState();const root=this.shadowRoot;
    const select=root?.getElementById("wr-rd-capability");const input=root?.getElementById("wr-rd-capability-filter");if(!select||!input)return;
    state.manual.capabilityFilter=input.value;
    const needle=input.value.trim().toLocaleLowerCase("de-DE");
    const rows=this._rdCapabilityEntries().filter(item=>!needle||item.uiNumber.includes(needle)||String(item.name||"").toLocaleLowerCase("de-DE").includes(needle)||String(item.id).toLocaleLowerCase("de-DE").includes(needle));
    const wanted=state.manual.capability||select.value;
    select.innerHTML=rows.map(item=>`<option value="${this._rdEsc(item.id)}" ${item.id===wanted?"selected":""}>${item.uiNumber} · ${this._rdEsc(item.name||item.id)} · ${this._rdEsc(item.id)}</option>`).join("");
    if(rows.some(item=>item.id===wanted))select.value=wanted;
    else if(rows.length){select.value=rows[0].id;state.manual.capability=rows[0].id;}
  };

  proto._rdUpdateHeaderActions = function() {
    const root=this.shadowRoot;const state=this._rdState();const disabled=!state.trace||state.exportBusy;
    for(const id of ["wr-rd-head-copy","wr-rd-head-json","wr-rd-head-report","wr-rd-head-csv","wr-rd-head-git"]){const button=root?.getElementById(id);if(button)button.disabled=disabled;}
    const status=root?.getElementById("wr-rd-head-status");
    if(status){
      status.textContent=state.exportMessage||"";
      status.className=`wr-rd-head-status ${state.exportKind||"muted"}`;
    }
    const git=root?.getElementById("wr-rd-head-git");
    if(git){
      const currentTraceId=state.trace?.meta?.trace_id||null;
      const exportedCurrentTrace=Boolean(
        state.gitExportResult
        && state.gitExportedTraceId
        && currentTraceId
        && state.gitExportedTraceId===currentTraceId
      );
      git.textContent=state.exportBusy
        ?"Git-Export …"
        :exportedCurrentTrace
          ?"✓ In Git"
          :"Nach Git übertragen";
      git.classList.toggle("wr-rd-git-exported",exportedCurrentTrace);
      git.title=exportedCurrentTrace
        ?("Aktueller Trace nach Git exportiert"+(state.gitExportResult?.path?" · "+state.gitExportResult.path:""))
        :"Aktuellen Trace nach Git übertragen";
    }
  };

  proto._rdOrganizeDiagnosticHub = function() {
    const root=this.shadowRoot;const sidebar=root?.querySelector(".sidebar");if(!root||!sidebar)return;
    let hub=root.getElementById("wr-diagnostic-hub");
    if(!hub){
      hub=document.createElement("section");hub.id="wr-diagnostic-hub";hub.className="wr-diagnostic-hub";
      hub.innerHTML='<div class="wr-diagnostic-hub-title"><span>Diagnose & Protokolle</span><small>Provider · Routing · Logs</small></div><div id="wr-diagnostic-hub-tools" class="wr-diagnostic-hub-tools"></div>';
      const hero=sidebar.querySelector(".hero");
      if(hero?.nextSibling)sidebar.insertBefore(hub,hero.nextSibling);else if(hero)hero.after(hub);else sidebar.prepend(hub);
    }
    const tools=hub.querySelector("#wr-diagnostic-hub-tools");if(!tools)return;
    for(const id of ["provider-diagnostics-launch","wr-routing-diagnostic-launch","wr-log-menu"]){const node=root.getElementById(id);if(node&&node.parentElement!==tools)tools.appendChild(node);}
  };

  proto._rdCurrentMap = function() {
    const map=this._map;if(!map)return;
    const bounds=map.getBounds?.();const center=map.getCenter?.();
    if(!bounds||!center)return;
    const type=this.shadowRoot?.getElementById("wr-rd-context-type");
    if(type)type.value="bbox";
    const context={type:"bbox",west:bounds.getWest(),south:bounds.getSouth(),east:bounds.getEast(),north:bounds.getNorth()};
    const state=this._rdState();state.manual.context=context;state.manual.preset="";
    const preset=this.shadowRoot?.getElementById("wr-rd-preset");if(preset)preset.value="";
    this._rdRenderManualContext(context);
    state.message=`Kartenausschnitt übernommen · Zentrum ${center.lat.toFixed(4)}, ${center.lng.toFixed(4)} · Zoom ${Number(map.getZoom?.()||0).toFixed(2)}`;
    state.messageKind="ok";this._rdRenderMessageOnly();
  };

  proto._rdBuildContext = function() {
    this._rdCaptureManual();
    const root=this.shadowRoot;const type=root?.getElementById("wr-rd-context-type")?.value||this._rdState().manual.context?.type||"bbox";
    if(type==="global")return{type:"global"};
    const number=id=>Number(root?.getElementById(id)?.value);
    if(type==="point")return{type:"point",latitude:number("wr-rd-lat"),longitude:number("wr-rd-lon")};
    return{type:"bbox",west:number("wr-rd-west"),south:number("wr-rd-south"),east:number("wr-rd-east"),north:number("wr-rd-north")};
  };

  proto._rdRunP0070FaultTest = async function() {
    const state=this._rdState();
    const root=this.shadowRoot;
    if(!this._hass||!root)return;
    const mode=String(root.getElementById("wr-rd-p0070-fault")?.value||"resource_temporarily_unavailable");
    state.manual.faultMode=mode;
    state.manual.capability="weather.precipitation.layer";
    state.manual.profileId="";
    state.manual.preset="germany";
    state.manual.context={...PRESETS.germany};
    state.manual.resourceType="";
    state.manual.sourceClass="";
    state.manual.maxAgeSeconds="";
    state.manual.timelineRequired=false;

    const capability=root.getElementById("wr-rd-capability");if(capability)capability.value=state.manual.capability;
    const profile=root.getElementById("wr-rd-profile");if(profile)profile.value="";
    const contextType=root.getElementById("wr-rd-context-type");if(contextType)contextType.value="bbox";
    const preset=root.getElementById("wr-rd-preset");if(preset)preset.value="germany";
    const resource=root.getElementById("wr-rd-resource-type");if(resource)resource.value="";
    const source=root.getElementById("wr-rd-source-class");if(source)source.value="";
    const maxAge=root.getElementById("wr-rd-max-age");if(maxAge)maxAge.value="";
    const timeline=root.getElementById("wr-rd-timeline-required");if(timeline)timeline.checked=false;
    this._rdRenderManualContext(state.manual.context);

    state.message="P0-070 Fehlerprobe wird vorbereitet …";state.messageKind="muted";this._rdRenderMessageOnly();
    try{
      await this._hass.callWS({
        type:"weather_router/routing_diagnostic_fault_arm",
        provider_id:"dwd",
        capability_id:"radar_precipitation_quality_checked",
        mode,
      });
      state.message=`P0-070 Fehlerprobe aktiv: ${mode} · nächster Resolve nutzt Deutschland + weather.precipitation.layer.`;
      state.messageKind="muted";this._rdRenderMessageOnly();
      await this._rdResolve();
    }catch(error){
      state.message=`P0-070 Fehlerprobe fehlgeschlagen: ${error?.message||String(error)}`;
      state.messageKind="error";this._rdRender();
    }
  };

  proto._rdResolve = async function() {
    const state=this._rdState();const root=this.shadowRoot;this._rdCaptureManual();
    const capability=root?.getElementById("wr-rd-capability")?.value||state.manual.capability;
    if(!capability)return;
    state.manual.capability=capability;
    const resourceType=root?.getElementById("wr-rd-resource-type")?.value||"";
    const sourceClass=String(root?.getElementById("wr-rd-source-class")?.value||"").trim();
    const maxAgeRaw=String(root?.getElementById("wr-rd-max-age")?.value||"").trim();
    const timelineRequired=Boolean(root?.getElementById("wr-rd-timeline-required")?.checked);
    const profileId=String(root?.getElementById("wr-rd-profile")?.value||"").trim();
    const message={
      type:"weather_router/consumer/resolve",contract_version:1,capability,
      context:this._rdBuildContext(),time:{mode:"latest"},
    };
    const requirements={};
    if(resourceType)requirements.resource_types=[resourceType];
    if(sourceClass)requirements.source_classes=[sourceClass];
    if(maxAgeRaw)requirements.max_age_seconds=Math.max(0,Math.floor(Number(maxAgeRaw)));
    if(timelineRequired)requirements.timeline_required=true;
    if(Object.keys(requirements).length)message.requirements=requirements;
    if(profileId)message.profile_id=profileId;
    state.message="Resolve läuft …";state.messageKind="muted";this._rdRenderMessageOnly();
    try{
      state.manualResult=await this._hass.callWS(message);
      state.gitExportResult=null;
      state.gitExportedTraceId=null;
      state.exportMessage="Aktueller Resolve noch nicht nach Git übertragen.";
      state.exportKind="muted";
      state.message=`Resolve: ${state.manualResult?.status||"?"} · ${state.manualResult?.unavailable?.code||state.manualResult?.routing?.reason_code||""}`;
      state.messageKind=state.manualResult?.status==="ready"?"ok":"muted";
      await this._rdRefresh(true);
    }catch(error){state.message=error?.message||String(error);state.messageKind="error";this._rdRender();}
  };

  proto._rdCompare = async function() {
    const state=this._rdState();
    if(!state.compareA||!state.compareB)return;
    try{
      const [a,b]=await Promise.all([
        this._hass.callWS({type:"weather_router/routing_diagnostics",trace_id:state.compareA}),
        this._hass.callWS({type:"weather_router/routing_diagnostics",trace_id:state.compareB}),
      ]);
      const pick=t=>({
        id:t?.meta?.trace_id,capability:t?.request?.capability,context:t?.context,
        provider:t?.decision?.selected_provider,status:t?.decision?.status,code:t?.decision?.code,
        reason:t?.decision?.reason_code,duration_ms:t?.performance?.total_ms,
        candidate_count:t?.candidates?.length||0,
        coverage:(t?.coverage||[]).map(item=>({candidate:item.candidate,match:item.routing_match,overlap:item.overlap_percent,status:item.final_status})),
        resource_type:t?.resource?.type||null,
      });
      const pa=pick(a),pb=pick(b);
      const candidatesA=(a?.candidates||[]).map(item=>`${item.provider_id}/${item.capability_id}`);
      const candidatesB=(b?.candidates||[]).map(item=>`${item.provider_id}/${item.capability_id}`);
      const setA=new Set(candidatesA),setB=new Set(candidatesB);
      state.compareResult={
        changes:{
          provider_changed:pa.provider!==pb.provider,
          provider:{a:pa.provider,b:pb.provider},
          status_changed:pa.status!==pb.status||pa.code!==pb.code,
          status:{a:`${pa.status||""}/${pa.code||pa.reason||""}`,b:`${pb.status||""}/${pb.code||pb.reason||""}`},
          resource_type_changed:pa.resource_type!==pb.resource_type,
          resource_type:{a:pa.resource_type,b:pb.resource_type},
          candidates_added:candidatesB.filter(item=>!setA.has(item)),
          candidates_removed:candidatesA.filter(item=>!setB.has(item)),
          coverage_changed:JSON.stringify(pa.coverage)!==JSON.stringify(pb.coverage),
          duration_delta_ms:(
            Number.isFinite(Number(pa.duration_ms))&&Number.isFinite(Number(pb.duration_ms))
              ?Number((Number(pb.duration_ms)-Number(pa.duration_ms)).toFixed(3)):null
          ),
        },
        a:pa,b:pb
      };
      state.message="Vergleich aktualisiert.";state.messageKind="ok";
    }catch(error){state.message=error?.message||String(error);state.messageKind="error";}
    this._rdRender();
  };

  proto._rdCopyText = async function(text) {
    if(typeof this._wrEventLogCopyText==="function")return this._wrEventLogCopyText(text);
    try{await navigator.clipboard.writeText(text);return true;}catch(_e){return false;}
  };

  proto._rdSetExportStatus = function(message, kind="muted", busy=false, result=null) {
    const state=this._rdState();
    state.exportMessage=message;
    state.exportKind=kind;
    state.exportBusy=Boolean(busy);
    if(result!==null){
      state.gitExportResult=result;
      state.gitExportedTraceId=state.trace?.meta?.trace_id||null;
    }

    this._rdUpdateHeaderActions();
    const status=this.shadowRoot?.getElementById("wr-rd-export-status");
    if(status){
      status.textContent=message||"";
      status.className=`wr-rd-export-status ${kind}`;
    }
    for(const id of [
      "wr-rd-copy-compact","wr-rd-copy-json","wr-rd-download-json",
      "wr-rd-download-csv","wr-rd-git"
    ]){
      const button=this.shadowRoot?.getElementById(id);
      if(button) button.disabled=Boolean(busy);
    }
    const link=this.shadowRoot?.getElementById("wr-rd-git-link");
    if(link){
      if(state.gitExportResult?.file_url){
        link.href=state.gitExportResult.file_url;
        link.hidden=false;
      }else{
        link.hidden=true;
      }
    }
  };

  proto._rdCopy = async function(compact=false) {
    const trace=this._rdState().trace;
    if(!trace){
      this._rdSetExportStatus("Kein Routingtrace zum Kopieren vorhanden.","error");
      return;
    }
    this._rdSetExportStatus("Kopieren …","muted",true);
    const text=compact?this._rdCompactText(trace):JSON.stringify(trace,null,2);
    const ok=await this._rdCopyText(text);
    this._rdSetExportStatus(
      ok
        ? (compact?"Diagnose in die Zwischenablage kopiert.":"JSON in die Zwischenablage kopiert.")
        : "Kopieren nicht möglich.",
      ok?"ok":"error",
      false,
    );
  };

  proto._rdCompactText = function(trace) {
    const d=trace?.decision||{},r=trace?.request||{},c=trace?.context||{};
    const rows=[
      `WeatherRouter Routing-Diagnose ${trace?.meta?.trace_id||""}`,
      `Zeit: ${trace?.meta?.completed_at||""}`,
      `Capability: ${r.capability||""}`,
      `Context: ${r.context_type||""} ${JSON.stringify(c)}`,
      `Status: ${d.status||""} ${d.code||d.reason_code||""}`,
      `Provider: ${d.selected_provider||"—"}`,
      `Dauer: ${trace?.performance?.total_ms??"—"} ms`,
      "Kandidaten:",
      ...(trace?.candidates||[]).map(item=>`- ${item.provider_id}/${item.capability_id}: ${item.result} · ${item.reason||""} · intent=${item.intent||r.capability||"—"} · topics=${(item.topics||[]).join("|")||"—"} · resource=${item.resource_type||"—"} · origin=${item.data_origin||"—"} · method=${item.measurement_method||"—"} · kind=${item.observation_kind||"—"} · quantity=${item.quantity||"—"} · unit=${item.unit??"—"} · time=${JSON.stringify(item.time_semantics||{})} · coverage_contract=${JSON.stringify(item.coverage_semantics||{})} · freshness=${JSON.stringify(item.freshness||{})} · score=${JSON.stringify(item.routing_score||[])} · overlap=${item.coverage?.overlap_percent??"—"}`),
    ];
    return rows.join("\n");
  };

  proto._rdDownload = function(kind="json") {
    const trace=this._rdState().trace;
    if(!trace){
      this._rdSetExportStatus("Kein Routingtrace zum Herunterladen vorhanden.","error");
      return;
    }

    try{
      let content,mime,ext,label;
      if(kind==="csv"){
        const headers=["order","intent","topics","provider","capability","resource_type","data_origin","measurement_method","observation_kind","quantity","unit","time_semantics","coverage_semantics","freshness","routing_score","coverage_runtime","center_inside","overlap_percent","result","reason","duration_ms"];
        const rows=[headers,...(trace.candidates||[]).map(c=>[
          c.order,c.intent||trace?.request?.capability||"",(c.topics||[]).join("|"),c.provider_id,c.capability_id,c.resource_type,c.data_origin||"",c.measurement_method||"",c.observation_kind||"",c.quantity||"",c.unit??"",JSON.stringify(c.time_semantics||{}),JSON.stringify(c.coverage_semantics||{}),JSON.stringify(c.freshness||{}),JSON.stringify(c.routing_score||[]),c.coverage?.final_status||"",
          c.coverage?.center_inside??"",c.coverage?.overlap_percent??"",c.result,c.reason||"",c.duration_ms??""
        ])];
        const esc=v=>`"${String(v??"").replaceAll('"','""')}"`;
        content=rows.map(row=>row.map(esc).join(",")).join("\r\n")+"\r\n";
        mime="text/csv;charset=utf-8";ext="csv";label="Kandidaten-CSV";
      }else{
        content=JSON.stringify(trace,null,2);
        mime="application/json";ext="json";label="Routingreport";
      }

      const blob=new Blob([content],{type:mime});
      const url=URL.createObjectURL(blob);
      const anchor=document.createElement("a");
      anchor.href=url;
      anchor.download=`weather-router-routing-${trace?.meta?.trace_id||Date.now()}.${ext}`;
      anchor.style.display="none";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      this._rdSetExportStatus(`${label}-Download gestartet.`,"ok");
    }catch(error){
      this._rdSetExportStatus(
        `Download fehlgeschlagen: ${error?.message||String(error)}`,
        "error",
      );
    }
  };

  proto._rdGitExport = async function() {
    const state=this._rdState();
    const manualCapability=String(
      this.shadowRoot?.getElementById("wr-rd-capability")?.value
      || state.manual.capability
      || ""
    ).trim();
    const traceCapability=String(state.trace?.request?.capability||"").trim();
    if(manualCapability && traceCapability && manualCapability!==traceCapability){
      this._rdSetExportStatus(
        `Nicht exportiert: manuelle Auswahl ${manualCapability} stimmt nicht mit dem aktuellen Trace ${traceCapability} überein. Erst „Resolve testen“ ausführen.`,
        "error",
      );
      return;
    }
    if(!state.trace){
      this._rdSetExportStatus("Kein Routingtrace für Git vorhanden.","error");
      return;
    }
    if(!this._hass || typeof this._wrGitExportSnapshot!=="function"){
      this._rdSetExportStatus(
        "Gemeinsamer WeatherRouter-Git-Exporter ist nicht verfügbar.",
        "error",
      );
      return;
    }

    // The visible UI number belongs to this selected capability in the actual
    // current routing catalogue. Never manufacture a number if it is absent.
    const displayed=traceCapability
      ?this._rdCapabilityEntries().find(item=>item.id===traceCapability)
      :null;
    const snapshotForArchive={
      ...state.trace,
      test:{
        ...(state.trace.test && typeof state.trace.test==="object" ? state.trace.test : {}),
        ...(displayed?.uiNumber ? {capabilityUiNumber:displayed.uiNumber} : {}),
      },
    };
    this._rdSetExportStatus("Git-Status wird geprüft …","muted",true);
    try{
      const result=await this._wrGitExportSnapshot(snapshotForArchive,{
        onConfigure: () => {
          this._rdSetExportStatus(
            "Git-Zugang ist noch nicht eingerichtet. Konfigurationsdialog geöffnet; nach dem Speichern wird der Routingtrace automatisch exportiert.",
            "muted",
            false,
          );
        },
        onStart: gitState => {
          this._rdSetExportStatus(
            `Export nach Git läuft · ${gitState?.branch||"Branch unbekannt"} …`,
            "muted",
            true,
          );
        },
        onSuccess: exported => {
          this._rdSetExportStatus(
            `Nach Git exportiert · ${exported?.path||"Pfad unbekannt"}`,
            "ok",
            false,
            exported,
          );
        },
        onError: error => {
          this._rdSetExportStatus(
            `Git-Export fehlgeschlagen: ${error?.message||String(error)}`,
            "error",
            false,
          );
        },
      });
      if(result?.pending_configuration) return;
    }catch(error){
      this._rdSetExportStatus(
        `Git-Export fehlgeschlagen: ${error?.message||String(error)}`,
        "error",
        false,
      );
    }
  };

  proto._rdClear = async function() {
    const state=this._rdState();
    try{await this._hass.callWS({type:"weather_router/routing_diagnostics_clear"});state.trace=null;state.index=[];state.selectedId="";state.gitExportResult=null;state.gitExportedTraceId=null;state.message="Routing-Ringpuffer geleert.";state.messageKind="ok";}
    catch(error){state.message=error?.message||String(error);state.messageKind="error";}
    this._rdRender();
  };

  proto._rdCheckCell = function(checks,name) {
    const item=checks?.[name];if(!item)return'<span class="wr-rd-muted">—</span>';
    return item.passed?'<span class="wr-rd-pass">✓</span>':`<span class="wr-rd-fail" title="${this._rdEsc(item.reason||"")}">×</span>`;
  };

  proto._rdCandidateTable = function(trace) {
    const rows=trace?.candidates||[];
    return `<div class="wr-rd-table-wrap"><table class="wr-rd-table"><thead><tr>
      <th>#</th><th>Intent / Topic</th><th>Provider / Capability</th><th>Origin / Methode</th><th>Semantik</th><th>Zeit</th><th>Coverage-Vertrag</th><th>Freshness</th><th>Score</th><th>Router</th><th>Domain</th><th>Provider</th><th>Profil</th><th>Candidate-Policy</th>
      <th>Resource</th><th>Context</th><th>Coverage Runtime</th><th>Mitte</th><th>Overlap</th><th>Result</th><th>Reason</th><th>ms</th>
    </tr></thead><tbody>${rows.map(c=>`<tr>
      <td>${c.order??""}</td><td><strong>${this._rdEsc(c.intent||trace?.request?.capability||"—")}</strong><br><span class="wr-rd-muted">${this._rdEsc((c.topics||[]).join(", ")||"—")}</span></td><td><strong>${this._rdEsc(c.provider_id)}</strong><br><span class="wr-rd-muted">${this._rdEsc(c.capability_id)} · ${this._rdEsc(c.resource_type)}</span></td>
      <td>${this._rdEsc(c.data_origin||"—")}<br><span class="wr-rd-muted">${this._rdEsc(c.measurement_method||"—")}</span></td>
      <td>${this._rdEsc(c.observation_kind||"—")}<br><span class="wr-rd-muted">${this._rdEsc(c.quantity||"—")}${c.unit!=null?` · ${this._rdEsc(c.unit)}`:""}</span></td>
      <td><span class="wr-rd-muted">${this._rdEsc(JSON.stringify(c.time_semantics||{}))}</span></td><td><span class="wr-rd-muted">${this._rdEsc(JSON.stringify(c.coverage_semantics||{}))}</span></td><td><span class="wr-rd-muted">${this._rdEsc(c.freshness?.age_seconds!=null?`${Number(c.freshness.age_seconds).toFixed(1)} s`:(c.freshness?.data_time||"—"))}</span></td>
      <td>${this._rdEsc(JSON.stringify(c.routing_score||[]))}</td>
      <td>${this._rdCheckCell(c.checks,"router_enabled")}</td><td>${this._rdCheckCell(c.checks,"domain_enabled")}</td>
      <td>${this._rdCheckCell(c.checks,"provider_enabled")}</td><td>${this._rdCheckCell(c.checks,"profile_allowed")}</td><td>${this._rdCheckCell(c.checks,"candidate_policy")}</td>
      <td>${this._rdCheckCell(c.checks,"resource_implemented")}</td><td>${this._rdCheckCell(c.checks,"context_supported")}</td>
      <td>${c.coverage?this._rdEsc(c.coverage.final_status||c.coverage.support||"—"):"—"}</td>
      <td>${c.coverage?.center_inside==null?"—":c.coverage.center_inside?"✓":"×"}</td>
      <td>${c.coverage?.overlap_percent==null?"—":`${Number(c.coverage.overlap_percent).toFixed(1)} %`}</td>
      <td>${this._rdEsc(c.result||"")}</td><td>${this._rdEsc(c.reason||"")}</td><td>${c.duration_ms??"—"}</td>
    </tr>`).join("")}</tbody></table></div><div class="wr-rd-candidate-cards">${rows.map(c=>`<div class="wr-rd-candidate-card"><div class="wr-rd-candidate-card-head"><strong>#${c.order??""} · ${this._rdEsc(c.provider_id)}</strong><span class="wr-rd-badge ${c.result==="selected"?"ready":c.result==="rejected"?"unavailable":""}">${this._rdEsc(c.result||"pending")}</span></div><div class="wr-rd-muted" style="margin-top:3px;overflow-wrap:anywhere">${this._rdEsc(c.capability_id||"")}</div><div class="wr-rd-candidate-card-grid"><div><small>Intent / Topic</small>${this._rdEsc(c.intent||trace?.request?.capability||"—")}<br>${this._rdEsc((c.topics||[]).join(", ")||"—")}</div><div><small>Semantik</small>${this._rdEsc(c.data_origin||"—")} · ${this._rdEsc(c.observation_kind||"—")}<br>${this._rdEsc(c.quantity||"—")}${c.unit!=null?` · ${this._rdEsc(c.unit)}`:""}</div><div><small>Methode / Score</small>${this._rdEsc(c.measurement_method||"—")}<br>${this._rdEsc(JSON.stringify(c.routing_score||[]))}</div><div><small>Zeit / Freshness</small>${this._rdEsc(c.freshness?.age_seconds!=null?`${Number(c.freshness.age_seconds).toFixed(1)} s`:(c.freshness?.data_time||"—"))}<br><span class="wr-rd-muted">${this._rdEsc(JSON.stringify(c.time_semantics||{}))}</span></div><div><small>Profil / Policy</small>${this._rdCheckCell(c.checks,"profile_allowed")} Profil · ${this._rdCheckCell(c.checks,"candidate_policy")} Candidate</div><div><small>Coverage</small>${c.coverage?this._rdEsc(c.coverage.final_status||c.coverage.support||"—"):"—"}${c.coverage?.overlap_percent==null?"":` · ${Number(c.coverage.overlap_percent).toFixed(1)} %`}<br><span class="wr-rd-muted">${this._rdEsc(JSON.stringify(c.coverage_semantics||{}))}</span></div><div><small>Grund</small>${this._rdEsc(c.reason||"—")}</div><div><small>Dauer</small>${c.duration_ms??"—"} ms</div></div></div>`).join("")}</div>`;
  };

  proto._rdTraceOptions = function(selected) {
    const rows=this._rdState().index;
    return rows.map(item=>`<option value="${this._rdEsc(item.trace_id)}" ${item.trace_id===selected?"selected":""}>
      ${this._rdEsc(item.started_at||"")} · ${this._rdEsc(item.capability||"")} · ${this._rdEsc(item.selected_provider||item.code||item.status||"")}
    </option>`).join("");
  };

  proto._rdFold = function(title,meta,body,open=false) {
    return `<details class="wr-rd-fold" ${open?"open":""}><summary><span>${this._rdEsc(title)}</span><span class="wr-rd-muted">${this._rdEsc(meta||"")}</span></summary><div class="wr-rd-fold-body">${body}</div></details>`;
  };

  proto._rdRenderMessageOnly = function() {
    const el=this.shadowRoot?.getElementById("wr-rd-message");const state=this._rdState();
    if(el){el.textContent=state.message||"";el.className=`wr-rd-message ${state.messageKind||"muted"}`;}
  };

  proto._rdRender = function() {
    const body=this.shadowRoot?.getElementById("wr-rd-body");if(!body)return;
    this._rdCaptureManual();
    const state=this._rdState(),trace=state.trace,decision=trace?.decision||{},request=trace?.request||{};
    const statusClass=decision.status==="ready"?"ready":decision.status==="error"?"error":"unavailable";
    const capabilities=this._rdCapabilityEntries();
    const compactMobile=Boolean(window.matchMedia?.("(max-width:900px)")?.matches);
    const selectedCapability=state.manual.capability||request.capability||capabilities.find(x=>x.id==="weather.precipitation.layer")?.id||capabilities.find(x=>x.id==="weather.radar.precipitation")?.id||capabilities[0]?.id||"";
    state.manual.capability=selectedCapability;
    const traceMeta=trace?.meta||{};
    const context=trace?.context||{};
    const coverage=trace?.coverage||[];

    body.innerHTML=`
      <div class="wr-rd-toolbar">
        <label>Letzte Routingentscheidungen
          <select id="wr-rd-trace">${this._rdTraceOptions(state.selectedId)||'<option value="">Noch keine Traces</option>'}</select>
        </label>
        <button id="wr-rd-refresh" type="button">${state.loading?"Lädt …":"Aktualisieren"}</button>
        <label style="display:flex;align-items:center;gap:6px;margin:0 4px 4px">
          <input id="wr-rd-live" type="checkbox" ${state.live?"checked":""}> Live Routing beobachten
        </label>
        <button id="wr-rd-clear" type="button">Ringpuffer leeren</button>
      </div>
      <div id="wr-rd-message" class="wr-rd-message ${state.messageKind}">${this._rdEsc(state.message||"")}</div>

      ${this._rdFold("Manuelle Testanfrage","keine Providerwahl · erzeugt einen echten Consumer-V1-Resolve",`
        <div class="wr-rd-manual-grid">
          <label>Capability suchen<input id="wr-rd-capability-filter" class="wr-rd-cap-search" value="${this._rdEsc(state.manual.capabilityFilter||"")}" placeholder="Nr., Name oder ID"></label>
          <label>Capability<select id="wr-rd-capability">${capabilities.map(item=>`<option value="${this._rdEsc(item.id)}" ${item.id===selectedCapability?"selected":""}>${item.uiNumber} · ${this._rdEsc(item.name||item.id)} · ${this._rdEsc(item.id)}</option>`).join("")}</select></label>
          <label>Context<select id="wr-rd-context-type"><option value="bbox" ${state.manual.context?.type==="bbox"?"selected":""}>bbox</option><option value="point" ${state.manual.context?.type==="point"?"selected":""}>point</option><option value="global" ${state.manual.context?.type==="global"?"selected":""}>global</option></select></label>
          <label>Preset<select id="wr-rd-preset"><option value="">— Preset —</option>${Object.entries(PRESETS).map(([key,p])=>`<option value="${key}" ${state.manual.preset===key?"selected":""}>${this._rdEsc(p.label)}</option>`).join("")}</select></label>
          <label>Requirement Resource<select id="wr-rd-resource-type"><option value="" ${!state.manual.resourceType?"selected":""}>kein Zwang</option><option value="raster_tile" ${state.manual.resourceType==="raster_tile"?"selected":""}>raster_tile</option><option value="value" ${state.manual.resourceType==="value"?"selected":""}>value</option><option value="event_feed" ${state.manual.resourceType==="event_feed"?"selected":""}>event_feed</option><option value="hazard_feed" ${state.manual.resourceType==="hazard_feed"?"selected":""}>hazard_feed</option><option value="data_file" ${state.manual.resourceType==="data_file"?"selected":""}>data_file</option><option value="image_sequence" ${state.manual.resourceType==="image_sequence"?"selected":""}>image_sequence</option><option value="live_stream" ${state.manual.resourceType==="live_stream"?"selected":""}>live_stream</option><option value="planetary_tile" ${state.manual.resourceType==="planetary_tile"?"selected":""}>planetary_tile</option></select></label>
          <label>Source-Class<input id="wr-rd-source-class" value="${this._rdEsc(state.manual.sourceClass||"")}" placeholder="optional · observation" style="width:100%;min-height:34px"></label>
          <label>max_age_seconds<input id="wr-rd-max-age" type="number" min="0" step="1" value="${this._rdEsc(state.manual.maxAgeSeconds||"")}" placeholder="optional" style="width:100%;min-height:34px"></label>
          <label style="display:flex;align-items:center;gap:7px;padding-top:21px"><input id="wr-rd-timeline-required" type="checkbox" ${state.manual.timelineRequired?"checked":""}> Timeline erforderlich</label>
          <label>Profil<select id="wr-rd-profile">
            <option value="">— ohne Profil —</option>
            ${(state.profiles||[]).map(profile=>`<option value="${this._rdEsc(profile.id)}" ${profile.id===state.manual.profileId?"selected":""}>${this._rdEsc(profile.name||profile.id)} · ${this._rdEsc(profile.id)} · r${Number(profile.revision||0)}</option>`).join("")}
            ${state.manual.profileId && !(state.profiles||[]).some(profile=>profile.id===state.manual.profileId)?`<option value="${this._rdEsc(state.manual.profileId)}" selected>${this._rdEsc(state.manual.profileId)} · nicht im aktuellen Profilkatalog</option>`:""}
          </select></label>
        </div>
        <div class="wr-rd-profile-testbox" style="margin-top:8px">
          <strong>P0-060 Profiltests</strong>
          <div class="wr-rd-muted" style="margin:4px 0 8px">Legt die fünf reservierten Testprofile an bzw. aktualisiert sie. Danach stehen sie direkt in der Profilauswahl oben.</div>
          <button id="wr-rd-create-p0060-profiles" type="button">P0-060-Testprofile anlegen / aktualisieren</button>
        </div>
        <div class="wr-rd-profile-testbox" style="margin-top:8px">
          <strong>P0-070 Fehler-/Ausfall-Fallback</strong>
          <div class="wr-rd-muted" style="margin:4px 0 8px">Admin-only · einmalig für den nächsten manuellen Resolve · Ziel: DWD quality-checked in Deutschland. Normales Routing bleibt unverändert.</div>
          <label>Fehlerprobe
            <select id="wr-rd-p0070-fault">
              <option value="resource_temporarily_unavailable" ${state.manual.faultMode==="resource_temporarily_unavailable"?"selected":""}>Resource temporär nicht verfügbar · nach Coverage</option>
              <option value="rate_limited" ${state.manual.faultMode==="rate_limited"?"selected":""}>Rate Limit · nach Coverage</option>
              <option value="source_stale" ${state.manual.faultMode==="source_stale"?"selected":""}>Quelle veraltet · nach Resource-Abruf</option>
            </select>
          </label>
          <button id="wr-rd-run-p0070-fault" type="button" style="margin-top:8px">P0-070 Fehlerprobe + Resolve starten</button>
        </div>
        <div id="wr-rd-context-fields" class="wr-rd-context-grid" style="margin-top:8px"></div>
        <div class="wr-rd-actions" style="margin-top:8px"><button id="wr-rd-trace-context" type="button" ${trace?"":"disabled"}>Kontext aus Trace übernehmen</button><button id="wr-rd-map" type="button">Aktuellen Kartenausschnitt testen</button><button id="wr-rd-resolve" class="primary" type="button">Resolve testen</button></div>
      `,false)}

      ${trace?`
        <div class="wr-rd-summary-grid">
          <div class="wr-rd-card"><small>Trace</small><strong>${this._rdEsc(traceMeta.trace_id||"")}</strong></div>
          <div class="wr-rd-card"><small>Capability</small><strong>${this._rdEsc(request.capability||"")}</strong></div>
          <div class="wr-rd-card"><small>Status</small><strong><span class="wr-rd-badge ${statusClass}">${this._rdEsc(decision.status||"")}</span> ${this._rdEsc(decision.code||decision.reason_code||"")}</strong></div>
          <div class="wr-rd-card"><small>Provider</small><strong>${this._rdEsc(decision.selected_provider||"—")}</strong></div>
          <div class="wr-rd-card"><small>Context</small><strong>${this._rdEsc(request.context_type||"—")}</strong></div>
          <div class="wr-rd-card"><small>Dauer</small><strong>${trace.performance?.total_ms??"—"} ms</strong></div>
        </div>
        ${this._rdFold("A · Anfrage",`${request.family||"—"} · ${(request.phenomena||[]).join(", ")||"—"}`,`<pre class="wr-rd-pre">${this._rdJson(request)}</pre>`)}
        ${this._rdFold("B · Räumlicher Kontext",context.routing_uses||"",`<pre class="wr-rd-pre">${this._rdJson(context)}</pre>`,!compactMobile)}
        ${this._rdFold("C · Zeitlicher Kontext",request.time_mode||"latest",`<pre class="wr-rd-pre">${this._rdJson({time_mode:request.time_mode,timeline:trace.timeline})}</pre>`)}
        ${this._rdFold("D · Consumer-Profil / Policy",trace.profile?.id||"normale API",`<pre class="wr-rd-pre">${this._rdJson({profile:trace.profile,policy:trace.policy})}</pre>`)}
        ${this._rdFold("E · Kandidatenmatrix",`${trace.candidates?.length||0} Kandidaten`,this._rdCandidateTable(trace),true)}
        ${this._rdFold("F · Coverage",`${coverage.length} Prüfungen`,`<pre class="wr-rd-pre">${this._rdJson(coverage)}</pre>`,!compactMobile)}
        ${this._rdFold("G · Providerentscheidung",decision.reason_code||decision.code||"",`<pre class="wr-rd-pre">${this._rdJson(decision)}</pre>`)}
        ${this._rdFold("H · Ressourcenbeschreibung",trace.resource?.type||"—",`<pre class="wr-rd-pre">${this._rdJson(trace.resource)}</pre>`)}
        ${this._rdFold("I · Timeline / Frames",trace.timeline?.frame_count!=null?`${trace.timeline.frame_count} Frames`:"keine Timeline",`<pre class="wr-rd-pre">${this._rdJson(trace.timeline)}</pre>`)}
        ${this._rdFold("J · Freshness",trace.freshness?.age_seconds!=null?`${Number(trace.freshness.age_seconds).toFixed(1)} s`:"—",`<pre class="wr-rd-pre">${this._rdJson(trace.freshness)}</pre>`)}
        ${this._rdFold("K · Netzwerk",trace.network?.instrumentation||"",`<pre class="wr-rd-pre">${this._rdJson(trace.network)}</pre>`)}
        ${this._rdFold("L · Cache",`${trace.cache?.entries?.length||0} Einträge`,`<pre class="wr-rd-pre">${this._rdJson(trace.cache)}</pre>`)}
        ${this._rdFold("M · Performance",`${trace.performance?.total_ms??"—"} ms`,`<pre class="wr-rd-pre">${this._rdJson(trace.performance)}</pre>`)}
        ${this._rdFold("N · Fehler / Fallback",`${trace.errors?.length||0} Fehler · ${decision.fallback_count||0} Fallbacks`,`<pre class="wr-rd-pre">${this._rdJson(trace.errors)}</pre>`)}
        ${this._rdFold("O · Letzte Entscheidungen",`${state.index.length}/${ROUTING_DIAGNOSTIC_LIMIT}`,`<pre class="wr-rd-pre">${this._rdJson(state.index)}</pre>`)}
        ${this._rdFold("P · Rohdaten",ROUTING_DIAGNOSTIC_SCHEMA,`<pre class="wr-rd-pre">${this._rdJson(trace)}</pre>`)}
        ${this._rdFold("Q · Export","Text · JSON · CSV · Git",`
          <div class="wr-rd-actions">
            <button id="wr-rd-copy-compact" ${state.exportBusy?"disabled":""}>Diagnose kopieren</button>
            <button id="wr-rd-copy-json" ${state.exportBusy?"disabled":""}>JSON kopieren</button>
            <button id="wr-rd-download-json" ${state.exportBusy?"disabled":""}>Routingreport herunterladen</button>
            <button id="wr-rd-download-csv" ${state.exportBusy?"disabled":""}>Kandidaten CSV</button>
            <button id="wr-rd-git" ${state.exportBusy?"disabled":""}>Nach Git übertragen</button>
          </div>
          <div id="wr-rd-export-status" class="wr-rd-export-status ${this._rdEsc(state.exportKind||"muted")}">${this._rdEsc(state.exportMessage||"")}</div>
          <a id="wr-rd-git-link" class="wr-rd-export-link" href="${this._rdEsc(state.gitExportResult?.file_url||"#")}" target="_blank" rel="noopener" ${state.gitExportResult?.file_url?"":"hidden"}>Letzten Git-Export öffnen</a>
        `)}
      `:'<div class="wr-rd-card">Noch kein Consumer-Resolve im Ringpuffer. Verwende die Testanfrage oder öffne Gewitterradar und löse eine WeatherRouter-Capability auf.</div>'}

      ${this._rdFold("Vergleichsmodus","zwei Routingentscheidungen gegenüberstellen",`
        <div class="wr-rd-compare-grid"><label>A<select id="wr-rd-compare-a">${this._rdTraceOptions(state.compareA)}</select></label><label>B<select id="wr-rd-compare-b">${this._rdTraceOptions(state.compareB)}</select></label><button id="wr-rd-compare" type="button">Vergleichen</button></div>
        ${state.compareResult?`<pre class="wr-rd-pre">${this._rdJson(state.compareResult)}</pre>`:""}
      `)}
    `;

    body.querySelector("#wr-rd-trace")?.addEventListener("change",e=>void this._rdLoadTrace(e.target.value));
    body.querySelector("#wr-rd-refresh")?.addEventListener("click",()=>void this._rdRefresh(false));
    body.querySelector("#wr-rd-live")?.addEventListener("change",e=>void this._rdSetLive(e.target.checked));
    body.querySelector("#wr-rd-clear")?.addEventListener("click",()=>void this._rdClear());
    body.querySelector("#wr-rd-create-p0060-profiles")?.addEventListener("click",()=>void this._rdEnsureP0060Profiles());
    body.querySelector("#wr-rd-p0070-fault")?.addEventListener("change",e=>{state.manual.faultMode=e.target.value;});
    body.querySelector("#wr-rd-run-p0070-fault")?.addEventListener("click",()=>void this._rdRunP0070FaultTest());
    body.querySelector("#wr-rd-capability-filter")?.addEventListener("input",()=>this._rdApplyCapabilityFilter());
    body.querySelector("#wr-rd-capability")?.addEventListener("change",e=>{state.manual.capability=e.target.value;});
    body.querySelector("#wr-rd-context-type")?.addEventListener("change",()=>this._rdRenderManualContext());
    body.querySelector("#wr-rd-preset")?.addEventListener("change",e=>this._rdPreset(e.target.value));
    body.querySelector("#wr-rd-trace-context")?.addEventListener("click",()=>this._rdUseTraceContext());
    body.querySelector("#wr-rd-map")?.addEventListener("click",()=>this._rdCurrentMap());
    body.querySelector("#wr-rd-resolve")?.addEventListener("click",()=>void this._rdResolve());
    body.querySelector("#wr-rd-copy-compact")?.addEventListener("click",()=>void this._rdCopy(true));
    body.querySelector("#wr-rd-copy-json")?.addEventListener("click",()=>void this._rdCopy(false));
    body.querySelector("#wr-rd-download-json")?.addEventListener("click",()=>this._rdDownload("json"));
    body.querySelector("#wr-rd-download-csv")?.addEventListener("click",()=>this._rdDownload("csv"));
    body.querySelector("#wr-rd-git")?.addEventListener("click",()=>void this._rdGitExport());
    body.querySelector("#wr-rd-compare-a")?.addEventListener("change",e=>{state.compareA=e.target.value;});
    body.querySelector("#wr-rd-compare-b")?.addEventListener("change",e=>{state.compareB=e.target.value;});
    body.querySelector("#wr-rd-compare")?.addEventListener("click",()=>void this._rdCompare());
    this._rdRenderManualContext(state.manual.context);
    this._rdApplyCapabilityFilter();
    this._rdUpdateHeaderActions();
    this._rdOrganizeDiagnosticHub();
  };

  proto._renderShell = function(...args) {
    const result=previousRenderShell?.apply(this,args);
    this._rdInstall();
    return result;
  };

  proto.disconnectedCallback = function(...args) {
    const state=this._rdState();
    clearTimeout(state.liveRefreshTimer);
    if(typeof state.liveUnsub==="function"){try{state.liveUnsub();}catch(_e){}}
    state.liveUnsub=null;state.live=false;
    return previousDisconnectedCallback?.apply(this,args);
  };

}
