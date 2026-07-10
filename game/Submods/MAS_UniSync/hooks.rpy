init -968 python:
    import mas_unisync_http
    import mas_unisync_sync
    import datetime
    import os
    import sys
    import threading
    import time

    MAS_UNISYNC_LOCK_NOT_HELD_CHKSUM = "Unisync_lock_not_held"
    mas_unisync_session = None
    mas_unisync_upload_thread = None
    mas_unisync_heartbeat_thread = None
    mas_unisync_stop_event = threading.Event()
    mas_unisync_original_persistent_save = None
    mas_unisync_lock_not_held = False
    mas_unisync_startup_failed = False
    mas_unisync_guest_warning_visible = False

    def mas_unisync_savedir():
        return renpy.config.savedir

    def mas_unisync_persistent_path():
        return mas_unisync_core.get_persistent_path(mas_unisync_savedir())

    def mas_unisync_versions():
        renpy_version = None
        try:
            renpy_version = renpy.version(tuple=False)
        except Exception:
            renpy_version = getattr(renpy, "version_string", "")
        mas_version = getattr(config, "version", "")
        return str(renpy_version or ""), str(mas_version or "")

    def mas_unisync_cleanup_for_renpy6():
        for key in ("_voice_mute", "_mas_acs_pre_list", "_mas_windowreacts_notif_filters", "_mas_unisync_status"):
            try:
                if key in persistent.__dict__:
                    del persistent.__dict__[key]
            except Exception:
                pass

    def mas_unisync_make_session():
        renpy_version, mas_version = mas_unisync_versions()
        return mas_unisync_sync.SyncSession(
            mas_unisync_get_host(),
            mas_unisync_get_profile_key(),
            mas_unisync_persistent_path(),
            renpy_version=renpy_version,
            mas_version=mas_version
        )

    def mas_unisync_enter_lock_not_held_mode(reason=None):
        global mas_unisync_lock_not_held
        mas_unisync_lock_not_held = True
        message = "MAS UniSync lock is not held; persistent save and upload are disabled"
        if reason is not None:
            message = message + ": " + mas_unisync_core.text_type(reason)
        try:
            persistent._mas_moni_chksum = MAS_UNISYNC_LOCK_NOT_HELD_CHKSUM
        except Exception:
            pass
        mas_override_label("mas_dockstat_found_monika", "mas_unisync_empty_return")
        mas_unisync_status["sync_status"] = "disabled"
        mas_unisync_status["lock_state"] = "not_held"
        mas_unisync_status["last_error"] = mas_unisync_core.renpy_safe_text(message)
        try:
            if mas_unisync_session is not None:
                mas_unisync_session.status.enabled = False
                mas_unisync_session.status.lock_state = "not_held"
                mas_unisync_session.status.lease_token = ""
                mas_unisync_session.status.mark_error_full(message)
        except Exception:
            pass
        mas_unisync_core.submod_log_error(message)
        return None

    def mas_unisync_enter_startup_failure_mode(reason=None):
        global mas_unisync_startup_failed
        mas_unisync_startup_failed = True
        message = "当前会话无法保存，因为连接至 UniSync 服务器失败。请清除 UniSync API key 以禁用 UniSync。"
        if reason is not None:
            message = message + " " + mas_unisync_core.text_type(reason)
        mas_unisync_status["sync_status"] = "disabled"
        mas_unisync_status["lock_state"] = "startup_failed"
        mas_unisync_status["last_error"] = mas_unisync_core.renpy_safe_text(message)
        try:
            if mas_unisync_session is not None:
                mas_unisync_session.status.enabled = False
                mas_unisync_session.status.lock_state = "startup_failed"
                mas_unisync_session.status.lease_token = ""
                mas_unisync_session.status.mark_error_full(message)
        except Exception:
            pass
        mas_unisync_core.submod_log_error(message)
        return None

    def mas_unisync_start_heartbeat():
        global mas_unisync_heartbeat_thread
        if mas_unisync_session is None:
            return
        if mas_unisync_heartbeat_thread is not None and mas_unisync_heartbeat_thread.is_alive():
            return
        mas_unisync_stop_event.clear()

        def heartbeat_loop():
            while not mas_unisync_stop_event.wait(15.0):
                try:
                    mas_unisync_session.heartbeat()
                except mas_unisync_core.UniSyncLockNotHeldError as exc:
                    mas_unisync_enter_lock_not_held_mode(exc)
                    break
                except Exception as exc:
                    mas_unisync_core.submod_log_debug(str(exc))
                    mas_unisync_session.status.mark_error(exc)
                    mas_unisync_update_status(mas_unisync_session.status)

        mas_unisync_heartbeat_thread = threading.Thread(target=heartbeat_loop)
        mas_unisync_heartbeat_thread.daemon = True
        mas_unisync_heartbeat_thread.start()

    def mas_unisync_persist_guest_created():
        persistent._mas_unisync_guest_created = True
        mas_unisync_original_persistent_save()

    def mas_unisync_start_initial_guest_sync():
        return mas_unisync_startup_sync(force=True, upload_after_sync=True, load_remote_into_memory=True)

    def mas_unisync_log_guest_provision_error(exc):
        mas_unisync_core.submod_log_debug(
            "MAS UniSync guest profile creation failed: {0}".format(exc)
        )

    def mas_unisync_try_provision_guest():
        return mas_unisync_sync.provision_guest_profile(
            mas_unisync_get_host(),
            mas_unisync_get_profile_key(),
            bool(getattr(persistent, "_mas_unisync_guest_created", False)),
            lambda profile_key: mas_unisync_save_key(mas_unisync_core.PROFILE_KEY_FEATURE, profile_key),
            mas_unisync_persist_guest_created,
            mas_unisync_start_initial_guest_sync,
            on_error=mas_unisync_log_guest_provision_error
        )

    def mas_unisync_show_guest_warning_if_needed(resolved_profile):
        global mas_unisync_guest_warning_visible
        today = datetime.date.today().isoformat()
        last_warning_date = getattr(persistent, "_mas_unisync_guest_warning_date", "")
        if not mas_unisync_sync.should_show_guest_warning(
            resolved_profile,
            last_warning_date,
            today
        ):
            return False
        persistent._mas_unisync_guest_warning_date = today
        mas_unisync_original_persistent_save()
        mas_unisync_guest_warning_visible = True
        return True

    def mas_unisync_startup_sync(force=False, raise_on_failure=False, upload_after_sync=False, load_remote_into_memory=False):
        global mas_unisync_session, mas_unisync_lock_not_held, mas_unisync_startup_failed
        profile_key = mas_unisync_get_profile_key()
        if not profile_key:
            mas_unisync_lock_not_held = False
            mas_unisync_startup_failed = False
            mas_unisync_update_status(message="")
            mas_unisync_status["sync_status"] = "disabled"
            mas_unisync_status["lock_state"] = "unlocked"
            return None
        if mas_unisync_session is not None and not force:
            return mas_unisync_session
        mas_unisync_session = mas_unisync_make_session()
        try:
            mas_unisync_session.start(upload_after_sync=upload_after_sync, load_remote_into_memory=load_remote_into_memory)
            mas_unisync_show_guest_warning_if_needed(mas_unisync_session.resolved_profile)
            mas_unisync_lock_not_held = False
            mas_unisync_startup_failed = False
            mas_unisync_update_status(mas_unisync_session.status)
            mas_unisync_start_heartbeat()
            return mas_unisync_session
        except mas_unisync_core.UniSyncLockNotHeldError as exc:
            return mas_unisync_enter_lock_not_held_mode(exc)
        except (mas_unisync_http.UniSyncHTTPError, mas_unisync_core.UniSyncError) as exc:
            mas_unisync_core.submod_log_debug(str(exc))
            mas_unisync_session.status.mark_error(exc)
            mas_unisync_update_status(mas_unisync_session.status)
            if raise_on_failure:
                raise
            return mas_unisync_enter_startup_failure_mode(exc)
        except Exception as exc:
            mas_unisync_core.submod_log_debug(str(exc))
            mas_unisync_session.status.mark_error(exc)
            mas_unisync_update_status(mas_unisync_session.status)
            if raise_on_failure:
                raise
            return None

    def mas_unisync_validate_persistent_for_upload(raise_on_failure=False):
        if mas_unisync_startup_failed:
            if raise_on_failure:
                raise mas_unisync_core.UniSyncError("startup connection to UniSync server failed")
            return False
        if mas_unisync_lock_not_held:
            if raise_on_failure:
                raise mas_unisync_core.UniSyncLockNotHeldError("sync lock is not held")
            return False
        if mas_unisync_session is None or not mas_unisync_session.status.enabled:
            return False
        validate = getattr(mas_unisync_guard, "validate_persistent_dict", None)
        if validate is None:
            return False
        ok, reason = validate(persistent.__dict__)
        if not ok:
            message = "MAS UniSync blocked upload: " + reason
            mas_unisync_core.submod_log_debug(message)
            mas_unisync_session.status.mark_error(message)
            mas_unisync_update_status(mas_unisync_session.status)
            if raise_on_failure:
                raise Exception(message)
            return False
        return True

    def mas_unisync_guard_enabled():
        if not mas_unisync_get_profile_key():
            return False
        if mas_unisync_session is None:
            return False
        try:
            return bool(mas_unisync_session.status.enabled)
        except Exception:
            return False

    def mas_unisync_find_persistent_issues():
        find_issues = getattr(mas_unisync_guard, "find_persistent_issues", None)
        if find_issues is None:
            return []
        return find_issues(persistent.__dict__)

    def mas_unisync_set_guard_issues(issues, message=None):
        global mas_unisync_guard_state
        if not isinstance(globals().get("mas_unisync_guard_state"), dict):
            mas_unisync_guard_state = {}
        mas_unisync_guard_state["issues"] = issues
        mas_unisync_guard_state["last_blocked_at"] = mas_unisync_core.iso_now()
        if message is not None:
            mas_unisync_guard_state["message"] = message
            mas_unisync_status["last_error"] = message
            try:
                mas_unisync_session.status.mark_error_full(message)
            except Exception:
                pass

    def mas_unisync_block_persistent_save(issues):
        count = len(issues)
        message = "MAS UniSync blocked persistent save: {0} unsupported persistent value(s) found".format(count)
        mas_unisync_set_guard_issues(issues, message=message)
        mas_unisync_core.submod_log_error(message)
        try:
            renpy.show_screen("mas_unisync_persistent_guard_warning")
        except Exception:
            pass
        return None

    def mas_unisync_upload_now(raise_on_failure=False, force=False):
        if mas_unisync_startup_failed:
            return None
        if mas_unisync_lock_not_held:
            return None
        if not mas_unisync_validate_persistent_for_upload(raise_on_failure=raise_on_failure):
            return None
        try:
            if force:
                result = mas_unisync_session.upload_persistent()
            else:
                result = mas_unisync_session.upload_if_changed()
            mas_unisync_update_status(mas_unisync_session.status)
            return result
        except mas_unisync_core.UniSyncLockNotHeldError as exc:
            return mas_unisync_enter_lock_not_held_mode(exc)
        except Exception as exc:
            mas_unisync_core.submod_log_debug(str(exc))
            mas_unisync_session.status.mark_error(exc)
            mas_unisync_update_status(mas_unisync_session.status)
            if raise_on_failure:
                raise
            return None

    def mas_unisync_enqueue_upload():
        global mas_unisync_upload_thread
        if mas_unisync_startup_failed:
            return
        if mas_unisync_lock_not_held:
            return
        if mas_unisync_session is None or not mas_unisync_session.status.enabled:
            return
        if mas_unisync_upload_thread is not None and mas_unisync_upload_thread.is_alive():
            return
        if not mas_unisync_validate_persistent_for_upload(raise_on_failure=False):
            return

        def upload_worker():
            try:
                mas_unisync_session.upload_if_changed()
                mas_unisync_update_status(mas_unisync_session.status)
            except mas_unisync_core.UniSyncLockNotHeldError as exc:
                mas_unisync_enter_lock_not_held_mode(exc)
            except Exception as exc:
                mas_unisync_core.submod_log_debug(str(exc))
                mas_unisync_session.status.mark_error(exc)
                mas_unisync_update_status(mas_unisync_session.status)

        mas_unisync_upload_thread = threading.Thread(target=upload_worker)
        mas_unisync_upload_thread.daemon = True
        mas_unisync_upload_thread.start()

    def mas_unisync_wrapped_persistent_save():
        if mas_unisync_startup_failed:
            return None
        if mas_unisync_lock_not_held:
            return None
        if not mas_unisync_guard_enabled():
            return mas_unisync_original_persistent_save()
        _issues = mas_unisync_find_persistent_issues()
        if _issues:
            mas_unisync_block_persistent_save(_issues)
            return None
        rv = mas_unisync_original_persistent_save()
        mas_unisync_enqueue_upload()
        return rv

    def mas_unisync_install_save_hook():
        global mas_unisync_original_persistent_save
        if mas_unisync_original_persistent_save is not None:
            return
        mas_unisync_original_persistent_save = renpy.persistent.save
        renpy.persistent.save = mas_unisync_wrapped_persistent_save

    def mas_unisync_install_lock_not_held_overlay():
        try:
            if "mas_unisync_lock_not_held_overlay" not in config.overlay_screens:
                config.overlay_screens.append("mas_unisync_lock_not_held_overlay")
            if "mas_unisync_startup_failure_overlay" not in config.overlay_screens:
                config.overlay_screens.append("mas_unisync_startup_failure_overlay")
            if "mas_unisync_guest_warning_overlay" not in config.overlay_screens:
                config.overlay_screens.append("mas_unisync_guest_warning_overlay")
        except Exception:
            pass

    def mas_unisync_shutdown():
        if mas_unisync_startup_failed:
            return
        if mas_unisync_lock_not_held:
            return
        mas_unisync_stop_event.set()
        try:
            if mas_unisync_upload_thread is not None and mas_unisync_upload_thread.is_alive():
                mas_unisync_upload_thread.join(5.0)
            if mas_unisync_session is not None and mas_unisync_session.status.enabled:
                mas_unisync_upload_now(raise_on_failure=True)
        finally:
            if mas_unisync_session is not None and mas_unisync_session.status.lease_token:
                try:
                    mas_unisync_session.release()
                    mas_unisync_update_status(mas_unisync_session.status)
                except Exception as exc:
                    mas_unisync_core.submod_log_debug(str(exc))

    mas_unisync_cleanup_for_renpy6()
    mas_unisync_install_save_hook()
    mas_unisync_install_lock_not_held_overlay()
    mas_unisync_try_provision_guest()

    if mas_unisync_session is None and not mas_unisync_lock_not_held:
        _api_url = mas_unisync_get_host()
        _profile_key = mas_unisync_get_profile_key()
        if _api_url and _profile_key:
            mas_unisync_session = mas_unisync_make_session()
            mas_unisync_startup_sync(force=True, load_remote_into_memory=True)

init python:
    @store.mas_submod_utils.functionplugin("_quit", priority=-100)
    def mas_unisync_on_quit():
        if mas_unisync_startup_failed:
            return
        if mas_unisync_lock_not_held:
            return
        if not mas_unisync_guard_enabled():
            renpy.persistent.save()
            mas_unisync_shutdown()
            return
        _issues = mas_unisync_find_persistent_issues()
        if _issues:
            mas_unisync_block_persistent_save(_issues)
            raise Exception(
                "MAS UniSync final persistent save blocked because persistent contains unsupported class data. "
                "Open MAS UniSync guard details and remove the listed persistent attributes before quitting."
            )
        try:
            renpy.persistent.save()
            mas_unisync_shutdown()
        except Exception as exc:
            raise Exception(
                "MAS UniSync final upload failed: {0}\n"
                "Please manually back up your local persistent file before troubleshooting or using another client.".format(exc)
            )

label mas_unisync_empty_return:
    while True:
        pause 1.0
    return
