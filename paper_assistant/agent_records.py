"""JSON-safe diagnostic snapshots; never replace input used for validation."""

from math import isfinite


DIAGNOSTIC_SNAPSHOT_VERSION = "d8-json-diagnostic-snapshot-v1"


def diagnostic_snapshot(value):
    """Return (snapshot, replacements); finite canonical JSON data is unchanged.

    Rejecting a malformed tool response must still leave a serializable trace.
    Non-JSON values receive explicit data markers, not valid retrieval scores.
    No repr/str of an arbitrary object or exception is evaluated.
    """
    replacements, active = [], set()
    nodes = 0

    def marker(path, kind):
        replacements.append({"path": path, "kind": kind})
        return {"diagnostic_invalid_value": kind}

    def visit(item, path, depth):
        nonlocal nodes
        nodes += 1
        if nodes > 100000 or depth > 40:
            return marker(path, "diagnostic_limit")
        if item is None or type(item) in (str, bool):
            return item
        if type(item) is int:
            return item if item.bit_length() <= 4096 else marker(path, "oversized_integer")
        if type(item) is float:
            if isfinite(item):
                return item
            return marker(path, "nan" if item != item else ("positive_infinity" if item > 0 else "negative_infinity"))
        if type(item) in (dict, list, tuple):
            if id(item) in active:
                return marker(path, "cyclic_container")
            active.add(id(item))
            try:
                if type(item) is dict:
                    result = {key: visit(val, [*path, key], depth + 1)
                              for key, val in item.items() if type(key) is str}
                    if any(type(key) is not str for key in item):
                        key = "diagnostic_non_string_mapping_key"
                        while key in result:
                            key += "_"
                        result[key] = marker([*path, key], "non_string_mapping_key")
                    return result
                return [visit(val, [*path, index], depth + 1) for index, val in enumerate(item)]
            finally:
                active.remove(id(item))
        return marker(path, "unsupported_type")

    return visit(value, [], 0), replacements
