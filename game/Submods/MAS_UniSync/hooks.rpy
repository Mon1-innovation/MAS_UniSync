init -968 python:
    import os
    import sys
    import threading
    import time

    mas_unisync_session = None
    mas_unisync_upload_thread = None
    mas_unisync_heartbeat_thread = None
    mas_unisync_stop_event = threading.Event()
    mas_unisync_original_persistent_save = None

    def mas_unisync_savedir():
        return renpy.config.savedir

    def mas_unisync_persistent_path():
        return mas_unisync_core.get_persistent_path(mas_unisync_savedir())

    def mas_unisync_backup_dir():
        return mas_unisync_core.get_backup_dir(mas_unisync_savedir())

    def mas_unisync_versions():
        renpy_version = None
        try:
            renpy_version = renpy.version(tuple=False)
        except Exception:
            renpy_version = getattr(renpy, "version_string", "")
        mas_version = getattr(persistent, "version_number", "")
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
            mas_unisync_backup_dir(),
            renpy_version=renpy_version,
            mas_version=mas_version
        )

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
                except Exception as exc:
                    mas_unisync_core.submod_log_debug(str(exc))
                    mas_unisync_session.status.mark_error(exc)
                    mas_unisync_update_status(mas_unisync_session.status)

        mas_unisync_heartbeat_thread = threading.Thread(target=heartbeat_loop)
        mas_unisync_heartbeat_thread.daemon = True
        mas_unisync_heartbeat_thread.start()

    def mas_unisync_startup_sync(force=False, raise_on_failure=False, upload_after_sync=False):
        global mas_unisync_session
        profile_key = mas_unisync_get_profile_key()
        if not profile_key:
            mas_unisync_update_status(message="")
            mas_unisync_status["sync_status"] = "disabled"
            mas_unisync_status["lock_state"] = "unlocked"
            return None
        if mas_unisync_session is not None and not force:
            return mas_unisync_session
        mas_unisync_session = mas_unisync_make_session()
        try:
            mas_unisync_session.start(upload_after_sync=upload_after_sync)
            mas_unisync_update_status(mas_unisync_session.status)
            mas_unisync_start_heartbeat()
            return mas_unisync_session
        except Exception as exc:
            mas_unisync_core.submod_log_debug(str(exc))
            mas_unisync_session.status.mark_error(exc)
            mas_unisync_update_status(mas_unisync_session.status)
            if raise_on_failure:
                raise
            return None

    def mas_unisync_validate_persistent_for_upload(raise_on_failure=False):
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

    def mas_unisync_upload_now(raise_on_failure=False, force=False):
        if not mas_unisync_validate_persistent_for_upload(raise_on_failure=raise_on_failure):
            return None
        try:
            if force:
                result = mas_unisync_session.upload_persistent()
            else:
                result = mas_unisync_session.upload_if_changed()
            mas_unisync_update_status(mas_unisync_session.status)
            return result
        except Exception as exc:
            mas_unisync_core.submod_log_debug(str(exc))
            mas_unisync_session.status.mark_error(exc)
            mas_unisync_update_status(mas_unisync_session.status)
            if raise_on_failure:
                raise
            return None

    def mas_unisync_enqueue_upload():
        global mas_unisync_upload_thread
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
            except Exception as exc:
                mas_unisync_core.submod_log_debug(str(exc))
                mas_unisync_session.status.mark_error(exc)
                mas_unisync_update_status(mas_unisync_session.status)

        mas_unisync_upload_thread = threading.Thread(target=upload_worker)
        mas_unisync_upload_thread.daemon = True
        mas_unisync_upload_thread.start()

    def mas_unisync_wrapped_persistent_save():
        rv = mas_unisync_original_persistent_save()
        if mas_unisync_session is not None:
            mas_unisync_enqueue_upload()
        return rv

    def mas_unisync_install_save_hook():
        global mas_unisync_original_persistent_save
        if mas_unisync_original_persistent_save is not None:
            return
        mas_unisync_original_persistent_save = renpy.persistent.save
        renpy.persistent.save = mas_unisync_wrapped_persistent_save

    def mas_unisync_test_connection():
        try:
            session = mas_unisync_startup_sync(force=True, raise_on_failure=True)
            if session is not None:
                mas_unisync_update_status(session.status)
            renpy.notify(_("MAS UniSync connection OK"))
        except Exception as exc:
            mas_unisync_update_status(message=str(exc))
            renpy.notify("MAS UniSync connection failed: " + str(exc))

    def mas_unisync_manual_upload():
        global mas_unisync_session
        try:
            if not mas_unisync_get_profile_key():
                mas_unisync_update_status(message="MAS UniSync profile key is not configured")
                renpy.notify(_("MAS UniSync profile key is not configured"))
                return
            if mas_unisync_session is not None and mas_unisync_session.status.lease_token:
                try:
                    mas_unisync_session.release()
                except Exception:
                    pass
            if mas_unisync_session is None or not mas_unisync_session.status.enabled:
                mas_unisync_session = mas_unisync_make_session()
            if not mas_unisync_session.status.lease_token:
                mas_unisync_session.acquire_lock()
            mas_unisync_update_status(mas_unisync_session.status)
            mas_unisync_start_heartbeat()
            mas_unisync_upload_now(raise_on_failure=True, force=True)
            renpy.notify(_("MAS UniSync upload complete"))
        except Exception as exc:
            mas_unisync_update_status(message=str(exc))
            renpy.notify("MAS UniSync upload failed: " + str(exc))
        finally:
            renpy.restart_interaction()

    def mas_unisync_shutdown():
        mas_unisync_stop_event.set()
        if mas_unisync_upload_thread is not None and mas_unisync_upload_thread.is_alive():
            mas_unisync_upload_thread.join(5.0)
        if mas_unisync_session is not None and mas_unisync_session.status.enabled:
            mas_unisync_upload_now(raise_on_failure=True)
            mas_unisync_session.release()
            mas_unisync_update_status(mas_unisync_session.status)

    mas_unisync_cleanup_for_renpy6()
    mas_unisync_install_save_hook()
    # If startup sync fails for any reason (lock unavailable, network error, etc.),
    # propagate the exception to block game load entirely.
    mas_unisync_startup_sync()

init python:
    @store.mas_submod_utils.functionplugin("_quit", priority=-100)
    def mas_unisync_on_quit():
        try:
            renpy.persistent.save()
            mas_unisync_shutdown()
        except Exception as exc:
            raise Exception(
                "MAS UniSync final upload failed: {0}\n"
                "Please manually back up your local persistent file before troubleshooting or using another client.".format(exc)
            )
