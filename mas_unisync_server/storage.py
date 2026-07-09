from __future__ import annotations

from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx


class ObjectStorage(Protocol):
    def put(self, profile_id: int, version_id: int, sha256_hex: str, data: bytes) -> str:
        ...

    def get(self, object_path: str) -> bytes:
        ...

    def delete(self, object_path: str) -> None:
        ...


class LocalObjectStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, profile_id: int, version_id: int, sha256_hex: str, data: bytes) -> str:
        relative = Path(str(profile_id)) / sha256_hex[:2] / f"{version_id}-{sha256_hex}.bin"
        full_path = self.root / relative
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        return relative.as_posix()

    def get(self, object_path: str) -> bytes:
        full_path = (self.root / object_path).resolve()
        root = self.root.resolve()
        if not full_path.is_relative_to(root):
            raise ValueError("object_path escapes storage root")
        return full_path.read_bytes()

    def delete(self, object_path: str) -> None:
        full_path = (self.root / object_path).resolve()
        root = self.root.resolve()
        if not full_path.is_relative_to(root):
            raise ValueError("object_path escapes storage root")
        try:
            full_path.unlink()
        except FileNotFoundError:
            pass


class WebDavObjectStorage:
    def __init__(
        self,
        *,
        base_url: str,
        username: str = "",
        password: str = "",
        root_path: str = "",
        timeout: float = 30.0,
    ):
        self.base_url = base_url.strip().rstrip("/")
        self.username = username
        self.password = password
        self.root_path = root_path.strip("/")
        self.timeout = timeout

    def put(self, profile_id: int, version_id: int, sha256_hex: str, data: bytes) -> str:
        relative = Path(str(profile_id)) / sha256_hex[:2] / f"{version_id}-{sha256_hex}.bin"
        object_path = relative.as_posix()
        self._ensure_collections(object_path)
        with self._client() as client:
            response = client.put(self._url(object_path), content=data)
        response.raise_for_status()
        return object_path

    def get(self, object_path: str) -> bytes:
        with self._client() as client:
            response = client.get(self._url(object_path))
        response.raise_for_status()
        return response.content

    def delete(self, object_path: str) -> None:
        with self._client() as client:
            response = client.request("DELETE", self._url(object_path))
        if response.status_code == 404:
            return
        response.raise_for_status()

    def _client(self) -> httpx.Client:
        auth = (self.username, self.password) if self.username else None
        return httpx.Client(timeout=self.timeout, auth=auth)

    def _url(self, object_path: str) -> str:
        pieces = [self.base_url]
        if self.root_path:
            pieces.append(self._quote_path(self.root_path))
        pieces.append(self._quote_path(object_path.strip("/")))
        return "/".join(part.strip("/") if index else part for index, part in enumerate(pieces))

    def _ensure_collections(self, object_path: str) -> None:
        parts = object_path.strip("/").split("/")[:-1]
        current: list[str] = []
        for part in parts:
            current.append(part)
            collection_path = "/".join(current)
            with self._client() as client:
                response = client.request("MKCOL", self._url(collection_path))
            if response.status_code not in {200, 201, 204, 405}:
                response.raise_for_status()

    @staticmethod
    def _quote_path(value: str) -> str:
        return "/".join(quote(part, safe="") for part in value.split("/") if part)
