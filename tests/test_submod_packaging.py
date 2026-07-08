from __future__ import annotations

from pathlib import Path


def test_submod_source_package_excludes_generated_cache_files():
    submod_paths = list(Path("game/Submods/MAS_UniSync").rglob("*"))
    submod_files = [path for path in submod_paths if path.is_file()]

    assert submod_files
    assert all(path.name != "__pycache__" for path in submod_paths)
    assert all("__pycache__" not in path.parts for path in submod_files)
    assert all(path.suffix != ".rpyc" for path in submod_files)


def test_renpy_compat_uses_python2_safe_module_names():
    compat_source = Path("game/Submods/MAS_UniSync/00_compat.rpy").read_text(
        encoding="utf-8"
    )

    assert 'import renpy' not in compat_source
    assert 'from renpy' not in compat_source
    assert 'types.ModuleType(b"renpy.revertable")' in compat_source
    assert 'sys.modules[b"renpy.revertable"]' in compat_source
    assert 'sys.modules.get(b"renpy.python")' in compat_source


def test_persistent_reload_runs_after_mas_api_keys_init_not_python_early():
    compat_source = Path("game/Submods/MAS_UniSync/00_compat.rpy").read_text(
        encoding="utf-8"
    )
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )

    assert "early_sync_persistent" not in compat_source
    assert "MAS_UniSync: early sync starting" not in compat_source
    assert "init -968 python:" in hooks_source
    assert "def mas_unisync_reload_persistent_after_api_keys():" in hooks_source
    assert "mas_unisync_reload_persistent_after_api_keys()" in hooks_source
    assert "mas_unisync_core.reload_persistent_from_remote(" in hooks_source
    assert "mas_unisync_get_host()" in hooks_source
    assert "mas_unisync_get_profile_key()" in hooks_source
    assert "except mas_unisync_core.UniSyncError:" in hooks_source
    assert hooks_source.index("mas_unisync_reload_persistent_after_api_keys()") < hooks_source.index("mas_unisync_startup_sync(force=True)")


def test_persistent_reload_keeps_direct_in_memory_replacement():
    core_source = Path("game/Submods/MAS_UniSync/mas_unisync_core.py").read_text(
        encoding="utf-8"
    )

    assert "def reload_persistent_from_remote(api_url, profile_key, savedir, early_log=None):" in core_source
    assert "early_load_api_keys" not in core_source
    assert "load_pickle_payload(_s)" in core_source
    assert "renpy.game.persistent.__dict__.clear()" in core_source
    assert "renpy.game.persistent.__dict__.update(remote_persistent.__dict__)" in core_source
    assert "renpy.game.persistent._update()" in core_source


def test_remote_persistent_current_eli_data_is_cleaned_after_in_memory_replacement():
    core_source = Path("game/Submods/MAS_UniSync/mas_unisync_core.py").read_text(
        encoding="utf-8"
    )
    replacement_index = core_source.index(
        "renpy.game.persistent.__dict__.update(remote_persistent.__dict__)"
    )
    cleanup_index = core_source.index(
        "cleanup_current_eli_data_for_device(renpy.game.persistent, renpy.has_label)"
    )
    update_index = core_source.index("renpy.game.persistent._update()")

    assert replacement_index < cleanup_index < update_index


def test_submod_http_does_not_import_uuid_module_missing_from_renpy_699():
    http_source = Path("game/Submods/MAS_UniSync/mas_unisync_http.py").read_text(
        encoding="utf-8"
    )

    assert "import uuid" not in http_source


def test_startup_sync_does_not_abort_mas_when_profile_key_is_invalid():
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )

    assert "def mas_unisync_startup_sync(force=False, raise_on_failure=False, upload_after_sync=False):" in hooks_source
    assert "if raise_on_failure:" in hooks_source
    assert "                raise" in hooks_source
    assert "if _api_url and _profile_key:" in hooks_source
    assert "mas_unisync_startup_sync(force=True)" in hooks_source
    assert "mas_unisync_startup_sync(force=True, raise_on_failure=True, upload_after_sync=True)" in header_source
    assert "mas_unisync_startup_sync(force=True, raise_on_failure=True)" in hooks_source


