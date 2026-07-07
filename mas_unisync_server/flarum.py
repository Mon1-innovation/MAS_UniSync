from __future__ import annotations

import httpx


class FlarumClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def login(self, identification: str, password: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            response = await client.post(
                "/api/token",
                json={"identification": identification, "password": password},
            )
            response.raise_for_status()
            payload = response.json()
            return {"token": payload["token"], "user_id": str(payload["userId"])}

    async def get_user(self, token: str, user_id: str) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10) as client:
            response = await client.get(
                f"/api/users/{user_id}",
                headers={"Authorization": f"Token {token}"},
            )
            response.raise_for_status()
            data = response.json()["data"]
            included = response.json().get("included", [])
            user_attrs = data.get("attributes", {})
            relationships = data.get("relationships", {})
            included_groups = {
                str(item.get("id")): item.get("attributes", {})
                for item in included
                if item.get("type") == "groups"
            }
            groups = []
            for group in relationships.get("groups", {}).get("data", []):
                group_id = str(group.get("id"))
                group_attrs = group.get("attributes") or included_groups.get(group_id, {})
                groups.append({"id": group_id, "name": group_attrs.get("nameSingular") or group_attrs.get("name")})
            return {
                "flarum_user_id": str(data["id"]),
                "username": user_attrs.get("username") or "",
                "display_name": user_attrs.get("displayName"),
                "avatar_url": user_attrs.get("avatarUrl"),
                "groups": groups,
            }
