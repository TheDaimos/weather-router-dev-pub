"use strict";
/** Offline regression: diagnostics can never be written to the source repo. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const modulePath = path.join(__dirname, "../custom_components/weather_router/frontend/weather-router-lab-log-export.js");
class FakeLab {}
FakeLab.prototype._renderShell = () => {};
FakeLab.prototype._wrEventLogBadge = () => {};
vm.runInNewContext(fs.readFileSync(modulePath, "utf8"), {
  customElements: { get: () => FakeLab }, console: { info: () => {} },
}, { filename: modulePath });

async function main() {
  const app = new FakeLab();
  const requests = [];
  const config = {
    archive: { configured: true, branch: "main", repository: "TheDaimos/Project-Log-And-Export" },
    wr: { configured: false, retired: true, legacy_token_saved: true, repository: "TheDaimos/weather-router-dev" },
  };
  const switchControl = { checked: false, disabled: false };
  const message = { textContent: "", className: "" };
  app.shadowRoot = { getElementById(id) {
    if (id === "wr-log-git-default-switch") return switchControl;
    if (id === "wr-log-git-config-result") return message;
    return null;
  } };
  app._wrLogExportRefreshState = () => {};
  app._wrLogGitOpenConfig = target => { app.openedTarget = target; };
  app._hass = { async callWS(request) {
    requests.push(request);
    if (request.type === "weather_router/log_git_status") {
      return { ...config[request.target], target: request.target, default_target: "archive" };
    }
    if (request.type === "weather_router/log_git_export") {
      assert.equal(request.target, "archive", "No source-repo write is permitted");
      if (!config.archive.configured) throw new Error("Archive not configured");
      return { repository: config.archive.repository, path: "synthetic/trace.json" };
    }
    throw new Error("Unexpected request " + request.type);
  } };
  const sample = { schema: "weather_router.routing_diagnostic.v1",
                   decision: { status: "ready" }, candidates: [] };

  const first = await app._wrGitExportSnapshot(sample);
  assert.equal(first.repository, config.archive.repository);

  const explicit = await app._wrGitExportSnapshot(sample, { target: "archive" });
  assert.equal(explicit.repository, config.archive.repository);

  await assert.rejects(app._wrGitExportSnapshot(sample, { target: "wr" }),
                       /gesperrt/);
  assert.equal(requests.filter(r => r.type === "weather_router/log_git_export").length, 2);

  config.archive.configured = false;
  let prompted = false;
  const missing = await app._wrGitExportSnapshot(sample, {
    onConfigure: () => { prompted = true; },
  });
  assert.equal(missing.pending_configuration, true);
  assert.equal(prompted, true);
  assert.equal(app.openedTarget, "archive");
  assert.equal(app._wrGitPendingExport.target, "archive");

  app._wrGitActiveTarget = "wr";
  switchControl.checked = true;
  app._wrLogGitSetDefault();
  assert.equal(switchControl.checked, false);
  app._wrGitActiveTarget = "archive";
  switchControl.checked = false;
  app._wrLogGitSetDefault();
  assert.equal(switchControl.checked, true);
  assert.equal(requests.filter(r => r.type === "weather_router/log_git_set_default").length, 0);

  assert.equal(requests.filter(r => r.type === "weather_router/log_git_export"
                         && r.target !== "archive").length, 0);

  // Load the real routing module to check whether the archived UI number
  // matches the catalogue and does not mutate the original trace.
  const routingModulePath = path.join(__dirname,
    "../custom_components/weather_router/frontend/weather-router-lab-routing-diagnostics.js");
  vm.runInNewContext(fs.readFileSync(routingModulePath, "utf8"), {
    customElements: { get: () => FakeLab }, console: { info: () => {} },
  }, { filename: routingModulePath });

  let captured = null;
  let selectedCapability = "weather.radar.precipitation";
  const rawTrace = {
    schema: "weather_router.routing_diagnostic.v1",
    meta: { trace_id: "rt-test-001" },
    request: { capability: selectedCapability }, candidates: [],
    decision: { status: "ready" },
  };
  const routeState = {
    trace: rawTrace,
    manual: { capability: selectedCapability },
    capabilities: [
      { id: "weather.satellite.visible", name: "Visible" },
      { id: selectedCapability, name: "Precipitation" },
    ],
  };
  app._rdState = () => routeState;
  app._rdSetExportStatus = () => {};
  app._wrGitExportSnapshot = async snapshot => {
    captured = snapshot;
    return { path: "exports/weather-router/2026-10/routing-test/synthetic.json" };
  };
  app.shadowRoot = { getElementById(id) {
    if (id === "wr-rd-capability") return { value: selectedCapability };
    return null;
  } };
  await app._rdGitExport();
  assert.equal(captured.test.capabilityUiNumber, "001");
  assert.equal(captured.meta.trace_id, "rt-test-001");
  assert.equal(rawTrace.test, undefined, "Do not mutate original trace");

  // No catalogue match means no fabricated displayed capability number.
  selectedCapability = "weather.unknown.test";
  routeState.trace = {
    ...rawTrace, request: { capability: selectedCapability },
  };
  routeState.manual.capability = selectedCapability;
  captured = null;
  await app._rdGitExport();
  assert.ok(captured);
  assert.equal(captured.test.capabilityUiNumber, undefined);

  console.log("PASS: archive isolation (5), actual routing UI number, unknown-number protection (7 groups)");
}
main().catch(err => { console.error(err); process.exitCode = 1; });
