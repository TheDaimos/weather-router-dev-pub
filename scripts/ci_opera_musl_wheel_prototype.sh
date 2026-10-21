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
      patchelf binutils
    python3 -m venv --system-site-packages /tmp/f7-build-venv
    echo "F7 BUILD: python=$(python3 --version), GDAL=$(gdal-config --version)"
    /tmp/f7-build-venv/bin/python -m pip install --disable-pip-version-check \
      --only-binary=:all: "auditwheel==6.8.2"
    mkdir -p /wheelhouse/raw /wheelhouse/repaired /wheelhouse/repaired-repeat
    # Build from authentic Rasterio source, against native Alpine GDAL headers.
    # This is NOT a Home Assistant install, not an official package publication.
    # Deterministic-build EXPERIMENT, disposable CI ONLY. Pin the build
    # timestamp and eliminate pip's random source extraction directories.
    # This does not attest the downloaded source's authenticity or licenses.
    export SOURCE_DATE_EPOCH=1704067200
    export CFLAGS="${CFLAGS:+$CFLAGS }-ffile-prefix-map=/tmp/f7-opera-repro-source=/usr/src/f7-rasterio -fdebug-prefix-map=/tmp/f7-opera-repro-source=/usr/src/f7-rasterio"
    mkdir -p /wheelhouse/source /wheelhouse/raw-repeat
    /tmp/f7-build-venv/bin/python -m pip download \
      --disable-pip-version-check --no-cache-dir --no-deps --no-build-isolation \
      --no-binary=:all: --dest /wheelhouse/source "rasterio==1.5.2"
    # Independently published Rasterio 1.5.2 Sdist SHA-256 from official
    # PyPI release https://pypi.org/project/rasterio/1.5.2/ (2026-09-30).
    # This verifies exact SOURCE bytes, NOT full downstream toolchain trust.
    echo "e65a15b7bd22ce8f8ce8159856669dc9fafabf66cde6156e8f8e71d55abcd515  /wheelhouse/source/rasterio-1.5.2.tar.gz" | sha256sum -c -
    python3 scripts/f7_prepare_fixed_source.py \
      /wheelhouse/source/rasterio-1.5.2.tar.gz \
      > /wheelhouse/f7-fixed-source-first.json
    PACKAGE_DATA=1 GDAL_CONFIG=/usr/bin/gdal-config GDAL_DATA=/usr/share/gdal \
      PROJ_DATA=/usr/share/proj /tmp/f7-build-venv/bin/python -m pip wheel \
      --disable-pip-version-check --no-cache-dir --no-deps --no-build-isolation \
      --wheel-dir /wheelhouse/raw /tmp/f7-opera-repro-source/rasterio-1.5.2
    # Freshly unpack the same Sdist to the SAME fixed source path, restoring
    # a clean tree. Never run pip on a wheel left by the previous build.
    python3 scripts/f7_prepare_fixed_source.py \
      /wheelhouse/source/rasterio-1.5.2.tar.gz \
      > /wheelhouse/f7-fixed-source-second.json
    cmp -s /wheelhouse/f7-fixed-source-first.json /wheelhouse/f7-fixed-source-second.json
    cp /wheelhouse/f7-fixed-source-first.json /wheelhouse/f7-fixed-source-unapproved.json
    PACKAGE_DATA=1 GDAL_CONFIG=/usr/bin/gdal-config GDAL_DATA=/usr/share/gdal \
      PROJ_DATA=/usr/share/proj /tmp/f7-build-venv/bin/python -m pip wheel \
      --disable-pip-version-check --no-cache-dir --no-deps --no-build-isolation \
      --wheel-dir /wheelhouse/raw-repeat /tmp/f7-opera-repro-source/rasterio-1.5.2
    python3 scripts/probe_opera_raw_elf_drift.py \
      /wheelhouse/raw/rasterio-1.5.2-cp314-cp314-linux_x86_64.whl \
      /wheelhouse/raw-repeat/rasterio-1.5.2-cp314-cp314-linux_x86_64.whl \
      > /wheelhouse/f7-raw-elf-drift-unapproved.json
    python3 - <<'PY'
import json
from pathlib import Path
report = json.loads(Path("/wheelhouse/f7-raw-elf-drift-unapproved.json").read_text())
assert report["extensions_count"] == 15
assert report["status"] == "DIAGNOSTIC_ONLY_NOT_DISTRIBUTABLE"
assert not report["wheel_reproducibility_proven"]
assert report["ha_installation"] == "BLOCKED"
print("F7 REAL DOUBLE SOURCE BUILD ELF:", report["changed_extensions"],
      "of", report["extensions_count"], "changed extensions;",
      "root cause and distribution NOT approved")
