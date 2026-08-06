from backend.app.schemas.mass_io import mass_input_from_payload


def test_mass_input_parser_preserves_typed_floor_context() -> None:
    mass = mass_input_from_payload(
        {
            "project_id": "planm-parser",
            "floors": 1,
            "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
            "site_edges": [{"edge_index": 0, "kind": "street"}],
            "access_candidates": [],
            "use_mix": {"office": 1.0},
            "building_code_context": {
                "jurisdiction": "KR",
                "effective_date": "2026-08-05",
                "floor_facts": [{"floor_index": 1, "above_grade": True}],
            },
        }
    )

    assert mass.building_code_context is not None
    assert mass.building_code_context.jurisdiction == "KR"
    assert mass.building_code_context.floor_facts[0].floor_index == 1
    assert mass.building_code_context.floor_facts[0].above_grade is True


def test_mass_input_parser_rejects_non_list_floor_facts() -> None:
    payload = {
        "project_id": "planm-invalid-context",
        "floors": 1,
        "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
        "use_mix": {"office": 1.0},
        "building_code_context": {"floor_facts": {}},
    }

    try:
        mass_input_from_payload(payload)
    except TypeError as error:
        assert str(error) == "building_code_context.floor_facts must be a list"
    else:
        raise AssertionError("invalid floor_facts must be rejected")
