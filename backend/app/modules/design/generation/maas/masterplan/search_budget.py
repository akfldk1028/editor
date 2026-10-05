"""Explicit bounded design-study search; no legal or feasibility conclusion."""
class BasementSearchBudget:
    """Explicit invocation cap; exhaustion means truncated search, not infeasibility."""
    def __init__(self, limit=None):
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 1000):
            raise ValueError('max_basement_solves must be an integer in 1..1000')
        self.limit, self.invoked, self.truncated = limit, 0, False

    def run(self, fn, *args, **kwargs):
        if self.limit is not None and self.invoked >= self.limit:
            self.truncated = True
            return None
        self.invoked += 1
        return fn(*args, **kwargs)

    def record(self):
        return dict(limit=self.limit, invoked=self.invoked, truncated=self.truncated)
