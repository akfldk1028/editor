"""What the Orchestrator knows when a question arrives — data the ledger prompt reads, never prose written here.

The situation is the site the conversation is about, the goal catalog (`goals.py`: what each goal does, who owns
it, whether the door takes it) and which agents the Orchestrator's catalog reports up. The model answers a
"what can you do / who is on" question from these lines; nothing about capabilities is spelled in the prompt.
"""
from backend.app.modules.platform.goals import capabilities


def _goal_lines() -> list[str]:
    lines = []
    for goal in capabilities()['goals']:
        state = 'available now' if goal['available'] else 'not open to the editor yet'
        owners = ' -> '.join(goal['owners']) or 'orchestrator'
        lines.append(f"- goal {goal['id']} ({goal['label']}): {state}; owners {owners}; needs {', '.join(goal['inputs']) or 'nothing'}")
    return lines


def _agent_lines(agents) -> list[str]:
    if not agents:
        return ['- agent states: unknown (the Orchestrator catalog did not answer)']
    # The Orchestrator catalog's words: available / local (the Orchestrator itself) are on; unavailable is off;
    # not_declared / http_provider_declared are not agents of the network and are left out.
    up = [a.agent_id for a in agents if a.connection_status in ('available', 'local')]
    down = [a.agent_id for a in agents if a.connection_status == 'unavailable']
    return [f"- agents up: {', '.join(up) or 'none'}", f"- agents down: {', '.join(down) or 'none'}"]


def describe(*, pnu: str | None, address: str | None = None, assessment_date: str | None = None, agents=None) -> str:
    """One text block: site, date, goals, agents."""
    site = f"- selected site: {address or ''} PNU {pnu}".strip() if pnu else '- selected site: none yet (the user picks a parcel on the map)'
    date = f'- assessment date: {assessment_date}' if assessment_date else '- assessment date: not given'
    return '\n'.join([site, date, *_goal_lines(), *_agent_lines(agents)])
