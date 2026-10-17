"""Bounded UCB1 parameter exploration scored by executed delivery gates."""

from collections import Counter
from math import log, sqrt


class DeliveryVariantSearch:
    def __init__(self, *, variant_count, baseline_variant, max_retries=96):
        if variant_count < 1 or not 0 <= baseline_variant < variant_count or max_retries < 0:
            raise ValueError('invalid delivery search domain or budget')
        self.variant_count = variant_count
        self.baseline_variant = baseline_variant
        self.max_retries = max_retries
        self.retry_count = 0
        self.visits = Counter()
        self.successes = Counter()
        self.trials = []
        self.cache = {}
        self.budget_exhausted = False

    def find(self, key, evaluate):
        """Evaluate regenerated geometry; never turn missing budget into a pass."""
        if key in self.cache:
            return self.cache[key]
        remaining = set(range(self.variant_count))
        result = None
        while remaining:
            baseline = len(remaining) == self.variant_count
            if not baseline and self.retry_count >= self.max_retries:
                self.budget_exhausted = True
                break
            if baseline:
                variant = self.baseline_variant
            else:
                def priority(v):
                    n = self.visits[v]
                    score = (self.successes[v] / n + sqrt(2 * log(max(2, len(self.trials))) / n)
                             if n else float('inf'))
                    return score, -v
                variant = max(remaining, key=priority)
            remaining.remove(variant)
            if not baseline:
                self.retry_count += 1
            accepted, value, reason = evaluate(variant)
            self.visits[variant] += 1
            self.successes[variant] += int(accepted)
            self.trials.append({'key': str(key), 'variant': variant,
                                'accepted': bool(accepted), 'reason': str(reason)})
            if accepted:
                result = value
                break
        self.cache[key] = result
        return result

    def evidence(self):
        return {
            'algorithm': 'delivery_guided_ucb1_parameter_search.v1',
            'reward': '1 iff regenerated candidate passes existing compilation and site delivery gates; else 0',
            'quality_claim': 'measured_deliverability_not_aesthetic_quality',
            'variant_count': self.variant_count, 'baseline_variant': self.baseline_variant,
            'max_retries': self.max_retries, 'attempt_count': len(self.trials),
            'retry_count': self.retry_count,
            'budget_scope': 'regenerated alternatives; each unseen pair retains one baseline evaluation',
            'budget_exhausted': self.budget_exhausted,
            'refusal_counts': dict(Counter(t['reason'] for t in self.trials if not t['accepted'])),
            'trials': list(self.trials),
        }
