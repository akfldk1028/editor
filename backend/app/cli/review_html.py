from __future__ import annotations

import html


def _quality_table_html(item: dict) -> str:
    quality = item["building_quality"]
    components = quality["component_scores"]
    vertical = quality["vertical"]
    regulatory = item["regulatory_screening"]
    unresolved_facts = ", ".join(regulatory.get("unresolved_facts", ())) or "-"
    rows = (
        ("Quality policy", quality["policy_version"]),
        ("Hard pass", str(quality["hard_pass"]).lower()),
        ("Total score", f"{quality['score']:.4f}"),
        ("Daylight proxy", f"{components['daylight']:.4f}"),
        ("Room form", f"{components['room_form']:.4f}"),
        ("Vertical stacking", f"{components['vertical_stacking']:.4f}"),
        ("Egress", f"{components['egress']:.4f}"),
        ("Coverage/efficiency", f"{components['coverage_efficiency']:.4f}"),
        ("Core stack", f"{vertical['core_stack_ratio']:.4f}"),
        ("Shaft stack", f"{vertical['shaft_stack_ratio']:.4f}"),
        ("Wet-service stack", f"{vertical['wet_service_stack_ratio']:.4f}"),
        ("Regulatory", f"Regulatory: {regulatory['status']}"),
        ("Unresolved regulatory facts", unresolved_facts),
    )
    return (
        '<table class="quality"><tbody>'
        + "".join(
            f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
            for label, value in rows
        )
        + "</tbody></table>"
    )


def _generator_repairs_table_html(item: dict) -> str:
    repairs = item["generator_repairs"]
    if not repairs:
        return ""
    headers = ("operator", "issue", "floor", "rooms", "before", "threshold", "after")
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(repair['operator_id'])}</td>"
        f"<td>{html.escape(repair['issue_code'])}</td>"
        f"<td>{html.escape(str(repair['floor_index']))}</td>"
        f"<td>{html.escape(', '.join(repair['room_ids']))}</td>"
        f"<td>{repr(float(repair['before_value']))}</td>"
        f"<td>{repr(float(repair['threshold']))}</td>"
        f"<td>{repr(float(repair['after_value']))}</td>"
        "</tr>"
        for repair in repairs
    )
    return (
        '<table class="generator-repairs"><thead><tr>'
        + "".join(f"<th>{html.escape(header)}</th>" for header in headers)
        + f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _floor_caption_html(item: dict, floor: dict) -> str:
    quality_floor = next(
        (
            candidate
            for candidate in item["building_quality"]["floors"]
            if candidate["floor_index"] == floor["floor_index"]
        ),
        None,
    )
    if quality_floor is None:
        raise ValueError("floor quality evidence is missing")
    return (
        f"<figcaption>Floor {floor['floor_index']} | "
        f"coverage={floor['coverage_score']:.4f} | "
        f"unallocated={floor['unallocated_ratio']:.4f} | "
        "open work share="
        f"{floor['office_space_ratio']['actual_primary_share']:.4f} | "
        "daylight proxy="
        f"{quality_floor['primary_daylight_ratio']:.4f} | "
        f"room form={quality_floor['room_form_pass_ratio']:.4f}"
        "</figcaption>"
    )
