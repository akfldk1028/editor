"""Pass-through endpoints for the agents that need the design engine's writers (KMassAgent).

    POST /design/agent/research-bundle   {candidate, run_id, pnu}
        -> creative_research_bundle.write_creative_mass_research_bundle, written under the
           editor's research-bundle root; the reply names run_directory (absolute) and
           mass_directory (relative to it) so a same-host agent can collect the files.

Kept out of views.py on purpose: this is the agent seam, not the frontend API.
"""
import json
import re
from pathlib import Path

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from backend.app.modules.design.generation.paths import backend_root

RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def research_bundle_root():
    return backend_root() / "research-bundles"


def _bad(message):
    return JsonResponse({"success": False, "error": message}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def research_bundle(request):
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError, TypeError):
        return _bad("request body must be a JSON object")
    if not isinstance(body, dict) or not isinstance(body.get("candidate"), dict):
        return _bad("candidate object is required")
    run_id, pnu = str(body.get("run_id") or ""), str(body.get("pnu") or "")
    if not RUN_ID.match(run_id) or not pnu:
        return _bad("run_id (slug) and pnu are required")
    from backend.app.modules.design.generation.maas.creative_research_bundle import write_creative_mass_research_bundle

    run_directory = (research_bundle_root() / run_id).resolve()
    run_directory.mkdir(parents=True, exist_ok=True)
    try:
        bundle = write_creative_mass_research_bundle(body["candidate"], run_directory=run_directory, run_id=run_id, pnu=pnu)
    except (ValueError, TypeError, KeyError) as exc:
        return _bad(f"{type(exc).__name__}: {exc}")
    except OSError as exc:
        return JsonResponse({"success": False, "error": f"{type(exc).__name__}: {exc}"}, status=502)
    return JsonResponse({"success": True, "run_directory": str(run_directory),
                         "mass_directory": str(bundle["mass_directory"])})
