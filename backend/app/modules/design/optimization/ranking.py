import math


class OptimizationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def remap(value, min1, max1, min2, max2):
    """Linear interpolation between two ranges."""
    return float(min2) + (float(value) - float(min1)) * (float(max2) - float(min2)) / (float(max1) - float(min1))

def rank(population, outputs_def):
    """
    NSGA-II ranking: Pareto fronts + crowding distances.

    Args:
        population: list of Design objects with .get_objectives() and .get_penalty()
        outputs_def: list of output definitions with 'type' and 'Goal' keys

    Returns:
        (rankings, distances, penalties) — lists parallel to population
    """
    goals = [item.get('Goal') for item in outputs_def if item.get('type') == 'Objective']
    if not goals or any(goal not in ('Minimize', 'Maximize') for goal in goals):
        raise OptimizationError('invalid_ranking', 'Ranking requires supported objective directions')
    for design in population:
        values = design.get_objectives()
        if len(values) != len(goals) or any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            raise OptimizationError('invalid_ranking', 'Ranking requires finite complete objective evidence')
    designs = []
    for i, des in enumerate(population):
        designs.append({'id': i, 'scores': des.get_objectives()})
    objective_goals = [x['Goal'] for x in outputs_def if x['type'] == 'Objective']
    valid_set = [x for x in designs if len(x['scores']) == len(objective_goals)]
    dom = []
    ranking = []
    P = valid_set
    while len(P) > 0:
        ranking.append([x['id'] for x in getDominantSet(P, objective_goals)])
        dom = dom + ranking[-1]
        P = [x for x in valid_set if x['id'] not in dom]
    distances = [0.0] * len(population)
    for front_ids in ranking:
        front_designs = [design for design in designs if design['id'] in front_ids]
        for score in range(len(objective_goals)):
            sorted_designs = sorted(front_designs, key=lambda k: k['scores'][score])
            distances[sorted_designs[0]['id']] += float('inf')
            distances[sorted_designs[-1]['id']] += float('inf')
            if len(sorted_designs) > 2:
                f_min = sorted_designs[0]['scores'][score]
                f_max = sorted_designs[-1]['scores'][score]
                if f_min < f_max:
                    for i, des in enumerate(sorted_designs[1:-1]):
                        distances[des['id']] += (sorted_designs[i + 2]['scores'][score] - sorted_designs[i]['scores'][score]) / (f_max - f_min)
    ranking.reverse()
    penalties = [x.get_penalty() for x in population]
    ranking_out = [0] * len(population)
    for i, ids in enumerate(ranking):
        for _id in ids:
            ranking_out[_id] = i + 1
    return (ranking_out, distances, penalties)

def getDominantSet(data, objective_goals):
    """Find the Pareto-dominant set from data."""
    if len(objective_goals) == 1:
        scores = [float(x['scores'][0]) for x in data]
        if objective_goals[0] == 'Minimize':
            return [data[scores.index(min(scores))]]
        else:
            return [data[scores.index(max(scores))]]
    else:

        def keyfunc(x):
            fac = [(obj == 'Minimize') * 2 - 1 for obj in objective_goals]
            keys = [x['scores'][i] * fac[i] for i in range(len(x['scores']))]
            return tuple(keys)
        P = sorted(data, key=keyfunc)
        return front(P, objective_goals)

def front(P, objective_goals):
    """Recursive divide-and-conquer Pareto front algorithm."""
    if len(P) == 1:
        return P
    div = int(math.floor(len(P) / 2.0))
    T = front(P[:div], objective_goals)
    B = front(P[div:], objective_goals)
    M = []
    for des1 in B:
        dominated = True
        for des2 in T:
            dominated = True
            for k in range(len(des1['scores'])):
                fac = (objective_goals[k] == 'Minimize') * 2 - 1
                if fac * float(des1['scores'][k]) < fac * float(des2['scores'][k]):
                    dominated = False
                    break
            if dominated:
                break
        if not dominated:
            M.append(des1)
    return T + M