def test_mas_version_metadata_comes_from_config_version():
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )
    versions_source = hooks_source.split(
        "def mas_unisync_versions():",
        1,
    )[1].split(
        "    def mas_unisync_cleanup_for_renpy6():",
        1,
    )[0]

    assert 'getattr(config, "version", "")' in versions_source
    assert 'getattr(persistent, "version_number", "")' not in versions_source


def test_profile_key_setup_requests_immediate_upload_after_cloud_sync():
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )

    assert "def mas_unisync_startup_sync(force=False, raise_on_failure=False, upload_after_sync=False):" in hooks_source
    assert "mas_unisync_session.start(upload_after_sync=upload_after_sync)" in hooks_source
    assert header_source.count("upload_after_sync=True") == 1
    assert "def mas_unisync_bootstrap_setup" in header_source
    assert "show_screen" in header_source
    assert "dialog" in header_source
    assert "renpy.quit" in header_source


def test_settings_panel_exposes_manual_upload_button():
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )

    assert "def mas_unisync_manual_upload():" in hooks_source
    assert 'textbutton _("立即上传")' in header_source
    assert "action Function(mas_unisync_manual_upload)" in header_source


def test_runtime_sync_status_is_not_stored_in_persistent():
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )

    assert "default persistent._mas_unisync_status" not in header_source
    assert "persistent._mas_unisync_status" not in header_source
    assert "persistent._mas_unisync_status" not in hooks_source
    assert "mas_unisync_status = {" in header_source
    assert '"_mas_unisync_status"' in hooks_source


def test_persistent_guard_hook_only_runs_when_unisync_is_enabled():
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )
    wrapped_save_source = hooks_source.split(
        "def mas_unisync_wrapped_persistent_save():", 1
    )[1].split(
        "    def mas_unisync_install_save_hook():",
        1,
    )[0]

    assert "def mas_unisync_guard_enabled():" in hooks_source
    assert "if not mas_unisync_get_profile_key():" in hooks_source
    assert "if mas_unisync_session is None:" in hooks_source
    assert "return bool(mas_unisync_session.status.enabled)" in hooks_source
    assert "if not mas_unisync_guard_enabled():" in wrapped_save_source
    assert "return mas_unisync_original_persistent_save()" in wrapped_save_source


def test_persistent_guard_blocks_original_save_and_upload_when_issues_exist():
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )
    wrapped_save_source = hooks_source.split(
        "def mas_unisync_wrapped_persistent_save():", 1
    )[1].split(
        "    def mas_unisync_install_save_hook():",
        1,
    )[0]
    issue_index = wrapped_save_source.index("mas_unisync_find_persistent_issues()")
    original_save_index = wrapped_save_source.index("rv = mas_unisync_original_persistent_save()")
    enqueue_index = wrapped_save_source.index("mas_unisync_enqueue_upload()")

    assert issue_index < original_save_index < enqueue_index
    assert "if _issues:" in wrapped_save_source
    assert "return None" in wrapped_save_source.split("if _issues:", 1)[1].split(
        "rv = mas_unisync_original_persistent_save()", 1
    )[0]
    assert "mas_unisync_enqueue_upload()" not in wrapped_save_source.split(
        "if _issues:", 1
    )[1].split("return None", 1)[0]
    assert "renpy.show_screen(\"mas_unisync_persistent_guard_warning\")" in hooks_source


def test_persistent_guard_quit_only_blocks_when_unisync_is_enabled():
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )
    quit_source = hooks_source.split("def mas_unisync_on_quit():", 1)[1]

    assert "if not mas_unisync_guard_enabled():" in quit_source
    assert "mas_unisync_find_persistent_issues()" in quit_source
    assert "MAS UniSync final persistent save blocked" in quit_source


