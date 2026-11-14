"""Help: the panel's websocket calls go through (status, hide, share, send)."""

from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.update_guard.support import Support


async def test_websocket(hass: HomeAssistant, hass_ws_client) -> None:
    s = Support(hass, "update_guard", "update-guard", "Update Guard", summary=None)
    await s.async_setup()
    client = await hass_ws_client(hass)

    async def post(path, data, timeout=30):
        if path == "/":
            assert data["diagnostics"]["version"] and data["install"]
            return {"ok": True, "id": "20261114-abc123"}
        return {"reports": [], "notes": []}

    with patch.object(s, "_post", post):
        await client.send_json_auto_id({"type": "update_guard/support", "action": "status"})
        r = await client.receive_json()
        assert r["success"] and r["result"]["share"] is True
        await client.send_json_auto_id({"type": "update_guard/support", "action": "send", "note": "hi", "images": []})
        r = await client.receive_json()
        assert r["success"] and r["result"]["ok"] and r["result"]["last_help"]["id"] == "20261114-abc123"
        await client.send_json_auto_id({"type": "update_guard/support", "action": "reply", "report": "20261114-abc123", "text": "x"})
        r = await client.receive_json()
        assert r["success"]
        await client.send_json_auto_id({"type": "update_guard/support", "action": "share", "on": False})
        r = await client.receive_json()
        assert r["success"] and r["result"]["share"] is False
    s.unload()
