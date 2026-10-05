"""One module talks to the Plan Agent. Everything else in the backend is transport-blind."""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).parents[1] / "app"
OWNER = BACKEND / "adapters" / "planm_agent.py"
FORBIDDEN = ("PLANM_AGENT_URL", "8308", "/planm/stage", "/planm/generate", "agent-card.json", "SendMessage")


def test_only_the_plan_agent_adapter_knows_the_agent():
    offenders = []
    for file in sorted(BACKEND.rglob("*.py")):
        if file == OWNER or "__pycache__" in file.parts:
            continue
        text = file.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            if needle in text:
                offenders.append(f"{file.relative_to(BACKEND)}: {needle}")
    assert offenders == []


def test_the_run_service_imports_no_transport():
    source = (BACKEND / "modules" / "planm_runs" / "service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert "httpx" not in modules and "requests" not in modules
    adapters = {m for m in modules if m.startswith("backend.app.adapters")}
    assert adapters == {"backend.app.adapters.planm_agent", "backend.app.adapters.dwg_client"}
