"""Public OPERA original-pair science verification. No production code or approval."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import h5py
import numpy as np
import rasterio
from pyproj import CRS

ROOT = Path(__file__).resolve().parent / "fixtures" / "opera"
PATTERN = re.compile(r"OPERA@(20\d{6}T\d{4})@0@RATE\.(h5|tiff)$")
REF_VALID = (329116, 330764, 330456, 330511, 327191, 328902, 328006)
REF_TIMES = ("0600", "0615", "0630", "0645", "0700", "0715", "0730")
REF_MAX = (1.2207031261368684e-05, 6.713867179541921e-06,
           1.2207031261368684e-05, 2.6855468718167685e-05,
           1.2207031261368684e-05, 6.713867179541921e-06,
           1.464843751364242e-05)


def attr(v):
    if isinstance(v, (bytes, np.bytes_)):
        return bytes(v).decode("ascii").strip("\x00 ")
    return str(v).strip("\x00 ")


def manifest_files():
    manifests = [ROOT / "manifest.json",
                 ROOT / "2026-10-25" / "manifest-sturm-20261025.json"]
    result = {}
    for m in manifests:
        data = json.loads(m.read_text(encoding="utf-8-sig"))
        assert data["product"] == "EUMETNET OPERA-RATE"
        for e in data["files"]:
            name = e["filename"]
            hit = PATTERN.fullmatch(name)
            assert hit and name not in result, name
            stamp = hit.group(1)
            date = datetime.strptime(stamp, "%Y%m%dT%H%M").replace(tzinfo=timezone.utc)
            assert date.date().isoformat() == data["date_utc"]
            path = (ROOT / data["date_utc"] / name) if data["date_utc"] == "2026-10-25" else ROOT / "2026-10-26" / name
            assert path.is_file() and not path.is_symlink(), name
            assert path.stat().st_size == e["size_bytes"], "LFS or size mismatch: " + name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == e["sha256"], "SHA mismatch: " + name
            result[name] = (path, digest)
    assert len(result) == 38, len(result)
    assert len(list(ROOT.rglob("OPERA@*RATE.*"))) == 38
    return result


def _chunks(path, tif, source, gain, offset, nodata, undetect):
    height, width = source.shape
    good = badmask = qual_good = qual_total = 0
    maxdiff = 0.
    other = 0
    # Bounded row strips (avoid full original raster copies).
    for y in range(0, height, 128):
        stop = min(height, y + 128)
        raw = source[y:stop, :]
        t = tif.read(1, window=((y, stop), (0, width)), masked=False)
        h_no = np.isfinite(raw) & (raw == nodata)
        h_un = np.isfinite(raw) & (raw == undetect)
        h_valid = np.isfinite(raw) & ~h_no & ~h_un
        t_no = np.isfinite(t) & (t == tif.nodata)
        t_un = np.isnan(t)
        t_valid = np.isfinite(t) & ~t_no & ~t_un
        assert np.array_equal(h_valid, t_valid), "validity mask mismatch"
        assert np.array_equal(h_no, t_no), "nodata category mismatch"
        assert np.array_equal(h_un, t_un), "undetect/NaN category mismatch"
        if np.any(h_valid):
            calibrated = raw[h_valid].astype(np.float64) * gain + offset
            difference = np.abs(calibrated - t[h_valid])
            assert np.all(difference <= 1e-4), "RATE calibration mismatch"
            maxdiff = max(maxdiff, float(np.max(difference)))
            good += int(h_valid.sum())
        # Flip-check strictly on physical valid values: the alternative cannot
        # match identically without independent evidence.
        q = tif.read(2, window=((y, stop), (0, width)), masked=False)
        quality = source.file["dataset1/data1/quality1/data"][y:stop, :]
        assert q.shape == quality.shape
        assert np.allclose(q, quality, rtol=0, atol=1e-5, equal_nan=True), "quality mismatch"
        qual_good += int(np.count_nonzero(np.isclose(q, quality, rtol=0, atol=1e-5, equal_nan=True)))
        qual_total += quality.size
    return {"valid_pixels": good, "max_difference_mmh": maxdiff,
            "quality_matching_pixels": qual_good, "quality_total_pixels": qual_total,
            "mask_disagreements": 0}


def compare(path_h5, path_tiff, stamp):
    with h5py.File(path_h5, "r") as h, rasterio.open(path_tiff) as t:
        assert h["dataset1/data1/data"].shape == (2200, 1900)
        assert t.width == 1900 and t.height == 2200 and t.count == 2
        ds = h["dataset1/data1/data"]
        attrs = h["dataset1/data1/what"].attrs
        gain, offset, nodata, undetect = (float(attrs[k]) for k in
                                           ("gain", "offset", "nodata", "undetect"))
        assert np.isfinite([gain, offset, nodata, undetect]).all()
        assert gain > 0 and nodata != undetect
        assert attr(attrs["quantity"]) == "RATE"
        assert attr(h["what"].attrs["date"]) == stamp[:8]
        assert attr(h["what"].attrs["time"])[:4] == stamp[9:13]
        assert CRS.from_user_input(attr(h["where"].attrs["projdef"])).equals(CRS.from_user_input(t.crs))
        assert t.transform.a > 0 and t.transform.e < 0 and t.transform.b == 0 and t.transform.d == 0
        assert abs(t.transform.a - 2000) < 0.001 and abs(t.transform.e + 2000) < 0.001
        result = _chunks(path_h5, t, ds, gain, offset, nodata, undetect)
        result.update(utc=stamp, crs=str(t.crs), row_zero_north=True,
                      independent_meteorological_approval=False,
                      scientific_tile_approved=False)
        return result


def main():
    files = manifest_files()
    groups = {}
    for name, (path, digest) in files.items():
        stamp, ext = PATTERN.fullmatch(name).groups()
        groups.setdefault(stamp, {})[ext] = (path, digest)
    assert len(groups) == 19 and all(set(v) == {"h5", "tiff"} for v in groups.values())
    results = []
    for stamp, group in sorted(groups.items()):
        result = compare(group["h5"][0], group["tiff"][0], stamp)
        result["hdf5_sha256"] = group["h5"][1]
        result["geotiff_sha256"] = group["tiff"][1]
        result["reference_group"] = "SCI02_SEVEN" if stamp.startswith("20261026") else "HISTORIC_TWELVE"
        if stamp.startswith("20261026"):
            index = REF_TIMES.index(stamp[9:13])
            assert result["valid_pixels"] == REF_VALID[index], "SCI02 valid-pixel regression"
            assert result["max_difference_mmh"] <= 1e-4
            assert result["max_difference_mmh"] <= REF_MAX[index] + 1e-6
            assert result["quality_matching_pixels"] == 4180000
        results.append(result)
        print(stamp, result["valid_pixels"], result["max_difference_mmh"], flush=True)
    assert len(results) == 19
    out = Path("opera-science-results.json")
    out.write_text(json.dumps({"pair_count": 19, "reference_count": 7,
                               "historical_count": 12,
                               "scientific_release": False,
                               "pairs": results}, indent=2) + "\n", encoding="utf-8")
    Path("opera-science-summary.md").write_text(
        "# OPERA SCI-05 original checks\n\n19 pairs processed; science release remains blocked.\n"
        + "\n".join(f"- {r['utc']}: {r['valid_pixels']} valid pixels, max {r['max_difference_mmh']:.9f} mm/h"
                    for r in results) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
