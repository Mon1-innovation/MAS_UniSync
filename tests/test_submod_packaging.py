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
    assert "mas_unisync_startup_sync()" in hooks_source
    assert "mas_unisync_startup_sync(force=True, raise_on_failure=True, upload_after_sync=True)" in header_source
    assert "mas_unisync_startup_sync(force=True, raise_on_failure=True)" in hooks_source


def test_profile_key_setup_requests_immediate_upload_after_cloud_sync():
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )

    assert "def mas_unisync_startup_sync(force=False, raise_on_failure=False, upload_after_sync=False):" in hooks_source
    assert "mas_unisync_session.start(upload_after_sync=upload_after_sync)" in hooks_source
    assert header_source.count("upload_after_sync=True") == 2


def test_settings_panel_exposes_manual_upload_button():
    header_source = Path("game/Submods/MAS_UniSync/header.rpy").read_text(
        encoding="utf-8"
    )
    hooks_source = Path("game/Submods/MAS_UniSync/hooks.rpy").read_text(
        encoding="utf-8"
    )

    assert "def mas_unisync_manual_upload():" in hooks_source
    assert 'textbutton _("Upload Now")' in header_source
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
