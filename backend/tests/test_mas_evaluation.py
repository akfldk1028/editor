import pytest
from backend.evaluation.mas.metrics import vendi_score, score_candidates


def test_vendi_duplicate_and_orthogonal_limits():
    assert vendi_score([[1,1],[1,1]]) == pytest.approx(1)
    assert vendi_score([[1,0],[0,1]]) == pytest.approx(2)


@pytest.mark.parametrize('matrix', [[[1,2],[2,1]], [[2,0],[0,1]], [[1,float('nan')],[0,1]], [[1,1],[0,1]]])
def test_invalid_kernel_refused(matrix):
    with pytest.raises(ValueError): vendi_score(matrix)


def test_feasible_diversity_excludes_invalid_candidates_and_deduplicates_geometry():
    candidates=[{'geometry_hash':'a','valid':True},{'geometry_hash':'a','valid':True},
                {'geometry_hash':'b','valid':False}]
    result=score_candidates(candidates, [[1,1,0],[1,1,0],[0,0,1]])
    assert result['valid_fraction']==pytest.approx(2/3)
    assert result['feasible_vendi']==pytest.approx(1)
    assert result['unique_feasible_geometries']==1
    assert result['all_vendi']>result['feasible_vendi']


def test_unknown_validity_and_single_valid_candidate_cannot_claim_diversity():
    result=score_candidates([{'geometry_hash':'a','valid':True},{'geometry_hash':'b','valid':None}],[[1,0],[0,1]])
    assert result['unknown_validity_n']==1 and result['feasible_vendi'] is None
def test_validity_rejects_numeric_truthiness():
    import pytest
    from backend.evaluation.mas.metrics import score_candidates
    with pytest.raises(ValueError):
        score_candidates([{'valid':1}],[[1]])

