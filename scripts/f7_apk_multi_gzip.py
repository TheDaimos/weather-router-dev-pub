"""F7 safe reader for multi-member gzip Alpine APK archives (v2 format).

Alpine APK v2 concatenates independently gzipped .SIGN, .PKGINFO and data TARs.
Python tarfile.open("r|gz") stops after the FIRST tar EOF: provenance would be
incorrect if it silently ignored the real source ELF and license files.
This read-only decompressor separates gzip streams by zlib unused_data, caps
compressed/decompressed lengths, forbids unknown trailing formats, and never
extracts or executes anything. For v3 non-gzip packages fail closed.
"""
from __future__ import annotations

import io
from pathlib import Path
import tarfile
import zlib

MAX_ARCHIVE = 100 * 1024 * 1024
MAX_STREAM_EXPANDED = 256 * 1024 * 1024
MAX_TOTAL_EXPANDED = 512 * 1024 * 1024
MAX_STREAMS = 8

class UnsafeApkArchive(ValueError):
    pass

def open_apk_tar_segments(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= MAX_ARCHIVE:
        raise UnsafeApkArchive("invalid_apk_file")
    content=p.read_bytes()
    cursor=0
    expanded=0
    parts=[]
    while cursor<len(content):
        if len(parts)>=MAX_STREAMS or content[cursor:cursor+2]!=b"\x1f\x8b":
            raise UnsafeApkArchive("invalid_or_trailing_gzip_stream")
        d=zlib.decompressobj(16+zlib.MAX_WBITS)
        try:
            decompressed=d.decompress(content[cursor:],MAX_STREAM_EXPANDED+1)
        except zlib.error as exc:
            raise UnsafeApkArchive("corrupt_gzip") from exc
        if (not d.eof or d.unconsumed_tail or len(decompressed)>MAX_STREAM_EXPANDED):
            raise UnsafeApkArchive("incomplete_or_oversized_stream")
        consumed=len(content)-cursor-len(d.unused_data)
        if consumed<=0 or not decompressed:
            raise UnsafeApkArchive("empty_gzip_member")
        cursor+=consumed
        expanded+=len(decompressed)
        if expanded>MAX_TOTAL_EXPANDED:
            raise UnsafeApkArchive("total_unpacked_limit")
        # Validate each segment as a TAR; return in-memory bytes, never use
        # tarfile.extract/extractall or filesystem path resolution.
        try:
            with tarfile.open(fileobj=io.BytesIO(decompressed),mode="r:") as archive:
                if not any(True for _ in archive):
                    raise UnsafeApkArchive("empty_tar_stream")
        except (tarfile.TarError,OSError) as exc:
            raise UnsafeApkArchive("invalid_tar_stream") from exc
        parts.append(io.BytesIO(decompressed))
    if cursor != len(content):
        raise UnsafeApkArchive("trailing_archive_bytes")
    return parts
