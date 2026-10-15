"""E-078 standalone v2 buffer-policy extension loader (isolated preview).

Does not alter legacy provider extension loader, permissions, or routing.
Only explicit administrative calls can load local code. Not sandboxing.
"""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import re
import sys

from .buffer_policy import BufferPolicyRegistry

SCHEMA = "weather_router.extension.v2"
KIND = "buffer_policy"
_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
MAX_MANIFEST_BYTES = 32 * 1024


def validate_manifest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("extension root must be a real directory")
    manifest = root / "extension.json"
    init_file = root / "__init__.py"
    if (not manifest.is_file() or manifest.is_symlink()
            or not init_file.is_file() or init_file.is_symlink()
            or manifest.stat().st_size > MAX_MANIFEST_BYTES):
        raise ValueError("invalid extension files")
    obj = json.loads(manifest.read_text(encoding="utf-8"))
    if (not isinstance(obj, dict) or obj.get("schema") != SCHEMA
            or obj.get("kind") != KIND
            or obj.get("id") != root.name
            or not isinstance(obj.get("id"), str)
            or not _ID.fullmatch(obj["id"])
            or set(obj) != {"schema", "kind", "id"}):
        raise ValueError("invalid buffer policy manifest")
    return obj["id"]


def load_policy_extension(root: Path, registry: BufferPolicyRegistry) -> str:
    """Explicitly import trusted local code and register its declared rule.

    Call only for operator-installed modules in the admin-controlled extension
    root, never based on untrusted consumer request content.
    """
    extension_id = validate_manifest(root)
    name = f"_weather_router_buffer_policy_{extension_id}"
    if name in sys.modules:
        raise ValueError("extension already imported")
    module_spec = spec_from_file_location(name, root / "__init__.py",
                                         submodule_search_locations=[str(root)])
    if module_spec is None or module_spec.loader is None:
        raise ImportError("extension cannot be loaded")
    module = module_from_spec(module_spec)
    sys.modules[name] = module
    try:
        module_spec.loader.exec_module(module)
        fn = getattr(module, "buffer_policy", None)
        registry.register(extension_id, fn)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return extension_id


def unload_policy_extension(extension_id: str, registry: BufferPolicyRegistry) -> None:
    registry.unregister(extension_id)
    sys.modules.pop(f"_weather_router_buffer_policy_{extension_id}", None)
