def _select_compact_grid_candidates(
    candidates: list[dict[str, Any]],
    *,
    required_spaces: int,
    accessible_spaces: int,
    access_edges: list[LineString] | None = None,
) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=_grid_candidate_sort_key)
    if required_spaces <= 0 or not ordered:
        return []
    contiguous_row = _select_contiguous_row_candidates(
        ordered,
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        access_edges=access_edges,
    )
    if len(contiguous_row) >= required_spaces:
        return contiguous_row[:required_spaces]

    exact_small_group = _select_exact_small_grid_group(
        ordered,
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        access_edges=access_edges,
    )
    if len(exact_small_group) >= required_spaces:
        return exact_small_group[:required_spaces]

    # Preserve feasible partial searches too: an unmet request is exactly when
    # throwing away a better partial count conceals available capacity.
    def score_group(group: list[dict[str, Any]]) -> tuple[Any, ...]:
        return _grid_group_score(
            group, required_spaces=required_spaces,
            accessible_spaces=accessible_spaces, access_edges=access_edges,
        )
    best = max((contiguous_row, exact_small_group), key=score_group)
    best_score = score_group(best)
    for seed in ordered:
        if accessible_spaces > 0 and seed["type"] != "accessible":
            continue
        group: list[dict[str, Any]] = []
        occupied: list[Polygon] = []
        remaining_accessible = max(0, min(accessible_spaces, required_spaces))

        def add(candidate: dict[str, Any]) -> bool:
            nonlocal remaining_accessible
            if candidate in group:
                return False
            if remaining_accessible > 0 and candidate["type"] != "accessible":
                return False
            if any(_stall_polygons_overlap(candidate["stall_polygon"], existing) for existing in occupied):
                return False
            group.append(candidate)
            occupied.append(candidate["stall_polygon"])
            if candidate["type"] == "accessible":
                remaining_accessible -= 1
            return True

        add(seed)
        while len(group) < required_spaces:
            eligible = [
                candidate for candidate in ordered
                if candidate not in group
                and not any(_stall_polygons_overlap(candidate["stall_polygon"], existing) for existing in occupied)
                and (remaining_accessible <= 0 or candidate["type"] == "accessible")
            ]
            if not eligible:
                break
            eligible.sort(key=lambda candidate: (
                0 if remaining_accessible > 0 or candidate["type"] == "standard" else 1,
                _grid_candidate_compact_sort_key(candidate, group),
            ))
            if not add(eligible[0]):
                break

        score = _grid_group_score(
            group,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            access_edges=access_edges,
        )
        if best_score is None or score > best_score:
            best = group
            best_score = score

    if len(best) >= required_spaces:
        return best[:required_spaces]

    selected: list[dict[str, Any]] = []
    occupied: list[Polygon] = []
    remaining_accessible = max(0, min(accessible_spaces, required_spaces))
    for candidate in ordered:
        if len(selected) >= required_spaces:
            break
        if remaining_accessible > 0 and candidate["type"] != "accessible":
            continue
        if any(_stall_polygons_overlap(candidate["stall_polygon"], existing) for existing in occupied):
            continue
        selected.append(candidate)
        occupied.append(candidate["stall_polygon"])
        if candidate["type"] == "accessible":
            remaining_accessible -= 1
    if len(selected) < required_spaces:
        for candidate in ordered:
            if len(selected) >= required_spaces:
                break
            if candidate in selected:
                continue
            if any(_stall_polygons_overlap(candidate["stall_polygon"], existing) for existing in occupied):
                continue
            selected.append(candidate)
            occupied.append(candidate["stall_polygon"])
    return max((best, selected), key=score_group)[:required_spaces]