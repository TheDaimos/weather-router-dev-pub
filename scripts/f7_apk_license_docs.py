"""F7: collect authentic APK-shipped copyright/LICENSE/NOTICE evidence in CI.

This inspects only the exact SHA-bound APKs fetched from Alpine repositories
and verified by apk-tools against image-bundled keys. Records full document
hashes and package metadata, never assumes declarations are legal clearance.
Read-only; never extracts to disk, loads or executes binaries.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
from f7_apk_multi_gzip import open_apk_tar_segments, UnsafeApkArchive

MAX_ARCHIVE = 100 * 1024 * 1024
MAX_MEMBER = 1024 * 1024
MAX_TOTAL = 8 * 1024 * 1024
MAX_MEMBERS = 20000
LABEL = re.compile(r"(?:^|/)(?:COPYING|COPYRIGHT|LICENSE(?:[.-][^/]*)?|NOTICE(?:[.-][^/]*)?)$",re.I)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def read_doc(archive):
    docs=[]
    metadata={}
    total=0
    count=0
    for segment in open_apk_tar_segments(archive):
      with tarfile.open(fileobj=segment, mode="r:") as opened:
        for m in opened:
            count+=1
            if count>MAX_MEMBERS:
                raise ValueError("too_many_apk_members")
            name=m.name.removeprefix("./")
            if not m.isfile() or PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                continue
            if name==".PKGINFO" or (name.startswith(("usr/share/licenses/","usr/share/doc/"))
                                     and LABEL.search(name)):
                if not 0 < m.size <= MAX_MEMBER or total+m.size>MAX_TOTAL:
                    raise ValueError("license_document_limit")
                fd=opened.extractfile(m)
                if fd is None:
                    continue
                raw=fd.read(MAX_MEMBER+1)
                if len(raw)!=m.size:
                    raise ValueError("license_document_truncated")
                total+=len(raw)
                if name==".PKGINFO":
                    for line in raw.decode("utf-8",errors="replace").splitlines():
                        if " = " in line:
                            key,val=line.split(" = ",1)
                            if key in ("pkgname","pkgver","license","origin","url",
                                       "commit","maintainer","builddate"):
                                metadata.setdefault(key,val)
                else:
                    docs.append({"path":name,"sha256":digest(raw),"bytes":len(raw),
                                 "text_is_complete_in_original_apk":True})
    return metadata,docs

def audit(download_report, archive_dir):
    if download_report.get("schema")!="weather_router.f7.official_apk_archive_candidates.v1":
        raise ValueError("wrong_report")
    folder=Path(archive_dir)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("unsafe_archive_directory")
    output=[]
    for entry in download_report.get("packages",[]):
        name,version=entry.get("name"),entry.get("version")
        status={"name":name,"version":version,
                "apk_sha256":entry.get("archive_sha256"),
                "license_documents":[],"pkginfo":{},
                "status":"NOT_INDEPENDENTLY_REVIEWED",
                "license_cleared":False}
        if entry.get("apk_verify_result")=="VALID_AGAINST_CI_CONTAINER_KEYS":
            file=folder/f"{name}-{version}.apk"
            if (file.is_file() and not file.is_symlink()
                    and 0 < file.stat().st_size <= MAX_ARCHIVE
                    and digest(file.read_bytes())==entry.get("archive_sha256")):
                metadata,documents=read_doc(file)
                if metadata.get("pkgname")==name and metadata.get("pkgver")==version:
                    status["pkginfo"]=metadata
                    status["license_documents"]=documents
                    status["status"]=("APK_SIGNED_AND_DOCUMENTS_HASHED_NOT_LICENSE_CLEARED"
                                      if documents else "APK_SIGNED_NO_LICENSE_DOCUMENT_IN_PACKAGE")
                else:
                    status["status"]="PKGINFO_PACKAGE_ID_NOT_CONFIRMED"
        output.append(status)
    return {"schema":"weather_router.f7.apk_original_license_docs.v1",
            "status":"LICENSE_DOC_EVIDENCE_NOT_A_LEGAL_CLEARANCE",
            "wheel_sha256":download_report.get("wheel_sha256"),
            "packages_examined":len(output),
            "packages_with_original_license_docs":sum(bool(x["license_documents"]) for x in output),
            "document_hashes_count":sum(len(x["license_documents"]) for x in output),
            "signed_by_ci_image_keys_only":True,
            "independent_source_key_trust":False,
            "original_copyright_and_distribution_obligations_reviewed":False,
            "gpl_lgpl_mpl_gcc_exceptions_reviewed":False,
            "ha_installation":"BLOCKED","binary_distribution":"BLOCKED",
            "opera_activation":"BLOCKED","packages":output}

def main(args):
    if len(args)!=4:
        print("usage: f7_apk_license_docs.py FETCH.json APK_DIR OUTPUT.json",file=sys.stderr)
        return 2
    try:
        import os
        if os.environ.get("GITHUB_ACTIONS")!="true" or os.environ.get("WR_OPERA_ISOLATED_CI")!="1":
            raise ValueError("CI_only")
        report=audit(json.loads(Path(args[1]).read_text()),args[2])
        Path(args[3]).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    except (ValueError,KeyError,TypeError,OSError,tarfile.TarError,UnsafeApkArchive):
        print("F7 original APK license evidence rejected",file=sys.stderr)
        return 1
    print("F7 ORIGINAL APK LICENSE DOCUMENTS:",report["document_hashes_count"],
          "hashes, distribution and legal review BLOCKED")
    return 0

if __name__=="__main__":
    raise SystemExit(main(sys.argv))
