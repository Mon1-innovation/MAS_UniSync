init -990 python:
    import os
    import sys
    import webbrowser
    import pygame
    import json

    mas_unisync_version = "0.1.0"

    mas_unisync_dir = os.path.join(renpy.config.gamedir, "Submods", "MAS_UniSync")

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
        author="P",
        name="MAS UniSync",
        description=_("Monika After Story 跨设备 persistent 同步。"),
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
    mas_unisync_guard_state = {
        "issues": [],
        "message": "",
        "last_blocked_at": "",
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
            renpy.notify(_("剪贴板为空"))
            return
        mas_unisync_save_api_url(value)
        renpy.notify(_("MAS UniSync API URL 已保存"))
        renpy.restart_interaction()

    def mas_unisync_bootstrap_setup():
        """Set profile key: upload immediately if no remote current, otherwise prompt restart."""
        session = mas_unisync_make_session()
        try:
            session.resolve_profile()
            session.acquire_lock()
        except Exception:
            try:
                session.release()
            except Exception:
                pass
            raise

        try:
            current_meta = session.current_metadata()
        finally:
            session.release()

        if current_meta is None:
            mas_unisync_startup_sync(force=True, raise_on_failure=True, upload_after_sync=True)
        else:
            global mas_unisync_session
            mas_unisync_session = None
            renpy.show_screen(
                "dialog",
                message=_("MAS UniSync 检测到已有云端数据。\n请重启游戏以同步。"),
                ok_action=Function(renpy.quit, relaunch=False),
            )

    def mas_unisync_paste_profile_key():
        value = mas_unisync_clipboard_text()
        if not value:
            renpy.notify(_("剪贴板为空"))
            return
        mas_unisync_save_key(mas_unisync_core.PROFILE_KEY_FEATURE, value)
        try:
            mas_unisync_bootstrap_setup()
            renpy.notify(_("MAS UniSync Profile Key 已保存"))
        except Exception as exc:
            mas_unisync_update_status(message=mas_unisync_core.renpy_safe_text(str(exc)))
            renpy.notify(_("MAS UniSync 连接失败：") + mas_unisync_core.renpy_safe_text(str(exc)))
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
        return False, _("请使用 MAS UniSync 设置面板里的粘贴按钮配置 Profile Key。")
    def mas_unisync_host_on_change(host):
        mas_unisync_save_api_url(host)
        return True, ""

    def mas_unisync_display_status(value):
        labels = {
            "enabled": _("已启用"),
            "disabled": _("未启用"),
            "locked": _("已锁定"),
            "unlocked": _("未锁定"),
            "released": _("已释放"),
        }
        return labels.get(value, value)

    def mas_unisync_guard_runtime_enabled():
        enabled = globals().get("mas_unisync_guard_enabled")
        if enabled is None:
            return False
        try:
            return bool(enabled())
        except Exception:
            return False

    def mas_unisync_refresh_guard_issues():
        global mas_unisync_guard_state
        if not isinstance(mas_unisync_guard_state, dict):
            mas_unisync_guard_state = {}
        if not mas_unisync_guard_runtime_enabled():
            mas_unisync_guard_state["issues"] = []
            mas_unisync_guard_state["message"] = ""
            return []
        find_issues = globals().get("mas_unisync_find_persistent_issues")
        if find_issues is None:
            return []
        issues = find_issues()
        mas_unisync_guard_state["issues"] = issues
        if not issues:
            mas_unisync_guard_state["message"] = ""
        return issues

    def mas_unisync_open_persistent_guard_detail():
        mas_unisync_refresh_guard_issues()
        renpy.show_screen("mas_unisync_persistent_guard_detail")
        renpy.restart_interaction()

    def mas_unisync_delete_persistent_guard_issue(top_key):
        try:
            if top_key in persistent.__dict__:
                del persistent.__dict__[top_key]
        except Exception as exc:
            mas_unisync_update_status(message=mas_unisync_core.renpy_safe_text(str(exc)))
        mas_unisync_refresh_guard_issues()
        renpy.restart_interaction()

    def mas_unisync_toggle_guard_help(index):
        if index in mas_unisync_guard_help_expanded:
            mas_unisync_guard_help_expanded.remove(index)
        else:
            mas_unisync_guard_help_expanded.add(index)
        renpy.restart_interaction()

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

default mas_unisync_guard_help_expanded = set()

screen mas_unisync_persistent_guard_warning():
    zorder 200
    frame:
        align (0.98, 0.04)
        xmaximum 520
        padding (14, 12)
        vbox:
            spacing 8
            text _("MAS UniSync 已阻止 persistent 保存"):
                style "main_menu_version"
            text _("当前 persistent 无法保存，因为包含非标准 class。带有这些 class 的 persistent 可能无法在其他客户端运行。"):
                style "main_menu_version"
                size 16
            hbox:
                spacing 10
                textbutton _("打开详情"):
                    style "mas_button_simple"
                    action Function(mas_unisync_open_persistent_guard_detail)
                textbutton _("关闭"):
                    style "mas_button_simple"
                    action Hide("mas_unisync_persistent_guard_warning")

screen mas_unisync_persistent_guard_detail():
    zorder 201
    modal True
    python:
        _guard_enabled = mas_unisync_guard_runtime_enabled()
        _issues = mas_unisync_guard_state.get("issues", []) if isinstance(mas_unisync_guard_state, dict) else []

    frame:
        align (0.5, 0.5)
        xmaximum 980
        ymaximum 660
        padding (18, 16)
        vbox:
            spacing 10
            text _("persistent 非标准 class 检查"):
                style "main_menu_version"
            if not _guard_enabled:
                text _("UniSync 未启用，当前不检查 persistent 非标准 class。"):
                    style "main_menu_version"
            elif not _issues:
                text _("未检测到非标准 class。"):
                    style "main_menu_version"
            else:
                text _("当前 persistent 无法保存，因为包含非标准 class。带有这些 class 的 persistent 可能无法在其他客户端运行。"):
                    style "main_menu_version"
                    size 16
                viewport:
                    mousewheel True
                    draggable True
                    ymaximum 470
                    vbox:
                        spacing 12
                        for _index, _issue in enumerate(_issues):
                            frame:
                                xfill True
                                padding (10, 8)
                                vbox:
                                    spacing 5
                                    text _("属性名：") + mas_unisync_core.renpy_display_text(_issue.get("top_key", "")):
                                        style "main_menu_version"
                                        size 16
                                    text _("完整路径：") + mas_unisync_core.renpy_display_text(_issue.get("path", "")):
                                        style "main_menu_version"
                                        size 16
                                    text _("class：") + mas_unisync_core.renpy_display_text(_issue.get("type_name", "")):
                                        style "main_menu_version"
                                        size 16
                                    text _("module：") + mas_unisync_core.renpy_display_text(_issue.get("module_name", "")):
                                        style "main_menu_version"
                                        size 16
                                    text _("repr：") + mas_unisync_core.renpy_display_text(_issue.get("repr_text", "")):
                                        style "main_menu_version"
                                        size 16
                                    hbox:
                                        spacing 10
                                        textbutton _("展开/收起 help()"):
                                            style "mas_button_simple"
                                            action Function(mas_unisync_toggle_guard_help, _index)
                                        textbutton _("删除该 persistent 属性"):
                                            style "mas_button_simple"
                                            action Function(mas_unisync_delete_persistent_guard_issue, _issue.get("top_key", ""))
                                    if _index in mas_unisync_guard_help_expanded:
                                        text mas_unisync_core.renpy_display_text(_issue.get("help_text", "") or _("没有 help() 内容。")):
                                            style "main_menu_version"
                                            size 12
            hbox:
                spacing 10
                textbutton _("刷新"):
                    style "mas_button_simple"
                    action Function(mas_unisync_refresh_guard_issues)
                textbutton _("关闭"):
                    style "mas_button_simple"
                    action Hide("mas_unisync_persistent_guard_detail")

screen mas_unisync_settingpane():
    python:
        _status = mas_unisync_status if isinstance(mas_unisync_status, dict) else {}
        _api_url = mas_unisync_get_api_url()
        _key = mas_unisync_get_profile_key()
        _masked_key = _key[:12] + "..." if len(_key) > 15 else _key
        _display_api = mas_unisync_core.renpy_display_text(_api_url)
        _display_key = mas_unisync_core.renpy_display_text(_masked_key if _masked_key else _("未配置"))
        _display_sync_status = mas_unisync_core.renpy_display_text(mas_unisync_display_status(_status.get("sync_status", "disabled")))
        _display_lock_state = mas_unisync_core.renpy_display_text(mas_unisync_display_status(_status.get("lock_state", "unlocked")))
        _display_last_upload = mas_unisync_core.renpy_display_text(_status.get("last_upload_at") or "-")
        _display_last_download = mas_unisync_core.renpy_display_text(_status.get("last_download_at") or "-")
        _display_last_error = mas_unisync_core.renpy_display_text(_status.get("last_error") or "")

    vbox:
        spacing 8
        xpos 45
        xmaximum 900

        text _("MAS UniSync"):
            style "main_menu_version"

        text _("API URL：") + _display_api:
            style "main_menu_version"
        text _("Profile Key：") + _display_key:
            style "main_menu_version"
        text _("同步状态：") + _display_sync_status:
            style "main_menu_version"
        text _("锁状态：") + _display_lock_state:
            style "main_menu_version"
        text _("最后上传：") + _display_last_upload:
            style "main_menu_version"
        text _("最后下载：") + _display_last_download:
            style "main_menu_version"

        if _display_last_error:
            text _("错误：") + _display_last_error:
                style "main_menu_version"
            text _("（详情见 submod_log）"):
                style "main_menu_version"
                size 12

        hbox:
            spacing 12
            textbutton _("粘贴 API URL"):
                style "mas_button_simple"
                action Function(mas_unisync_paste_host)
            textbutton _("粘贴 Profile Key"):
                style "mas_button_simple"
                action Function(mas_unisync_paste_profile_key)
            textbutton _("清除 Profile Key"):
                style "mas_button_simple"
                action Function(mas_unisync_clear_profile_key)

        hbox:
            spacing 12
            textbutton _("打开 Profile Key 页面"):
                style "mas_button_simple"
                action Function(mas_unisync_open_profile_keys)
            textbutton _("立即上传"):
                style "mas_button_simple"
                action Function(mas_unisync_manual_upload)
            textbutton _("测试连接"):
                style "mas_button_simple"
                action Function(mas_unisync_test_connection)
            textbutton _("查看 persistent 非标准 class"):
                style "mas_button_simple"
                action Function(mas_unisync_open_persistent_guard_detail)
