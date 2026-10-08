"""Every agent with a say in routing — one module each; the order is the tie-break when scores are equal."""
from backend.app.modules.platform.routing.roles import (cost, design_intent, domain_expert, elevation, interior, kmass, law, mass,
                                                        masterplan, plan, program, requirement, revision, scene, site, systems)

MODULES = (law, site, masterplan, mass, program, elevation, plan, kmass, requirement, design_intent, revision, domain_expert,
           systems, interior, scene, cost)
ROLES = tuple(module.ROLE for module in MODULES)
# What each agent does, in one line (the module docstring, written from its A2A card) — the LLM judge's roster.
DESCRIPTIONS = {module.ROLE.agent: (module.__doc__ or '').strip().splitlines()[0] for module in MODULES}
