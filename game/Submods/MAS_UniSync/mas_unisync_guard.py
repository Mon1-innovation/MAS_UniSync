from __future__ import print_function

import collections
import datetime

try:
    import pydoc
except Exception:
    pydoc = None

try:
    unicode
except NameError:
    unicode = str
try:
    long
except NameError:
    long = int


PRIMITIVE_TYPES = (type(None), str, unicode, bool, int, long, float, bytes)
DATE_TYPES = (datetime.date, datetime.timedelta)
TIME_TYPES = (datetime.datetime, datetime.time)
OPAQUE_TYPE_NAMES = ("Preferences", "Persistent", "MASAudioData")
BUILTIN_CLASS_MODULES = ("builtins", "__builtin__")


def _type_name(value):
    return type(value).__name__


def _module_name(value):
    if isinstance(value, type):
        return getattr(value, "__module__", "") or ""
    return getattr(type(value), "__module__", "") or ""


def _is_builtin_class(value):
    return isinstance(value, type) and _module_name(value) in BUILTIN_CLASS_MODULES


def _text(value):
    try:
        return unicode(value)
    except Exception:
        return str(value)


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


def find_persistent_issues(data, max_depth=80):
    if not isinstance(data, dict):
        return [
            _make_issue(
                "persistent",
                "persistent",
                data,
                "persistent data must be a dict",
            )
        ]
    issues = []
    seen = set()
    try:
        for key, value in data.items():
            top_key = _text(key)
            _find_value_issues(key, max_depth, seen, top_key, top_key + ".key", issues)
            _find_value_issues(value, max_depth, seen, top_key, top_key, issues)
    except RuntimeError as exc:
        if "maximum recursion depth exceeded" in str(exc):
            issues.append(
                _make_issue(
                    "persistent",
                    "persistent",
                    data,
                    "recursive persistent data exceeds recursion depth",
                )
            )
        else:
            raise
    return issues


def _safe_repr(value):
    try:
        return repr(value)
    except Exception as exc:
        return "<repr failed: {0}: {1}>".format(_type_name(exc), exc)


def _safe_help(value):
    if pydoc is None:
        return ""
    try:
        renderer = getattr(pydoc, "plaintext", None)
        if renderer is not None:
            try:
                return pydoc.render_doc(value, renderer=renderer)
            except TypeError:
                pass
        return pydoc.render_doc(value)
    except Exception:
        return ""


def _make_issue(top_key, path, value, reason):
    return {
        "top_key": _text(top_key),
        "path": _text(path),
        "type_name": _type_name(value),
        "module_name": _module_name(value),
        "repr_text": _safe_repr(value),
        "help_text": _safe_help(value),
    }


def _find_value_issues(value, depth, seen, top_key, path, issues):
    if depth < 0:
        issues.append(_make_issue(top_key, path, value, "{0} exceeds recursion depth".format(path)))
        return
    value_type = type(value)
    if value_type in PRIMITIVE_TYPES:
        return
    if _is_builtin_class(value):
        return
    if value_type in DATE_TYPES:
        return
    if value_type in TIME_TYPES:
        if getattr(value, "tzinfo", None) is not None:
            issues.append(_make_issue(top_key, path, value, "{0} has timezone-aware datetime/time".format(path)))
        return

    is_sequence = value_type in (list, tuple, set, frozenset) or _type_name(value) in ("RevertableList", "RevertableSet")
    is_sequence = is_sequence or value_type is collections.deque or _type_name(value) == "deque"
    is_mapping = isinstance(value, dict) or _type_name(value) == "RevertableDict"
    if is_sequence or is_mapping:
        object_id = id(value)
        if object_id in seen:
            issues.append(_make_issue(top_key, path, value, "{0} contains recursive data".format(path)))
            return
        seen.add(object_id)
        try:
            if is_sequence:
                for index, item in enumerate(value):
                    _find_value_issues(item, depth - 1, seen, top_key, "{0}[{1}]".format(path, index), issues)
            else:
                for key, item in value.items():
                    _find_value_issues(key, depth - 1, seen, top_key, "{0}.key".format(path), issues)
                    _find_value_issues(item, depth - 1, seen, top_key, "{0}.{1}".format(path, key), issues)
        finally:
            seen.remove(object_id)
        return

    if _type_name(value) in OPAQUE_TYPE_NAMES:
        return

    issues.append(_make_issue(top_key, path, value, "{0} contains unsupported {1}".format(path, _type_name(value))))


def _validate_value(value, depth, seen, path="value"):
    if depth < 0:
        return False, "{0} exceeds recursion depth".format(path)
    value_type = type(value)
    if value_type in PRIMITIVE_TYPES:
        return True, ""
    if _is_builtin_class(value):
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
