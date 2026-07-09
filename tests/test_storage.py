from __future__ import annotations

import httpx
import pytest

from mas_unisync_server.storage import LocalObjectStorage, WebDavObjectStorage


def test_local_storage_rejects_read_paths_outside_root(tmp_path):
    storage = LocalObjectStorage(tmp_path / "objects")

    with pytest.raises(ValueError, match="escapes storage root"):
        storage.get("../outside.bin")


def test_webdav_storage_put_get_delete_uses_encoded_paths_and_auth(monkeypatch):
    calls = []
    clients = []

    class FakeClient:
        def __init__(self, *, timeout, auth):
            self.timeout = timeout
            self.auth = auth
            self.closed = False
            clients.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.closed = True

        def put(self, url, content):
            calls.append(("PUT", url, content))
            return httpx.Response(201, request=httpx.Request("PUT", url))

        def get(self, url):
            calls.append(("GET", url, None))
            return httpx.Response(200, content=b"downloaded", request=httpx.Request("GET", url))

        def request(self, method, url):
            calls.append((method, url, None))
            return httpx.Response(201 if method == "MKCOL" else 204, request=httpx.Request(method, url))

    monkeypatch.setattr("mas_unisync_server.storage.httpx.Client", FakeClient)
    storage = WebDavObjectStorage(
        base_url="https://dav.example.test/root/",
        username="mas",
        password="secret",
        root_path="persistent saves",
        timeout=12.5,
    )

    object_path = storage.put(7, 3, "abcdef123456", b"payload")
    downloaded = storage.get(object_path)
    storage.delete(object_path)

    assert object_path == "7/ab/3-abcdef123456.bin"
    assert downloaded == b"downloaded"
    assert clients
    assert all(client.timeout == 12.5 and client.auth == ("mas", "secret") for client in clients)
    assert all(client.closed for client in clients)
    assert calls == [
        ("MKCOL", "https://dav.example.test/root/persistent%20saves/7", None),
        ("MKCOL", "https://dav.example.test/root/persistent%20saves/7/ab", None),
        ("PUT", "https://dav.example.test/root/persistent%20saves/7/ab/3-abcdef123456.bin", b"payload"),
        ("GET", "https://dav.example.test/root/persistent%20saves/7/ab/3-abcdef123456.bin", None),
        ("DELETE", "https://dav.example.test/root/persistent%20saves/7/ab/3-abcdef123456.bin", None),
    ]
