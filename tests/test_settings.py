from __future__ import annotations

import pytest

from mas_unisync_server.settings import build_settings


def test_build_settings_defaults_test_environment_to_sqlite(monkeypatch):
    monkeypatch.delenv("MAS_UNISYNC_ENV", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    settings = build_settings()

    assert settings.database_url == "sqlite:///./data/mas_unisync.db"


def test_build_settings_uses_explicit_postgres_url_in_production(monkeypatch):
    database_url = "postgresql+psycopg://mas_unisync:secret@postgres:5432/mas_unisync"
    monkeypatch.setenv("MAS_UNISYNC_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = build_settings()

    assert settings.database_url == database_url


def test_build_settings_builds_compose_postgres_url_in_production(monkeypatch):
    monkeypatch.setenv("MAS_UNISYNC_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret value")

    settings = build_settings()

    assert settings.database_url == "postgresql+psycopg://mas_unisync:secret%20value@postgres:5432/mas_unisync"


def test_build_settings_requires_postgres_configuration_in_production(monkeypatch):
    monkeypatch.setenv("MAS_UNISYNC_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        build_settings()


def test_build_settings_reads_trusted_proxy_ips(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "127.0.0.1,10.0.0.0/8,172.16.0.0/12")

    settings = build_settings()

    assert settings.trusted_proxy_ips == {"127.0.0.1", "10.0.0.0/8", "172.16.0.0/12"}


def test_build_settings_rejects_invalid_trusted_proxy_ips(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_IPS", "127.0.0.1,not-an-ip")

    with pytest.raises(ValueError, match="TRUSTED_PROXY_IPS contains invalid IP or CIDR: not-an-ip"):
        build_settings()
