"""Mass workspace data belongs to the caller; executable tools belong to Editor."""
import os
from pathlib import Path


def workspace_root():
    value = os.environ.get('MASSV2_WS')
    if not value:
        raise RuntimeError('MASSV2_WS must name an explicit Mass workspace')
    return Path(value).expanduser().resolve()


def tools_root():
    return Path(__file__).resolve().parent / 'workspace_tools'
