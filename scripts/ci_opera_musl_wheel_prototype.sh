#!/bin/sh
# F7: isolated GitHub Actions disposable-container feasibility test ONLY.
# No execution in Home Assistant Core, no installation or deployment.
set -eu

if [ "$GITHUB_ACTIONS" != "true" ] || [ "$WR_OPERA_ISOLATED_CI" != "1" ]; then
  echo "F7 WHEEL PROTOTYPE BLOCKED: isolated CI-only guard not satisfied" >&2
  exit 90
fi
if [ "$(uname -m)" != "x86_64" ]; then
  echo "F7 WHEEL PROTOTYPE BLOCKED: target currently x86_64 only" >&2
  exit 91
fi
if [ ! -r /etc/alpine-release ]; then
  echo "F7 WHEEL PROTOTYPE BLOCKED: Alpine container required" >&2
  exit 92
fi
if [ ! -d /wheelhouse ]; then
  echo "F7 WHEEL PROTOTYPE BLOCKED: explicit disposable wheelhouse required" >&2
  exit 93
fi

mode="$1"
case "$mode" in
  build)
    echo "F7 BUILD: alpine=$(cat /etc/alpine-release) arch=$(uname -m)"
    apk add --no-cache \
      python3 python3-dev py3-pip py3-numpy py3-numpy-dev cython py3-setuptools py3-wheel \
      py3-packaging build-base linux-headers gdal-dev gdal-tools \
      patchelf
    python3 -m venv --system-site-packages /tmp/f7-build-venv
    echo "F7 BUILD: python=$(python3 --version), GDAL=$(gdal-config --version)"
    /tmp/f7-build-venv/bin/python -m pip install --disable-pip-version-check \
      --only-binary=:all: "auditwheel==6.8.2"
    mkdir -p /wheelhouse/raw /wheelhouse/repaired
    # Build from authentic Rasterio source, against native Alpine GDAL headers.
    # This is NOT a Home Assistant install, not an official package publication.
    GDAL_CONFIG=/usr/bin/gdal-config /tmp/f7-build-venv/bin/python -m pip wheel \
      --disable-pip-version-check --no-deps --no-build-isolation \
      --no-binary rasterio --wheel-dir /wheelhouse/raw "rasterio==1.5.2"
    set -- /wheelhouse/raw/rasterio-1.5.2-cp314-cp314-linux_x86_64.whl
    if [ ! -f "$1" ]; then
      echo "F7 BUILD FAIL: source compilation did not yield exact CP314 Linux wheel" >&2
      exit 94
    fi
    /tmp/f7-build-venv/bin/auditwheel show "$1"
    # Repair must actually bundle native GDAL/PROJ dependencies; relabeling
    # alone is insufficient. A clean runtime will check the repaired result.
    /tmp/f7-build-venv/bin/auditwheel repair \
      --plat musllinux_1_2_x86_64 --wheel-dir /wheelhouse/repaired "$1"
    /tmp/f7-build-venv/bin/auditwheel show /wheelhouse/repaired/*.whl
    echo "F7 BUILD-PROTOTYPE READY FOR ISOLATED RUNTIME; NOT DISTRIBUTABLE"
    ;;
  verify)
    echo "F7 VERIFY: fresh alpine=$(cat /etc/alpine-release) arch=$(uname -m)"
    # This must be a SECOND fresh disposable Alpine container, without
    # gdal-dev, gdal-libs, py3-rasterio, py3-pyproj or build-tool APKs.
    apk add --no-cache python3 py3-pip py3-numpy py3-pillow
    if apk info -e gdal-libs >/dev/null 2>&1; then
      echo "F7 VERIFY FAIL: fresh runtime unexpectedly has GDAL installed" >&2
      exit 95
    fi
    python3 -m venv --system-site-packages /tmp/f7-runtime-venv
    /tmp/f7-runtime-venv/bin/python -m pip install --disable-pip-version-check \
      --only-binary=:all: "affine" "attrs" "certifi" "click" "cligj" "click-plugins" "pyparsing"
    set -- /wheelhouse/repaired/rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl
    if [ ! -f "$1" ]; then
      echo "F7 VERIFY FAIL: no exact CP314 musllinux x86_64 repaired wheel" >&2
      exit 96
    fi
    # Archive must contain actual GDAL shared objects, not just a wheel tag.
    /tmp/f7-runtime-venv/bin/python - "$1" <<'PY'
import sys
import zipfile
wheel = sys.argv[1]
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    gdal = [name for name in names if "libgdal" in name.lower() and ".so" in name]
    proj = [name for name in names if "libproj" in name.lower() and ".so" in name]
    if not gdal or not proj:
        raise SystemExit("F7 VERIFY FAIL: native GDAL/PROJ not bundled; tag alone is invalid")
    print("F7 VERIFY: bundled GDAL objects=", len(gdal), "PROJ objects=", len(proj))
PY
    /tmp/f7-runtime-venv/bin/python -m pip install --disable-pip-version-check \
      --no-deps "$1"
    /tmp/f7-runtime-venv/bin/python -I -c '
import numpy, rasterio
from rasterio.warp import reproject
print("F7 VERIFY: actual native import", rasterio.__version__,
      rasterio.__gdal_version__, rasterio.__proj_version__, numpy.__version__)
'
    # Run the existing actual WR tile renderer in an isolated native context.
    /tmp/f7-runtime-venv/bin/python scripts/probe_opera_raster_runtime.py
    /tmp/f7-runtime-venv/bin/python scripts/probe_opera_concurrent_raster.py
    echo "F7 ISOLATED CP314 MUSL NATIVE-PROBE PASS; HA INSTALLATION BLOCKED"
    ;;
  *)
    echo "Usage: script build|verify (only inside ephemeral CI Alpine containers)" >&2
    exit 97
    ;;
esac
