"""Bounded grammar derivation search with measured compiler/delivery feedback."""

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from backend.app.modules.design.generation.maas.book_language.corpus_contract import BASE_OPERATIVES, BOOK_VARIATION_COUNT
from backend.app.modules.design.generation.maas.grammar.vocab import BOOK_BASE_VERBS, AGGREGATION_VERBS

BOOK_EXECUTABLE_VERBS = BOOK_BASE_VERBS | AGGREGATION_VERBS


@dataclass(frozen=True)
class GrammarProposal:
    key: str
    node_id: str
    parent_id: str | None
    verbs: tuple[str, ...]
    variation_index: int
    depth: int
    production: str

    def evidence(self):
        return {**self.__dict__, 'verbs': list(self.verbs)}


@dataclass(frozen=True)
class GrammarFeedback:
    accepted: bool
    value: Any
    reason: str
    score: float
    novelty: float
    program_hash: str = ''
    geometry_hash: str = ''


def _identity(key, verbs, variation):
    return hashlib.sha256(json.dumps([str(key), verbs, variation], separators=(',', ':')).encode()).hexdigest()[:24]


def _vocabulary(seed):
    # Round-robin corpus semantic groups; no completed-form or style menu.
    groups = {}
    for item in BASE_OPERATIVES:
        if item.verb in BOOK_EXECUTABLE_VERBS:
            groups.setdefault((item.transformation, item.cardinality), []).append(item.verb)
    groups['aggregation'] = sorted(BOOK_EXECUTABLE_VERBS - {item.verb for item in BASE_OPERATIVES})
    queues = [sorted(values, key=lambda verb: _identity(seed, (verb,), 0)) for values in groups.values() if values]
    queues.sort(key=lambda values: _identity(seed, tuple(values), 0))
    return tuple(values[index] for index in range(max(map(len, queues))) for values in queues if index < len(values))


class GrammarBeamSearch:
    def __init__(self, *, max_retries=96, max_depth=3, beam_width=3, branching_factor=6):
        if any(type(value) is not int for value in (max_retries, max_depth, beam_width, branching_factor)) or max_retries < 0 or not 1 <= max_depth <= 4 or not 1 <= beam_width <= 8 or not 1 <= branching_factor <= 16:
            raise ValueError('invalid grammar search budget')
        self.max_retries = max_retries
        self.max_depth = max_depth
        self.beam_width = beam_width
        self.branching_factor = branching_factor
        self.retry_count = 0
        self.trials = []
        self.cache = {}
        self.budget_exhausted = False
        self.stop_reasons = Counter()
        self.pair_summaries = []

    def find(self, key, verbs, evaluate):
        key = str(key)
        verbs = tuple(verbs)
        cache_key = (key, verbs)
        if cache_key in self.cache:
            return self.cache[cache_key]
        if not verbs or any(verb not in BOOK_EXECUTABLE_VERBS for verb in verbs):
            raise ValueError('unknown grammar terminal')
        baseline = GrammarProposal(key, _identity(key, verbs, 5), None, verbs, 5, 0, 'scheduled_sentence')
        seen = {(verbs, 5)}
        started_at = len(self.trials)

        def measure(proposal):
            feedback = evaluate(proposal)
            self.trials.append({**proposal.evidence(), 'accepted': feedback.accepted,
                                'reason': feedback.reason, 'score': feedback.score,
                                'novelty': feedback.novelty, 'program_hash': feedback.program_hash,
                                'geometry_hash': feedback.geometry_hash})
            return proposal, feedback

        beam = [measure(baseline)]
        result = beam[0][1].value if beam[0][1].accepted else None
        stop = 'baseline_accepted' if result is not None else 'depth_limit'
        for depth in range(1, self.max_depth + 1):
            if result is not None:
                break
            children = []
            for parent, _feedback in beam:
                moves = []
                terminals = _vocabulary(parent.node_id)[:self.branching_factor]
                retunes = [v for v in range(BOOK_VARIATION_COUNT) if v != baseline.variation_index] if depth == 1 else []
                for index in range(max(len(terminals), len(retunes))):
                    if index < len(retunes):
                        moves.append((parent.verbs, retunes[index], 'retune'))
                    if index < len(terminals):
                        verb = terminals[index]
                        prepend = index % 2 == 1
                        chain = (verb, *parent.verbs) if prepend else (*parent.verbs, verb)
                        variation = int(_identity(parent.node_id, chain, depth), 16) % BOOK_VARIATION_COUNT
                        moves.append((chain, variation, 'prepend' if prepend else 'append'))
                for chain, variation, production in moves:
                    if self.retry_count >= self.max_retries:
                        self.budget_exhausted = True
                        stop = 'retry_budget'
                        break
                    if (chain, variation) in seen:
                        continue
                    seen.add((chain, variation))
                    proposal = GrammarProposal(key, _identity(key, chain, variation), parent.node_id,
                                               chain, variation, depth, production)
                    self.retry_count += 1
                    children.append(measure(proposal))
                if self.budget_exhausted:
                    break
            if not children:
                break
            children.sort(key=lambda pair: (pair[1].accepted, pair[1].score, pair[1].novelty), reverse=True)
            accepted = [pair for pair in children if pair[1].accepted]
            if accepted:
                proposal, feedback = accepted[0]
                result = feedback.value
                stop = 'delivered_derivation'
                break
            beam = children[:self.beam_width]
        self.stop_reasons[stop] += 1
        self.pair_summaries.append({'key': key, 'attempt_count': len(self.trials) - started_at,
                                    'stop_reason': stop, 'accepted': result is not None})
        self.cache[cache_key] = result
        return result

    def evidence(self):
        return {'algorithm': 'delivery_guided_grammar_beam.v1',
                'grammar': 'S -> verb S | S verb | retune(S); terminals from canonical BOOK executable vocabulary',
                'ranking': 'existing gate progress, then measured morphology distance; never substitutes for acceptance',
                'quality_claim': 'measured_deliverability_and_morphology_not_aesthetic_quality',
                'max_depth': self.max_depth, 'beam_width': self.beam_width,
                'branching_factor': self.branching_factor, 'max_retries': self.max_retries,
                'baseline_retune_count': BOOK_VARIATION_COUNT - 1,
                'attempt_count': len(self.trials), 'retry_count': self.retry_count,
                'budget_scope': 'shared derived-node budget; one baseline per unseen source/slot pair',
                'budget_exhausted': self.budget_exhausted,
                'stop_reasons': dict(self.stop_reasons),
                'pairs': list(self.pair_summaries),
                'refusal_counts': dict(Counter(row['reason'] for row in self.trials if not row['accepted'])),
                'trials': list(self.trials)}
