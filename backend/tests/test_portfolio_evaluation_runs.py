import json
import os
from backend.app.modules.design.generation.maas.portfolio_evaluation_catalog import portfolio_evaluation_manifest


def test_empty_latest_keeps_older_evaluations_navigable(tmp_path):
    for run, stamp, records in [('older', 100, [{'candidate_id':'one','program_hash':'a'*64,'geometry_hash':'b'*64,'overall_status':'failed'}]), ('latest-empty', 200, [])]:
        directory = tmp_path / run
        directory.mkdir()
        path = directory / 'maas-portfolio-evaluation.json'
        path.write_text(json.dumps({'schema_version':'arr.maas.portfolio_evaluation_manifest.v1','programs':[
            {'schema_version':'arr.maas.portfolio_evaluation_ledger.v1','run_id':run,'program_slug':'office','records':records}]}))
        os.utime(path, (stamp, stamp))
    latest = portfolio_evaluation_manifest(tmp_path)
    assert latest['run_id'] == 'latest-empty'
    assert latest['candidates'] == [] and latest['status_counts'] == {}
    assert [(r['run_id'],r['candidate_count']) for r in latest['runs']] == [('older',1),('latest-empty',0)]
    older = portfolio_evaluation_manifest(tmp_path, 'older')
    assert older['candidate_count'] == 1
    assert older['status_counts'] == {'failed':1}
    assert older['runs'] == latest['runs']
