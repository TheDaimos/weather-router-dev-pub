const LAB_ELEMENT = "weather-router-lab";
const LOG_MENU_STATE_KEY = "weather_router_log_menu_open_v1";
const LOG_EXPORT_SCHEMA = "weather_router.event_log.v1";

const LabClass = customElements.get(LAB_ELEMENT);
if (!LabClass) {
  throw new Error(`${LAB_ELEMENT} muss vor dem Log-Exportmodul registriert sein.`);
}

const proto = LabClass.prototype;

if (!proto.__weatherRouterLogExportEnhanced) {
  proto.__weatherRouterLogExportEnhanced = true;

  const previousRenderShell = proto._renderShell;
  const previousEventLogBadge = proto._wrEventLogBadge;

  const csvEscape = value => {
    const text = String(value ?? "");
    return `"${text.replaceAll('"', '""')}"`;
  };

  proto._wrLogSnapshotForExport = function() {
    const snapshot = this._wrEventLogSnapshot();
    const providers = (this._providers || []).map(provider => ({
      id: provider.id,
      name: provider.name,
      revision: provider.revision || null,
      capabilities: (provider.capabilities || []).map(capability => ({
        id: capability.id,
        name: capability.name,
        source_class: capability.source_class,
        render_mode: capability.render_mode,
      })),
    }));

    const enriched = {
      ...snapshot,
      schema: LOG_EXPORT_SCHEMA,
      home_assistant: {
        version: this._hass?.config?.version || null,
      },
      providers,
      latest_point_results: this._results
        ? this._wrEventSanitize(this._results)
        : null,
    };

    return JSON.parse(JSON.stringify(enriched));
  };

  proto._wrLogGenerate = function() {
    this._wrLog?.("log_snapshot_generated", {
      event_count_before_snapshot: this._wrEventLogStore().events.length,
    });
    this._wrGeneratedLog = this._wrLogSnapshotForExport();
    this._wrLastGitExport = null;
    this._wrLogExportRefreshState();

    const status = this.shadowRoot?.getElementById("wr-log-status");
    if (status) {
      status.textContent =
        `Log erzeugt · ${this._wrGeneratedLog.events?.length || 0} Ereignisse · ` +
        new Date(this._wrGeneratedLog.generated_at).toLocaleString();
      status.className = "wr-log-status ok";
    }
    return this._wrGeneratedLog;
  };

  proto._wrLogCsv = function(snapshot = this._wrGeneratedLog) {
    if (!snapshot) return "";

    const rows = [[
      "record_type",
      "generated_at",
      "build",
      "seq",
      "time",
      "level",
      "event",
      "provider",
      "capability",
      "details_json",
    ]];

    const metadata = { ...snapshot };
    delete metadata.events;
    rows.push([
      "snapshot",
      snapshot.generated_at || "",
      snapshot.build || "",
      "",
      "",
      "",
      "",
      "",
      "",
      JSON.stringify(metadata),
    ]);

    for (const event of snapshot.events || []) {
      rows.push([
        "event",
        snapshot.generated_at || "",
        snapshot.build || "",
        event.seq ?? "",
        event.time || "",
        event.level || "",
        event.event || "",
        event.provider || "",
        event.capability || "",
        event.details ? JSON.stringify(event.details) : "",
      ]);
    }

    return rows.map(row => row.map(csvEscape).join(",")).join("\r\n") + "\r\n";
  };

  proto._wrLogDownload = function(kind) {
    if (!this._wrGeneratedLog) return;

    const isCsv = kind === "csv";
    const content = isCsv
      ? this._wrLogCsv(this._wrGeneratedLog)
      : JSON.stringify(this._wrGeneratedLog, null, 2);
    const mime = isCsv ? "text/csv;charset=utf-8" : "application/json";
    const extension = isCsv ? "csv" : "json";
    const stamp = new Date(this._wrGeneratedLog.generated_at || Date.now())
      .toISOString()
      .replaceAll(":", "-");
    const fileName = `weather-router-log-${stamp}.${extension}`;

    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);

    this._wrLog?.("log_download", { format: extension });
    const status = this.shadowRoot?.getElementById("wr-log-status");
    if (status) {
      status.textContent = `${extension.toUpperCase()}-Download gestartet.`;
      status.className = "wr-log-status ok";
    }
  };

  proto._wrLogCopyGenerated = async function() {
    if (!this._wrGeneratedLog) return;
    const copied = await this._wrEventLogCopyText(
      JSON.stringify(this._wrGeneratedLog, null, 2),
    );
    this._wrLog?.("log_clipboard", { copied });
    const status = this.shadowRoot?.getElementById("wr-log-status");
    if (status) {
      status.textContent = copied
        ? "Log in die Zwischenablage kopiert."
        : "Kopieren nicht möglich.";
      status.className = copied ? "wr-log-status ok" : "wr-log-status error";
    }
  };

  proto._wrLogGitStatus = async function(target = "archive") {
    this._wrGitTargets ||= {};
    try {
      const result = await this._hass.callWS({ type: "weather_router/log_git_status", target });
      this._wrGitTargets[target] = result;
      this._wrGitDefaultTarget = result.default_target || "archive";
      this._wrLogExportRefreshState();
      return result;
    } catch (error) {
      this._wrGitTargets[target] = { configured: false, error: error?.message || String(error) };
      this._wrLogExportRefreshState();
      return this._wrGitTargets[target];
    }
  };

  proto._wrGitExportSnapshot = async function(snapshot, options = {}) {
    if (!snapshot || !this._hass) throw new Error("Kein exportierbarer Snapshot verfügbar.");
    // Source repositories may later be published; only the isolated archive
    // is a valid destination, including for manual and routing exports.
    if (options.target && options.target !== "archive") {
      const error = new Error("Git-WR ist für Diagnoseexporte gesperrt. Nur Log&Export ist erlaubt.");
      options.onError?.(error);
      throw error;
    }
    const target = "archive";
    let state = await this._wrLogGitStatus(target);
    if (!state?.configured) {
      this._wrGitPendingExport = { target, snapshot, options };
      options.onConfigure?.();
      this._wrLogGitOpenConfig(target);
      return { pending_configuration: true };
    }
    try {
      options.onStart?.(state);
      const result = await this._hass.callWS({
        type: "weather_router/log_git_export", target, snapshot,
      });
      options.onSuccess?.(result);
      return result;
    } catch (error) {
      options.onError?.(error);
      throw error;
    }
  };

  proto._wrLogGitOpenConfig = function(target = "archive") {
    this._wrGitActiveTarget = target;
    const modal = this.shadowRoot?.getElementById("wr-log-git-modal");
    const config = this._wrGitTargets?.[target];
    this.shadowRoot.getElementById("wr-log-git-title").textContent =
      target === "archive" ? "WeatherRouter · Log&Export" : "WeatherRouter · Git-WR";
    const repo = this.shadowRoot.getElementById("wr-log-git-repository");
    repo.value = target === "archive" ? "TheDaimos/Project-Log-And-Export" : "TheDaimos/weather-router-dev";
    const token = this.shadowRoot.getElementById("wr-log-git-token");
    token.value = "";
    token.placeholder = config?.configured ? "Gespeicherten Token beibehalten" : "Fine-grained Schreibtoken";
    const result = this.shadowRoot.getElementById("wr-log-git-config-result");
    result.textContent = target === "wr"
      ? "Git-WR ist als Diagnoseziel gesperrt. Ein vorhandener Alt-Token kann hier entfernt werden."
      : config?.configured ? "Zugang eingerichtet · Token wird nicht angezeigt" : "Noch nicht eingerichtet";
    result.className = "wr-log-status muted";
    const standard = this.shadowRoot.getElementById("wr-log-git-default-switch");
    if (standard) {
      standard.checked = target === "archive";
      standard.disabled = true;
    }
    if (token) token.disabled = target === "wr";
    const save = this.shadowRoot.getElementById("wr-log-git-save");
    if (save) save.disabled = target === "wr";
    this._wrLogExportRefreshState();
    modal.hidden = false;
  };

  proto._wrLogGitSetDefault = function() {
    // Archive is a mandatory security boundary, not a user-overridable preference.
    const control = this.shadowRoot?.getElementById("wr-log-git-default-switch");
    if (control) control.checked = this._wrGitActiveTarget !== "wr";
  };

  proto._wrLogGitCloseConfig = function() {
    this._wrGitPendingExport = null;
    const modal = this.shadowRoot?.getElementById("wr-log-git-modal");
    if (modal) modal.hidden = true;
    const input = this.shadowRoot?.getElementById("wr-log-git-token");
    if (input) input.value = "";
  };

  proto._wrLogGitConfigure = async function(clear = false) {
    if (!this._hass) return;
    const target = this._wrGitActiveTarget || "archive";
    const tokenField = this.shadowRoot?.getElementById("wr-log-git-token");
    const repository = this.shadowRoot?.getElementById("wr-log-git-repository")?.value?.trim() || "";
    const status = this.shadowRoot?.getElementById("wr-log-git-config-result");
    const save = this.shadowRoot?.getElementById("wr-log-git-save");
    if (save) save.disabled = true;
    if (status) {
      status.textContent = clear ? "Entferne Zugang …" : "Prüfe Repository und Schreibzugang …";
      status.className = "wr-log-status muted";
    }
    try {
      const result = await this._hass.callWS({
        type: "weather_router/log_git_configure",
        target, repository, token: clear ? "" : tokenField.value.trim(), clear,
      });
      this._wrGitTargets ||= {};
      this._wrGitTargets[target] = result;
      this._wrGitDefaultTarget = result.default_target || this._wrGitDefaultTarget || "archive";
      tokenField.value = "";
      this._wrLogExportRefreshState();
      const pending = !clear && result.configured && this._wrGitPendingExport?.target === target
        ? this._wrGitPendingExport : null;
      if (clear && this._wrGitPendingExport?.target === target) this._wrGitPendingExport = null;
      if (status) {
        status.textContent = clear ? "Zugang entfernt." :
          "Gespeichert und Repository geprüft · " + result.repository + " · " + result.branch;
        status.className = "wr-log-status ok";
      }
      if (pending) {
        this._wrLogGitCloseConfig();
        await this._wrGitExportSnapshot(pending.snapshot, {
          ...pending.options, target,
        });
      }
    } catch (error) {
      if (status) {
        status.textContent = "Speichern & Testen fehlgeschlagen: " + (error?.message || String(error));
        status.className = "wr-log-status error";
      }
    } finally {
      if (save) save.disabled = target === "wr";
    }
  };

  proto._wrLogGitExport = async function(target = "archive") {
    if (!this._wrGeneratedLog || !this._hass) return;
    const button = this.shadowRoot?.getElementById(target === "archive" ? "wr-log-archive" : "wr-log-git");
    const status = this.shadowRoot?.getElementById("wr-log-status");
    if (button) button.disabled = true;
    if (status) {
      status.textContent = "Git-Export läuft …";
      status.className = "wr-log-status muted";
    }
    try {
      await this._wrGitExportSnapshot(this._wrGeneratedLog, {
        target,
        onSuccess: result => {
          this._wrLastGitExport = result;
          if (status) {
            status.textContent = "Exportiert nach " + result.repository + " · " + result.path;
            status.className = "wr-log-status ok";
          }
        },
        onError: error => {
          if (status) {
            status.textContent = "Git-Export fehlgeschlagen: " + (error?.message || String(error));
            status.className = "wr-log-status error";
          }
        },
      });
    } catch (_error) {
      // Feedback is already shown in the error callback.
    } finally {
      this._wrLogExportRefreshState();
    }
  };

  proto._wrLogExportRefreshState = function() {
    const hasLog = Boolean(this._wrGeneratedLog);
    for (const id of ["wr-log-csv", "wr-log-json", "wr-log-copy"]) {
      const button = this.shadowRoot?.getElementById(id);
      if (button) button.disabled = !hasLog;
    }
    const oldButton = this.shadowRoot?.getElementById("wr-log-git");
    if (oldButton) oldButton.disabled = true;
    const archiveButton = this.shadowRoot?.getElementById("wr-log-archive");
    if (archiveButton) archiveButton.disabled = !hasLog || !this._wrGitTargets?.archive?.configured;
    const legacyToken = this.shadowRoot?.getElementById("wr-log-git-settings");
    if (legacyToken) legacyToken.title = "Alten Git-WR-Zugang prüfen oder entfernen; Export gesperrt";
    const archiveToken = this.shadowRoot?.getElementById("wr-log-archive-settings");
    if (archiveToken) archiveToken.title = this._wrGitTargets?.archive?.configured
      ? "Privaten Archivzugang bearbeiten" : "Privaten Archivzugang einrichten";
    const count = this.shadowRoot?.getElementById("wr-log-count");
    if (count) count.textContent = hasLog ? `${this._wrGeneratedLog.events?.length || 0} Ereignisse` : "noch kein Log";
    const state = this.shadowRoot?.getElementById("wr-log-git-state");
    if (state) state.textContent = "Diagnoseziel: privates Log&Export · " +
      (this._wrGitTargets?.archive?.configured ? "bereit" : "Zugang nicht eingerichtet") +
      " · Git-WR gesperrt";
    const standard = this.shadowRoot?.getElementById("wr-log-git-default-switch");
    if (standard) {
      standard.checked = this._wrGitActiveTarget !== "wr";
      standard.disabled = true;
    }
    const wrSettings = this.shadowRoot?.getElementById("wr-log-git-settings");
    const archiveSettings = this.shadowRoot?.getElementById("wr-log-archive-settings");
    if (wrSettings) wrSettings.textContent = "Alt-Token WR";
    if (archiveSettings) archiveSettings.textContent = "Token L&E ★";
    const link = this.shadowRoot?.getElementById("wr-log-git-link");
    if (link) {
      if (this._wrLastGitExport?.file_url) {
        link.href = this._wrLastGitExport.file_url;
        link.hidden = false;
      } else link.hidden = true;
    }
    if (typeof previousEventLogBadge === "function") previousEventLogBadge.call(this);
  };

  proto._wrLogExportInstallUI = function() {
    const root = this.shadowRoot;
    const sidebar = root?.querySelector(".sidebar");
    if (!root || !sidebar) return;

    root.getElementById("wr-event-log-launch-wrap")?.remove();
    root.getElementById("wr-event-log-window")?.remove();

    if (!root.getElementById("wr-log-export-style")) {
      const style = document.createElement("style");
      style.id = "wr-log-export-style";
      style.textContent = `
        .wr-log-menu { border-color:color-mix(in srgb,#d4af37 32%,var(--divider-color,#444)); }
        .wr-log-summary { justify-content:space-between; }
        .wr-log-summary-main { display:flex; align-items:center; gap:8px; }
        .wr-log-count { margin-left:auto; font-size:10px; opacity:.58; font-weight:500; }
        .wr-log-intro { margin:0 0 10px; font-size:11px; line-height:1.45; opacity:.72; }
        .wr-log-actions { display:grid; grid-template-columns:1fr 1fr; gap:7px; }
        .wr-log-actions button { min-height:38px; }
        .wr-log-token-pair { display:grid;grid-template-columns:1fr 1fr;gap:7px;min-width:0; }
        .wr-log-token-pair button { font-size:11px; }
        .wr-log-refresh { grid-column:1 / -1; color:#d4af37; border-color:color-mix(in srgb,#d4af37 55%,var(--divider-color,#555)); }
        .wr-log-actions button:disabled { opacity:.38; }
        .wr-log-status { margin:9px 0 0; min-height:18px; font-size:10px; line-height:1.4; overflow-wrap:anywhere; }
        .wr-log-git-meta { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:7px; font-size:9px; opacity:.65; }
        .wr-log-git-meta button { min-height:26px; padding:3px 7px; font-size:10px; }
        .wr-log-git-link { color:#d4af37; }
        .wr-log-git-modal[hidden] { display:none !important; }
        .wr-log-git-modal {
          position:fixed; inset:0; z-index:10020; display:grid; place-items:center;
          padding:18px; background:rgba(0,0,0,.62);
        }
        .wr-log-git-dialog {
          width:min(620px,100%); padding:18px; border:1px solid var(--divider-color,#555);
          border-radius:14px; background:var(--card-background-color,#1c1c1c);
          box-shadow:0 18px 70px rgba(0,0,0,.65);
        }
        .wr-log-git-dialog h3 { margin:0 0 12px; font-size:16px; }
        .wr-log-git-dialog input {
          width:100%; min-height:40px; padding:8px 10px; border:1px solid var(--divider-color,#555);
          border-radius:8px; background:var(--secondary-background-color,#282828);
          color:var(--primary-text-color,#eee);
        }
        .wr-log-git-help { margin:8px 0 12px; font-size:10px; line-height:1.45; opacity:.7; }
        .wr-log-git-actions { display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
        .wr-log-default-option {
          display:flex; align-items:center; gap:12px; justify-content:space-between;
          padding:12px; margin:12px 0 8px;
          border:1px solid color-mix(in srgb,#d4af37 45%,var(--divider-color,#555));
          border-radius:10px; background:color-mix(in srgb,#d4af37 8%,transparent);
          cursor:pointer; opacity:1;
        }
        .wr-log-default-option span { display:grid; gap:3px; flex:1; }
        .wr-log-default-option strong { font-size:12px; }
        .wr-log-default-option small { font-size:10px; line-height:1.35; opacity:.75; }
        .wr-log-default-option input[type="checkbox"] {
          appearance:none; -webkit-appearance:none; position:relative;
          width:42px; min-width:42px; height:24px; min-height:24px;
          border-radius:99px; border:1px solid var(--divider-color,#777);
          background:var(--secondary-background-color,#444); padding:0;
          margin:0; cursor:pointer; transition:background .15s;
        }
        .wr-log-default-option input[type="checkbox"]::before {
          content:""; position:absolute; top:3px; left:3px; width:16px; height:16px;
          border-radius:50%; background:white; transition:transform .15s;
        }
        .wr-log-default-option input[type="checkbox"]:checked {
          background:#9d7b21; border-color:#d4af37;
        }
        .wr-log-default-option input[type="checkbox"]:checked::before { transform:translateX(18px); }
        .wr-log-default-option input[type="checkbox"]:focus-visible { outline:2px solid var(--primary-color,#03a9f4); outline-offset:3px; }
        .wr-log-default-option input[type="checkbox"]:disabled { opacity:.5; cursor:wait; }
        @media(max-width:520px) {
          .wr-log-actions { grid-template-columns:minmax(0,1fr) minmax(0,1fr); }
          .wr-log-actions button { font-size:10px; overflow-wrap:anywhere; }
          .wr-log-token-pair { gap:4px; }
          .wr-log-git-actions button { flex:1; }
        }
      `;
      root.appendChild(style);
    }

    if (!root.getElementById("wr-log-menu")) {
      const menu = document.createElement("details");
      menu.id = "wr-log-menu";
      menu.className = "card lab-menu wr-log-menu";

      try {
        menu.open = localStorage.getItem(LOG_MENU_STATE_KEY) === "1";
      } catch (_error) {
        menu.open = false;
      }

      menu.innerHTML = `
        <summary class="wr-log-summary">
          <span class="wr-log-summary-main">📋 Protokolle & Logs</span>
          <span id="wr-log-count" class="wr-log-count">noch kein Log</span>
        </summary>
        <div class="lab-menu-content">
          <p class="wr-log-intro">
            Öffnen erzeugt einen redigierten Snapshot des aktuellen WeatherRouter-Zustands.
            Git-Exporte gehen ausschließlich in das private Project-Log-And-Export-Archiv.
            Das WeatherRouter-Quellrepository ist als Diagnoseziel gesperrt.
          </p>
          <div class="wr-log-actions">
            <button id="wr-log-refresh" class="wr-log-refresh" type="button">Snapshot aktualisieren</button>
            <button id="wr-log-csv" type="button" disabled>CSV herunterladen</button>
            <button id="wr-log-git" type="button" disabled title="Quellrepository ist für Diagnoseexporte gesperrt">Git-WR gesperrt</button>
            <button id="wr-log-json" type="button" disabled>JSON herunterladen</button>
            <button id="wr-log-archive" class="primary" type="button" disabled>Ins private Archiv exportieren</button>
            <button id="wr-log-copy" type="button" disabled>In Zwischenablage</button>
            <div class="wr-log-token-pair">
              <button id="wr-log-git-settings" type="button">Alt-Token WR</button>
              <button id="wr-log-archive-settings" type="button">Token L&E</button>
            </div>
          </div>
          <div id="wr-log-status" class="wr-log-status muted">
            Noch kein Export-Snapshot erzeugt.
          </div>
          <div class="wr-log-git-meta">
            <span id="wr-log-git-state">Git: Status wird geladen …</span>

            <a id="wr-log-git-link" class="wr-log-git-link" href="#" target="_blank" rel="noopener" hidden>Letzten Export öffnen</a>
          </div>
        </div>
      `;

      const hero = root.getElementById("weather-router-brand-hero");
      if (hero?.nextSibling) sidebar.insertBefore(menu, hero.nextSibling);
      else if (hero) hero.after(menu);
      else sidebar.prepend(menu);

      menu.addEventListener("toggle", () => {
        try {
          localStorage.setItem(LOG_MENU_STATE_KEY, menu.open ? "1" : "0");
        } catch (_error) {
          // Optional browser-only convenience.
        }
        if (menu.open) {
          this._wrLogGenerate();
          this._wrLogGitStatus("wr");
          this._wrLogGitStatus("archive");
        }
      });

      root.getElementById("wr-log-refresh").addEventListener("click", () => this._wrLogGenerate());
      root.getElementById("wr-log-csv").addEventListener("click", () => this._wrLogDownload("csv"));
      root.getElementById("wr-log-json").addEventListener("click", () => this._wrLogDownload("json"));
      root.getElementById("wr-log-copy").addEventListener("click", () => this._wrLogCopyGenerated());
      root.getElementById("wr-log-git").addEventListener("click", () => this._wrLogGitExport("wr"));
      root.getElementById("wr-log-archive").addEventListener("click", () => this._wrLogGitExport("archive"));
      root.getElementById("wr-log-archive-settings").addEventListener("click", () => this._wrLogGitOpenConfig("archive"));
      root.getElementById("wr-log-git-settings").addEventListener("click", () => this._wrLogGitOpenConfig("wr"));
    }

    if (!root.getElementById("wr-log-git-modal")) {
      const modal = document.createElement("div");
      modal.id = "wr-log-git-modal";
      modal.className = "wr-log-git-modal";
      modal.hidden = true;
      modal.innerHTML = `
        <div class="wr-log-git-dialog" role="dialog" aria-modal="true">
          <h3 id="wr-log-git-title">WeatherRouter · Git-Export</h3>
          <label for="wr-log-git-repository">Repository-Adresse</label>
          <input id="wr-log-git-repository" type="text" autocomplete="off" spellcheck="false">
          <label for="wr-log-git-token">Separater GitHub-Schreibtoken</label>
          <input id="wr-log-git-token" type="password" autocomplete="off">
          <div class="wr-log-git-help">
            Fine-grained Token: Metadata · Read und Contents · Read and write.
            Der Zugang wird serverseitig gespeichert. Diagnoseexporte sind nur in privaten Ziel-Repositories zulässig.
          </div>
          <label class="wr-log-default-option" for="wr-log-git-default-switch">
            <span>
              <strong>Als Standard-Repository verwenden</strong>
              <small>Für Diagnoseexporte ist ausschließlich das private Archiv erlaubt; nicht umschaltbar.</small>
            </span>
            <input id="wr-log-git-default-switch" type="checkbox" role="switch" aria-label="Als Standard-Repository verwenden">
          </label>
          <div id="wr-log-git-config-result" class="wr-log-status muted"></div>
          <div class="wr-log-git-actions">
            <button id="wr-log-git-remove" type="button">Token entfernen</button>
            <button id="wr-log-git-cancel" type="button">Abbrechen</button>
            <button id="wr-log-git-save" class="primary" type="button">Speichern & Testen</button>
          </div>
        </div>
      `;
      root.appendChild(modal);

      root.getElementById("wr-log-git-cancel").addEventListener("click", () => this._wrLogGitCloseConfig());
      root.getElementById("wr-log-git-save").addEventListener("click", () => this._wrLogGitConfigure(false));
      root.getElementById("wr-log-git-default-switch").addEventListener("change", () => void this._wrLogGitSetDefault());
      root.getElementById("wr-log-git-remove").addEventListener("click", () => this._wrLogGitConfigure(true));
    }

    this._wrLogExportRefreshState();
    this._wrLogGitStatus("archive");
    this._wrLogGitStatus("wr");

    const installedMenu = root.getElementById("wr-log-menu");
    if (installedMenu?.open && !this._wrGeneratedLog) {
      const status = root.getElementById("wr-log-status");
      if (status) {
        status.textContent =
          "Menü war beim Start bereits geöffnet · Snapshot nach dem Test aktualisieren.";
        status.className = "wr-log-status muted";
      }
    }
  };

  proto._renderShell = function() {
    previousRenderShell.call(this);
    this._wrLogExportInstallUI();
  };

  proto._wrEventLogBadge = function() {
    if (typeof previousEventLogBadge === "function") {
      previousEventLogBadge.call(this);
    }
    const count = this.shadowRoot?.getElementById("wr-log-count");
    if (!count) return;
    const currentCount = this._wrEventLogStore().events.length;
    if (!this._wrGeneratedLog) {
      count.textContent = `noch kein Log · ${currentCount} Ereignisse gesammelt`;
      return;
    }
    const frozenCount = this._wrGeneratedLog.events?.length || 0;
    const newer = Math.max(0, currentCount - frozenCount);
    count.textContent = newer
      ? `${frozenCount} im Snapshot · ${newer} neu`
      : `${frozenCount} Ereignisse`;
  };

  console.info("[WeatherRouter] compact log export menu enabled");
}
