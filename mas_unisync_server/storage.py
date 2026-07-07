from __future__ import annotations

from pathlib import Path


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
        return (self.root / object_path).read_bytes()

    def delete(self, object_path: str) -> None:
        full_path = (self.root / object_path).resolve()
        root = self.root.resolve()
        if not full_path.is_relative_to(root):
            raise ValueError("object_path escapes storage root")
        try:
            full_path.unlink()
        except FileNotFoundError:
            pass
