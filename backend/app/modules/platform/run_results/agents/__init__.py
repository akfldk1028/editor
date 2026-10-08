"""One parser per agent whose answer the contract reads; `PARSERS` names them by tool. A new agent's step
= one module here + one row in the contract (parse.py)."""
from backend.app.modules.platform.run_results.agents import law, review, site

PARSERS = {site.TOOL: site, law.TOOL: law, review.TOOL: review}
