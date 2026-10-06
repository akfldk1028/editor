"""The agent network's shared bearer token, as the editor sees it.

A2A_TOKEN is named once for the whole network in agents/a2a_common/protocol.py. Agents
on other servers reach the editor's agent-only doors (`/api/v1/{domain}/agent/{op}`,
the planning operations) with `Authorization: Bearer <token>`; the editor sends the same
header to the agents it calls (planm, the Orchestrator). Unset on a single machine: no
check, no header.
"""
import hmac
import os

ENV = 'A2A_TOKEN'


def network_token(env=os.environ):
    return (env.get(ENV) or '').strip() or None


def network_headers(env=os.environ):
    token = network_token(env)
    return {'Authorization': f'Bearer {token}'} if token else {}


def token_accepted(authorization, env=os.environ):
    """True when no token is configured, or the header carries exactly that token."""
    token = network_token(env)
    if not token:
        return True
    return hmac.compare_digest((authorization or '').encode(), f'Bearer {token}'.encode())
