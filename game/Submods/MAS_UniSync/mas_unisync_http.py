from __future__ import print_function

import json
import hashlib
import mimetypes
import os
import socket

try:
    from urllib import request as urllib_request
    from urllib import error as urllib_error
except ImportError:
    import urllib2 as urllib_request
    import urllib2 as urllib_error


class UniSyncHTTPError(Exception):
    def __init__(self, message, status=None, code=None):
        Exception.__init__(self, message)
        self.status = status
        self.code = code


DEFAULT_TIMEOUT = 30


def generate_multipart_boundary():
    try:
        random_bytes = os.urandom(16)
    except Exception:
        random_bytes = repr(os.getpid()).encode("ascii")
    return "MASUniSync{0}".format(hashlib.sha1(random_bytes).hexdigest())


def parse_json_body(body):
    if not body:
        return None
    if not isinstance(body, str):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def describe_error_body(body):
    parsed = parse_json_body(body)
    if parsed is not None:
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    if body:
        if not isinstance(body, str):
            return body.decode("utf-8", "replace")
        return body
    return "no response body"


def extract_error_code(body):
    parsed = parse_json_body(body)
    if not parsed:
        return None
    detail = parsed.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code")
        return code if isinstance(code, str) else None
    return None


def build_multipart_form_data(file_path, renpy_version=None, mas_version=None, boundary=None):
    boundary = boundary or generate_multipart_boundary()
    chunks = []

    def add_text_field(name, value):
        chunks.extend(
            [
                ("--{0}\r\n".format(boundary)).encode("ascii"),
                ('Content-Disposition: form-data; name="{0}"\r\n\r\n'.format(name)).encode("ascii"),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    if renpy_version:
        add_text_field("renpy_version", renpy_version)
    if mas_version:
        add_text_field("mas_version", mas_version)

    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(file_path, "rb") as handle:
        file_data = handle.read()
    chunks.extend(
        [
            ("--{0}\r\n".format(boundary)).encode("ascii"),
            (
                'Content-Disposition: form-data; name="file"; filename="{0}"\r\n'
                "Content-Type: {1}\r\n\r\n"
            ).format(filename, content_type).encode("utf-8"),
            file_data,
            b"\r\n",
            ("--{0}--\r\n".format(boundary)).encode("ascii"),
        ]
    )
    return b"".join(chunks), "multipart/form-data; boundary={0}".format(boundary)


def make_request(method, url, headers=None, data=None):
    headers = headers or {}
    try:
        return urllib_request.Request(url, data=data, headers=headers, method=method)
    except TypeError:
        request = urllib_request.Request(url, data=data, headers=headers)
        request.get_method = lambda: method
        return request


def request(method, url, headers=None, data=None, timeout=DEFAULT_TIMEOUT, urlopen=None):
    urlopen = urlopen or urllib_request.urlopen
    req = make_request(method, url, headers=headers, data=data)
    try:
        response = urlopen(req, timeout=timeout)
        try:
            status = response.getcode()
            body = response.read()
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
    except urllib_error.HTTPError as exc:
        body = exc.read()
        raise UniSyncHTTPError(
            "{0} {1} failed with HTTP {2}: {3}".format(method, url, exc.code, describe_error_body(body)),
            status=exc.code,
            code=extract_error_code(body),
        )
    except socket.timeout as exc:
        raise UniSyncHTTPError(
            "{0} {1} timed out after {2} seconds: {3}".format(method, url, timeout, exc)
        )
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise UniSyncHTTPError("{0} {1} failed: {2}".format(method, url, reason))

    if status < 200 or status >= 300:
        raise UniSyncHTTPError(
            "{0} {1} failed with HTTP {2}: {3}".format(method, url, status, describe_error_body(body)),
            status=status,
            code=extract_error_code(body),
        )
    return status, body


def request_json(method, url, headers=None, data=None, timeout=DEFAULT_TIMEOUT, urlopen=None):
    _status, body = request(method, url, headers=headers, data=data, timeout=timeout, urlopen=urlopen)
    return parse_json_body(body)
