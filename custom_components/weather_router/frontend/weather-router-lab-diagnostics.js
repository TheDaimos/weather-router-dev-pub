const LAB_ELEMENT = "weather-router-lab";
const SINGLE_DIAGNOSTIC_SCHEMA = "weather_router.provider_diagnostics.v1";
const ALL_DIAGNOSTIC_SCHEMA = "weather_router.all_provider_diagnostics.v1";

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Diagnosemodul registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterProviderDiagnosticsEnhanced) {
  proto.__weatherRouterProviderDiagnosticsEnhanced = true;

  const originalRenderShell = proto._renderShell;
  const originalRenderWeatherLayers = proto._renderWeatherLayers;

  // The checkbox is a view of the persisted server-side Config Entry, not a local switch.
  proto._operaPreviewSyncState = async function() {
    const toggle = this.shadowRoot?.getElementById("opera-preview-enabled");
    if (!toggle || this._operaPreviewUpdating || this._operaPreviewSyncRunning) return;
    if (this._operaPreviewSyncedToggle === toggle &&
        Date.now() - (this._operaPreviewLastSync || 0) < 1500) return;
    if (typeof this._hass?.callWS !== "function") {
      toggle.disabled = true;
      return; // retry on the next HA render; never display an assumed false state
    }
    this._operaPreviewSyncRunning = true;
    const generation = this._operaPreviewGeneration || 0;
    toggle.disabled = true;
    try {
      const state = await this._hass.callWS({
        type: "weather_router/opera/preview_control",
        acknowledgement: "UNVERIFIED_DEV_VM109"
      });
      if (generation === (this._operaPreviewGeneration || 0) &&
          this.shadowRoot?.getElementById("opera-preview-enabled") === toggle) {
        toggle.checked = state?.preview_enabled === true;
        // Never overwrite a value being edited. HA re-renders may run while
        // a mobile number keyboard / native select is open.
        const ageInput = this.shadowRoot?.getElementById("opera-preview-max-age");
        const staleInput = this.shadowRoot?.getElementById("opera-preview-stale-after");
        const serveSelect = this.shadowRoot?.getElementById("opera-preview-serve-stale");
        if (!this._operaPreviewAgeUpdating && !this._operaPreviewDirty) {
          if (ageInput) ageInput.value = String(state?.max_age_seconds ?? 1500);
          if (staleInput) staleInput.value = String(state?.stale_after_seconds ?? 1500);
          if (serveSelect) serveSelect.value = state?.serve_stale === true ? "yes" : "no";
        }
        for (const control of [ageInput, staleInput, serveSelect]) {
          if (control) control.disabled = false;
        }
        this._operaPreviewLastSync = Date.now();
        this._operaPreviewSyncedToggle = toggle;
      }
    } catch (error) {
      this._diagnosticSetStatus("OPERA-Freigabe konnte nicht gelesen werden: " +
        (error?.message || String(error)), "error");
    } finally {
      this._operaPreviewSyncRunning = false;
      if (!this._operaPreviewUpdating &&
          this.shadowRoot?.getElementById("opera-preview-enabled") === toggle)
        toggle.disabled = false;
    }
  };

  proto._diagnosticInstallUI = function() {
    const root = this.shadowRoot;
    const sidebar = root?.querySelector(".sidebar");
    if (!root || !sidebar) return;

    if (!root.getElementById("provider-diagnostics-style")) {
      const style = document.createElement("style");
      style.id = "provider-diagnostics-style";
      style.textContent = `
        .wr-diagnostic-launch-wrap {
          display:flex;
          gap:8px;
          margin:0 0 12px;
        }
        .wr-diagnostic-launch {
          width:100%;
          min-height:38px;
          font-weight:750;
          border-color:color-mix(in srgb,var(--primary-color,#03a9f4) 55%,var(--divider-color,#555));
          background:color-mix(in srgb,var(--primary-color,#03a9f4) 14%,var(--secondary-background-color,#282828));
        }
        .wr-diagnostic-window[hidden] { display:none !important; }
        .wr-diagnostic-window {
          position:fixed;
          inset:6vh auto auto 50%;
          transform:translateX(-50%);
          z-index:10000;
          width:min(920px,calc(100vw - 28px));
          max-height:88vh;
          display:flex;
          flex-direction:column;
          border:1px solid color-mix(in srgb,var(--primary-color,#03a9f4) 45%,var(--divider-color,#555));
          border-radius:16px;
          background:var(--card-background-color,#1c1c1c);
          color:var(--primary-text-color,#eee);
          box-shadow:0 18px 65px rgba(0,0,0,.58);
          overflow:hidden;
        }
        .wr-diagnostic-head {
          display:flex;
          align-items:center;
          gap:12px;
          justify-content:space-between;
          padding:13px 15px;
          border-bottom:1px solid var(--divider-color,#444);
          background:color-mix(in srgb,var(--secondary-background-color,#282828) 88%,transparent);
        }
        .wr-diagnostic-head strong { font-size:16px; }
        .wr-diagnostic-head small { display:block; margin-top:2px; opacity:.6; }
        .wr-diagnostic-close {
          min-width:38px;
          min-height:34px;
          padding:5px 10px;
          font-size:18px;
        }
        .wr-diagnostic-body {
          overflow:auto;
          padding:14px;
        }
        .wr-diagnostic-all {
          padding:12px;
          margin-bottom:14px;
          border:1px solid color-mix(in srgb,var(--primary-color,#03a9f4) 38%,var(--divider-color,#555));
          border-radius:12px;
          background:color-mix(in srgb,var(--primary-color,#03a9f4) 8%,transparent);
        }
        .wr-diagnostic-all h3,
        .wr-diagnostic-single h3 {
          margin:0 0 6px;
          font-size:14px;
        }
        .wr-diagnostic-all p,
        .wr-diagnostic-single p {
          margin:0 0 10px;
          font-size:11px;
          line-height:1.45;
          opacity:.68;
        }
        .wr-diagnostic-single {
          padding:12px;
          border:1px solid var(--divider-color,#444);
          border-radius:12px;
        }
        .wr-diagnostic-grid {
          display:grid;
          grid-template-columns:minmax(180px,1fr) minmax(220px,1.4fr);
          gap:9px;
        }
        .wr-diagnostic-actions {
          display:flex;
          gap:8px;
          flex-wrap:wrap;
          margin-top:10px;
        }
        .wr-diagnostic-actions button { min-height:36px; }
        .wr-diagnostic-actions .primary { min-width:180px; }
        .wr-diagnostic-status {
          margin-top:11px;
          font-size:12px;
          line-height:1.4;
        }
        .wr-diagnostic-progress[hidden] { display:none !important; }
        .wr-diagnostic-progress {
          margin-top:10px;
          padding:10px;
          border:1px solid color-mix(in srgb,var(--primary-color,#03a9f4) 36%,var(--divider-color,#555));
          border-radius:10px;
          background:color-mix(in srgb,var(--primary-color,#03a9f4) 7%,transparent);
        }
        .wr-diagnostic-progress-row {
          display:flex;
          align-items:center;
          gap:10px;
        }
        .wr-diagnostic-spinner {
          width:22px;
          height:22px;
          flex:0 0 22px;
          border:3px solid color-mix(in srgb,var(--primary-color,#03a9f4) 20%,transparent);
          border-top-color:var(--primary-color,#03a9f4);
          border-radius:50%;
          animation:wr-diagnostic-spin .85s linear infinite;
        }
        .wr-diagnostic-progress-text {
          min-width:0;
          flex:1 1 auto;
        }
        .wr-diagnostic-progress-text strong {
          display:block;
          font-size:12px;
        }
        .wr-diagnostic-progress-text small {
          display:block;
          margin-top:2px;
          font-size:10px;
          opacity:.65;
          overflow:hidden;
          text-overflow:ellipsis;
          white-space:nowrap;
        }
        .wr-diagnostic-progress-track {
          height:6px;
          margin-top:9px;
          overflow:hidden;
          border-radius:999px;
          background:color-mix(in srgb,var(--divider-color,#555) 65%,transparent);
        }
        .wr-diagnostic-progress-bar {
          width:0%;
          height:100%;
          border-radius:inherit;
          background:var(--primary-color,#03a9f4);
          transition:width .22s ease;
        }
        @keyframes wr-diagnostic-spin {
          to { transform:rotate(360deg); }
        }
        .wr-diagnostic-output {
          display:none;
          max-height:42vh;
          margin-top:11px;
          white-space:pre;
          overflow:auto;
        }
        @media(max-width:650px) {
          .wr-diagnostic-window {
            inset:10px 8px 10px 8px;
            transform:none;
            width:auto;
            max-height:none;
          }
          .wr-diagnostic-grid { grid-template-columns:1fr; }
          .wr-diagnostic-actions .primary { width:100%; }
        }
      `;
      root.appendChild(style);
    }

    if (!root.getElementById("provider-diagnostics-launch")) {
      const launchWrap = document.createElement("div");
      launchWrap.className = "wr-diagnostic-launch-wrap";
      launchWrap.id = "provider-diagnostics-launch";
      launchWrap.innerHTML = `
        <button class="wr-diagnostic-launch" type="button">🩺 Provider-Diagnose öffnen</button>
      `;
      const hero = root.getElementById("weather-router-brand-hero");
      if (hero?.nextSibling) {
        sidebar.insertBefore(launchWrap, hero.nextSibling);
      } else if (hero) {
        hero.after(launchWrap);
      } else {
        sidebar.prepend(launchWrap);
      }
      launchWrap.querySelector("button").addEventListener("click", () => {
        this._diagnosticOpen();
      });
    }

    if (!root.getElementById("opera-science-preflight")) {
      const button = document.createElement("button");
      button.id = "opera-science-preflight";
      button.type = "button";
      button.textContent = "🔬 OPERA · Wissenschaftliche Vorprüfung";
      button.style.cssText = "width:100%;min-height:38px;margin:0 0 12px";
      const providerLaunch = root.getElementById("provider-diagnostics-launch");
      if (providerLaunch) providerLaunch.after(button);
      else sidebar.prepend(button);
      button.addEventListener("click", async () => {
        if (!this._hass || button.disabled) return;
        button.disabled = true;
        button.textContent = "🔬 OPERA-Prüfung läuft …";
        try {
          const report = await this._hass.callWS({
            type: "weather_router/opera/scientific_selfcheck"
          });
          this._diagnosticOpen();
          this._diagnosticStoreReport(report, "scientific");
          this._diagnosticSetStatus(
            report?.status === "preflight_passed"
              ? "OPERA-Vorprüfung bestanden · Wissenschaftliche Bildfreigabe weiterhin gesperrt."
              : "OPERA-Vorprüfung fehlgeschlagen · Einzelheiten im JSON.",
            report?.status === "preflight_passed" ? "ok" : "error"
          );
        } catch (error) {
          this._diagnosticOpen();
          this._diagnosticStoreReport({
            schema: "weather_router.opera.scientific_selfcheck.v1",
            status: "request_failed",
            code: typeof error?.code === "string" ? error.code.slice(0, 60) : "unknown",
            scientific_raster_approved: false
          }, "scientific");
          this._diagnosticSetStatus("OPERA-Vorprüfung nicht ausführbar.", "error");
        } finally {
          button.disabled = false;
          button.textContent = "🔬 OPERA · Wissenschaftliche Vorprüfung";
        }
      });
    }

    if (!root.getElementById("opera-science-functiontests")) {
      const wrap = document.createElement("div");
      wrap.id = "opera-science-functiontests";
      wrap.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px";
      const picker = document.createElement("select");
      picker.setAttribute("aria-label", "OPERA-Prüfbereich");
      picker.style.cssText = "flex:1 1 155px;min-height:42px;max-width:100%";
      [["all", "Alle Bereiche"], ["decoder", "Decoder"], ["geometry", "Geografie"],
       ["security", "Sicherheit / V2"]].forEach(([value, label]) => {
        const option = document.createElement("option");
        option.value = value; option.textContent = label; picker.appendChild(option);
      });
      const button = document.createElement("button");
      button.id = "opera-functiontests-start";
      button.type = "button";
      button.textContent = "🔬 Funktionstests starten";
      button.style.cssText = "flex:1 1 185px;min-height:42px";
      const jsonExport = document.createElement("button");
      jsonExport.id = "opera-science-json-export";
      jsonExport.type = "button";
      jsonExport.textContent = "JSON exportieren";
      const gitExport = document.createElement("button");
      gitExport.id = "opera-science-git-export";
      gitExport.type = "button";
      gitExport.textContent = "Export2Git";
      for (const action of [jsonExport, gitExport]) {
        action.style.cssText = "flex:1 1 135px;min-height:42px";
        action.disabled = true;
      }
      const mark = (action) => {
        action.style.background = "var(--success-color, #2e7d32)";
        action.style.color = "#fff";
        action.style.borderColor = "var(--success-color, #2e7d32)";
      };
      this._operaScienceMarkExport = mark;
      jsonExport.addEventListener("click", () => {
        if (this._diagnosticLastMode !== "scientific") return;
        this._diagnosticDownload();
      });
      gitExport.addEventListener("click", () => {
        if (this._diagnosticLastMode !== "scientific") return;
        this._diagnosticGitExport();
      });
      wrap.append(picker, button, jsonExport, gitExport);
      (root.getElementById("opera-science-preflight") ||
       root.getElementById("provider-diagnostics-launch"))?.after(wrap);
      button.addEventListener("click", async () => {
        if (!this._hass || button.disabled) return;
        button.disabled = true; picker.disabled = true;
        button.textContent = "Prüfung läuft …";
        try {
          const report = await this._hass.callWS({
            type: "weather_router/opera/functiontests", suite: picker.value
          });
          this._diagnosticOpen();
          this._diagnosticStoreReport(report, "scientific");
          this._diagnosticSetStatus(
            report?.status === "passed"
              ? "Synthetische Funktionstests bestanden · Wissenschaftliche Bildfreigabe weiterhin gesperrt."
              : "OPERA-Funktionstests nicht bestanden · Einzelheiten im JSON.",
            report?.status === "passed" ? "ok" : "error"
          );
        } catch (error) {
          this._diagnosticOpen();
          this._diagnosticStoreReport({
            schema: "weather_router.opera.functiontests.v1",
            status: "request_failed",
            code: typeof error?.code === "string" ? error.code.slice(0, 60) : "unknown",
            scientific_raster_approved: false, dra_candidate_approved: false
          }, "scientific");
          this._diagnosticSetStatus("OPERA-Funktionstests nicht ausführbar.", "error");
        } finally {
          picker.disabled = false; button.disabled = false;
          button.textContent = "🔬 Funktionstests starten";
        }
      });
    }

    if (!root.getElementById("opera-preview-controls")) {
      const box = document.createElement("section");
      box.id = "opera-preview-controls";
      box.style.cssText = "display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px;align-items:center";
      const caption = document.createElement("strong");
      caption.textContent = "OPERA · UNVERIFIED / ENTWICKLUNGSVORSCHAU (nur VM 109)";
      caption.style.cssText = "flex:1 1 100%;font-size:12px";
      const label = document.createElement("label");
      label.style.cssText = "display:flex;align-items:center;gap:10px;min-height:44px;cursor:pointer";
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.id = "opera-preview-enabled";
      toggle.style.cssText = "width:22px;height:22px;accent-color:var(--warning-color,#b46a00)";
      const text = document.createElement("span");
      text.textContent = "Experimentelle OPERA-Darstellung aktivieren";
      label.append(toggle, text);
      box.append(caption, label);
      const ageLabel = document.createElement("label");
      ageLabel.textContent = "Gültigkeitsdauer der OPERA-Vorschau (Sekunden): ";
      ageLabel.style.cssText = "font-size:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap";
      const ageInput = document.createElement("input");
      ageInput.type = "number";
      ageInput.id = "opera-preview-max-age";
      ageInput.min = "900";
      ageInput.max = "3600";
      ageInput.step = "1";
      ageInput.value = "1500";
      ageInput.disabled = false;
      ageInput.style.cssText = "width:90px;min-height:36px";
      ageLabel.append(ageInput);
      const ageHelp = document.createElement("small");
      ageHelp.textContent = "Empfehlung: 1.500 Sekunden – ca. 10 Minuten Bereitstellungsverzögerung durch OPERA + 15 Minuten Radarzyklus. Individuell anpassbar (900–3.600 Sekunden). Nur Entwicklungsvorschau; keine wissenschaftliche Freigabe.";
      ageHelp.style.cssText = "flex:1 1 100%;opacity:.8";
      box.append(ageLabel, ageHelp);
      const staleLabel = document.createElement("label");
      staleLabel.textContent = "Als veraltet kennzeichnen ab (Sekunden): ";
      const staleInput = document.createElement("input");
      staleInput.type = "number";
      staleInput.id = "opera-preview-stale-after";
      staleInput.min = "900";
      staleInput.max = "3600";
      staleInput.step = "1";
      staleInput.value = "1500";
      staleInput.disabled = false;
      staleInput.style.cssText = "width:90px;min-height:36px";
      staleLabel.append(staleInput);
      const serveLabel = document.createElement("label");
      serveLabel.textContent = "Veraltete Daten weiterhin bereitstellen: ";
      const serveSelect = document.createElement("select");
      serveSelect.id = "opera-preview-serve-stale";
      serveSelect.disabled = false;
      for (const [value, label] of [["no", "Nein"], ["yes", "Ja"]]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        serveSelect.append(option);
      }
      serveLabel.append(serveSelect);
      const staleHelp = document.createElement("small");
      staleHelp.textContent = "Bei Ja: als veraltet gekennzeichnete Entwicklungsvorschau, maximal 3.600 Sekunden seit Messzeitpunkt. Keine aktuellen Messwerte, kein Warnbetrieb.";
      staleHelp.style.cssText = "flex:1 1 100%;opacity:.8";
      box.append(staleLabel, serveLabel, staleHelp);
      // Edit locally and save the three values together on explicit action.
      // No "change" events that compete with server refresh on mobile.
      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.id = "opera-preview-save-settings";
      saveButton.textContent = "OPERA-Einstellungen speichern";
      saveButton.style.cssText = "min-height:44px;padding:8px 16px;flex:1 1 100%";
      box.append(saveButton);
      const markDirty = () => { this._operaPreviewDirty = true; };
      for (const field of [ageInput, staleInput, serveSelect]) {
        field.addEventListener("input", markDirty);
        field.addEventListener("change", markDirty);
      }
      saveButton.addEventListener("click", async () => {
        const age = Number(ageInput.value);
        const stale = Number(staleInput.value);
        const serve = serveSelect.value === "yes";
        if (![age, stale].every(v => Number.isInteger(v) && v >= 900 && v <= 3600)) {
          this._diagnosticSetStatus("OPERA-Zeitwerte: jeweils 900–3600 Sekunden.", "error");
          return;
        }
        if (!this._hass?.callWS) {
          this._diagnosticSetStatus("Home Assistant ist noch nicht verbunden.", "error");
          return;
        }
        this._operaPreviewAgeUpdating = true;
        saveButton.disabled = true;
        saveButton.textContent = "Speichern …";
        try {
          const reply = await this._hass.callWS({
            type: "weather_router/opera/preview_control",
            max_age_seconds: age,
            stale_after_seconds: stale,
            serve_stale: serve,
            acknowledgement: "UNVERIFIED_DEV_VM109"
          });
          if (reply?.max_age_seconds !== age ||
              reply?.stale_after_seconds !== stale ||
              reply?.serve_stale !== serve) throw new Error("Server hat Werte nicht bestätigt");
          this._operaPreviewDirty = false;
          this._diagnosticSetStatus("OPERA-Einstellungen gespeichert.", "ok");
        } catch (error) {
          // Keep values in the fields for correction or retry.
          this._diagnosticSetStatus("OPERA-Speicherung fehlgeschlagen: " +
            (error?.message || String(error)), "error");
        } finally {
          this._operaPreviewAgeUpdating = false;
          saveButton.disabled = false;
          saveButton.textContent = "OPERA-Einstellungen speichern";
          if (!this._operaPreviewDirty) {
            this._operaPreviewLastSync = 0;
            this._operaPreviewSyncState();
          }
        }
      });
      toggle.disabled = true;
      root.querySelector('[data-lab-menu-key="opera"] > .lab-menu-content')?.prepend(box);
      toggle.addEventListener("change", async () => {
        const enabled = toggle.checked;
        this._operaPreviewGeneration = (this._operaPreviewGeneration || 0) + 1;
        this._operaPreviewUpdating = true;
        if (!this._hass) { toggle.checked = !enabled; this._operaPreviewUpdating = false; return; }
        if (enabled && !window.confirm(
            "Nur auf HA DEV VM 109: Diese OPERA-Darstellung ist wissenschaftlich ungeprüft und darf nicht für Warnungen verwendet werden. Aktivieren?")) {
          toggle.checked = false;
          this._operaPreviewUpdating = false;
          return;
        }
        toggle.disabled = true;
        try {
          const result = await this._hass.callWS({
            type: "weather_router/opera/preview_control",
            enabled,
            acknowledgement: "UNVERIFIED_DEV_VM109"
          });
          if (result?.preview_enabled !== enabled) throw new Error("Umschaltung nicht bestätigt");
          this._diagnosticSetStatus(enabled ?
            "Experimentelle OPERA-Darstellung aktiviert · reguläre Freigabe gesperrt." :
            "Experimentelle OPERA-Darstellung deaktiviert.", "ok");
        } catch (error) {
          toggle.checked = !enabled;
          this._diagnosticSetStatus("OPERA-Vorschau konnte nicht umgeschaltet werden: " +
            (error?.message || String(error)), "error");
        } finally {
          this._operaPreviewUpdating = false;
          this._operaPreviewLastSync = 0;
          toggle.disabled = false;
        }
      });
    }
    this._operaPreviewSyncState();

    if (!root.getElementById("provider-diagnostics-window")) {
      const panel = document.createElement("section");
      panel.className = "wr-diagnostic-window";
      panel.id = "provider-diagnostics-window";
      panel.hidden = true;
      panel.innerHTML = `
        <div class="wr-diagnostic-head">
          <div>
            <strong>WeatherRouter · Provider-Diagnose</strong>
            <small>One-shot · admin-only · redigiertes JSON · keine Hintergrunddiagnose</small>
          </div>
          <button class="wr-diagnostic-close" id="diagnostic-close" title="Schließen" type="button">×</button>
        </div>
        <div class="wr-diagnostic-body">
          <section class="wr-diagnostic-all">
            <h3>Alle Provider auf einmal</h3>
            <p>
              Prüft alle aktuell aktivierten Provider in einem Lauf. Deaktivierte Provider und
              Fachbereiche werden bewusst ohne Netzwerkzugriff als übersprungen protokolliert.
              Punktprovider nutzen den WeatherRouter-Bezugsstandort intern, ohne dessen Koordinaten
              in den Export zu schreiben. Das Ergebnis ist eine einzige strukturierte JSON-Datei.
            </p>
            <label for="diagnostic-domain-filter">Fachbereich</label>
            <select id="diagnostic-domain-filter">
              <option value="">Alle Fachbereiche</option>
              <option value="weather">Wetter</option>
              <option value="pollen">Pollen</option>
              <option value="natural_hazards">Naturgefahren</option>
              <option value="civil_protection">Bevölkerungsschutz</option>
              <option value="security">Öffentliche Sicherheit</option>
              <option value="aviation">Luftfahrtwarnungen</option>
              <option value="space">Sonne &amp; Weltraum</option>
              <option value="biological_hazards">Biologische Gefahren</option>
            </select>
            <label for="diagnostic-result-filter">Angezeigte Ergebnisse</label>
            <select id="diagnostic-result-filter">
              <option value="">Alle Ergebnisse</option>
              <option value="failed">Nur Fehler</option>
              <option value="skipped">Nur übersprungen</option>
              <option value="success">Nur erfolgreich</option>
            </select>
            <button id="diagnostic-run-all" class="primary" type="button">Alle Provider prüfen</button>
            <button id="diagnostic-center-snapshot" type="button">Systemzustand · Schnellprüfung</button>
            <label><input type="checkbox" id="diagnostic-deep-system" checked> Systemzustand im Gesamtexport erfassen</label>
            <label><input type="checkbox" id="diagnostic-native-probe"> Native Bibliotheken bei Tiefenprüfung ausdrücklich importieren (bis 8 s)</label>
            <label><input id="diagnostic-technical-details" type="checkbox" checked> Technische Einzelheiten anzeigen</label>
            <button id="diagnostic-compare" type="button">Mit vorherigem Ergebnis vergleichen</button>
            <button id="diagnostic-cancel" type="button" disabled>Prüfung abbrechen</button>
            <small>Lesende Core-Prüfung ohne Provider-Netzwerkaufrufe; Einzel-/Gesamttests bleiben separat verfügbar.</small>
          </section>

          <section class="wr-diagnostic-single">
            <h3>Einzeltest</h3>
            <p>Für gezielte Nachtests eines Providers oder einer konkreten Capability.</p>
            <div class="wr-diagnostic-grid">
              <div>
                <label for="diagnostic-provider">Provider</label>
                <select id="diagnostic-provider"><option value="">Lade Provider …</option></select>
              </div>
              <div>
                <label for="diagnostic-capability">Umfang</label>
                <select id="diagnostic-capability">
                  <option value="">Gesamter Provider</option>
                </select>
              </div>
            </div>
            <div class="wr-diagnostic-actions">
              <button id="diagnostic-run-single" class="primary" type="button">Ausgewählten Provider prüfen</button>
              <button id="diagnostic-copy" type="button" disabled>JSON kopieren</button>
              <button id="diagnostic-download" type="button" disabled>JSON teilen / speichern</button>
              <button id="diagnostic-git" type="button" disabled>Nach Git übertragen</button>
            </div>
          </section>

          <div id="diagnostic-status" class="wr-diagnostic-status muted">
            Noch keine Diagnose ausgeführt.
          </div>
          <div id="diagnostic-progress" class="wr-diagnostic-progress" hidden>
            <div class="wr-diagnostic-progress-row">
              <div class="wr-diagnostic-spinner" aria-hidden="true"></div>
              <div class="wr-diagnostic-progress-text">
                <strong id="diagnostic-progress-title">Provider 0/0</strong>
                <small id="diagnostic-progress-provider">Vorbereitung …</small>
              </div>
            </div>
            <div class="wr-diagnostic-progress-track" aria-hidden="true">
              <div id="diagnostic-progress-bar" class="wr-diagnostic-progress-bar"></div>
            </div>
          </div>
          <div id="diagnostic-summary-panel" role="status" aria-live="polite" style="margin:8px 0;font-size:12px;line-height:1.5"></div>
          <details id="diagnostic-timeline-details" style="margin:10px 0">
            <summary>Zeitlicher Diagnoseablauf (UTC)</summary>
            <label for="diagnostic-timeline-filter">Ablauf filtern</label>
            <select id="diagnostic-timeline-filter">
              <option value="">Alle Stationen</option>
              <option value="failure">Fehler</option>
              <option value="success">Erfolge</option>
              <option value="unavailable">Nicht verfügbar</option>
              <option value="recovered">Wiederherstellung</option>
            </select>
            <pre id="diagnostic-timeline" class="wr-diagnostic-output">Noch kein Ablauf vorhanden.</pre>
          </details>
          <pre id="diagnostic-output" class="wr-diagnostic-output">—</pre>
        </div>
      `;
      root.appendChild(panel);

      root.getElementById("diagnostic-close").addEventListener("click", () => {
        this._diagnosticClose();
      });
      root.getElementById("diagnostic-technical-details").addEventListener("change", () => {
        this._diagnosticStoreReport(this._diagnosticLastReport,this._diagnosticLastMode);
      });
      root.getElementById("diagnostic-cancel").addEventListener("click", () => {
        this._diagnosticCancelRequested = true;
        this._diagnosticSetStatus("Abbruch angefordert; laufender Provider-Aufruf endet regulär.");
      });
      root.getElementById("diagnostic-compare").addEventListener("click", () => {
        if (!this._diagnosticPreviousReport || !this._diagnosticLastReport) return;
        const before = new Map((this._diagnosticPreviousReport.providers||[])
          .map(p => [p.id || p.provider?.id, p.summary?.routing_skipped===true ? "übersprungen" : String(p.summary?.ok)]));
        const after = new Map((this._diagnosticLastReport.providers||[])
          .map(p => [p.id || p.provider?.id, p.summary?.routing_skipped===true ? "übersprungen" : String(p.summary?.ok)]));
        const changed = [];
        for (const [id,status] of after) {
          if (id && before.get(id) !== status) changed.push({provider:id,vorher:before.get(id)||"nicht vorhanden",aktuell:status});
        }
        for (const [id,status] of before) {
          if (id && !after.has(id)) changed.push({provider:id,vorher:status,aktuell:"nicht vorhanden"});
        }
        this._diagnosticLastComparison = {
          generated_at: new Date().toISOString(),
          changed:changed.slice(0,80), truncated:changed.length>80,
          previous_count:before.size,current_count:after.size
        };
        this._diagnosticSetStatus("Zustandsvergleich: "+changed.length+" geänderte Provider · "+before.size+" vorher · "+after.size+" aktuell.","ok");
        const view=this.shadowRoot?.getElementById("diagnostic-output");
        if(view) view.textContent=JSON.stringify(this._diagnosticLastComparison,null,2);
      });
      root.getElementById("diagnostic-center-snapshot").addEventListener("click", () => {
        this._diagnosticRunCenterSnapshot();
      });
      root.getElementById("diagnostic-run-all").addEventListener("click", () => {
        this._diagnosticRunAll();
      });
      root.getElementById("diagnostic-run-single").addEventListener("click", () => {
        this._diagnosticRunSingle();
      });
      root.getElementById("diagnostic-timeline-filter").addEventListener("change", () => {
        if (this._diagnosticLastReport) this._diagnosticStoreReport(this._diagnosticLastReport,this._diagnosticLastMode);
      });
      root.getElementById("diagnostic-result-filter").addEventListener("change", () => {
        if (this._diagnosticLastReport) this._diagnosticStoreReport(this._diagnosticLastReport,this._diagnosticLastMode);
      });
      root.getElementById("diagnostic-provider").addEventListener("change", event => {
        this._diagnosticProvider = event.target.value;
        this._diagnosticRefreshCapabilities();
      });
      root.getElementById("diagnostic-capability").addEventListener("change", event => {
        this._diagnosticCapability = event.target.value;
      });
      root.getElementById("diagnostic-copy").addEventListener("click", () => {
        this._diagnosticCopy();
      });
      root.getElementById("diagnostic-download").addEventListener("click", () => {
        this._diagnosticDownload();
      });
      root.getElementById("diagnostic-git").addEventListener("click", () => {
        this._diagnosticGitExport();
      });
    }

    this._diagnosticRefreshSelectors();
  };

  proto._diagnosticOpen = function() {
    const panel = this.shadowRoot?.getElementById("provider-diagnostics-window");
    if (!panel) return;
    panel.hidden = false;
    this._diagnosticRefreshSelectors();
  };

  proto._diagnosticClose = function() {
    const panel = this.shadowRoot?.getElementById("provider-diagnostics-window");
    if (panel) panel.hidden = true;
  };

  proto._diagnosticRefreshSelectors = function() {
    const providerSelect = this.shadowRoot?.getElementById("diagnostic-provider");
    if (!providerSelect) return;

    const providers = Array.isArray(this._providers) ? this._providers : [];
    const previous = this._diagnosticProvider || providerSelect.value;
    providerSelect.innerHTML = "";

    if (!providers.length) {
      providerSelect.add(new Option("Keine Provider verfügbar", ""));
      providerSelect.disabled = true;
      return;
    }

    const eligibleProviders = providers.filter(provider => provider.eligible !== false);
    providerSelect.disabled = !eligibleProviders.length;
    for (const provider of providers) {
      const suffix = provider.eligible === false ? " · deaktiviert" : "";
      const option = new Option(`${provider.name}${suffix}`, provider.id);
      option.disabled = provider.eligible === false;
      providerSelect.add(option);
    }

    const selected = eligibleProviders.some(item => item.id === previous)
      ? previous
      : eligibleProviders[0]?.id || "";
    providerSelect.value = selected;
    this._diagnosticProvider = selected;
    this._diagnosticRefreshCapabilities();
  };

  proto._diagnosticRefreshCapabilities = function() {
    const capabilitySelect = this.shadowRoot?.getElementById("diagnostic-capability");
    if (!capabilitySelect) return;

    const provider = (this._providers || []).find(
      item => item.id === this._diagnosticProvider
    );
    const previous = this._diagnosticCapability || capabilitySelect.value;
    capabilitySelect.innerHTML = "";

    const capabilities = provider?.capabilities || [];
    const eligibleCapabilities = capabilities.filter(
      capability => capability.eligible !== false
    );
    const wholeProviderAllowed = (
      Boolean(provider)
      && provider.eligible !== false
      && eligibleCapabilities.length === capabilities.length
    );
    const wholeOption = new Option(
      wholeProviderAllowed
        ? "Gesamter Provider · empfohlen"
        : "Gesamter Provider · Fachbereich teilweise deaktiviert",
      ""
    );
    wholeOption.disabled = !wholeProviderAllowed;
    capabilitySelect.add(wholeOption);

    for (const capability of eligibleCapabilities) {
      const suffix = capability.render_mode === "value"
        ? " · Punktwert"
        : capability.render_mode === "hazard_feed"
          ? " · Gefahrenfeed"
          : " · Kartenebene";
      capabilitySelect.add(
        new Option(`${capability.name}${suffix}`, capability.id)
      );
    }

    const previousOption = [...capabilitySelect.options].find(
      option => option.value === previous && !option.disabled
    );
    capabilitySelect.value = previousOption?.value
      ?? (wholeProviderAllowed ? "" : eligibleCapabilities[0]?.id || "");
    this._diagnosticCapability = capabilitySelect.value;
  };

  proto._diagnosticSetProgress = function(current, total, providerName, detail="") {
    const root = this.shadowRoot;
    const box = root?.getElementById("diagnostic-progress");
    const title = root?.getElementById("diagnostic-progress-title");
    const provider = root?.getElementById("diagnostic-progress-provider");
    const bar = root?.getElementById("diagnostic-progress-bar");
    if (!box || !title || !provider || !bar) return;

    const safeTotal = Math.max(1, Number(total) || 1);
    const safeCurrent = Math.max(0, Math.min(Number(current) || 0, safeTotal));
    box.hidden = false;
    title.textContent = `Provider ${safeCurrent}/${safeTotal}`;
    provider.textContent = [providerName, detail].filter(Boolean).join(" · ") || "Vorbereitung …";
    bar.style.width = `${Math.round((safeCurrent / safeTotal) * 100)}%`;
  };

  proto._diagnosticHideProgress = function() {
    const box = this.shadowRoot?.getElementById("diagnostic-progress");
    if (box) box.hidden = true;
  };

  proto._diagnosticAggregateReports = function(chunks) {
    const reports = [];
    let referenceContext = null;
    let apiVersion = 1;
    let generatedAt = new Date().toISOString();
    let routerEnabled = true;

    for (const chunk of chunks) {
      if (!chunk || typeof chunk !== "object") continue;
      if (Array.isArray(chunk.providers)) reports.push(...chunk.providers);
      if (chunk.reference_context) referenceContext = chunk.reference_context;
      if (chunk.api_version != null) apiVersion = chunk.api_version;
      if (chunk.generated_at) generatedAt = chunk.generated_at;
      if (chunk.summary?.router_enabled != null) {
        routerEnabled = Boolean(chunk.summary.router_enabled);
      }
    }

    const failed = reports.filter(item => item?.summary?.ok === false);
    const skipped = reports.filter(item => item?.summary?.routing_skipped === true);
    const tested = reports.filter(item => item?.summary?.routing_skipped !== true);
    const testsRun = reports.reduce(
      (sum, item) => sum + Number(item?.summary?.tests_run || 0),
      0
    );
    const testsFailed = reports.reduce(
      (sum, item) => sum + Number(item?.summary?.tests_failed || 0),
      0
    );
    const testsSkipped = reports.reduce(
      (sum, item) => sum + Number(item?.summary?.tests_skipped || 0),
      0
    );

    return {
      schema: ALL_DIAGNOSTIC_SCHEMA,
      generated_at: generatedAt,
      api_version: apiVersion,
      reference_context: referenceContext,
      providers: reports,
      summary: {
        ok: failed.length === 0,
        router_enabled: routerEnabled,
        provider_count: reports.length,
        providers_tested: tested.length,
        providers_skipped: skipped.length,
        providers_ok: tested.length - failed.length,
        providers_failed: failed.length,
        tests_run: testsRun,
        tests_failed: testsFailed,
        tests_skipped: testsSkipped,
      },
    };
  };

  proto._diagnosticTransportFailureReport = function(provider, error) {
    return {
      id: provider?.id || "unknown",
      name: provider?.name || provider?.id || "Unbekannter Provider",
      capabilities: provider?.capabilities || [],
      routing: {
        eligible: provider?.eligible !== false,
        disabled_reason: provider?.disabled_reason || null,
        domains: provider?.router_domains || [],
        enabled_by_user: provider?.enabled_by_user !== false,
      },
      info: provider?.info || null,
      network_targets: provider?.network_targets || [],
      provider_probe: null,
      tests: [
        {
          kind: "transport",
          ok: false,
          status: "websocket_error",
          exception: {
            type: error?.constructor?.name || "Error",
            message: error?.message || String(error),
            code: error?.code || null,
          },
        },
      ],
      summary: {
        ok: false,
        provider_probe_failed: false,
        tests_run: 1,
        tests_failed: 1,
        tests_skipped: 0,
        routing_skipped: false,
      },
    };
  };

  proto._diagnosticSetStatus = function(text, className = "muted") {
    const status = this.shadowRoot?.getElementById("diagnostic-status");
    if (!status) return;
    status.textContent = text;
    status.className = `wr-diagnostic-status ${className}`;
  };

  proto._diagnosticSetBusy = function(busy) {
    this._diagnosticLoading = busy;
    const cancel = this.shadowRoot?.getElementById("diagnostic-cancel");
    if (cancel) cancel.disabled = !busy;
    if (busy) this._diagnosticCancelRequested = false;
    for (const id of ["diagnostic-run-all", "diagnostic-run-single"]) {
      const button = this.shadowRoot?.getElementById(id);
      if (button) button.disabled = busy;
    }
  };


  proto._diagnosticRunCenterSnapshot = async function() {
    if (!this._hass || this._diagnosticLoading) return;
    this._diagnosticSetBusy(true);
    this._diagnosticSetStatus("Lese Systemzustand direkt aus Home Assistant Core …");
    try {
      const report = await this._hass.callWS({type:"weather_router/diagnostic_center/snapshot",deep:this.shadowRoot?.getElementById("diagnostic-native-probe")?.checked===true});
      if (report?.schema !== "weather_router.diagnostic_center.v1") throw new Error("Diagnosevertrag ungültig");
      this._diagnosticStoreReport(report,"system");
      this._diagnosticSetStatus("Systemprüfung abgeschlossen · Export ins private Archiv möglich.","ok");
    } catch (error) {
      this._diagnosticSetStatus("Systemprüfung fehlgeschlagen: " + String(error?.message || error).slice(0,160),"error");
    } finally {
      this._diagnosticSetBusy(false);
    }
  };

  proto._diagnosticStoreReport = function(report, mode) {
    if (this._diagnosticLastReport && this._diagnosticLastReport !== report)
      this._diagnosticPreviousReport = this._diagnosticLastReport;
    this._diagnosticLastReport = report;
    this._diagnosticLastMode = mode;
    for (const id of ["opera-science-json-export", "opera-science-git-export"]) {
      const action = this.shadowRoot?.getElementById(id);
      if (!action) continue;
      action.disabled = mode !== "scientific" || !report;
      action.style.background = "";
      action.style.color = "";
      action.style.borderColor = "";
    }
    const output = this.shadowRoot?.getElementById("diagnostic-output");
    const copyButton = this.shadowRoot?.getElementById("diagnostic-copy");
    const downloadButton = this.shadowRoot?.getElementById("diagnostic-download");
    const gitButton = this.shadowRoot?.getElementById("diagnostic-git");
    const summaryPanel = this.shadowRoot?.getElementById("diagnostic-summary-panel");
    if (summaryPanel) {
      const counts = report?.summary || {};
      const total = Array.isArray(report?.providers) ? report.providers.length : null;
      const warning = (report?.not_executed || []).length;
      const cancelled = report?.diagnostic_cancelled === true;
      summaryPanel.textContent = [
        "Version " + String(report?.version || this._wrVersion || "nicht gemeldet"),
        total === null ? "Systemprüfung" : ("Provider " + total),
        counts.providers_failed === undefined ? "" : ("Fehler " + counts.providers_failed),
        counts.providers_skipped === undefined ? "" : ("Übersprungen " + counts.providers_skipped),
        warning ? ("Nicht geprüft " + warning) : "",
        cancelled ? "Vom Benutzer abgebrochen" : ""
      ].filter(Boolean).join(" · ");
    }
    const timelineNode = this.shadowRoot?.getElementById("diagnostic-timeline");
    if (timelineNode) {
      const raw = report?.system_diagnostic?.trace || report?.trace ||
        report?.system_diagnostic?.events || report?.events || [];
      const selected = this.shadowRoot?.getElementById("diagnostic-timeline-filter")?.value || "";
      const rows = (Array.isArray(raw)?raw:[]).filter(ev=>!selected ||
        (ev.state || ev.outcome)===selected).slice(-120);
      timelineNode.textContent = rows.length
        ? rows.map(ev => [
            String(ev.utc || "").slice(0,32),
            String(ev.category || "").slice(0,32),
            String(ev.state || ev.outcome || "").slice(0,32),
            Number.isFinite(ev.metrics?.duration_ms) ? ev.metrics.duration_ms + " ms" : ""
          ].filter(Boolean).join(" · ")).join("\n")
        : "Keine passenden UTC-Ereignisse vorhanden.";
    }
    if (output) {
      output.style.display = "block";
      const resultFilter = this.shadowRoot?.getElementById("diagnostic-result-filter")?.value || "";
      const shown = resultFilter && Array.isArray(report?.providers)
        ? {...report, providers:report.providers.filter(p=>{
            const s=p?.summary || {};
            return resultFilter==="failed" ? s.ok===false
              : resultFilter==="skipped" ? s.routing_skipped===true
              : s.ok===true && s.routing_skipped!==true;
          })} : report;
      output.textContent = this.shadowRoot?.getElementById("diagnostic-technical-details")?.checked === false
        ? JSON.stringify({schema:shown?.schema, generated_at:shown?.generated_at, status:shown?.status, provider_count:shown?.providers?.length, not_executed:shown?.not_executed},null,2)
        : JSON.stringify(shown, null, 2);
    }
    if (copyButton) copyButton.disabled = false;
    if (downloadButton) downloadButton.disabled = false;
    if (gitButton) gitButton.disabled = false;
  };

  proto._diagnosticRefreshProviderScope = async function() {
    if (!this._hass) return [];

    this._diagnosticSetStatus("Aktueller Provider- und Routingumfang wird geladen …");

    // Never start a diagnostic run from a cached provider catalog. Routing
    // toggles are persisted immediately and can change eligibility without a
    // browser reload.
    this._providers = [];
    await this._ensureProviderCatalog();

    // Also refresh the routing snapshot itself so counters and eligibility
    // labels describe exactly the scope used by the upcoming test.
    if (typeof this._routingLoadSettings === "function") {
      await this._routingLoadSettings(false, true);
    }

    this._diagnosticRefreshSelectors();
    return Array.isArray(this._providers) ? [...this._providers] : [];
  };

  proto._diagnosticRunAll = async function() {
    if (!this._hass || this._diagnosticLoading) return;

    let providers = [];
    try {
      providers = await this._diagnosticRefreshProviderScope();
    } catch (error) {
      this._diagnosticSetStatus(
        `Providerumfang konnte nicht aktualisiert werden: ${error?.message || String(error)}`,
        "error"
      );
      return;
    }
    const domain = this.shadowRoot?.getElementById("diagnostic-domain-filter")?.value || "";
    if (domain) {
      providers = providers.filter(p => (p.router_domains || p.domains || p.routing?.domains || []).includes(domain));
    }
    if (!providers.length) {
      this._diagnosticSetStatus("Keine Provider im gewählten Fachbereich vorhanden.", "error");
      return;
    }

    this._diagnosticSetBusy(true);
    if (this._diagnosticLastReport) this._diagnosticPreviousReport = this._diagnosticLastReport;
    this._diagnosticLastReport = null;
    this._diagnosticLastMode = null;
    for (const id of ["diagnostic-copy", "diagnostic-download", "diagnostic-git"]) {
      const button = this.shadowRoot?.getElementById(id);
      if (button) button.disabled = true;
    }

    const output = this.shadowRoot?.getElementById("diagnostic-output");
    if (output) {
      output.style.display = "block";
      output.textContent = "Gesamtdiagnose wird vorbereitet …";
    }

    const chunks = [];
    const started = performance.now();

    try {
      for (let index = 0; index < providers.length; index += 1) {
        if (this._diagnosticCancelRequested) break;
        const provider = providers[index];
        const number = index + 1;
        const eligibility = provider.eligible === false
          ? "deaktiviert – wird ohne Netzwerkzugriff protokolliert"
          : "Liveprüfung läuft";

        this._diagnosticSetProgress(
          number,
          providers.length,
          provider.name || provider.id,
          eligibility
        );
        this._diagnosticSetStatus(
          `Prüfe Provider ${number}/${providers.length}: ${provider.name || provider.id} …`
        );
        if (output) {
          output.textContent = [
            "Provider-Gesamtdiagnose läuft …",
            "",
            `Fortschritt: ${number}/${providers.length}`,
            `Aktuell: ${provider.name || provider.id}`,
            `Abgeschlossen: ${chunks.length}`,
          ].join("\n");
        }

        try {
          const result = await this._hass.callWS({
            type: "weather_router/all_provider_diagnostics",
            provider: provider.id,
          });
          chunks.push(result);
        } catch (error) {
          chunks.push({
            schema: ALL_DIAGNOSTIC_SCHEMA,
            generated_at: new Date().toISOString(),
            api_version: 1,
            reference_context: null,
            providers: [this._diagnosticTransportFailureReport(provider, error)],
            summary: {
              ok: false,
              router_enabled: true,
              provider_count: 1,
              providers_tested: 1,
              providers_skipped: 0,
              providers_ok: 0,
              providers_failed: 1,
              tests_run: 1,
              tests_failed: 1,
              tests_skipped: 0,
            },
          });
        }
      }

      const result = this._diagnosticAggregateReports(chunks);
      // Preserve only bounded, server-redacted, actually executed provider
      // stations in the complete private archive report.
      result.diagnostic_stations = (result.providers || []).slice(0, 128)
        .flatMap(provider => (Array.isArray(provider.diagnostic_stations)
          ? provider.diagnostic_stations.slice(0, 16).map(stage => ({
              provider_id: provider.id,
              stage: stage.stage,
              status: stage.status,
              observed_at_utc: stage.observed_at_utc,
              values: stage.values
            })) : [])).slice(0, 128);
      const systemRequested = this.shadowRoot?.getElementById("diagnostic-deep-system")?.checked === true;
      if (systemRequested && !this._diagnosticCancelRequested) {
        try {
          const system = await this._hass.callWS({type:"weather_router/diagnostic_center/snapshot",deep:this.shadowRoot?.getElementById("diagnostic-native-probe")?.checked===true});
          if (system?.schema === "weather_router.diagnostic_center.v1") {
            result.system_diagnostic = system;
          } else {
            result.system_diagnostic_error = "invalid_schema";
          }
        } catch (_) {
          result.system_diagnostic_error = "runtime_unavailable";
        }
      } else {
        result.system_diagnostic_not_executed = this._diagnosticCancelRequested
          ? "operator_cancelled" : "operator_disabled";
      }
      result.diagnostic_cancelled = Boolean(this._diagnosticCancelRequested);
      result.not_executed = this._diagnosticCancelRequested ? providers.slice(chunks.length).map(x=>({provider_id:x.id,reason:"operator_cancelled"})) : [];
      const elapsedSeconds = ((performance.now() - started) / 1000).toFixed(1);
      this._diagnosticStoreReport(result, "all");

      const summary = result.summary || {};
      this._diagnosticSetProgress(
        providers.length,
        providers.length,
        "Gesamtdiagnose abgeschlossen",
        `${elapsedSeconds} s`
      );
      this._diagnosticSetStatus(
        summary.ok === true
          ? `Gesamtdiagnose abgeschlossen · ${summary.providers_ok ?? 0}/${summary.providers_tested ?? summary.provider_count ?? 0} geprüfte Provider ohne Fehler · ${summary.providers_skipped ?? 0} deaktiviert/übersprungen · ${elapsedSeconds} s.`
          : `Gesamtdiagnose abgeschlossen · ${summary.providers_failed ?? "?"} Provider mit Fehlern · ${summary.providers_skipped ?? 0} deaktiviert/übersprungen · ${elapsedSeconds} s · Details im JSON.`,
        summary.ok === true ? "ok" : "error"
      );

      setTimeout(() => {
        if (!this._diagnosticLoading) this._diagnosticHideProgress();
      }, 1400);
    } finally {
      this._diagnosticSetBusy(false);
    }
  };

  proto._diagnosticRunSingle = async function() {
    if (!this._hass || this._diagnosticLoading) return;

    try {
      await this._diagnosticRefreshProviderScope();
    } catch (error) {
      this._diagnosticSetStatus(
        `Providerumfang konnte nicht aktualisiert werden: ${error?.message || String(error)}`,
        "error"
      );
      return;
    }

    if (!this._diagnosticProvider) {
      this._diagnosticSetStatus("Kein aktuell prüfbarer Provider ausgewählt.", "error");
      return;
    }

    this._diagnosticHideProgress();
    this._diagnosticSetBusy(true);
    this._diagnosticSetStatus("Provider-Diagnose läuft …");
    const output = this.shadowRoot?.getElementById("diagnostic-output");
    if (output) {
      output.style.display = "block";
      output.textContent = "Diagnose läuft …";
    }

    const request = {
      type: "weather_router/provider_diagnostics",
      provider: this._diagnosticProvider,
    };
    if (this._diagnosticCapability) {
      request.capability = this._diagnosticCapability;
    }

    try {
      const result = await this._hass.callWS(request);
      this._diagnosticStoreReport(result, "single");
      const ok = result?.summary?.ok === true;
      this._diagnosticSetStatus(
        ok
          ? "Diagnose abgeschlossen · kein Fehler im geprüften Pfad."
          : "Diagnose abgeschlossen · Fehlerdetails im JSON.",
        ok ? "ok" : "error"
      );
    } catch (error) {
      const fallback = {
        schema: SINGLE_DIAGNOSTIC_SCHEMA,
        client_error: {
          type: error?.constructor?.name || "Error",
          message: error?.message || String(error),
          code: error?.code || null,
        },
      };
      this._diagnosticStoreReport(fallback, "single");
      this._diagnosticSetStatus("Diagnoseaufruf fehlgeschlagen · Clientfehler im JSON.", "error");
    } finally {
      this._diagnosticSetBusy(false);
    }
  };

  proto._diagnosticLegacyCopy = function(text) {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);

    let copied = false;
    try {
      textarea.focus({ preventScroll: true });
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      copied = document.execCommand?.("copy") === true;
    } finally {
      textarea.remove();
    }
    return copied;
  };

  proto._diagnosticCopy = async function() {
    if (!this._diagnosticLastReport) return;
    const text = JSON.stringify(this._diagnosticLastReport, null, 2);

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        this._diagnosticSetStatus("JSON in die Zwischenablage kopiert.", "ok");
        return;
      }

      if (this._diagnosticLegacyCopy(text)) {
        this._diagnosticSetStatus(
          "JSON über mobilen Kompatibilitätsmodus kopiert.",
          "ok"
        );
        return;
      }

      throw new Error("Zwischenablage-API ist in diesem Browser nicht verfügbar");
    } catch (error) {
      this._diagnosticSetStatus(
        `Kopieren nicht möglich: ${error?.message || String(error)} · bitte „JSON teilen / speichern“ verwenden.`,
        "error"
      );
    }
  };

  proto._diagnosticGitExport = async function() {
    if (!this._hass || !this._diagnosticLastReport) return;

    const button = this.shadowRoot?.getElementById("diagnostic-git");
    if (button) button.disabled = true;
    this._diagnosticSetStatus("Provider-Diagnose wird ins private Archiv übertragen …");

    try {
      const result = await this._wrGitExportSnapshot(this._diagnosticLastReport, {
        target: "archive",
        onConfigure: () => {
          this._diagnosticSetStatus(
            "Privaten Archivzugang einrichten; der Export wird anschließend fortgesetzt.",
          );
        },
        onSuccess: exported => {
          const path = exported?.path || "unbekannt";
          const shortSha = typeof exported?.commit_sha === "string"
            ? exported.commit_sha.slice(0, 10) : null;
          if (this._diagnosticLastMode === "scientific") {
            const scienceButton = this.shadowRoot?.getElementById("opera-science-git-export");
            if (scienceButton) this._operaScienceMarkExport?.(scienceButton);
          }
          this._diagnosticSetStatus(
            `Provider-Diagnose im privaten Archiv gespeichert · ${path}${shortSha ? ` · Commit ${shortSha}` : ""}.`,
            "ok",
          );
          this._wrLog?.("provider_diagnostics_git_exported", {
            mode: this._diagnosticLastMode || null, path, commit_sha: shortSha,
          });
        },
        onError: error => {
          this._diagnosticSetStatus(
            `Archivübertragung fehlgeschlagen: ${error?.message || String(error)}.`,
            "error",
          );
          this._wrLog?.("provider_diagnostics_git_export_failed", {
            mode: this._diagnosticLastMode || null, error,
          }, "error");
        },
      });
      if (result?.pending_configuration) return;
    } catch (error) {
      this._diagnosticSetStatus(
        `Archivübertragung fehlgeschlagen: ${error?.message || String(error)}.`,
        "error",
      );
    } finally {
      if (button) button.disabled = !this._diagnosticLastReport;
    }
  };

  proto._diagnosticDownload = async function() {
    if (!this._diagnosticLastReport) return;

    const text = JSON.stringify(this._diagnosticLastReport, null, 2) + "\n";
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const suffix = this._diagnosticLastMode === "all"
      ? "all-providers"
      : (this._diagnosticProvider || "provider");
    const fileName = `weather-router-diagnostics-${suffix}-${stamp}.json`;
    const blob = new Blob([text], { type: "application/json;charset=utf-8" });

    try {
      if (typeof File === "function" && navigator.share) {
        const file = new File([blob], fileName, { type: blob.type });
        const shareData = { files: [file], title: "WeatherRouter Diagnose" };
        if (!navigator.canShare || navigator.canShare(shareData)) {
          await navigator.share(shareData);
          if (this._diagnosticLastMode === "scientific") {
            const scienceButton = this.shadowRoot?.getElementById("opera-science-json-export");
            if (scienceButton) this._operaScienceMarkExport?.(scienceButton);
          }
          this._diagnosticSetStatus(
            "JSON über die mobile Teilen-/Speichern-Funktion bereitgestellt.",
            "ok"
          );
          return;
        }
      }
    } catch (error) {
      if (error?.name === "AbortError") {
        this._diagnosticSetStatus("Teilen abgebrochen.", "muted");
        return;
      }
      // Fall through to classic download for browsers/WebViews where file sharing fails.
    }

    try {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      link.rel = "noopener";
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        link.remove();
        URL.revokeObjectURL(url);
      }, 1500);
      if (this._diagnosticLastMode === "scientific") {
        const scienceButton = this.shadowRoot?.getElementById("opera-science-json-export");
        if (scienceButton) this._operaScienceMarkExport?.(scienceButton);
      }
      this._diagnosticSetStatus("JSON-Datei zum Speichern bereitgestellt.", "ok");
    } catch (error) {
      this._diagnosticSetStatus(
        `JSON konnte nicht geteilt oder gespeichert werden: ${error?.message || String(error)}.`,
        "error"
      );
    }
  };

  proto._renderShell = function() {
    originalRenderShell.call(this);
    this._diagnosticInstallUI();
  };

  proto._renderWeatherLayers = function() {
    const result = originalRenderWeatherLayers.call(this);
    this._diagnosticInstallUI();
    this._diagnosticRefreshSelectors();
    return result;
  };

  console.info("[WeatherRouter] provider diagnostic popup + aggregate JSON mode enabled");
}
