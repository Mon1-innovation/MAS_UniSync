from __future__ import print_function

import collections
import datetime

try:
    unicode
except NameError:
    unicode = str
try:
    long
except NameError:
    long = int


PRIMITIVE_TYPES = (type(None), str, unicode, bool, int, long, float)
DATE_TYPES = (datetime.date, datetime.timedelta)
TIME_TYPES = (datetime.datetime, datetime.time)
OPAQUE_TYPE_NAMES = ("Preferences", "Persistent")


def _type_name(value):
    return type(value).__name__


def _is_revertable_type(value):
    name = _type_name(value)
    return name in ("RevertableList", "RevertableDict", "RevertableSet")


def validate_persistent_dict(data, max_depth=80):
    if not isinstance(data, dict):
        return False, "persistent data must be a dict"
    seen = set()
    try:
        for key, value in data.items():
            ok, reason = _validate_value(key, max_depth, seen)
            if not ok:
                return ok, reason
            ok, reason = _validate_value(value, max_depth, seen, path=str(key))
            if not ok:
                return ok, reason
    except RuntimeError as exc:
        if "maximum recursion depth exceeded" in str(exc):
            return False, "recursive persistent data exceeds recursion depth"
        raise
    return True, ""


def _validate_value(value, depth, seen, path="value"):
    if depth < 0:
        return False, "{0} exceeds recursion depth".format(path)
    value_type = type(value)
    if value_type in PRIMITIVE_TYPES:
        return True, ""
    if value_type in DATE_TYPES:
        return True, ""
    if value_type in TIME_TYPES:
        if getattr(value, "tzinfo", None) is not None:
            return False, "{0} has timezone-aware datetime/time".format(path)
        return True, ""

    is_sequence = value_type in (list, tuple, set, frozenset) or _type_name(value) in ("RevertableList", "RevertableSet")
    is_sequence = is_sequence or value_type is collections.deque or _type_name(value) == "deque"
    is_mapping = isinstance(value, dict) or _type_name(value) == "RevertableDict"
    if is_sequence or is_mapping:
        object_id = id(value)
        if object_id in seen:
            return False, "{0} contains recursive data".format(path)
        seen.add(object_id)
        try:
            if is_sequence:
                for index, item in enumerate(value):
                    ok, reason = _validate_value(item, depth - 1, seen, "{0}[{1}]".format(path, index))
                    if not ok:
                        return ok, reason
            else:
                for key, item in value.items():
                    ok, reason = _validate_value(key, depth - 1, seen, "{0}.key".format(path))
                    if not ok:
                        return ok, reason
                    ok, reason = _validate_value(item, depth - 1, seen, "{0}.{1}".format(path, key))
                    if not ok:
                        return ok, reason
        finally:
            seen.remove(object_id)
        return True, ""

    if _type_name(value) in OPAQUE_TYPE_NAMES:
        return True, ""

    return False, "{0} contains unsupported {1}".format(path, _type_name(value))
