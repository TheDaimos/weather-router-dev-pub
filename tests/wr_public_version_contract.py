"""Prüft die tatsächliche Version in vier Oberflächen statt einen alten Fixwert."""
import re


def _value(content, pattern, surface):
    hits = re.findall(pattern, content, flags=re.MULTILINE)
    if len(hits) != 1:
        raise AssertionError(f"{surface}: genau eine Versionsangabe erwartet, gefunden {len(hits)}")
    return hits[0]


def assert_current_version_surfaces(case, backend, lab, loader):
    backend_build = _value(backend, r'^DEV_BUILD_VERSION:\s*Final\s*=\s*"(0\.10\.\d+)"', "Backend-Build")
    backend_loader = _value(backend, r'^DEV_LOADER_REV:\s*Final\s*=\s*"(0\.10-loader-\d+)"', "Backend-Loader")
    lab_build = _value(lab, r'^\s*(?:const\s+)?WR_LAB_BUILD_VERSION\s*=\s*"(0\.10\.\d+)"', "Labor-Build")
    loader_build = _value(loader, r'^\s*(?:const\s+)?WR_LAB_BUILD_VERSION\s*=\s*"(0\.10\.\d+)"', "Frontend-Loader-Build")
    frontend_loader = _value(loader, r'^\s*(?:const\s+)?LOADER_REV\s*=\s*"(0\.10-loader-\d+)"', "Frontend-Loader")
    case.assertEqual(backend_build, lab_build, "Backend und Labor nicht synchron")
    case.assertEqual(backend_build, loader_build, "Backend und Frontend-Loader nicht synchron")
    case.assertEqual(backend_loader, frontend_loader, "Loader-Kennungen nicht synchron")
