from __future__ import annotations

import os
from pathlib import Path


def planm_agent_dir(product_root: Path) -> Path:
    """Resolve the server-configured owner or its default sibling location."""
    configured = os.environ.get("PLANM_AGENT_DIR")
    if configured is not None:
        owner = Path(configured)
        if not owner.is_absolute():
            raise ValueError("PLANM_AGENT_DIR must be an absolute path")
        return owner.resolve()
    return product_root.resolve().parent / "agents" / "planm"
