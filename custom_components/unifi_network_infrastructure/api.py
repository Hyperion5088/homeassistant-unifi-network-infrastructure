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
        return {"device_count": len(devices)}

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

    async def async_get_networks(self) -> list[dict[str, Any]]:
        """Return UniFi network configuration rows."""
        payload = await self._request_json("GET", f"/proxy/network/api/s/{self.site}/rest/networkconf")
        raw_networks = payload.get("data", payload if isinstance(payload, list) else [])
        if not isinstance(raw_networks, list):
            raise UniFiInfrastructureError("Unexpected UniFi network response")
        return [network for network in raw_networks if isinstance(network, dict)]

    async def async_get_port_forwards(self) -> list[dict[str, Any]]:
        """Return UniFi port-forward rules."""
        payload = await self._request_json("GET", f"/proxy/network/api/s/{self.site}/rest/portforward")
        raw_rules = payload.get("data", payload if isinstance(payload, list) else [])
        if not isinstance(raw_rules, list):
            raise UniFiInfrastructureError("Unexpected UniFi port-forward response")
        return [rule for rule in raw_rules if isinstance(rule, dict)]

    async def async_set_wlan_enabled(self, wlan_id: str, enabled: bool) -> None:
        """Enable or disable a WLAN/SSID."""
        await self._request_json(
            "PUT",
            f"/proxy/network/api/s/{self.site}/rest/wlanconf/{wlan_id}",
            json_data={"enabled": enabled},
        )

    async def async_set_network_enabled(self, network: dict[str, Any], enabled: bool) -> None:
        """Enable or disable a network without altering other fields."""
        network_id = network.get("_id") or network.get("id")
        if network_id in (None, ""):
            raise UniFiInfrastructureError("Cannot update network without an ID")
        payload = dict(network)
        payload["enabled"] = enabled
        await self._request_json(
            "PUT",
            f"/proxy/network/api/s/{self.site}/rest/networkconf/{network_id}",
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
