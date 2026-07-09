from __future__ import print_function

import datetime
import hashlib
import os
import shutil


DEFAULT_HOST = "100.72.137.92"
API_PORT = 8000
MAX_LOCAL_BACKUPS = 10
PROFILE_KEY_FEATURE = "MAS_UniSync_Profile_Key"
HOST_FEATURE = "MAS_UniSync_Host"

class UniSyncError(Exception):
    pass


class UniSyncLockNotHeldError(UniSyncError):
    pass


class SyncStatus(object):
    def __init__(self):
        self.enabled = False
        self.lock_state = "unlocked"
        self.lease_token = ""
        self.last_upload_at = ""
        self.last_download_at = ""
        self.last_uploaded_hash = ""
        self.last_local_hash = ""
        self.last_error = ""
        self.last_remote_sha256 = ""

    def should_upload_hash(self, sha256):
        return bool(sha256) and sha256 != self.last_uploaded_hash

    def mark_upload_success(self, sha256, uploaded_at=None):
        self.last_uploaded_hash = sha256
        self.last_local_hash = sha256
        self.last_upload_at = uploaded_at or iso_now()
        self.last_error = ""

    def mark_download_success(self, sha256, downloaded_at=None):
        self.last_remote_sha256 = sha256
        self.last_local_hash = sha256
        self.last_download_at = downloaded_at or iso_now()
        self.last_error = ""

    def mark_error(self, message):
        if isinstance(message, Exception):
            submod_log_error(format_error_for_log(message))
            self.last_error = text_type(type(message).__name__)
        elif isinstance(message, str):
            self.last_error = text_type(message)
        else:
            self.last_error = text_type(message)

    def mark_error_full(self, message):
        self.last_error = text_type(message)


def submod_log_debug(message):
    """Log debug message to MAS submod log (safe no-op if unavailable)."""
    try:
        store.mas_submod_utils.submod_log.debug(str(message))
    except Exception:
        pass


def submod_log_error(message):
    """Log error message to MAS submod log (safe no-op if unavailable)."""
    try:
        store.mas_submod_utils.submod_log.error(text_type(message))
        return True
    except Exception:
        raise RuntimeError("MAS UniSync could not write log message: " + text_type(message))


def submod_log_info(message):
    """Log info message to MAS submod log (safe no-op if unavailable)."""
    try:
        store.mas_submod_utils.submod_log.info(str(message))
    except Exception:
        pass


def submod_log_panel_error(message):
    if message:
        submod_log_error("MAS UniSync panel error: " + text_type(message))


def format_error_for_log(message):
    if isinstance(message, Exception):
        detail = text_type(message)
        error_type = text_type(type(message).__name__)
        if detail:
            return "{0}: {1}".format(error_type, detail)
        return error_type
    return text_type(message)


def text_type(value):
    try:
        unicode
    except NameError:
        return str(value)
    return unicode(value)


def renpy_display_text(value):
    if value is None:
        return ""
    text = text_type(value)
    return (
        text.replace("{", "{{")
        .replace("}", "}}")
        .replace("[", "[[")
        .replace("]", "]]")
    )

def renpy_safe_text(value):
    """Escape Ren'Py text interpolation/control delimiters for display."""
    if value is None:
        return ""
    text = text_type(value)
    return (
        text.replace("{", "{{")
        .replace("}", "}}")
        .replace("[", "[[")
        .replace("]", "]]")
    )


def iso_now():
    return utc_now().replace(microsecond=0).isoformat() + "Z"


def utc_now():
    try:
        return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    except AttributeError:
        return datetime.datetime.utcnow()


def normalize_host(value):
    raw = (value or DEFAULT_HOST).strip()
    for prefix in ("http://", "https://"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix):]
            break
    raw = raw.split("/", 1)[0].strip()
    if raw.startswith("["):
        end = raw.find("]")
        if end >= 0:
            return raw[: end + 1]
    if ":" in raw:
        raw = raw.split(":", 1)[0]
    return raw or DEFAULT_HOST


def normalize_api_url(value):
    raw = (value or DEFAULT_HOST).strip().rstrip("/")
    if not raw:
        raw = DEFAULT_HOST
    lowered = raw.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        if "/account/" in raw:
            scheme, rest = raw.split("://", 1)
            host = rest.split("/", 1)[0]
            return "{0}://{1}".format(scheme, host).rstrip("/")
        return raw
    if raw.startswith("["):
        end = raw.find("]")
        if end >= 0:
            host = raw[: end + 1]
            rest = raw[end + 1:]
            if rest.startswith(":"):
                return "http://{0}{1}".format(host, rest)
            return "http://{0}:{1}".format(host, API_PORT)
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if ":" in raw:
        return "http://{0}".format(raw)
    return "http://{0}:{1}".format(raw, API_PORT)


