"""Every agent with a say in routing — one module each; the order is the tie-break when scores are equal."""
from backend.app.modules.platform.routing.roles import elevation, law, mass, masterplan, program, site

ROLES = (law.ROLE, site.ROLE, masterplan.ROLE, mass.ROLE, program.ROLE, elevation.ROLE)
