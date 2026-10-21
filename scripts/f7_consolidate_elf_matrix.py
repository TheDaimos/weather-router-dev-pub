"""F7: 101-component provenance/license decision table; never clearance."""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

HEX = re.compile(r"[a-f0-9]{64}\Z")
MAX_SIZE = 5 * 1024 * 1024

def read(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size < MAX_SIZE:
        raise ValueError("untrusted_evidence")
    return json.loads(p.read_text(encoding="utf-8"))

def render(binary, joined, license_docs, fetch):
    if (binary.get("schema")!="weather_router.f7.apk_embedded_binary_comparison.v1"
            or joined.get("schema")!="weather_router.f7.apk_signed_member_correlation.v1"
            or license_docs.get("schema")!="weather_router.f7.apk_original_license_docs.v1"
            or fetch.get("schema")!="weather_router.f7.official_apk_archive_candidates.v1"):
        raise ValueError("schema_mismatch")
    candidate=binary.get("wheel_sha256")
    if not isinstance(candidate,str) or not HEX.fullmatch(candidate):
        raise ValueError("wheel_hash_invalid")
    if any(x.get("wheel_sha256")!=candidate for x in (joined,license_docs,fetch)):
        raise ValueError("wheel_hash_disagreement")
    origins=binary.get("elf_components",[])
    correlations=joined.get("elf_components",[])
    if len(origins)!=101 or len(correlations)!=101:
        raise ValueError("incomplete_native_matrix")
    bypath={}
    for row in correlations:
        key=row.get("wheel_path")
        if not isinstance(key,str) or key in bypath:
            raise ValueError("duplicated_component")
        bypath[key]=row
    archive_by_name={(r.get("name"),r.get("version")):r
                     for r in fetch.get("packages",[])}
    docs_by_name={(r.get("name"),r.get("version")):r
                  for r in license_docs.get("packages",[])}
    q=chr(96)
    lines=[
        "# WeatherRouter F7 – 101-Komponenten-Herkunfts- und Rechteprüfung",
        "",
        "**NICHT FREIGEGEBEN:** Dateinamen, Archivsignaturen innerhalb der CI",
        "und Binärvergleiche ersetzen keine unabhängige Quellen- und Rechtsprüfung.",
        "",
        "Wheel-SHA256: "+q+candidate+q,
        "",
        "| Nr. | ELF-Mitglied | ELF-SHA im Wheel | Alpine-Kandidaten / APK-SHA | Installierte ELF-SHA | Archiv-Herkunft | Original-Lizenzdokumente | Rechteprüfung |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    classes={}
    for i,raw in enumerate(sorted(origins,key=lambda x:x["wheel_path"]),1):
        name=raw["wheel_path"]
        corr=bypath.pop(name,None)
        if corr is None or raw.get("wheel_sha256")!=corr.get("wheel_sha256"):
            raise ValueError("per_elf_integrity_mismatch")
        cls=corr.get("status","UNVERIFIED")
        classes[cls]=classes.get(cls,0)+1
        pkgs=[]
        docs=[]
        for pkg in raw.get("candidates",[]):
            key=(pkg.get("name"),pkg.get("version"))
            archive=archive_by_name.get(key,{})
            sha=archive.get("archive_sha256")
            pkgs.append(str(key[0])+"@"+str(key[1])+" ("+str(sha or "APK-SHA-OFFEN")+")")
            evidence=docs_by_name.get(key,{})
            docs.append(str(len(evidence.get("license_documents",[])))+
                        " Originaltext-Hashes; "+str(evidence.get("status","NICHT BESTAETIGT")))
        safe=lambda s:str(s).replace("|",r"\|").replace("\n"," ")
        lines.append("| "+str(i)+" | "+q+safe(name)+q+" | "+q+safe(raw.get("wheel_sha256"))+
                     q+" | "+safe("; ".join(pkgs) or "Rasterio-Quellbau; SDist-Herkunft offen")+
                     " | "+q+safe(raw.get("original_installed_sha256") or "NICHT ERMITTELT")+
                     q+" | "+safe(cls)+" | "+safe("; ".join(docs) or "ORIGINALTEXT OFFEN")+
                     " | OFFEN (Copyright, GPL/LGPL/MPL/GCC, NOTICE, Weitergabe) |")
    if bypath:
        raise ValueError("unused_native_correlations")
    lines.extend(["","## Nachweisklassen",""])
    for cls in sorted(classes):
        lines.append("- "+q+cls+q+": "+str(classes[cls]))
    lines.extend(["",
                  "Unterschiedliche Bedingungen für private Nutzung, Änderung und",
                  "kommerzielle Weitergabe sind je Ursprungs-Lizenz getrennt zu prüfen.",
                  "Auch eine signierte APK mit nur innerhalb des CI-Images bekannten",
                  "Schlüsseln ist noch kein unabhängig bezeugter Vertrauensanker.",
                  "Veränderte ELF-Bytes nach auditwheel gelten ohne überprüfbare",
                  "Transformationskette nicht als byteidentisch.",
                  "",
                  "HA DEV VM 109, HA PROD VM 101, DRA, Manifeständerungen,",
                  "Rasterio-Import, OPERA und Binärveröffentlichung: GESPERRT.",
                  ""])
    return "\n".join(lines)

def main(argv):
    if len(argv)!=6:
        print("usage: f7_consolidate_elf_matrix.py ORIGINAL.json CORRELATION.json LICENSE.json FETCH.json OUTPUT.md",file=sys.stderr)
        return 2
    try:
        md=render(*(read(x) for x in argv[1:5]))
        target=Path(argv[5])
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError("invalid_output")
        target.write_text(md,encoding="utf-8")
    except (ValueError,TypeError,KeyError,OSError):
        print("F7 native license decision matrix rejected",file=sys.stderr)
        return 1
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
