const Lab = customElements.get("weather-router-lab");
const buildVersion = Lab?.buildVersion || "0.10.25";

if (Lab && !Lab.prototype.__weatherRouterBrandingPatched) {
  const originalRenderShell = Lab.prototype._renderShell;

  Lab.prototype._renderShell = function (...args) {
    originalRenderShell.apply(this, args);

    const root = this.shadowRoot;
    const sidebar = root?.querySelector(".sidebar");
    if (!root || !sidebar || root.getElementById("weather-router-brand-hero")) return;

    const style = document.createElement("style");
    style.textContent = `
      .wr-brand-hero {
        position:relative;
        overflow:hidden;
        margin:-4px -4px 16px;
        padding:16px 14px 14px;
        border:1px solid color-mix(in srgb,var(--primary-color,#03a9f4) 52%,var(--divider-color,#445));
        border-radius:16px;
        background:
          radial-gradient(circle at 50% 24%,rgba(0,190,255,.22),transparent 48%),
          linear-gradient(145deg,rgba(11,42,67,.94),rgba(8,17,30,.97));
        box-shadow:0 10px 30px rgba(0,150,255,.10);
        text-align:center;
      }
      .wr-brand-hero::before {
        content:"";
        position:absolute;
        inset:-30%;
        background:radial-gradient(circle,rgba(55,220,255,.10),transparent 48%);
        pointer-events:none;
      }
      .wr-brand-build {
        position:absolute;
        top:10px;
        right:12px;
        z-index:2;
        padding:4px 8px;
        border:1px solid color-mix(in srgb,var(--primary-color,#03a9f4) 58%,var(--divider-color,#555));
        border-radius:999px;
        background:rgba(0,0,0,.30);
        color:var(--primary-text-color,#eee);
        font-size:10px;
        font-weight:800;
        letter-spacing:.02em;
      }
      .wr-brand-content { position:relative; z-index:1; }
      .wr-brand-logo {
        display:block;
        width:min(230px,78%);
        height:auto;
        margin:0 auto 5px;
        filter:drop-shadow(0 0 18px rgba(42,209,255,.28));
      }
      .wr-brand-title {
        margin:0;
        font-size:27px;
        line-height:1.05;
        letter-spacing:-.025em;
      }
      .wr-brand-subtitle {
        margin:7px auto 10px;
        max-width:340px;
        color:var(--secondary-text-color,#aaa);
        font-size:12px;
        line-height:1.4;
      }
      .wr-brand-meta {
        display:flex;
        justify-content:center;
        flex-wrap:wrap;
        gap:6px;
        margin:0 0 11px;
      }
      .wr-brand-pill {
        display:inline-flex;
        align-items:center;
        min-height:25px;
        padding:4px 8px;
        border:1px solid color-mix(in srgb,var(--primary-color,#03a9f4) 38%,var(--divider-color,#555));
        border-radius:999px;
        background:rgba(0,0,0,.16);
        font-size:10px;
        font-weight:700;
      }
      .wr-brand-help {
        display:inline-flex;
        align-items:center;
        justify-content:center;
        min-height:34px;
        padding:7px 12px;
        border:1px solid color-mix(in srgb,var(--primary-color,#03a9f4) 62%,transparent);
        border-radius:9px;
        background:color-mix(in srgb,var(--primary-color,#03a9f4) 18%,transparent);
        color:var(--primary-text-color,#eee);
        text-decoration:none;
        font-size:12px;
        font-weight:750;
      }
      .wr-brand-help:hover { background:color-mix(in srgb,var(--primary-color,#03a9f4) 28%,transparent); }
    `;
    root.appendChild(style);

    const existingTitle = sidebar.querySelector(":scope > h1");
    const existingSubtitle = sidebar.querySelector(":scope > .subtitle");
    existingTitle?.remove();
    existingSubtitle?.remove();

    const hero = document.createElement("section");
    hero.id = "weather-router-brand-hero";
    hero.className = "wr-brand-hero";
    hero.innerHTML = `
      <div class="wr-brand-build">WR ${buildVersion} · DEV</div>
      <div class="wr-brand-content">
        <img
          class="wr-brand-logo"
          src="/weather_router_static/assets/branding/weather-router-brandmark.png"
          alt="WeatherRouter Logo"
          onerror="this.style.display='none'"
        >
        <h1 class="wr-brand-title">WeatherRouter Lab</h1>
        <div class="wr-brand-subtitle">Interner Router-/Provider-Prüfstand · Wetterdaten nach Fähigkeit statt nach einem einzigen Anbieter.</div>
        <div class="wr-brand-meta">
          <span class="wr-brand-pill">V0.10 TEST</span>
          <span class="wr-brand-pill">API-Vertrag 1</span>
          <span class="wr-brand-pill">Development-Baseline</span>
        </div>
        <a class="wr-brand-help" href="/weather_router_static/weather-router-help.html" target="_blank" rel="noopener noreferrer">WeatherRouter · Projekt & Hilfe</a>
      </div>
    `;

    sidebar.prepend(hero);
  };

  Lab.prototype.__weatherRouterBrandingPatched = true;
}