def test_persistent_guard_screens_and_settings_entry_exist():
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )

    assert "mas_unisync_guard_state = {" in header_source
    assert "default mas_unisync_guard_help_expanded = set()" in header_source
    assert "screen mas_unisync_persistent_guard_warning():" in header_source
    assert "screen mas_unisync_persistent_guard_detail():" in header_source
    assert "当前 persistent 无法保存" in header_source
    assert "带有这些 class 的 persistent 可能无法在其他客户端运行" in header_source
    assert "Function(mas_unisync_delete_persistent_guard_issue" in header_source
    assert "查看 persistent 非标准 class" in header_source


def test_lock_not_held_mode_blocks_save_upload_and_shows_quit_prompt():
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )
    wrapped_save_source = hooks_source.split(
        "def mas_unisync_wrapped_persistent_save():", 1
    )[1].split(
        "    def mas_unisync_install_save_hook():",
        1,
    )[0]
    upload_now_source = hooks_source.split(
        "def mas_unisync_upload_now(raise_on_failure=False, force=False):", 1
    )[1].split(
        "    def mas_unisync_enqueue_upload():",
        1,
    )[0]
    enqueue_source = hooks_source.split(
        "def mas_unisync_enqueue_upload():", 1
    )[1].split(
        "    def mas_unisync_wrapped_persistent_save():",
        1,
    )[0]

    assert 'MAS_UNISYNC_LOCK_NOT_HELD_CHKSUM = "Unisync_lock_not_held"' in hooks_source
    assert "mas_unisync_enter_lock_not_held_mode" in hooks_source
    assert "persistent._mas_moni_chksum = MAS_UNISYNC_LOCK_NOT_HELD_CHKSUM" in hooks_source
    assert 'renpy.show_screen("mas_unisync_lock_not_held_warning")' in hooks_source
    assert 'config.overlay_screens.append("mas_unisync_lock_not_held_overlay")' in hooks_source
    assert "except mas_unisync_core.UniSyncLockNotHeldError as exc:" in hooks_source
    assert "mas_unisync_enter_lock_not_held_mode(exc)" in hooks_source

    assert "if mas_unisync_lock_not_held:" in wrapped_save_source
    assert wrapped_save_source.index("if mas_unisync_lock_not_held:") < wrapped_save_source.index(
        "mas_unisync_original_persistent_save()"
    )
    assert "return None" in wrapped_save_source.split("if mas_unisync_lock_not_held:", 1)[1].split(
        "mas_unisync_original_persistent_save()", 1
    )[0]
    assert "if mas_unisync_lock_not_held:" in upload_now_source
    assert "if mas_unisync_lock_not_held:" in enqueue_source

    assert "screen mas_unisync_lock_not_held_warning():" in header_source
    assert "screen mas_unisync_lock_not_held_overlay():" in header_source
    assert "if mas_unisync_lock_not_held:" in header_source
    assert "align (0.98, 0.04)" in header_source
    assert "[m_name]似乎不在这里呢..." in header_source
    assert 'textbutton _("退出游戏")' in header_source
    assert "Function(renpy.quit, relaunch=False)" in header_source


def test_persistent_guard_runtime_state_is_not_stored_in_persistent():
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )

    assert "persistent._mas_unisync_guard" not in header_source
    assert "persistent._mas_unisync_guard" not in hooks_source
    assert "default persistent.mas_unisync_guard" not in header_source


def test_manual_upload_button_uses_direct_upload_flow():
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )
    manual_upload_source = hooks_source.split("def mas_unisync_manual_upload():", 1)[1].split(
        "    def mas_unisync_shutdown():",
        1,
    )[0]

    assert "mas_unisync_make_session()" in manual_upload_source
    assert ".acquire_lock()" in manual_upload_source
    assert ".release()" in manual_upload_source
    assert "mas_unisync_upload_now(raise_on_failure=True, force=True)" in manual_upload_source
    assert "mas_unisync_startup_sync(" not in manual_upload_source
