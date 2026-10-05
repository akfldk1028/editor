"""Graph-derived constructive assembly accounting shared by author and BOOK gates."""

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram


def assembly_budget_nodes(program: GeometryProgram, *, eligible_node_ids: set[str] | None = None) -> tuple[set[str], set[str]]:
    """Separate constructive assembly from its affine implementation nodes.

    Only graph structure grants an exception. Non-affine effects, destructive
    booleans and placements consumed outside the assembly retain their budget.
    Geometry compilation/contact gates remain authoritative about physical joins.
    """
    nodes = {node.id: node for node in program.topological_nodes()}
    consumers: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for node in nodes.values():
        for operand in node.inputs:
            consumers.setdefault(operand, set()).add(node.id)
    eligible = set(nodes) if eligible_node_ids is None else eligible_node_ids
    joins = {
        node.id for node in nodes.values()
        if node.id in eligible and node.operator in {"union", "attach", "attach_volume", "bridge"}
        and len(node.inputs) >= 2 and len(set(node.inputs)) == len(node.inputs)
    }
    placements = {
        node.id for node in nodes.values()
        if node.id in eligible and node.operator in {"scale", "rotate", "translate", "matrix4"}
        and len(node.inputs) == 1
    }
    roots: set[str] = set()
    implementation: set[str] = set()
    # Work from final joins toward their operands so nested joins belong to
    # their enclosing assembly, rather than consuming one principle per join.
    for root in reversed(tuple(nodes)):
        if root not in joins or root in implementation:
            continue
        members = {root}
        pending = list(nodes[root].inputs)
        while pending:
            node_id = pending.pop()
            if node_id in members or node_id not in joins | placements:
                continue
            members.add(node_id)
            pending.extend(nodes[node_id].inputs)
        # A reused operand may also feed a cutter or modifier. Do not hide
        # that use behind an unrelated constructive branch; prune upstream.
        changed = True
        while changed:
            rejected = {
                node_id for node_id in members - {root}
                if not consumers[node_id].issubset(members)
            }
            changed = bool(rejected)
            members.difference_update(rejected)
        roots.add(root)
        implementation.update(members - {root})
    return roots - implementation, implementation
