"""F7: exact embedded ELF size hotspots; conservative driver-scope decision.

Pure JSON read, no native import/ELF modification, no automatic pruning.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

LIMIT=2*1024*1024
GROUPS={
  "SFCGAL":("libsfcgal",),
  "OpenBLAS":("libopenblas",),
  "LAPACK":("liblapack",),
  "ODBC":("libodbc","libodbcinst"),
  "GDAL":("libgdal",),
  "PROJ":("libproj",),
  "Spatialite":("libspatialite",),
  "Other_GEOS":("libgeos",),
}
def scope(inventory):
    if (inventory.get("schema")!="weather_router.f7.native_candidate_inventory.v2"
            or inventory.get("status")!="UNAPPROVED_NOT_DISTRIBUTABLE"
            or not isinstance(inventory.get("files"),list)):
        raise ValueError("invalid_inventory")
    rows=[r for r in inventory["files"] if r.get("elf_magic")]
    if len(rows)!=inventory.get("native_elf_count"):
        raise ValueError("native_count_mismatch")
    groups={g:{"bytes":0,"files":[]} for g in GROUPS}
    for row in rows:
        name=row.get("path"); size=row.get("size_bytes")
        if not isinstance(name,str) or type(size) is not int or size<0:
            raise ValueError("invalid_member")
        for group,terms in GROUPS.items():
            if name.startswith("rasterio.libs/") and any(term in name.lower() for term in terms):
                groups[group]["bytes"]+=size
                groups[group]["files"].append(name)
                break
    group_total=sum(x["bytes"] for x in groups.values())
    return {
        "schema":"weather_router.f7.native_size_scope.v1",
        "status":"ANALYSIS_ONLY_NO_BINARY_PRUNING",
        "native_elf_count":len(rows),
        "native_elf_uncompressed_bytes":sum(x["size_bytes"] for x in rows),
        "identified_named_group_bytes":group_total,
        "size_groups":groups,
        "necessary_raster_functions_to_verify":["GTiff","COG","VRT","MEM","PNG",
                                                "LAEA_to_WebMercator","DBZH","RATE"],
        "authentic_opera_driver_requirements_verified":False,
        "safe_to_remove_transitive_dependencies":False,
        "license_review":"REQUIRED","ha_installation":"BLOCKED",
        "opera_activation":"BLOCKED"}

def main(argv):
    if len(argv)!=3:
        print("usage: f7_native_size_scope.py NATIVE_INVENTORY OUTPUT_JSON",file=sys.stderr);return 2
    try:
        p=Path(argv[1])
        if p.is_symlink() or not p.is_file() or p.stat().st_size>LIMIT:
            raise ValueError("untrusted_input")
        r=scope(json.loads(p.read_text()))
        Path(argv[2]).write_text(json.dumps(r,sort_keys=True,indent=2)+"\n")
    except (ValueError,OSError,TypeError):
        print("F7 native size scope rejected",file=sys.stderr);return 1
    return 0
if __name__=="__main__":raise SystemExit(main(sys.argv))
