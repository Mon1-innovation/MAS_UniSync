init -990 python:
    import os
    import sys
    import webbrowser
    import pygame
    import json

    mas_unisync_version = "0.1.0"
    mas_unisync_dir = os.path.dirname(renpy.loader.transfn("Submods/MAS_UniSync/header.rpy"))
    if mas_unisync_dir not in sys.path:
        sys.path.insert(0, mas_unisync_dir)

    import mas_unisync_core
    import mas_unisync_http
    import mas_unisync_sync
    import mas_unisync_guard

    try:
        basestring
    except NameError:
        basestring = str

    store.mas_submod_utils.Submod(
        author="MAS UniSync",
        name="MAS UniSync",
        description=_("Cross-device persistent synchronization for Monika After Story."),
        version=mas_unisync_version,
        settings_pane="mas_unisync_settingpane"
    )

init -989 python:
    mas_unisync_status = {
        "sync_status": "disabled",
        "lock_state": "unlocked",
        "last_upload_at": "",
        "last_download_at": "",
        "last_error": "",
    }

    def mas_unisync_get_api_url():
        try:
            value = store.mas_getAPIKey(mas_unisync_core.HOST_FEATURE)
        except Exception:
            value = ""
        return mas_unisync_core.normalize_api_url(value)

    def mas_unisync_get_host():
        return mas_unisync_get_api_url()

    def mas_unisync_get_profile_key():
        try:
            return store.mas_getAPIKey(mas_unisync_core.PROFILE_KEY_FEATURE) or ""
        except Exception:
            return ""

    def mas_unisync_save_key(feature, value):
        store.mas_api_keys.api_keys.update({feature: value})
        mas_unisync_flush_api_keys()

    def mas_unisync_flush_api_keys():
        try:
            if len(store.mas_api_keys.api_keys) > 0:
                store.mas_api_keys.save_keys()
            else:
                with open(store.mas_api_keys.FILEPATH_KEYS, "w") as keys_file:
                    json.dump({}, keys_file, indent=4)
        except Exception:
            store.mas_api_keys.save_keys()

    def mas_unisync_save_api_url(api_url):
        cleaned = mas_unisync_core.normalize_api_url(api_url)
        mas_unisync_save_key(mas_unisync_core.HOST_FEATURE, cleaned)
        return cleaned

    def mas_unisync_save_host(host):
        return mas_unisync_save_api_url(host)

    def mas_unisync_clipboard_text():
        try:
            raw = pygame.scrap.get(pygame.SCRAP_TEXT)
        except Exception:
            return ""
        if raw is None:
            return ""
        if not isinstance(raw, basestring):
            try:
                raw = raw.decode("utf-8")
            except Exception:
                raw = str(raw)
        return raw.replace("\r", "").replace("\n", "").strip()

    def mas_unisync_paste_host():
        value = mas_unisync_clipboard_text()
        if not value:
            renpy.notify(_("Clipboard is empty"))
            return
        mas_unisync_save_api_url(value)
        renpy.notify(_("MAS UniSync API URL saved"))
        renpy.restart_interaction()

    def mas_unisync_paste_profile_key():
        value = mas_unisync_clipboard_text()
        if not value:
            renpy.notify(_("Clipboard is empty"))
            return
        mas_unisync_save_key(mas_unisync_core.PROFILE_KEY_FEATURE, value)
        try:
            mas_unisync_startup_sync(force=True, raise_on_failure=True, upload_after_sync=True)
            renpy.notify(_("MAS UniSync profile key saved"))
        except Exception as exc:
            mas_unisync_update_status(message=str(exc))
            renpy.notify("MAS UniSync connection failed: " + str(exc))
        renpy.restart_interaction()

    def mas_unisync_clear_profile_key():
        try:
            if globals().get("mas_unisync_session") is not None:
                globals().get("mas_unisync_stop_event").set()
                mas_unisync_session.release()
        except Exception:
            pass
        try:
            if mas_unisync_core.PROFILE_KEY_FEATURE in store.mas_api_keys.api_keys:
                store.mas_api_keys.api_keys.pop(mas_unisync_core.PROFILE_KEY_FEATURE)
                mas_unisync_flush_api_keys()
        except Exception:
            pass
        mas_unisync_update_status(message="")
        mas_unisync_status["sync_status"] = "disabled"
        mas_unisync_status["lock_state"] = "unlocked"
        renpy.restart_interaction()

    def mas_unisync_open_profile_keys():
        webbrowser.open_new(mas_unisync_sync.fetch_profile_keys_url(mas_unisync_get_api_url()))

    def mas_unisync_update_status(status_obj=None, message=None):
        global mas_unisync_status
        if not isinstance(mas_unisync_status, dict):
            mas_unisync_status = {}
        if status_obj is not None:
            mas_unisync_status["sync_status"] = "enabled" if status_obj.enabled else "disabled"
            mas_unisync_status["lock_state"] = status_obj.lock_state
            mas_unisync_status["last_upload_at"] = status_obj.last_upload_at
            mas_unisync_status["last_download_at"] = status_obj.last_download_at
            mas_unisync_status["last_error"] = status_obj.last_error
        if message is not None:
            mas_unisync_status["last_error"] = message

    def mas_unisync_profile_key_on_change(profile_key):
        if not profile_key:
            mas_unisync_update_status(message="")
            return True, ""
        try:
            mas_unisync_startup_sync(force=True, raise_on_failure=True, upload_after_sync=True)
            return True, ""
        except Exception as exc:
            return False, str(exc)

    def mas_unisync_host_on_change(host):
        mas_unisync_save_api_url(host)
        return True, ""

