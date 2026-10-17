"""Independent UCB1 grammar search, informed by Finch's recovered MCTS cycle.

Finch's floorplate actions are not copied: actions here are executable BOOK
derivations and rewards come from the existing Mass compiler/delivery callback.
"""

from collections import Counter
from dataclasses import dataclass, field
from math import isfinite, log, sqrt
import random

from backend.app.modules.design.generation.maas.book_language.grammar_search import (
    BOOK_EXECUTABLE_VERBS, BOOK_VARIATION_COUNT, GrammarFeedback, GrammarProposal,
    _identity, _vocabulary,
)


@dataclass
class _Node:
    proposal: GrammarProposal
    parent: object = None
    children: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    visits: int = 0
    reward_sum: float = 0.0
    exhausted: bool = False


class GrammarMCTSSearch:
    algorithm = 'delivery_guided_grammar_mcts.v1'

    def __init__(self, *, max_retries=96, pair_budget=32, max_depth=3, seed=0):
        if (any(type(x) is not int for x in (max_retries, pair_budget, max_depth, seed))
                or max_retries < 0 or pair_budget < 1 or not 1 <= max_depth <= 4):
            raise ValueError('invalid grammar MCTS budget')
        self.max_retries, self.pair_budget, self.max_depth, self.seed = max_retries, pair_budget, max_depth, seed
        self.retry_count = self.simulation_count = self.ucb_selection_count = 0
        self.trials, self.nodes, self.pair_summaries = [], [], []
        self.cache = {}
        self.stop_reasons = Counter()

    @staticmethod
    def _reward(feedback):
        if not isfinite(feedback.score) or not isfinite(feedback.novelty):
            raise ValueError('nonfinite grammar reward')
        return .95 * min(1., max(0., feedback.score / 6.)) + .05 * min(1., max(0., feedback.novelty))

    def find(self, key, verbs, evaluate):
        key, verbs = str(key), tuple(verbs)
        cache_key = key, verbs
        if cache_key in self.cache:
            return self.cache[cache_key]
        if not verbs or any(v not in BOOK_EXECUTABLE_VERBS for v in verbs):
            raise ValueError('unknown grammar terminal')
        rng = random.Random(_identity(self.seed, (key, *verbs), 0))
        baseline = GrammarProposal(key, _identity(key, verbs, 5), None, verbs, 5, 0, 'scheduled_sentence')
        root = _Node(baseline)
        self.nodes.append(root)
        start, first_trial, first_sim = self.retry_count, len(self.trials), self.simulation_count
        first_ucb = self.ucb_selection_count
        limit = min(self.pair_budget, self.max_retries - start)
        seen = set()
        accepted = []

        def remaining():
            return self.retry_count - start < limit

        def measure(p, phase):
            seen.add((p.verbs, p.variation_index))
            if p.depth:
                self.retry_count += 1
            f = evaluate(p)
            reward = self._reward(f)
            self.trials.append({**p.evidence(), 'phase': phase, 'accepted': f.accepted,
                                'reason': f.reason, 'score': f.score, 'novelty': f.novelty,
                                'reward': reward, 'program_hash': f.program_hash,
                                'geometry_hash': f.geometry_hash})
            if f.accepted:
                accepted.append((reward, p, f))
            return f, reward

        def actions(p):
            if p.depth >= self.max_depth:
                return []
            result = []
            for verb in _vocabulary(p.node_id):
                for production, chain in (('append', (*p.verbs, verb)), ('prepend', (verb, *p.verbs))):
                    variation = int(_identity(p.node_id, chain, self.seed), 16) % BOOK_VARIATION_COUNT
                    result.append((chain, variation, production))
            if p.depth:
                result.extend((p.verbs, v, 'retune') for v in range(BOOK_VARIATION_COUNT) if v != p.variation_index)
            rng.shuffle(result)
            return result

        def take_action(node):
            while node.actions:
                chain, variation, production = node.actions.pop()
                if (chain, variation) not in seen:
                    return GrammarProposal(key, _identity(key, chain, variation), node.proposal.node_id,
                                           chain, variation, node.proposal.depth + 1, production)
            return None

        measure(baseline, 'baseline')
        if not accepted:
            # Preserve the full old numeric lattice before spending on new topology.
            for variation in range(BOOK_VARIATION_COUNT):
                if variation == 5:
                    continue
                if not remaining():
                    break
                measure(GrammarProposal(key, _identity(key, verbs, variation), baseline.node_id,
                                        verbs, variation, 1, 'retune'), 'baseline_retune')
        root.actions = actions(baseline)
        while not accepted and remaining() and not root.exhausted:
            node = root
            while True:
                active = [c for c in node.children if not c.exhausted]
                # Progressive widening permits UCB revisits before the large
                # corpus action alphabet consumes the entire compiler budget.
                width = max(2, int(sqrt(node.visits + 1)))
                if node.actions and (len(node.children) < width or not active):
                    p = take_action(node)
                    if p is not None:
                        child = _Node(p, node, actions=actions(p))
                        node.children.append(child)
                        self.nodes.append(child)
                        node = child
                        feedback, reward = measure(p, 'expand')
                        break
                if not active:
                    node.exhausted = True
                    if node.parent is None:
                        break
                    node = node.parent
                    continue
                self.ucb_selection_count += 1
                node = max(active, key=lambda c: c.reward_sum / c.visits + sqrt(2. * log(max(1, node.visits)) / c.visits))
            if root.exhausted:
                break
            rollout = node
            # A one-step rollout leaves budget for adaptive revisits after the
            # full parameter lattice. Retain its state so its descendants remain searchable.
            if not feedback.accepted and remaining() and node.proposal.depth < self.max_depth:
                p = take_action(node)
                if p is not None:
                    feedback, reward = measure(p, 'rollout')
                    rollout = _Node(p, node, actions=actions(p))
                    node.children.append(rollout)
                    self.nodes.append(rollout)
                    rollout.exhausted = p.depth >= self.max_depth
            cursor = rollout
            while cursor is not None:
                cursor.visits += 1
                cursor.reward_sum += reward
                cursor = cursor.parent
            node.exhausted = node.proposal.depth >= self.max_depth
            self.simulation_count += 1
        selected = max(accepted, key=lambda entry: entry[0]) if accepted else None
        result = selected[2].value if selected else None
        stop = ('delivered_derivation' if selected and selected[1].depth else 'baseline_accepted') if selected else (
            'retry_budget' if self.retry_count >= self.max_retries else 'pair_budget' if not remaining() else 'tree_exhausted')
        self.stop_reasons[stop] += 1
        self.pair_summaries.append({'key': key, 'attempt_count': len(self.trials) - first_trial,
            'retry_count': self.retry_count - start, 'simulation_count': self.simulation_count - first_sim,
            'ucb_selection_count': self.ucb_selection_count - first_ucb,
            'stop_reason': stop, 'accepted': selected is not None,
            'selected_node_id': selected[1].node_id if selected else None})
        self.cache[cache_key] = result
        return result

    def evidence(self):
        return {'algorithm': self.algorithm, 'policy': 'UCB1', 'seed': self.seed, 'rollout_horizon': 1,
                'grammar': 'S -> verb S | S verb | retune(S); canonical executable BOOK terminals',
                'reward': '0.95*clip(existing_gate_progress/6,0,1) + 0.05*clip(measured_morphology_distance,0,1)',
                'quality_claim': 'measured_deliverability_and_morphology_not_aesthetic_quality',
                'provenance': 'independent grammar adaptation of recovered Finch select/expand/rollout/backprop; not vendor parity',
                'max_depth': self.max_depth, 'max_retries': self.max_retries, 'pair_budget': self.pair_budget,
                'baseline_retune_count': BOOK_VARIATION_COUNT - 1,
                'small_budget_limit': 'fewer than 10 retries may truncate parameter coverage; MCTS requires budget remaining after retunes',
                'budget_scope': 'shared derived compiler evaluations; per-pair cap; one free baseline per unseen pair',
                'budget_exhausted': self.retry_count >= self.max_retries,
                'attempt_count': len(self.trials), 'retry_count': self.retry_count,
                'simulation_count': self.simulation_count, 'ucb_selection_count': self.ucb_selection_count,
                'stop_reasons': dict(self.stop_reasons), 'pairs': list(self.pair_summaries),
                'refusal_counts': dict(Counter(r['reason'] for r in self.trials if not r['accepted'])),
                'nodes': [{**n.proposal.evidence(), 'visits': n.visits, 'reward_sum': n.reward_sum,
                           'exhausted': n.exhausted} for n in self.nodes], 'trials': list(self.trials)}
