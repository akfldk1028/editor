import pytest

from backend.app.modules.design.generation.maas import creative_floor_portfolio as module
from backend.app.modules.design.generation.maas.creative_floor_portfolio import build_creative_floor_portfolio
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram


def test_incomplete_portfolio_reports_rejected_input_stage_and_reason():
    unit = GeometryNode('unit', 'primitive', 'box', parameters={
        'width': 1.0, 'depth': 1.0, 'height': 1.0,
    })
    moved = GeometryNode('moved', 'transform', 'translate', inputs=('unit',),
                         parameters={'vector': [3.0, 0.0, 0.0]})
    union = GeometryNode('union', 'boolean', 'union', inputs=('unit', 'moved'))
    disconnected = GeometryProgram((unit, moved, union), 'union',
                                   metadata={'private_note': 'do-not-print-authored-payload'})

    with pytest.raises(RuntimeError) as failure:
        build_creative_floor_portfolio(count=2, authored_programs=({}, disconnected))

    message = str(failure.value)
    assert '0/2 explorations' in message
    assert 'input_index=0 stage=normalized_program reason=normalization_error' in message
    assert 'input_index=1 stage=structural_pass reason=disconnected' in message
    assert 'do-not-print-authored-payload' not in message


def test_incomplete_portfolio_bounds_rejection_details_and_reports_omissions():
    with pytest.raises(RuntimeError) as failure:
        build_creative_floor_portfolio(count=20, authored_programs=({},) * 20)

    message = str(failure.value)
    assert 'input_index=0 stage=normalized_program reason=normalization_error' in message
    assert '8 more rejections omitted' in message
    assert len(message) < 1500


def test_incomplete_portfolio_identifies_failed_book_assignment(monkeypatch):
    report = module.CreativeFloorPortfolioReport(
        status='partial', target_count=1, candidates=(), stage_counts={},
        rejection_counts={'book_disconnected': 1}, language_coverage={},
        rejections=(module.CreativePortfolioRejection(
            input_index=5, stage='book_structural_pass', reason_code='book_disconnected',
            principle_id='aggregation:join+array:pinch', scope_label='1/16',
        ),),
    )
    monkeypatch.setattr(module, 'build_creative_floor_portfolio_report', lambda **kwargs: report)

    with pytest.raises(RuntimeError) as failure:
        build_creative_floor_portfolio(count=1, authored_programs=())

    message = str(failure.value)
    assert 'input_index=5 stage=book_structural_pass reason=book_disconnected' in message
    assert 'principle=aggregation:join+array:pinch scope=1/16' in message
