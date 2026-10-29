"""F7: render 101 true ELF provenance/license candidate rows from CI JSON."""
from __future__ import annotations
from pathlib import Path
import sys
from f7_generate_sbom import _read, produce

def matrix(inv,audit):
    bom,quality=produce(inv,audit)
    bypath={r["path"]:r for r in inv["files"] if r.get("elf_magic")}
    licenses={r["wheel_path"]:r for r in audit["elf_candidates"]}
    q=chr(96)
    lines=[
        "# WeatherRouter F7 - native ELF Herkunfts- und Lizenzmatrix",
        "",
        "UNAPPROVED - Alpine-Quellzuordnung nur nach Dateinamen.",
        "Keine verifizierten vollständigen Lizenztexte, Copyright-Pflichten",
        "oder signierte Quell-/Paketnachweise. Keine Installationsfreigabe.",
        "",
        "Wheel-SHA256: "+q+quality["wheel_sha256"]+q,
        "ELF-Anzahl: "+str(quality["elf_included"]),
        "",
        "| Nr | ELF-Pfad | SHA256 | Bytes | Quellpakete/Versionen | Deklarierte Lizenzen | Vertrauensklasse | Rechteprüfung |",
        "|---:|---|---|---:|---|---|---|---|",
    ]
    for i,path in enumerate(sorted(bypath),1):
        r=bypath[path]
        a=licenses[path]
        candidates=a["apk_source_candidates"]
        pkgs=", ".join(str(c.get("package"))+" "+str(c.get("version"))
                       for c in candidates) or "UNBEKANNT"
        declared=", ".join(sorted(set(str(c.get("declared_license") or "UNBEKANNT")
                                      for c in candidates))) or "UNBEKANNT"
        # The path is an archive name, not interpreted markup.
        safe=path.replace("|",r"\|")
        lines.append("| "+str(i)+" | "+q+safe+q+" | "+q+r["sha256"]+q+
                     " | "+str(r["size_bytes"])+" | "+pkgs+" | "+declared+
                     " | "+a["attribution_confidence"]+" | OFFEN |")
    lines.extend(["","Binaere Herkunft, Lizenztexte, GPL/LGPL/MPL/GCC-Ausnahmen,",
                  "CVE-Pruefung und Distribution: NICHT FREIGEGEBEN.",""])
    return "\n".join(lines)

def main(argv):
    if len(argv)!=4:
        print("usage: f7_elf_license_matrix.py INVENTORY LICENSE_JSON OUTPUT_MD",file=sys.stderr)
        return 2
    try:
        result=matrix(_read(argv[1]),_read(argv[2]))
        dst=Path(argv[3])
        if dst.is_symlink():raise ValueError("invalid_output")
        dst.write_text(result,encoding="utf-8")
    except (ValueError,OSError,KeyError,TypeError):
        print("F7 matrix rejected",file=sys.stderr)
        return 1
    return 0
if __name__=="__main__":raise SystemExit(main(sys.argv))