PY
    set -- /wheelhouse/raw/rasterio-1.5.2-cp314-cp314-linux_x86_64.whl
    if [ ! -f "$1" ]; then
      echo "F7 BUILD FAIL: source compilation did not yield exact CP314 Linux wheel" >&2
      exit 94
    fi
    /tmp/f7-build-venv/bin/auditwheel show "$1"
    # F7-L08: instrument the actual auditwheel-invoked patchelf commands.
    # This shim lives ONLY in the disposable container; no installed code.
    mkdir -p /tmp/f7-patchelf-trace-bin
    printf '#!/bin/sh\\nexec python3 /wr/scripts/f7_trace_real_patchelf.py "$@"\\n' > /tmp/f7-patchelf-trace-bin/patchelf
    chmod 700 /tmp/f7-patchelf-trace-bin/patchelf
    : > /wheelhouse/f7-patchelf-operations-unapproved.jsonl
    export PATH="/tmp/f7-patchelf-trace-bin:$PATH"
    # Repair must actually bundle native GDAL/PROJ dependencies; relabeling
    # alone is insufficient. A clean runtime will check the repaired result.
    /tmp/f7-build-venv/bin/auditwheel repair \
      --plat musllinux_1_2_x86_64 --wheel-dir /wheelhouse/repaired "$1"
    # Second genuine repair of the SAME bit-identical raw wheel, in a separate
    # output directory. The comparator reports both file-level and ZIP metadata
    # drift without modifying the resulting binaries or asserting approval.
    /tmp/f7-build-venv/bin/auditwheel repair \
      --plat musllinux_1_2_x86_64 --wheel-dir /wheelhouse/repaired-repeat "$1"
    python3 scripts/probe_f7_repaired_double.py \
      /wheelhouse/repaired/rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl \
      /wheelhouse/repaired-repeat/rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl \
      > /wheelhouse/f7-repaired-double-unapproved.json
    python3 - <<'PY'