init -969 python:
    store.mas_registerAPIKey(
        mas_unisync_core.HOST_FEATURE,
        _("MAS UniSync API URL"),
        mas_unisync_host_on_change
    )
    store.mas_registerAPIKey(
        mas_unisync_core.PROFILE_KEY_FEATURE,
        _("MAS UniSync Profile Key"),
        mas_unisync_profile_key_on_change
    )

screen mas_unisync_settingpane():
    python:
        _status = mas_unisync_status if isinstance(mas_unisync_status, dict) else {}
        _api_url = mas_unisync_get_api_url()
        _key = mas_unisync_get_profile_key()
        _masked_key = _key[:12] + "..." if len(_key) > 15 else _key
        _display_api = mas_unisync_core.renpy_display_text(_api_url)
        _display_key = mas_unisync_core.renpy_display_text(_masked_key if _masked_key else _("not configured"))
        _display_sync_status = mas_unisync_core.renpy_display_text(_status.get("sync_status", "disabled"))
        _display_lock_state = mas_unisync_core.renpy_display_text(_status.get("lock_state", "unlocked"))
        _display_last_upload = mas_unisync_core.renpy_display_text(_status.get("last_upload_at") or "-")
        _display_last_download = mas_unisync_core.renpy_display_text(_status.get("last_download_at") or "-")
        _display_last_error = mas_unisync_core.renpy_display_text(_status.get("last_error") or "")

    vbox:
        spacing 8
        xpos 45
        xmaximum 900

        text _("MAS UniSync"):
            style "main_menu_version"

        text _("API URL: ") + _display_api:
            style "main_menu_version"
        text _("Profile key: ") + _display_key:
            style "main_menu_version"
        text _("Status: ") + _display_sync_status:
            style "main_menu_version"
        text _("Lock: ") + _display_lock_state:
            style "main_menu_version"
        text _("Last upload: ") + _display_last_upload:
            style "main_menu_version"
        text _("Last download: ") + _display_last_download:
            style "main_menu_version"

        if _display_last_error:
            text _("Error: ") + _display_last_error:
                style "main_menu_version"
            text _("(Details in submod_log)"):
                style "main_menu_version"
                size 12

        hbox:
            spacing 12
            textbutton _("Paste API URL"):
                style "mas_button_simple"
                action Function(mas_unisync_paste_host)
            textbutton _("Paste Profile Key"):
                style "mas_button_simple"
                action Function(mas_unisync_paste_profile_key)
            textbutton _("Clear Profile Key"):
                style "mas_button_simple"
                action Function(mas_unisync_clear_profile_key)

        hbox:
            spacing 12
            textbutton _("Open Profile Keys Page"):
                style "mas_button_simple"
                action Function(mas_unisync_open_profile_keys)
            textbutton _("Upload Now"):
                style "mas_button_simple"
                action Function(mas_unisync_manual_upload)
            textbutton _("Test Connection"):
                style "mas_button_simple"
                action Function(mas_unisync_test_connection)
