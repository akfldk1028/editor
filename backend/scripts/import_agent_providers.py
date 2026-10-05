"""Import the exact law/site provider owners without an old-application dependency."""
import argparse
import hashlib
import json
from pathlib import Path

from backend.scripts.import_design_runtime import destination, rewrite, SPECIAL


MODULES = (
    'law/design_review.py', 'law/program_review.py', 'law/facility_area_engine.py',
    'law/facility_area_rules.py', 'law/building_use_catalog.py', 'law/fire_requirements.py',
    'law/use_research_routes.py', 'law/ordinance_discovery.py', 'law/program_parking.py',
    'law/program_parking_scenario.py', 'land/services/zoning_use_evidence.py',
    'law/views_agent.py', 'land/views_agent.py', 'law/scripts/fetch_ordinance_caps.py',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    root = args.source.resolve()
    editor = Path(__file__).resolve().parents[2]
    SPECIAL.update({'law.views_agent': 'backend.app.api.agent_providers.law',
                    'land.views_agent': 'backend.app.api.agent_providers.land'})
    files = [root / name for name in MODULES]
    files += sorted((root / 'law/data/facility_sources').glob('*.json'))
    files += [root / 'law/data/use_research_sources.json']
    records = []
    prepared = []
    for source in files:
        relative = source.relative_to(root)
        target = destination(relative)
        original = source.read_bytes()
        if source.suffix == '.py':
            text, changes = rewrite(original.decode('utf-8-sig').replace('\r\n', '\n'), relative, root)
            output = text.encode('utf-8')
        else:
            output, changes = original, []
        if target.exists() and target.read_bytes() != output:
            raise RuntimeError(f'Refusing to overwrite changed destination: {target}')
        prepared.append((target, output))
        records.append({'source': relative.as_posix(), 'destination': target.relative_to(editor).as_posix(),
                        'source_sha256': hashlib.sha256(original).hexdigest(),
                        'imported_sha256': hashlib.sha256(output).hexdigest(), 'changes': changes})
    for target, output in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(output)
    manifest = editor / 'backend/app/modules/law/reference/provider-source-manifest.json'
    manifest.write_text(json.dumps({'schema': 'editor.agent-domain-provider-import.v1', 'files': records},
                                   ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Imported {len(records)} provider modules and source snapshots')


if __name__ == '__main__':
    main()
