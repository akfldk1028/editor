from __future__ import annotations

from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.schemas.mass import MassAnalysis, MassInput


def analyze_mass_route(mass: MassInput) -> MassAnalysis:
    return analyze_mass(mass)
