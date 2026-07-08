from __future__ import print_function

import os
import sys

try:
    from . import mas_unisync_core as core
    from . import mas_unisync_http as http
except (ImportError, ValueError):
    module_dir = os.path.dirname(os.path.abspath(__file__))
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    import mas_unisync_core as core
    import mas_unisync_http as http


class SyncSession(object):
    def __init__(self, api_url, profile_key, persistent_path, backup_dir, renpy_version=None, mas_version=None, urlopen=None):
        self.api_base = core.api_base_url(api_url)
        self.host = core.normalize_host(api_url)
        self.profile_key = profile_key
        self.persistent_path = persistent_path
        self.backup_dir = backup_dir
        self.renpy_version = renpy_version
        self.mas_version = mas_version
        self.urlopen = urlopen
        self.status = core.SyncStatus()
        self.status.enabled = bool(profile_key)

    def headers(self, include_lease=False, extra=None):
        headers = {"X-MAS-Profile-Key": self.profile_key}
        if include_lease and self.status.lease_token:
            headers["X-MAS-Lease-Token"] = self.status.lease_token
        if extra:
            headers.update(extra)
        return headers

    def url(self, path):
        return core.build_url(self.api_base, path)

    def request_json(self, method, path, headers=None, data=None):
        return http.request_json(
            method,
            self.url(path),
            headers=headers,
            data=data,
            urlopen=self.urlopen,
        )

    def request_bytes(self, method, path, headers=None, data=None):
        _status, body = http.request(
            method,
            self.url(path),
            headers=headers,
            data=data,
            urlopen=self.urlopen,
        )
        return body

    def start(self, upload_after_sync=False):
        if not self.profile_key:
            self.status.enabled = False
            return self.status
        self.resolve_profile()
        self.acquire_lock()
        self.sync_current()
        if upload_after_sync:
            self.upload_persistent()
        return self.status

    def resolve_profile(self):
        return self.request_json("GET", "/v1/profile/resolve", headers=self.headers())

    def acquire_lock(self):
        try:
            payload = self.request_json("POST", "/v1/locks/acquire", headers=self.headers(), data=b"")
        except http.UniSyncHTTPError as exc:
            if exc.status == 409:
                raise core.UniSyncLockNotHeldError(
                    "Unable to acquire sync lock: the lock is held by another client. "
                    "Please check other devices or wait ~60 seconds for the lease to expire."
                )
            raise core.UniSyncError(
                "Unable to acquire sync lock: {0}".format(str(exc))
            )
        lease_token = payload.get("lease_token") if isinstance(payload, dict) else None
        if not lease_token:
            raise core.UniSyncError("lock acquisition response did not include lease_token")
        self.status.lease_token = lease_token
        self.status.lock_state = "locked"
        return lease_token

    def heartbeat(self):
        if not self.status.lease_token:
            return None
        return self.request_json("POST", "/v1/locks/heartbeat", headers=self.headers(include_lease=True), data=b"")

    def release(self):
        if not self.status.lease_token:
            return
        try:
            self.request_json("POST", "/v1/locks/release", headers=self.headers(include_lease=True), data=b"")
        finally:
            self.status.lease_token = ""
            self.status.lock_state = "released"

    def current_metadata(self):
        try:
            return self.request_json("GET", "/v1/persistent/current", headers=self.headers())
        except http.UniSyncHTTPError as exc:
            if exc.status == 404 or exc.code == "no_current_persistent":
                return None
            raise

    def sync_current(self):
        metadata = self.current_metadata()
        if metadata is None:
            return None
        remote_sha = metadata.get("sha256")
        if not remote_sha:
            return metadata
        local_sha = core.sha256_file(self.persistent_path) if os.path.isfile(self.persistent_path) else ""
        if local_sha != remote_sha:
            body = self.request_bytes("GET", "/v1/persistent/download", headers=self.headers())
            new_sha = core.replace_persistent_from_bytes(body, self.persistent_path, self.backup_dir)
            self.status.mark_download_success(new_sha)
        else:
            self.status.last_local_hash = local_sha
            self.status.last_remote_sha256 = remote_sha
        return metadata

    def upload_if_changed(self):
        if not os.path.isfile(self.persistent_path):
            raise core.UniSyncError("persistent file not found: {0}".format(self.persistent_path))
        local_sha = core.sha256_file(self.persistent_path)
        if not self.status.should_upload_hash(local_sha):
            return None
        return self.upload_persistent(local_sha=local_sha)

    def upload_persistent(self, local_sha=None):
        if not os.path.isfile(self.persistent_path):
            raise core.UniSyncError("persistent file not found: {0}".format(self.persistent_path))
        if local_sha is None:
            local_sha = core.sha256_file(self.persistent_path)
        body, content_type = http.build_multipart_form_data(
            self.persistent_path,
            renpy_version=self.renpy_version,
            mas_version=self.mas_version,
        )
        payload = self.request_json(
            "POST",
            "/v1/persistent/upload",
            headers=self.headers(include_lease=True, extra={"Content-Type": content_type}),
            data=body,
        )
        uploaded_hash = payload.get("sha256", local_sha) if isinstance(payload, dict) else local_sha
        uploaded_at = payload.get("created_at") if isinstance(payload, dict) else None
        self.status.mark_upload_success(uploaded_hash, uploaded_at)
        return payload


def fetch_profile_keys_url(api_url, urlopen=None):
    payload = http.request_json(
        "GET",
        core.build_url(core.api_base_url(api_url), "/v1/config/web-url"),
        urlopen=urlopen,
    )
    if isinstance(payload, dict):
        profile_keys_url = payload.get("profile_keys_url")
        if profile_keys_url:
            return profile_keys_url
    raise core.UniSyncError("web-url config response did not include profile_keys_url")
