"""Turn an approved PLANM alternative into a Pascal editor scene."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from backend.app.modules.pascal_bridge.converter import ConversionResult, convert_floors


class PascalPublisher(Protocol):
    """The slice of the MCP client this service needs."""

    editor_url: str

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class PascalBridgeError(RuntimeError):
    """The requested run or alternative cannot be turned into a scene."""


def load_alternative_geometry(run_dir: Path, alternative_id: str) -> list[dict[str, Any]]:
    """Read every floor-geometry artifact for one alternative, lowest floor first."""
    root = run_dir / "artifacts" / "alternatives" / alternative_id
    if not root.is_dir():
        raise PascalBridgeError(f"alternative {alternative_id!r} has no artifacts")

    geometries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.geometry.json")):
        geometries.append(json.loads(path.read_text(encoding="utf-8")))
    if not geometries:
        raise PascalBridgeError(
            f"alternative {alternative_id!r} has no floor geometry; it predates the "
            "planm-floor-geometry/v1 artifact, so re-run it to publish to Pascal"
        )
    return sorted(geometries, key=lambda g: int(g.get("floor_index", 0)))


def build_plan(
    run_dir: Path,
    alternative_id: str,
    *,
    furnish: bool = True,
    level_height: float | None = None,
    plan_name: str | None = None,
) -> ConversionResult:
    geometries = load_alternative_geometry(run_dir, alternative_id)
    return convert_floors(
        geometries,
        furnish=furnish,
        level_height=level_height,
        plan_name=plan_name,
    )


def publish_to_pascal(
    client: PascalPublisher,
    plan: dict[str, Any],
    *,
    scene_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Bind a scene, apply the plan, and report where to look at it.

    Binding first is what makes the build persist and reach an open editor tab;
    without it `apply_floor_plan` only touches the in-memory session.
    """
    if dry_run:
        applied = client.call_tool("apply_floor_plan", {"plan": plan, "dryRun": True})
        return {
            "dry_run": True,
            "scene_id": None,
            "editor_url": None,
            "totals": applied.get("totals", {}),
            "pascal_warnings": applied.get("warnings", []),
        }

    _reset_scene(client)

    scene = client.call_tool("save_scene", {"name": scene_name})
    scene_id = scene.get("id") or scene.get("sceneId")

    # A first level with no id of its own builds on the scene's ground level
    # rather than stacking an empty one beneath it. Copy rather than edit in
    # place so the caller's plan is not quietly rewritten.
    applied_plan = plan
    levels = plan.get("levels")
    if isinstance(levels, list) and levels and not levels[0].get("levelId"):
        level_id = _first_level_id(client.call_tool("get_scene", {}))
        if level_id:
            applied_plan = {
                **plan,
                "levels": [{**levels[0], "levelId": level_id}, *levels[1:]],
            }

    applied = client.call_tool("apply_floor_plan", {"plan": applied_plan})
    return {
        "dry_run": False,
        "scene_id": scene_id,
        "editor_url": f"{client.editor_url}/scene/{scene_id}" if scene_id else None,
        "plan": applied_plan,
        "totals": applied.get("totals", {}),
        "pascal_warnings": applied.get("warnings", []),
    }


#: Node types the template ships a sample room in. Everything of these types is
#: cleared before a plan is applied; the site, building and level survive.
_TEMPLATE_CONTENT_TYPES = {
    "wall",
    "door",
    "window",
    "zone",
    "slab",
    "ceiling",
    "item",
    "panel",
    "stair",
    "roof",
}


def _reset_scene(client: PascalPublisher) -> None:
    """Give the plan a clean scene to build into.

    The MCP session holds one in-memory scene, so without a reset each publish
    stacks on whatever the previous one left behind — a second run turned 200
    walls into 400. `empty-studio` is the smallest known starting point, but it
    is not actually empty: it ships a one-room studio, so its contents are
    cleared too, leaving the site, building and ground level to build on.
    """
    client.call_tool("create_from_template", {"id": "empty-studio"})

    scene = client.call_tool("get_scene", {})
    nodes = scene.get("nodes")
    if not isinstance(nodes, dict):
        return
    doomed = [
        node_id
        for node_id, node in nodes.items()
        if isinstance(node, dict) and node.get("type") in _TEMPLATE_CONTENT_TYPES
    ]
    if doomed:
        client.call_tool(
            "apply_patch",
            {"patches": [{"op": "delete", "id": node_id} for node_id in doomed]},
        )


def _first_level_id(scene: dict[str, Any]) -> str | None:
    for key in ("nodes", "graph"):
        container = scene.get(key)
        if isinstance(container, dict):
            for node_id, node in container.items():
                if isinstance(node, dict) and node.get("type") == "level":
                    return str(node.get("id", node_id))
    # Fall back to scanning the serialised form for a level id.
    text = json.dumps(scene)
    marker = '"level_'
    index = text.find(marker)
    if index == -1:
        return None
    start = index + 1
    end = text.find('"', start)
    return text[start:end] if end != -1 else None


__all__ = [
    "PascalBridgeError",
    "PascalPublisher",
    "build_plan",
    "load_alternative_geometry",
    "publish_to_pascal",
]
