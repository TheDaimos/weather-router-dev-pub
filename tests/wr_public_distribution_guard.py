#!/usr/bin/env python3
"""Prueft oeffentliche Verteilungsdateien und lokal versionierte Dateien.
Kein Ersatz fuer manuelle Datenschutz- und Lizenzpruefung.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_COMPONENTS = {'.git', '.weather-router', '.deploy-relay', '__pycache__', 'wr-private-source', 'wr-history-source', 'wr-legacy-stage', 'wr-private-archive-candidate'}
FORBIDDEN_SUFFIXES = {'.pem', '.p12', '.pfx', '.key', '.pyc'}
FORBIDDEN_NAMES = {'.env', 'secrets.yaml', 'secrets.yml', 'known_hosts', 'id_rsa', 'id_ed25519'}
ALLOWED_PY = ROOT / 'custom_components/weather_router/extensions.py'
problems = []

# Git gibt bereits versionierte Dateien unabhaengig von .gitignore zurueck.
# Neue, nicht ignorierte Dateien werden zusaetzlich beruecksichtigt.
# GitHub Actions hat damit ebenfalls nur Inhalte im Blick, die veroeffentlicht werden koennen.
result = subprocess.run(['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], capture_output=True)
if result.returncode == 0:
    paths = [ROOT / p.decode('utf-8', errors='surrogateescape') for p in result.stdout.split(b'\0') if p]
else:
    # Kein Git-Repository: lokale Caches ignorieren, private Verzeichnisse aber weiterhin pruefen.
    paths = [p for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.relative_to(ROOT).parts and p.suffix.lower() != '.pyc' and '.git' not in p.relative_to(ROOT).parts]

for path in paths:
    if not path.is_file():
        continue
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if set(parts) & FORBIDDEN_COMPONENTS:
        problems.append('Unzulaessiges Verzeichnis: ' + str(rel))
    if path.name.lower() in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
        problems.append('Geheimnis-/Schluessel-/Cachedatei: ' + str(rel))
    if parts[:2] == ('exports', 'weather-router'):
        problems.append('Historischer Export: ' + str(rel))
if not ALLOWED_PY.is_file():
    problems.append('Gewollter generischer Erweiterungslader fehlt')
if problems:
    for problem in sorted(set(problems)):
        print('FEHLER:', problem)
    sys.exit(1)
print('OK: Verteilungsschutz bestanden (keine Veroeffentlichungsfreigabe).')
