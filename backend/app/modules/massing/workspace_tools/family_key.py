"""Workspace alias - the composition family moved into the package.

The key started life here beside the board curator; the day the audit showed
the cell selector seating one family six times, the selector needed it too,
and a quota's owner belongs in the code it polices. Everything imports from
`design.maas.massv2.family` now; this file keeps old tool invocations alive.
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import sys
from pathlib import Path

from backend.app.modules.design.generation.maas.massv2.family import FAMILY_OF_VERB, OPENERS, QUIET, family_key, family_tag, one_per_family
