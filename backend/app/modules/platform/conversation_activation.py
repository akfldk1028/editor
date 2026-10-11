from backend.app.core.tracing import EDITOR_ROOT
from backend.app.modules.platform import host
from backend.app.modules.platform.status.registry import Registry

CAPABILITY = 'design-conversation/v1'


async def activate():
    try:
        entries = Registry(EDITOR_ROOT / 'infra/config/services.json').entries()
        selected = [entry for entry in entries if CAPABILITY in entry.get('capabilities', [])]
        providers = [host.agent_id(entry['id']) for entry in selected]
        required = {host.agent_id(entry['id']) for entry in selected
                    if CAPABILITY in entry.get('required_for_capabilities', [])}
        if not required:
            raise host.HostUnavailable('No required conversation gateway registered')
        result = await host.ensure(providers, timeout_s=30)
        failed = {item['agent'] for item in result['failed']}
        if required & failed or not required.issubset(result['up']):
            raise host.HostUnavailable('Required conversation services are not ready')
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise host.HostUnavailable('Conversation activation unavailable') from exc
