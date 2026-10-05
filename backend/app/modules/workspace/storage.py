import os
from pathlib import Path


def resolve_directory():
    """The workspace storage directory, or None when nothing configures one."""
    root = os.environ.get('EDITOR_WORKSPACE_DATA_DIR')
    if root:
        return Path(root)
    platform = os.environ.get('EDITOR_PLATFORM_DATA_DIR')
    return Path(platform) / 'workspace' if platform else None
