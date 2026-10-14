from collections import Counter, defaultdict
from statistics import median


def correct(row):
    predicted = set(row['predicted_owners'])
    if row.get('should_ask'):
        return row.get('asked', False) and not predicted
    if row.get('asked'):
        return False
    required = set(row.get('required_owners', []))
    if required:
        return predicted == required
    return len(predicted) == 1 and predicted.issubset(set(row.get('acceptable_owners', [])))


def score_routes(rows):
    measured = [r for r in rows if r['status'] == 'measured']
    singleton = [r for r in measured if not r.get('required_owners')
                 and not r.get('should_ask') and len(r.get('acceptable_owners', [])) == 1]
    confusion = defaultdict(Counter)
    labels = set()
    for row in singleton:
        gold = row['acceptable_owners'][0]
        pred = row['predicted_owners']
        label = '<ask>' if row.get('asked') else '|'.join(sorted(pred)) or '<none>'
        confusion[gold][label] += 1
        labels.add(gold)
        labels.update(pred)
    per_owner = {}
    for label in sorted(labels):
        tp = confusion[label][label]
        support = sum(confusion[label].values())
        assigned = sum(c[label] for c in confusion.values())
        precision = tp / assigned if assigned else 0
        recall = tp / support if support else 0
        per_owner[label] = {'support': support, 'precision': precision, 'recall': recall,
                            'f1': 2*precision*recall/(precision+recall) if precision+recall else 0}
    model = [r for r in measured if r.get('decided_by') == 'llm' and not r.get('fallback')]
    joint = [r for r in measured if r.get('required_owners')]
    overlaps = sum(len(set(r['predicted_owners']) & set(r['required_owners'])) for r in joint)
    needed = sum(len(set(r['required_owners'])) for r in joint)
    assigned = sum(len(set(r['predicted_owners'])) for r in joint)
    asks = sum(bool(r.get('asked')) for r in measured)
    expected_asks = sum(bool(r.get('should_ask')) for r in measured)
    correct_asks = sum(bool(r.get('asked') and r.get('should_ask')) for r in measured)
    times = sorted(r['elapsed_ms'] for r in measured)
    n = len(measured)
    return {'n': len(rows), 'measured_n': n, 'availability': n/len(rows) if rows else None,
            'accuracy': sum(correct(r) for r in measured)/n if n else None,
            'macro_f1': sum(v['f1'] for v in per_owner.values())/len(per_owner) if per_owner else None,
            'per_owner': per_owner, 'confusion': {k:dict(v) for k,v in confusion.items()},
            'coverage': sum(not r.get('asked') for r in measured)/n if n else None,
            'wrong_assignment_rate': sum(not r.get('asked') and not correct(r) for r in measured)/n if n else None,
            'ask_precision': correct_asks/asks if asks else None,
            'ask_recall': correct_asks/expected_asks if expected_asks else None,
            'joint_owner_precision': overlaps/assigned if assigned else None,
            'joint_owner_recall': overlaps/needed if needed else None,
            'fallback_n': sum(bool(r.get('fallback')) for r in rows),
            'model_only_n': len(model), 'model_only_accuracy': sum(correct(r) for r in model)/len(model) if model else None,
            'latency_ms_p50': median(times) if times else None,
            'latency_ms_p95': times[max(0, (95*len(times)+99)//100-1)] if times else None}
