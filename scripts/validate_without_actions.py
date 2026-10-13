#!/usr/bin/env python3
"""WeatherRouter: reproduce core CI checks locally without GitHub Actions.

Run from a complete, clean checkout using Python 3.13 and Node.js:
    python scripts/validate_without_actions.py

No GitHub API, credentials or network connection is required by this runner.
Individual repository tests remain responsible for avoiding external requests.
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "weather_router"


def execute(command: list[str], *, title: str, output: Path, timeout: int = 900) -> dict:
    start = perf_counter()
    log = output / (re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") + ".log")
    with log.open("w", encoding="utf-8") as handle:
        try:
            run = subprocess.run(
                command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                timeout=timeout, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            code = run.returncode
            error = None
        except subprocess.TimeoutExpired:
            code, error = 124, "Zeitüberschreitung"
        except OSError as exc:
            code, error = 127, f"Programm konnte nicht gestartet werden: {type(exc).__name__}"
    result = {
        "name": title,
        "status": "PASS" if code == 0 else "FAIL",
        "exit_code": code,
        "duration_seconds": round(perf_counter() - start, 2),
        "log": str(log),
    }
    if error:
        result["error"] = error
    print(f"[{'OK' if code == 0 else 'FEHLER'}] {title} ({result['duration_seconds']} s)", flush=True)
    return result


def parse_python_and_json(output: Path) -> dict:
    start = perf_counter()
    paths = [ROOT / name for name in ("custom_components/weather_router", "tests", "scripts", "contracts", "docs")]
    py_files = sorted(p for folder in paths if folder.exists() for p in folder.rglob("*.py"))
    json_files = sorted(p for folder in paths if folder.exists() for p in folder.rglob("*.json"))
    failures = []
    for file in py_files:
        try:
            ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except (SyntaxError, UnicodeError, OSError) as exc:
            failures.append({"file": str(file.relative_to(ROOT)), "error": type(exc).__name__})
    for file in json_files:
        try:
            json.loads(file.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError, OSError) as exc:
            failures.append({"file": str(file.relative_to(ROOT)), "error": type(exc).__name__})
    result = {
        "name": "Python-Syntax und JSON-Dateien",
        "status": "PASS" if not failures else "FAIL",
        "duration_seconds": round(perf_counter() - start, 2),
        "python_files": len(py_files), "json_files": len(json_files),
        "failures": failures[:30],
    }
    (output / "syntax-json-summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"[{'OK' if not failures else 'FEHLER'}] Python/JSON: {len(py_files)} / {len(json_files)}", flush=True)
    return result


def package_component(output: Path) -> dict:
    start = perf_counter()
    archive = output / "WeatherRouter_v0.10.0_DEV.zip"
    if not COMPONENT.is_dir():
        return {"name": "Installationspaket", "status": "FAIL", "error": "Integration fehlt"}
    files = sorted(
        f for f in COMPONENT.rglob("*") if f.is_file()
        and not any(part in {"__pycache__", ".git", ".pytest_cache"} for part in f.parts)
        and f.suffix not in {".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx"}
        and not f.name.startswith(".env")
    )
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for file in files:
            zipped.write(file, file.relative_to(ROOT).as_posix())
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "WeatherRouter_v0.10.0_DEV.zip.sha256").write_text(
        f"{sha}  {archive.name}\n", encoding="ascii"
    )
    print(f"[OK] Installationspaket: {len(files)} Dateien", flush=True)
    return {"name": "Installationspaket", "status": "PASS", "files": len(files),
            "sha256": sha, "archive": str(archive),
            "duration_seconds": round(perf_counter() - start, 2)}


def git_info() -> dict:
    def command(*args: str) -> str:
        try:
            run = subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, text=True,
                timeout=10, check=False,
            )
            return run.stdout.strip() if run.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""
    return {
        "commit": command("rev-parse", "HEAD") or None,
        "branch": command("branch", "--show-current") or None,
        "clean": not bool(command("status", "--porcelain")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="WeatherRouter: Offline-Ersatz für GitHub-Actions-Prüfungen")
    parser.add_argument("--output", help="Privater Zielordner für Protokolle (Standard: System-Temp)")
    parser.add_argument("--allow-dirty", action="store_true", help="Nur für Entwicklung; keine Freigabe")
    args = parser.parse_args()
    output = Path(args.output).expanduser().resolve() if args.output else Path(
        tempfile.mkdtemp(prefix="weather-router-validation-")
    )
    output.mkdir(parents=True, exist_ok=True)
    revision = git_info()
    results = []
    results.append({"name": "Nachvollziehbarer Quellstand", "status": "PASS" if
                    revision["commit"] and (revision["clean"] or args.allow_dirty) else "FAIL",
                    "git": revision})
    results.append({"name": "Python 3.13", "status": "PASS" if
                    sys.version_info[:2] == (3, 13) else "FAIL",
                    "actual": ".".join(map(str, sys.version_info[:3]))})
    results.append(parse_python_and_json(output))
    results.append(execute([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
                           title="Vollständige Python-Regressionstests", output=output))
    results.append(execute([sys.executable, "scripts/verify_m2_structure.py"],
                           title="Verbindliche Strukturprüfung", output=output))
    js_files = sorted((COMPONENT / "frontend").rglob("*.js"))
    if not js_files:
        results.append({"name": "JavaScript-Syntax", "status": "FAIL", "error": "Keine Dateien vorhanden"})
    elif not shutil.which("node"):
        results.append({"name": "JavaScript-Syntax", "status": "FAIL", "error": "Node.js fehlt"})
    else:
        for file in js_files:
            results.append(execute(["node", "--check", str(file)],
                                   title="JS " + file.name, output=output, timeout=60))
    if shutil.which("node") and (ROOT / "tests" / "test_git_export_frontend.cjs").is_file():
        results.append(execute(["node", "tests/test_git_export_frontend.cjs"],
                               title="Git-Export Oberflächenregression", output=output, timeout=60))
    else:
        results.append({"name": "Git-Export Oberflächenregression", "status": "FAIL",
                        "error": "Node.js oder zugehöriger Test fehlt"})
    ok = all(r["status"] == "PASS" for r in results)
    if ok:
        try:
            results.append(package_component(output))
        except (OSError, zipfile.BadZipFile) as exc:
            results.append({"name": "Installationspaket", "status": "FAIL",
                            "error": type(exc).__name__})
    ok = all(r["status"] == "PASS" for r in results)
    report = {
        "schema": "weather_router.offline_validation.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git": revision,
        "python": sys.version.split()[0],
        "node": shutil.which("node") is not None,
        "result": "PASS" if ok else "FAIL",
        "tests": results,
        "notes": "Ersetzt keinen realen Home-Assistant-Abnahmetest. Protokolle lokal vertraulich behandeln.",
    }
    target = output / "validation-report.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{'ALLE PRÜFUNGEN BESTANDEN' if ok else 'PRÜFUNGEN NICHT VOLLSTÄNDIG BESTANDEN'}")
    print(f"Nachweis: {target}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
