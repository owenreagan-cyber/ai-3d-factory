"""Read-only local inspection of future cloud/paid tool gates (e.g. Meshy).

Reads `config/future_cloud_tools.json` only - never contacts a network,
never reads `.env`, never validates credentials, and never enables
anything. This module exists purely to make the gate's current (always
disabled, always future-gated) state inspectable. See
`docs/meshy-approval-gate.md`.
"""

from __future__ import annotations

from typing import Any

from factory import project_store

FUTURE_CLOUD_TOOLS_PATH = project_store.CONFIG_DIR / "future_cloud_tools.json"


class UnknownFutureCloudToolError(Exception):
    pass


def load_future_cloud_tools() -> dict[str, Any]:
    """Read config/future_cloud_tools.json as-is. Read-only: no network, no .env, no credential checks."""
    return project_store.load_json(FUTURE_CLOUD_TOOLS_PATH)


def list_future_cloud_tools() -> list[dict[str, Any]]:
    """Return every configured future cloud tool's gate status as a flat list of dicts."""
    config = load_future_cloud_tools()
    tools = []
    for tool_id, tool_config in config.get("tools", {}).items():
        entry = {"tool_id": tool_id}
        entry.update(tool_config)
        tools.append(entry)
    return tools


def get_future_cloud_tool(tool_id: str) -> dict[str, Any]:
    """Return one configured future cloud tool's gate status by id."""
    config = load_future_cloud_tools()
    tools = config.get("tools", {})
    if tool_id not in tools:
        known = ", ".join(sorted(tools.keys()))
        raise UnknownFutureCloudToolError(f"Unknown future cloud tool {tool_id!r}. Known tools: {known}")
    entry = {"tool_id": tool_id}
    entry.update(tools[tool_id])
    return entry