def api_base_url(api_url):
    return normalize_api_url(api_url)


def portal_base_url(host):
    return "http://{0}".format(normalize_host(host))


def portal_profile_keys_url(host):
    return portal_base_url(host).rstrip("/") + "/account/profile-keys"


def build_url(base_url, path):
    return "{0}/{1}".format(base_url.rstrip("/"), path.lstrip("/"))


def sha256_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def create_local_backup(persistent_path, backup_dir, timestamp=None, max_backups=MAX_LOCAL_BACKUPS):
    if not os.path.isfile(persistent_path):
        return None
    ensure_dir(backup_dir)
    timestamp = timestamp or utc_now()
    sha_prefix = sha256_file(persistent_path)[:12]
    filename = "{0}-{1}.persistent".format(timestamp.strftime("%Y%m%d-%H%M%S"), sha_prefix)
    target = os.path.join(backup_dir, filename)
    shutil.copy2(persistent_path, target)
    rotate_local_backups(backup_dir, max_backups=max_backups)
    return target


def rotate_local_backups(backup_dir, max_backups=MAX_LOCAL_BACKUPS):
    if not os.path.isdir(backup_dir):
        return
    entries = [
        os.path.join(backup_dir, name)
        for name in os.listdir(backup_dir)
        if os.path.isfile(os.path.join(backup_dir, name))
    ]
    entries.sort()
    for old_path in entries[:-max_backups]:
        try:
            os.unlink(old_path)
        except OSError:
            pass


def replace_persistent_from_bytes(data, persistent_path, backup_dir):
    create_local_backup(persistent_path, backup_dir)
    ensure_dir(os.path.dirname(persistent_path))
    tmp_path = persistent_path + ".unisync-new"
    with open(tmp_path, "wb") as handle:
        handle.write(data)
    if os.path.exists(persistent_path):
        os.unlink(persistent_path)
    os.rename(tmp_path, persistent_path)
    return sha256_file(persistent_path)


def get_persistent_path(savedir):
    return os.path.join(savedir, "persistent")


def get_backup_dir(savedir):
    return os.path.join(savedir, "MAS_UniSync_Backups")


def load_pickle_payload(payload):
    import pickle as _pickle
    try:
        return _pickle.loads(payload, encoding="latin1")
    except TypeError:
        return _pickle.loads(payload)


def cleanup_current_eli_data_for_device(persistent_obj, has_label):
    eli_data = getattr(persistent_obj, "_mas_curr_eli_data", None)
    if eli_data is None:
        return False

    try:
        event_label = eli_data[0]
    except Exception:
        persistent_obj._mas_curr_eli_data = None
        return True

    if not event_label:
        persistent_obj._mas_curr_eli_data = None
        return True

    try:
        label_exists = bool(has_label(text_type(event_label)))
    except Exception:
        return False

    if label_exists:
        return False

    persistent_obj._mas_curr_eli_data = None
    return True


def renpy_label_exists(label):
    try:
        import renpy as renpy_module
    except Exception:
        return False

    label = text_type(label)
    try:
        script = getattr(getattr(renpy_module, "game", None), "script", None)
        has_label = getattr(script, "has_label", None)
        if has_label is not None:
            return bool(has_label(label))
    except Exception:
        pass

    try:
        has_label = getattr(renpy_module, "has_label", None)
        if has_label is not None:
            return bool(has_label(label))
    except Exception:
        pass

    return False


def load_persistent_bytes_into_renpy(data, early_log=None):
    import renpy
    import zlib

    decompressor = zlib.decompressobj()
    payload = decompressor.decompress(data)
    remote_persistent = load_pickle_payload(payload)

    if early_log is not None:
        early_log.debug("load_persistent_bytes_into_renpy: loading remote persistent into memory")

    renpy.game.persistent.__dict__.clear()
    renpy.game.persistent.__dict__.update(remote_persistent.__dict__)
    cleanup_current_eli_data_for_device(renpy.game.persistent, renpy_label_exists)
    renpy.game.persistent._update()

    if early_log is not None:
        early_log.info("load_persistent_bytes_into_renpy: persistent swapped")
    return renpy.game.persistent
