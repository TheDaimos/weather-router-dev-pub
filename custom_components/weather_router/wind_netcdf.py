"""Bounded NetCDF classic subset reader; no native runtime or GRIB decoder.

Only numeric fixed/one-record CF subsets are accepted. Raw product values and
their explicit fill flags are retained; no spatial or temporal interpolation.
"""
from __future__ import annotations

import math
import struct

_TYPES = {1: ("b", 1), 2: ("c", 1), 3: ("h", 2), 4: ("i", 4), 5: ("f", 4), 6: ("d", 8)}


def read_classic(data: bytes) -> dict:
    if len(data) > 4_000_000 or data[:4] not in (b"CDF\x01", b"CDF\x02"):
        raise ValueError("wind_netcdf_format")
    version = data[3]
    pos = 4

    def uint():
        nonlocal pos
        result = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        return result

    def string():
        nonlocal pos
        size = uint()
        if size > 65536 or pos + size > len(data):
            raise ValueError("wind_netcdf_string")
        result = data[pos:pos + size].decode("utf-8")
        pos += (size + 3) // 4 * 4
        return result

    def values(kind, count, start):
        if kind not in _TYPES or count > 200000:
            raise ValueError("wind_netcdf_type_or_size")
        code, width = _TYPES[kind]
        if start + count * width > len(data):
            raise ValueError("wind_netcdf_truncated")
        if kind == 2:
            return data[start:start + count].decode("utf-8")
        return list(struct.unpack_from(">" + str(count) + code, data, start))

    def attributes():
        nonlocal pos
        tag, count = uint(), uint()
        if (tag, count) == (0, 0):
            return {}
        if tag != 12 or count > 128:
            raise ValueError("wind_netcdf_attributes")
        result = {}
        for _ in range(count):
            name, kind, size = string(), uint(), uint()
            result[name] = values(kind, size, pos)
            pos += (size * _TYPES[kind][1] + 3) // 4 * 4
        return result

    records = uint()
    tag, count = uint(), uint()
    if tag != 10 or not 1 <= count <= 16 or records > 1:
        raise ValueError("wind_netcdf_dimensions")
    dims = [(string(), uint()) for _ in range(count)]
    global_attributes = attributes()
    tag, count = uint(), uint()
    if tag != 11 or count > 64:
        raise ValueError("wind_netcdf_variables")
    variables = {}
    for _ in range(count):
        name, rank = string(), uint()
        if rank > 5:
            raise ValueError("wind_netcdf_rank")
        indices = [uint() for _ in range(rank)]
        attrs, kind, size = attributes(), uint(), uint()
        offset = uint()
        if version == 2:
            offset = (offset << 32) | uint()
        shape = [dims[index][1] or records for index in indices]
        variables[name] = {"dimensions": [dims[index][0] for index in indices], "shape": shape,
                           "attributes": attrs, "values": values(kind, math.prod(shape), offset)}
    return {"attributes": global_attributes, "variables": variables}
