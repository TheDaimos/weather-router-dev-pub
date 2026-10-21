"""F7 CI-only, dormant WeatherRouter-internal native candidate shelf.

Stores checked wheel bytes ONLY in explicitly isolated temporary CI sandboxes.
Never extracts, imports, installs, activates, or writes to HA paths.
No input, even a self-signed approval, can mark a package installable.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from functools import wraps

SHA = re.compile(r"[0-9a-f]{64}\Z")
ROOT = re.compile(r"f7-ci-[A-Za-z0-9_-]{3,60}\Z")
WHEEL = "rasterio-1.5.2-cp314-cp314-musllinux_1_2_x86_64.whl"
MAX_PACKAGE = 100 * 1024 * 1024
MAX_STATE = 16384
MAX_CANDIDATES = 2
SCHEMA = "weather_router.f7.offline_shelf.v1"

class ChannelBlocked(ValueError):
    pass

def _isolated_root(path):
    root = Path(path).absolute()
    temp = Path(tempfile.gettempdir()).resolve()
    if (os.environ.get("GITHUB_ACTIONS") != "true" or
            os.environ.get("WR_OPERA_ISOLATED_CI") != "1"):
        raise ChannelBlocked("ci_only")
    if root.parent != temp or not ROOT.fullmatch(root.name):
        raise ChannelBlocked("nonisolated_storage_path")
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise ChannelBlocked("unsafe_storage_root")
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.resolve() != root:
        raise ChannelBlocked("storage_root_moved")
    return root

def _serialized_mutation(func):
    """No competing state changes; never wait on a locked CI candidate store."""
    @wraps(func)
    def guarded(self, *args, **kwargs):
        lock=self.root/".state.lock"
        if lock.is_symlink():
            raise ChannelBlocked("unsafe_lock")
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
        try:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ChannelBlocked("concurrent_transition") from exc
            return func(self,*args,**kwargs)
        finally:
            os.close(fd)
    return guarded

class PassiveNativeShelf:
    def __init__(self, root):
        self.root = _isolated_root(root)
        self._state = self.root / "state.json"
        if not self._state.exists():
            self._write({"schema":SCHEMA,"staged":None,"previous":None,
                         "revoked":False,"active":None,
                         "ha_installation":"BLOCKED","opera_activation":"BLOCKED"})
        self.state()

    def state(self):
        if self._state.is_symlink() or self._state.stat().st_size > MAX_STATE:
            raise ChannelBlocked("unsafe_state")
        data = json.loads(self._state.read_text(encoding="utf-8"))
        if (not isinstance(data,dict) or data.get("schema")!=SCHEMA
                or data.get("active") is not None
                or data.get("ha_installation")!="BLOCKED"
                or data.get("opera_activation")!="BLOCKED"
                or any(x is not None and (not isinstance(x,str) or not SHA.fullmatch(x))
                       for x in (data.get("staged"),data.get("previous")))):
            raise ChannelBlocked("state_corrupted_or_not_passive")
        return data

    def _write(self, state):
        encoded=(json.dumps(state,sort_keys=True,separators=(",",":"))+"\n").encode()
        if len(encoded)>MAX_STATE:
            raise ChannelBlocked("state_too_large")
        handle,name=tempfile.mkstemp(prefix=".state-",dir=self.root)
        try:
            with os.fdopen(handle,"wb") as out:
                os.fchmod(out.fileno(),0o600)
                out.write(encoded)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name,self._state)
        finally:
            if os.path.lexists(name):
                os.unlink(name)

    @_serialized_mutation
    def stage(self, source, descriptor, provenance, inspector, *, fail_before_commit=False):
        """CI synthetic or unapproved candidate: never production admission.

        Caller-supplied inspector must validate wheel ZIP/tag/member safety.
        The provenance envelope here is UNSIGNED and explicitly non-approving.
        """
        self.state()
        if not isinstance(descriptor,dict) or descriptor.get("schema")!="weather_router.f7.native_package.v1":
            raise ChannelBlocked("bad_descriptor")
        sha=descriptor.get("sha256")
        if (not isinstance(sha,str) or not SHA.fullmatch(sha)
                or descriptor.get("package")!=WHEEL
                or descriptor.get("abi")!="cp314-cp314-musllinux_1_2_x86_64"):
            raise ChannelBlocked("candidate_identity_invalid")
        if (not isinstance(provenance,dict)
                or provenance.get("schema")!="weather_router.f7.provenance_envelope.v1"
                or provenance.get("status")!="BOUND_UNAPPROVED_EVIDENCE_ONLY"
                or provenance.get("candidate",{}).get("sha256")!=sha
                or provenance.get("signature_envelope",{}).get("independent_signature_verified") is not False
                or provenance.get("ha_installation")!="BLOCKED"):
            raise ChannelBlocked("provenance_not_bound_or_not_blocked")
        src=Path(source)
        if src.is_symlink() or not src.is_file() or src.name != WHEEL:
            raise ChannelBlocked("source_path_or_name")
        n=src.stat().st_size
        if not 0<n<=MAX_PACKAGE:
            raise ChannelBlocked("candidate_size")
        if not callable(inspector):
            raise ChannelBlocked("inspector_missing")
        inspector(src,sha)
        # Each digest has its own isolated directory, so a failed replacement
        # never overwrites the previously staged object.
        bucket=self.root / sha
        if bucket.is_symlink() or (bucket.exists() and not bucket.is_dir()):
            raise ChannelBlocked("candidate_bucket_unsafe")
        if not bucket.exists():
            if len([p for p in self.root.iterdir() if p.is_dir()])>=MAX_CANDIDATES:
                raise ChannelBlocked("candidate_count_limit")
            bucket.mkdir(mode=0o700)
        target=bucket/WHEEL
        if target.is_symlink():
            raise ChannelBlocked("candidate_target_symlink")
        fd,tmp=tempfile.mkstemp(prefix=".wheel-",dir=bucket)
        try:
            digest=hashlib.sha256()
            size=0
            with os.fdopen(fd,"wb") as dst, src.open("rb") as inp:
                os.fchmod(dst.fileno(),0o600)
                for block in iter(lambda:inp.read(1024*1024),b""):
                    size+=len(block)
                    if size>MAX_PACKAGE:
                        raise ChannelBlocked("stream_size_limit")
                    digest.update(block)
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
            if size!=n or digest.hexdigest()!=sha:
                raise ChannelBlocked("source_changed_during_copy")
            if fail_before_commit:
                raise ChannelBlocked("simulated_interrupted_update")
            os.replace(tmp,target)
            inspector(target,sha)
            prior=self.state()
            self._write({**prior,"previous":prior["staged"],"staged":sha,
                         "revoked":False,"active":None})
        finally:
            if os.path.lexists(tmp):
                os.unlink(tmp)
        return self.status()

    @_serialized_mutation
    def revoke(self):
        prior=self.state()
        self._write({**prior,"staged":None,"previous":None,"revoked":True,"active":None})
        return self.status()

    @_serialized_mutation
    def rollback(self, inspector):
        prior=self.state()
        if prior["revoked"]:
            raise ChannelBlocked("revocation_not_reversible")
        old=prior["previous"]
        # Never restore unverified, deleted, modified or symlinked old bytes.
        if old is not None:
            target=self.root/old/WHEEL
            if not callable(inspector) or target.is_symlink() or not target.is_file():
                old=None
            else:
                try:
                    inspector(target,old)
                except (ValueError,OSError):
                    old=None
        self._write({**prior,"staged":old,"previous":None,"revoked":False,"active":None})
        return self.status()

    def status(self):
        current=self.state()
        return {"schema":SCHEMA,"staged_candidate":current["staged"],
                "previous_candidate":current["previous"],
                "revoked":current["revoked"],"active":False,
                "signed_provenance_verified":False,
                "artifact_installable":False,
                "runtime_native_import":"FORBIDDEN",
                "ha_installation":"BLOCKED",
                "opera_activation":"BLOCKED",
                "fallback":"existing_v1_v2_without_rasterio",
                "max_workers":2,"max_queue":6,
                "native_timeout_is_hard_abort":False}