import json
from pathlib import Path
r = json.loads(Path("/wheelhouse/f7-repaired-double-unapproved.json").read_text())
assert r["distribution"] == "BLOCKED" and r["ha_installation"] == "BLOCKED"
print("F7 REPAIRED REAL DOUBLE:", r["status"], "changed members=", r["different_member_count"])
PY
    /tmp/f7-build-venv/bin/python -m pip show auditwheel | grep '^Version:' > /wheelhouse/f7-auditwheel-version.txt
    patchelf --version > /wheelhouse/f7-patchelf-version.txt
    python3 scripts/f7_auditwheel_repair_replay.py \
      /wheelhouse/raw/rasterio-1.5.2-cp314-cp314-linux_x86_64.whl \
      /wheelhouse/repaired/rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl \
      /wheelhouse/repaired-repeat/rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl \
      "$(/tmp/f7-build-venv/bin/python -m pip show auditwheel | sed -n 's/^Version: //p')" \
      "$(patchelf --version)" \
      /wheelhouse/f7-auditwheel-replay-unapproved.json
    # Capture actual subprocess commands, do not assert complete Python copy trace.
    python3 scripts/f7_verify_patchelf_trace.py \\
      /wheelhouse/f7-patchelf-operations-unapproved.jsonl \\
      /wheelhouse/f7-patchelf-trace-summary-unapproved.json
    /tmp/f7-build-venv/bin/auditwheel show /wheelhouse/repaired/*.whl
    # Build and inventory in the SAME disposable Alpine job; preserve only
    # an unapproved JSON evidence artifact. Do not publish or upload the wheel.
    set -- /wheelhouse/repaired/rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl
    candidate_sha="$(sha256sum "$1" | cut -d ' ' -f1)"
    python3 scripts/inventory_opera_native_wheel.py "$1" "$candidate_sha" --require-elf \
      > /wheelhouse/f7-native-inventory.json
    python3 - <<'PY'
import json
from pathlib import Path
report = json.loads(Path("/wheelhouse/f7-native-inventory.json").read_text())
assert report["status"] == "UNAPPROVED_NOT_DISTRIBUTABLE"
assert report["native_elf_count"] > 0
assert report["files_count"] > 0
assert not report["source_provenance_verified"]
assert report["ha_installation"] == "BLOCKED"
print("F7 REAL WHEEL ELF INVENTORY:", report["files_count"],
      "files,", report["native_elf_count"], "ELF objects,",
      len(report["elf_external_dependency_names"]), "external dependency names;",
      "license review REQUIRED and distribution BLOCKED")
PY
    # Attribute bundled ELF names to installed Alpine package records,
    # if possible; this does NOT prove license obligations or provenance.
    python3 scripts/audit_opera_native_apk_licenses.py \
      /wheelhouse/f7-native-inventory.json /lib/apk/db/installed \
      > /wheelhouse/f7-native-apk-license-candidates.json
    python3 - <<'PY'
import json
from pathlib import Path
r = json.loads(Path("/wheelhouse/f7-native-apk-license-candidates.json").read_text())
assert r["native_elf_count"] > 0
assert r["status"] == "UNAPPROVED_NOT_DISTRIBUTABLE"
assert r["ha_installation"] == "BLOCKED"
assert not r["mapping_is_binary_hash_verified"]
assert not r["full_sbom_approved"]
print("F7 SOURCE CANDIDATES:", r["apk_filename_candidate_count"],
      "APK name-only matches,", r["unresolved_component_count"],
      "unresolved native ELF objects;", "license clearance BLOCKED")
PY
    # Direct, measured origin chain: actual /usr/lib ELF bytes vs the Wheel.
    # Fetch exact Alpine APK archives only in the FIRST isolated builder.
    # No APK is installed, uploaded, or copied to the user/HA.
    if [ "${WR_F7_APK_ORIGIN_FETCH:-0}" = "1" ]; then
      if ! python3 scripts/f7_fetch_official_apks.py \
          /wheelhouse/f7-native-apk-license-candidates.json \
          /wheelhouse/f7-official-apks-unapproved.json; then
        # External network availability must never become a false approval.
        python3 - <<'PY'
import json
from pathlib import Path
a=json.loads(Path("/wheelhouse/f7-native-apk-license-candidates.json").read_text())
Path("/wheelhouse/f7-official-apks-unapproved.json").write_text(json.dumps({
    "schema":"weather_router.f7.official_apk_archive_candidates.v1",
    "status":"OFFICIAL_FETCH_UNAVAILABLE_NOT_VERIFIED",
    "wheel_sha256":a["wheel_sha256"],"packages":[],
    "apk_fetched_count":0,"apk_signature_verified_using_ci_keys_count":0,
    "binary_distribution":"BLOCKED","ha_installation":"BLOCKED",
    "opera_activation":"BLOCKED"},indent=2)+"\n")
PY
      fi
      python3 scripts/f7_compare_installed_elf.py \
        /wheelhouse/f7-native-inventory.json \
        /wheelhouse/f7-native-apk-license-candidates.json \
        /lib/apk/db/installed \
        /wheelhouse/repaired/rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl \
        /wheelhouse/f7-original-elf-comparison-unapproved.json \
        /wheelhouse/apk-originals
      # Record original and repaired ELF dynamic tags before any release gate.
      # Read-only, deliberately NOT treated as replay or provenance approval.
      python3 scripts/f7_observe_elf_dynamic_transform.py \
        /wheelhouse/f7-original-elf-comparison-unapproved.json \
        /wheelhouse/repaired/rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl \
        /wheelhouse/f7-elf-dynamic-observation-unapproved.json
      python3 scripts/f7_correlate_apk_archives.py \
        /wheelhouse/f7-original-elf-comparison-unapproved.json \
        /wheelhouse/f7-official-apks-unapproved.json \
        /wheelhouse/apk-originals \
        /wheelhouse/f7-apk-member-correlation-unapproved.json
      python3 scripts/f7_apk_license_docs.py \
        /wheelhouse/f7-official-apks-unapproved.json \
        /wheelhouse/apk-originals \
        /wheelhouse/f7-apk-license-docs-unapproved.json
      python3 scripts/f7_original_binary_release_gate.py \
        /wheelhouse/f7-original-elf-comparison-unapproved.json \
        /wheelhouse/f7-apk-member-correlation-unapproved.json \
        /wheelhouse/f7-apk-license-docs-unapproved.json \
        /wheelhouse/f7-original-binary-release-gate-unapproved.json
      python3 scripts/f7_consolidate_elf_matrix.py \
        /wheelhouse/f7-original-elf-comparison-unapproved.json \
        /wheelhouse/f7-apk-member-correlation-unapproved.json \
        /wheelhouse/f7-apk-license-docs-unapproved.json \
        /wheelhouse/f7-official-apks-unapproved.json \
        /wheelhouse/f7-101-elf-original-origin-license-matrix-unapproved.md
    fi
    python3 scripts/f7_build_input_snapshot.py /lib/apk/db/installed "$candidate_sha" "${WR_F7_IMAGE_DIGEST:?pinned_image_digest_required}" > /wheelhouse/f7-build-inputs-unapproved.json
    # Every one of the 101 native ELF files must become a candidate BOM row,
    # including the un-attributed components. No license/security approval.
    python3 scripts/f7_generate_sbom.py \
      /wheelhouse/f7-native-inventory.json \
      /wheelhouse/f7-native-apk-license-candidates.json \
      /wheelhouse/f7-cyclonedx-unapproved.json \
      /wheelhouse/f7-sbom-quality-unapproved.json
    python3 scripts/f7_native_size_scope.py \
      /wheelhouse/f7-native-inventory.json \
      /wheelhouse/f7-native-size-scope-unapproved.json
    python3 scripts/f7_elf_license_matrix.py \
      /wheelhouse/f7-native-inventory.json \
      /wheelhouse/f7-native-apk-license-candidates.json \
      /wheelhouse/f7-101-elf-license-matrix-unapproved.md
    # Security feeds are external advisory candidates only. If the public
    # Alpine feed is unavailable, preserve explicit NOT_SCANNED evidence.
    mkdir -p /wheelhouse/f7-secdb
    if wget -q -T 12 -O /wheelhouse/f7-secdb/main.json \
         https://secdb.alpinelinux.org/v3.24/main.json \
       && wget -q -T 12 -O /wheelhouse/f7-secdb/community.json \
         https://secdb.alpinelinux.org/v3.24/community.json; then
      if ! python3 scripts/f7_alpine_secdb_candidates.py \
           /wheelhouse/f7-build-inputs-unapproved.json \
           /wheelhouse/f7-secdb/main.json /wheelhouse/f7-secdb/community.json \
           /wheelhouse/f7-secdb-candidates-unapproved.json; then
        printf '%s\n' '{"schema":"weather_router.f7.secdb_feed_status.v1","status":"FEED_OR_VERSION_COMPARISON_UNAVAILABLE","vulnerability_review":"REQUIRED","ha_installation":"BLOCKED"}' \
          > /wheelhouse/f7-secdb-candidates-unapproved.json
      fi
    else
      printf '%s\n' '{"schema":"weather_router.f7.secdb_feed_status.v1","status":"FEED_UNAVAILABLE_NOT_SCANNED","vulnerability_review":"REQUIRED","ha_installation":"BLOCKED"}' \
        > /wheelhouse/f7-secdb-candidates-unapproved.json
    fi

    python3 - <<'PY'
import json
from pathlib import Path
bom=json.loads(Path("/wheelhouse/f7-cyclonedx-unapproved.json").read_text())
quality=json.loads(Path("/wheelhouse/f7-sbom-quality-unapproved.json").read_text())
assert len(bom["components"])==101
assert quality["elf_included"]==101
assert quality["elf_unverified_origin"]==101
assert quality["ha_installation"]=="BLOCKED"
print("F7 CANDIDATE CYCLONEDX:",len(bom["components"]),
      "ELF-file components; license/security/distribution not approved")
PY

    echo "F7 BUILD-PROTOTYPE INVENTORIED IN ISOLATED CI; NOT DISTRIBUTABLE"
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
    # The actual operator HA DEV has NumPy 2.3.2 and Pillow 12.3.0,
    # not the newer Alpine preinstalled versions used to build the wheel.
    # An isolated venv shadows those APK packages with exact tested pins.
    /tmp/f7-runtime-venv/bin/python -m pip install --disable-pip-version-check \
      --only-binary=:all: "numpy==2.3.2" "Pillow==12.3.0"
    /tmp/f7-runtime-venv/bin/python -I -c '
import numpy, PIL
assert numpy.__version__ == "2.3.2", numpy.__version__
assert PIL.__version__ == "12.3.0", PIL.__version__
print("F7 VERIFY: exact HA DEV NumPy/Pillow package versions", numpy.__version__, PIL.__version__)
'
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
    if not any(name.endswith("rasterio/proj_data/proj.db") for name in names):
        raise SystemExit("F7 VERIFY FAIL: essential PROJ database not bundled")
    if not any(name.endswith("rasterio/gdal_data/gdalvrt.xsd") for name in names):
        raise SystemExit("F7 VERIFY FAIL: essential GDAL data not bundled")
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
    if [ -d /runtime-evidence ]; then
      /tmp/f7-runtime-venv/bin/python \
        scripts/probe_f7_native_driver_scope.py \
        /runtime-evidence/f7-native-driver-scope-unapproved.json
    fi
    echo "F7 ISOLATED CP314 MUSL NATIVE-PROBE PASS; HA INSTALLATION BLOCKED"
    ;;
  *)
    echo "Usage: script build|verify (only inside ephemeral CI Alpine containers)" >&2
    exit 97
    ;;
esac
