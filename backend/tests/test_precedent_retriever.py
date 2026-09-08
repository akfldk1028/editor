from backend.app.modules.precedent_retriever.service import rank_precedents
from backend.app.schemas.precedent import PrecedentCase


def test_rank_precedents_prefers_same_use_and_similar_area():
    cases = [
        PrecedentCase(
            case_id="office-close",
            use_type="office",
            gross_area=410,
            floors=8,
            tags=["central_core"],
            metrics={"efficiency": 0.82},
        ),
        PrecedentCase(
            case_id="commercial-far",
            use_type="neighborhood_commercial",
            gross_area=900,
            floors=2,
            tags=["street_front"],
            metrics={"efficiency": 0.75},
        ),
    ]

    ranked = rank_precedents(
        cases,
        use_type="office",
        target_area=400,
        floors=8,
        tags=["central_core"],
    )

    assert [item.case.case_id for item in ranked] == ["office-close", "commercial-far"]
    assert ranked[0].score > ranked[1].score
