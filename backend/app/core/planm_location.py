from __future__ import annotations

from pathlib import Path


def planm_agent_dir(product_root: Path) -> Path:
    """PLANM lives beside the editor checkout, in the shared agents folder."""
    return product_root.resolve().parent / "agents" / "planm"
