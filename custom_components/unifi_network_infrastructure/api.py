"""UniFi Network API client for infrastructure-only polling."""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import UNIFI_HARDWARE_TYPES


class UniFiInfrastructureError(Exception):
    """Base error for UniFi Network Infrastructure."""


class UniFiInfrastructureAuthError(UniFiInfrastructureError):
    """Authentication failed."""


class UniFiInfrastructureClient:
    """Small UniFi OS / Network API client."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int,
        site: str,
        verify_ssl: bool,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the client."""
        self.host = host.strip().rstrip("/")
        self.username = username
        self.password = password
        self.port = port
        self.site = site.strip() or "default"
        self.verify_ssl = verify_ssl
        self.session = session
        self._csrf_token: str | None = None
        self._authenticated = False

    @property
    def base_url(self) -> str:
        """Return the controller base URL."""
        if self.host.startswith(("http://", "https://")):
            return self.host
        return f"https://{self.host}:{self.port}"

    async def async_login(self) -> None:
        """Authenticate to UniFi OS."""
        payload = {
            "username": self.username,
            "password": self.password,
            "rememberMe": True,
        }
        async with self.session.post(
            f"{self.base_url}/api/auth/login",
            json=payload,
            ssl=self.verify_ssl,
        ) as response:
            if response.status in (401, 403):
                raise UniFiInfrastructureAuthError("Invalid UniFi credentials")
            if response.status >= 400:
                text = await response.text()
                raise UniFiInfrastructureError(f"Login failed with HTTP {response.status}: {text}")
            self._csrf_token = response.headers.get("x-updated-csrf-token")
            self._authenticated = True

    async def async_logout(self) -> None:
        """Best-effort logout."""
        if not self._authenticated:
            return
        try:
            async with self.session.post(
                f"{self.base_url}/api/auth/logout",
                headers=self._headers(),
                ssl=self.verify_ssl,
            ):
                pass
        except aiohttp.ClientError:
            pass
        finally:
            self._authenticated = False
            self._csrf_token = None

    async def async_validate(self) -> dict[str, Any]:
        """Validate credentials and return a short summary."""
        devices = await self.async_get_devices()
        permissions = await self.async_get_account_permissions()
        return {"device_count": len(devices), **permissions}

    async def async_get_account_permissions(self) -> dict[str, Any]:
        """Return current-account permission summary from read-only endpoints."""
        user_payload: Any = {}
        network_payload: Any = {}
        last_error: UniFiInfrastructureError | None = None
        for path, target in (
            ("/api/users/self", "user"),
            (f"/proxy/network/api/s/{self.site}/self", "network"),
        ):
            try:
                payload = await self._request_json("GET", path)
            except UniFiInfrastructureError as err:
                last_error = err
                continue
            if target == "user":
                user_payload = payload
            else:
                network_payload = payload
        if not user_payload and not network_payload and last_error is not None:
            raise last_error
        network_user = _first_data_row(network_payload)
        site_role = str(network_user.get("site_role") or network_user.get("org_role") or "").lower()
        is_super = network_user.get("is_super") is True or network_user.get("is_owner") is True
        management_permissions = _network_management_permissions(user_payload)
        can_control = (
            is_super
            or site_role in {"admin", "administrator", "owner", "super_admin"}
            or bool({"admin", "write", "manage", "full"} & management_permissions)
        )
        read_only = not can_control
        return {
            "can_control": can_control,
            "read_only": read_only,
            "site_role": site_role or None,
            "network_management_permissions": sorted(management_permissions),
        }

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return adopted UniFi infrastructure devices only."""
        payload = await self._request_json("GET", f"/proxy/network/api/s/{self.site}/stat/device")
        raw_devices = payload.get("data", payload if isinstance(payload, list) else [])
        if not isinstance(raw_devices, list):
            raise UniFiInfrastructureError("Unexpected UniFi device response")
        return [
            device
            for device in raw_devices
            if isinstance(device, dict) and self._is_infrastructure_device(device)
        ]

    async def async_get_wlans(self) -> list[dict[str, Any]]:
        """Return UniFi WLAN/SSID configuration rows."""
        payload = await self._request_json("GET", f"/proxy/network/api/s/{self.site}/rest/wlanconf")
        raw_wlans = payload.get("data", payload if isinstance(payload, list) else [])
        if not isinstance(raw_wlans, list):
            raise UniFiInfrastructureError("Unexpected UniFi WLAN response")
        return [wlan for wlan in raw_wlans if isinstance(wlan, dict)]

    async def async_get_traffic_routes(self) -> list[dict[str, Any]]:
        """Return UniFi policy-based traffic routes."""
        payload = await self._request_json("GET", f"/proxy/network/v2/api/site/{self.site}/trafficroutes")
        raw_routes = payload if isinstance(payload, list) else payload.get("data", [])
        if not isinstance(raw_routes, list):
            raise UniFiInfrastructureError("Unexpected UniFi traffic-route response")
        return [route for route in raw_routes if isinstance(route, dict)]

    async def async_get_port_forwards(self) -> list[dict[str, Any]]:
        """Return UniFi port-forward rules."""
        payload = await self._request_json("GET", f"/proxy/network/api/s/{self.site}/rest/portforward")
        raw_rules = payload.get("data", payload if isinstance(payload, list) else [])
        if not isinstance(raw_rules, list):
            raise UniFiInfrastructureError("Unexpected UniFi port-forward response")
        return [rule for rule in raw_rules if isinstance(rule, dict)]

    async def async_get_firewall_policies(self) -> list[dict[str, Any]]:
        """Return UniFi firewall policy rows."""
        payload = await self._request_json("GET", f"/proxy/network/v2/api/site/{self.site}/firewall-policies")
        raw_policies = payload if isinstance(payload, list) else payload.get("data", [])
        if not isinstance(raw_policies, list):
            raise UniFiInfrastructureError("Unexpected UniFi firewall-policy response")
        return [policy for policy in raw_policies if isinstance(policy, dict)]

    async def async_set_wlan_enabled(self, wlan_id: str, enabled: bool) -> None:
        """Enable or disable a WLAN/SSID."""
        await self._request_json(
            "PUT",
            f"/proxy/network/api/s/{self.site}/rest/wlanconf/{wlan_id}",
            json_data={"enabled": enabled},
        )

    async def async_set_traffic_route_enabled(self, route: dict[str, Any], enabled: bool) -> None:
        """Enable or disable a policy-based traffic route without altering other fields."""
        route_id = route.get("_id") or route.get("id")
        if route_id in (None, ""):
            raise UniFiInfrastructureError("Cannot update traffic route without an ID")
        payload = dict(route)
        payload["enabled"] = enabled
        await self._request_json(
            "PUT",
            f"/proxy/network/v2/api/site/{self.site}/trafficroutes/{route_id}",
            json_data=payload,
        )

    async def async_set_port_forward_enabled(self, rule: dict[str, Any], enabled: bool) -> None:
        """Enable or disable a port-forward rule without altering other fields."""
        rule_id = rule.get("_id") or rule.get("id")
        if rule_id in (None, ""):
            raise UniFiInfrastructureError("Cannot update port-forward rule without an ID")
        payload = dict(rule)
        payload["enabled"] = enabled
        await self._request_json(
            "PUT",
            f"/proxy/network/api/s/{self.site}/rest/portforward/{rule_id}",
            json_data=payload,
        )

    async def async_set_firewall_policy_enabled(self, policy: dict[str, Any], enabled: bool) -> None:
        """Enable or disable a firewall policy without altering other fields."""
        policy_id = policy.get("_id") or policy.get("id")
        if policy_id in (None, ""):
            raise UniFiInfrastructureError("Cannot update firewall policy without an ID")
        payload = dict(policy)
        payload["enabled"] = enabled
        await self._request_json(
            "PUT",
            f"/proxy/network/v2/api/site/{self.site}/firewall-policies/{policy_id}",
            json_data=payload,
        )

    async def async_update_port_override(
        self,
        device: Any,
        port: Any,
        changes: dict[str, Any],
    ) -> None:
        """Update one port override on a UniFi device."""
        device_id = getattr(device, "key", None)
        if device_id in (None, ""):
            raise UniFiInfrastructureError("Cannot update port without a device ID")
        overrides = list(getattr(device, "raw", {}).get("port_overrides") or [])
        updated = False
        next_overrides: list[dict[str, Any]] = []
        for row in overrides:
            if not isinstance(row, dict):
                continue
            override = dict(row)
            if override.get("port_idx") == getattr(port, "port_idx", None):
                override.update(changes)
                override = {key: value for key, value in override.items() if value is not None}
                updated = True
            next_overrides.append(override)
        if not updated:
            override = self._default_port_override(port)
            override.update(changes)
            next_overrides.append(override)
        await self._request_json(
            "PUT",
            f"/proxy/network/api/s/{self.site}/rest/device/{device_id}",
            json_data={"port_overrides": next_overrides},
        )

    async def async_set_device_locate(self, mac: str, enabled: bool) -> None:
        """Enable or disable the controller locate action for a device."""
        await self._request_json(
            "POST",
            f"/proxy/network/api/s/{self.site}/cmd/devmgr",
            json_data={"cmd": "set-locate" if enabled else "unset-locate", "mac": mac},
        )

    async def async_reboot_device(self, mac: str) -> None:
        """Request a UniFi device reboot."""
        await self._request_json(
            "POST",
            f"/proxy/network/api/s/{self.site}/cmd/devmgr",
            json_data={"cmd": "restart", "mac": mac},
        )

    @staticmethod
    def _default_port_override(port: Any) -> dict[str, Any]:
        """Build a minimal port override from the current port row."""
        raw = getattr(port, "raw", {})
        override = {
            "port_idx": getattr(port, "port_idx", None),
            "name": getattr(port, "name", None),
            "autoneg": raw.get("autoneg", True),
        }
        for key in (
            "setting_preference",
            "forward",
            "native_networkconf_id",
            "tagged_vlan_mgmt",
            "voice_networkconf_id",
            "op_mode",
        ):
            if raw.get(key) not in (None, ""):
                override[key] = raw[key]
        return {key: value for key, value in override.items() if value not in (None, "")}

    async def _request_json(self, method: str, path: str, json_data: dict[str, Any] | None = None) -> Any:
        """Request JSON, refreshing the session once on auth failure."""
        if not self._authenticated:
            await self.async_login()
        response = await self._request(method, path, json_data=json_data)
        if response.status == 401:
            response.release()
            self._authenticated = False
            await self.async_login()
            response = await self._request(method, path, json_data=json_data)
        async with response:
            if response.status in (401, 403):
                raise UniFiInfrastructureAuthError("UniFi authentication failed")
            if response.status >= 400:
                text = await response.text()
                raise UniFiInfrastructureError(f"{path} returned HTTP {response.status}: {text}")
            self._csrf_token = response.headers.get("x-updated-csrf-token", self._csrf_token)
            if response.status == 204:
                return {}
            return await response.json(content_type=None)

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
    ) -> aiohttp.ClientResponse:
        """Open an API request."""
        return await self.session.request(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(),
            json=json_data,
            ssl=self.verify_ssl,
        )

    def _headers(self) -> dict[str, str]:
        """Return request headers."""
        headers = {"Accept": "application/json"}
        if self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token
        return headers

    @staticmethod
    def _is_infrastructure_device(device: dict[str, Any]) -> bool:
        """Return whether the row is adopted UniFi infrastructure."""
        device_type = str(device.get("type") or "").lower()
        if device_type not in UNIFI_HARDWARE_TYPES:
            return False
        if device.get("adopted") is False:
            return False
        return True


def _first_data_row(payload: Any) -> dict[str, Any]:
    """Return the first data row from a UniFi response."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        if isinstance(data, dict):
            return data
        return payload
    return {}


def _network_management_permissions(payload: Any) -> set[str]:
    """Return normalized network management permissions."""
    permissions: set[str] = set()
    if not isinstance(payload, dict):
        return permissions
    raw_permissions = payload.get("permissions")
    if not isinstance(raw_permissions, dict):
        return permissions
    for key, value in raw_permissions.items():
        if str(key).lower() != "network.management":
            continue
        if isinstance(value, list):
            permissions.update(str(item).lower() for item in value if item not in (None, ""))
        elif value not in (None, ""):
            permissions.add(str(value).lower())
    return permissions
