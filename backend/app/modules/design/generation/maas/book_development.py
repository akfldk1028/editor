"""Exact BOOK development: explicit parent inheritance, no exploration recipe."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from math import isfinite, isclose

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.dimensional_intent import KEY as DIMENSIONAL_INTENT_KEY, program_intent

MODE = 'exact-authored-development'
MARKER = 'book_exact_development'


def contract_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def validate_parent_contract(context):
    if not isinstance(context, dict):
        raise ValueError('exact development requires a verified parent contract')
    for key in ('parent', 'parent_shape_id', 'parent_program_hash', 'parent_certificate_id', 'site_pnu'):
        if not isinstance(context.get(key), str) or not context[key]:
            raise ValueError(f'parent contract missing {key}')
    count = context.get('storey_count')
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError('parent contract storey_count must be a positive integer')
    for key in ('storey_height_m', 'target_gfa_m2', 'height_m'):
        value = context.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value) or value <= 0:
            raise ValueError(f'parent contract invalid {key}')
    if not isclose(context['height_m'], count * context['storey_height_m'], rel_tol=1e-8, abs_tol=1e-6):
        raise ValueError('parent height is inconsistent with its floor schedule')
    return context


def validate_development_payload(payload, context, *, expected_count):
    validate_parent_contract(context)
    if payload.get('mode') != MODE or payload.get('inherit_parent_dimensions') is not True:
        raise ValueError(f'development requires mode={MODE} and inherit_parent_dimensions=true')
    for key in ('parent', 'parent_shape_id', 'parent_program_hash'):
        if payload.get(key) != context[key]:
            raise ValueError(f'development {key} mismatch')
    programs = payload.get('geometry_programs')
    if not isinstance(programs, list) or len(programs) != expected_count:
        raise ValueError(f'development requires exactly {expected_count} geometry_programs')
    parsed = []
    names, hashes = set(), set()
    for index, raw in enumerate(programs):
        # The developer writes the author's schema: typed nodes whose
        # `parameters` is an array of {name, value_type, *_value}. That is
        # what the author decoder reads; `from_dict` reads the kernel's
        # dict form and answered "parameters/provenance must be objects"
        # to a payload that followed the schema it was handed.
        nodes = raw.get('nodes') if isinstance(raw, dict) else None
        typed = isinstance(nodes, list) and any(
            isinstance(node, dict) and isinstance(node.get('parameters'), list)
            for node in nodes)
        if typed:
            from backend.app.modules.design.generation.maas.geometry_language.llm_adapter import _canonicalize_program_relation_suffix, _program_from_structured_author_item
            program = _canonicalize_program_relation_suffix(
                _program_from_structured_author_item(raw, index=index))
        else:
            program = GeometryProgram.from_dict(raw)
        if not program.name or program.name in names or program.program_hash() in hashes:
            raise ValueError('development child names and programs must be unique')
        for key, binding in (('parent_name', 'parent'), ('parent_shape_id', 'parent_shape_id')):
            if key in program.metadata and program.metadata[key] != context[binding]:
                raise ValueError(f'development child {key} mismatch')
        if MARKER in program.metadata:
            raise ValueError('development payload cannot supply a certified delivery marker')
        names.add(program.name)
        hashes.add(program.program_hash())
        parsed.append(program)
    return tuple(parsed)


def exact_dimensions(program_payload):
    """Validate the explicit generated evidence before disabling BOOK re-sizing.

    This is provenance integrity, not a legal exemption; final importer gates
    remain mandatory. Arbitrary truthy metadata is insufficient.
    """
    marker = (program_payload.get('metadata') or {}).get(MARKER)
    if marker is None:
        return None
    if not isinstance(marker, dict) or marker.get('mode') != MODE:
        raise ValueError('invalid exact development marker')
    context = validate_parent_contract(marker.get('parent_contract'))
    if marker.get('parent_contract_hash') != contract_hash(context):
        raise ValueError('exact development parent contract hash mismatch')
    raw = marker.get('authored_program')
    if not isinstance(raw, dict) or GeometryProgram.from_dict(raw).program_hash() != marker.get('authored_program_hash'):
        raise ValueError('exact development authored program hash mismatch')
    return context


def build_exact_development_portfolio(payload, context, *, expected_count):
    from backend.app.modules.design.generation.maas.creative_program_author import normalize_authored_programs, authored_program_result
    from backend.app.modules.design.generation.maas.creative_floor_portfolio import _compile_candidate, _creative_portfolio_payload
    from backend.app.modules.design.generation.maas.creative_morphology import morphology_distance
    programs = validate_development_payload(payload, context, expected_count=expected_count)
    candidates = []
    for index, raw_program in enumerate(programs):
        marker = {'mode': MODE, 'parent_contract': deepcopy(context),
                  'parent_contract_hash': contract_hash(context),
                  'authored_program': raw_program.to_dict(),
                  'authored_program_hash': raw_program.program_hash()}
        authored = normalize_authored_programs((raw_program,))[0]
        proposal = program_intent(authored.program)
        if proposal is not None:
            if (proposal['storey_count'] != context['storey_count']
                    or not isclose(proposal['storey_height_m'], context['storey_height_m'], rel_tol=1e-8, abs_tol=1e-6)
                    or not isclose(proposal['target_gfa_m2'], context['target_gfa_m2'], rel_tol=1e-5, abs_tol=1e-3)):
                raise ValueError('development dimensional intent conflicts with verified parent delivery')
            # The complete original proposal remains in the hashed authored
            # source above. Effective dimensions now belong to the verified
            # parent contract, not the earlier soft proposal.
            metadata = dict(authored.program.metadata)
            metadata.pop(DIMENSIONAL_INTENT_KEY, None)
            metadata['dimensional_intent_transition'] = {
                'historical_proposal': proposal,
                'effective_authority': 'verified_parent_delivery',
                'parent_contract_hash': contract_hash(context)}
            authored = replace(authored, program=replace(authored.program, metadata=metadata))
        authored = replace(authored, program=replace(authored.program, metadata={
            **authored.program.metadata, MARKER: marker}))
        result = authored_program_result(authored)
        candidate = _compile_candidate(result, family='exact-authored-development',
            source_family='llm_authored', family_index=0, variation_index=0,
            candidate_index=index, capacity_band='inherited_parent',
            capacity_ceiling_m2=context['target_gfa_m2'],
            author_evidence=dict(authored.author_evidence), physical_contract=context)
        if candidate is None:
            # Name the child and the reason: the cycle feeds this line back
            # to the developer, and "failed physical compilation" alone told
            # it nothing about which of a dozen silent refusals it was.
            from backend.app.modules.design.generation.maas.creative_floor_portfolio import _connected_compilation
            from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
            try:
                compilation = compile_geometry_program(authored.program)
                reason = ('not one connected solid'
                          f' (components={int(compilation.metrics.get("component_count", 0) or 0)})'
                          if not _connected_compilation(compilation)
                          else 'physical sizing under the inherited parent contract refused')
            except (RuntimeError, TypeError, ValueError) as exc:
                reason = f'compiler: {exc}'
            raise ValueError(f'exact development child {index + 1} ({raw_program.name}) '
                             f'failed physical compilation: {reason}')
        candidate['development_lineage'] = deepcopy(marker)
        candidate['storey_evidence']['capacity_authority'] = 'verified_parent_delivery_target; final imported area is measured separately'
        candidate['lineage']['stages'] = [s for s in candidate['lineage']['stages'] if s != 'typed_book_relation']
        candidate['lineage']['stages'].append('exact_authored_development')
        candidate['morphology_evidence']['decision'] = {'accepted': True,
            'nearest_distance': min((float(morphology_distance(
                candidate['morphology_evidence']['descriptor'], prior['morphology_evidence']['descriptor']))
                for prior in candidates), default=0.0),
            'reason': 'local_development; final delivered shape distinctness checked before pairs'}
        candidates.append(candidate)
    result = _creative_portfolio_payload(candidates, capacity_ceiling_m2=context['target_gfa_m2'], author_mode=MODE)
    result['morphology_evidence'] = {
        'decision': 'not_a_development_gate',
        'distinctness_authority': 'final delivered shape identity before pair rendering'}
    result['development_contract'] = deepcopy(context)
    return result
