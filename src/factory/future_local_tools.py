"""Read-only local inspection of future local (non-cloud) tool gates (e.g. Blender).

Reads `config/future_local_tools.json` only - never launches a tool,
never searches the filesystem for an installed application (not even a
read-only `/Applications` scan), never calls `subprocess`, never
installs anything, and never enables anything. This module exists purely
to make the gate's current (always disabled, always future-gated) state
inspectable. See `docs/blender-local-track.md`.
"""

from __future__ import annotations

from typing import Any

from factory import project_store

FUTURE_LOCAL_TOOLS_PATH = project_store.CONFIG_DIR / "future_local_tools.json"


class UnknownFutureLocalToolError(Exception):
    pass


def load_future_local_tools() -> dict[str, Any]:
    """Read config/future_local_tools.json as-is. Read-only: no filesystem discovery, no subprocess."""
    return project_store.load_json(FUTURE_LOCAL_TOOLS_PATH)


def list_future_local_tools() -> list[dict[str, Any]]:
    """Return every configured future local tool's gate status as a flat list of dicts."""
    config = load_future_local_tools()
    tools = []
    for tool_id, tool_config in config.get("tools", {}).items():
        entry = {"tool_id": tool_id}
        entry.update(tool_config)
        tools.append(entry)
    return tools


def get_future_local_tool(tool_id: str) -> dict[str, Any]:
    """Return one configured future local tool's gate status by id."""
    config = load_future_local_tools()
    tools = config.get("tools", {})
    if tool_id not in tools:
        known = ", ".join(sorted(tools.keys()))
        raise UnknownFutureLocalToolError(f"Unknown future local tool {tool_id!r}. Known tools: {known}")
    entry = {"tool_id": tool_id}
    entry.update(tools[tool_id])
    return entry
