from dataclasses import dataclass
import math
from random import Random
from .ranking import remap, OptimizationError


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class EvaluationRejected:
    rejections: tuple[str, ...]

    def __post_init__(self):
        if (not isinstance(self.rejections, tuple) or not self.rejections
                or len(self.rejections) > 40
                or any(not isinstance(reason, str) or not reason.strip() or len(reason) > 1000 for reason in self.rejections)):
            raise OptimizationError('invalid_rejection', 'Rejected evaluation requires bounded reason strings')


def validate_inputs(inputs_def):
    if not isinstance(inputs_def, list) or not 1 <= len(inputs_def) <= 256:
        raise OptimizationError('invalid_inputs', 'Expected a bounded nonempty gene list')
    for item in inputs_def:
        if (not isinstance(item, dict) or item.get('type') != 'Continuous'
                or type(item.get('Set length')) is not int or item['Set length'] != 1
                or any(not _finite(item.get(key)) or abs(item[key]) > 1e6 for key in ('Min', 'Max'))
                or item['Min'] > item['Max']):
            raise OptimizationError('invalid_inputs', 'Only finite ordered scalar continuous genes are supported')


def validate_definitions(outputs_def):
    if not isinstance(outputs_def, list) or not 1 <= len(outputs_def) <= 40:
        raise OptimizationError('invalid_outputs', 'Expected a bounded nonempty output definition list')
    objectives = 0
    for item in outputs_def:
        if not isinstance(item, dict):
            raise OptimizationError('invalid_outputs', 'Output definitions must be objects')
        if item.get('type') == 'Objective' and item.get('Goal') in ('Maximize', 'Minimize'):
            objectives += 1
        elif (item.get('type') == 'Constraint'
              and item.get('Requirement') in ('Less than', 'Greater than', 'Equals')
              and _finite(item.get('val'))):
            continue
        else:
            raise OptimizationError('invalid_outputs', 'Unsupported objective or constraint definition')
    if not objectives:
        raise OptimizationError('invalid_outputs', 'At least one objective is required')


def validate_outputs(outputs, outputs_def):
    validate_definitions(outputs_def)
    if isinstance(outputs, EvaluationRejected):
        return outputs
    if not isinstance(outputs, (list, tuple)) or len(outputs) != len(outputs_def) or not all(_finite(v) for v in outputs):
        raise OptimizationError('invalid_evaluation', 'Evaluation vector must have exact length and finite numeric values')
    penalty_bound = 0.0
    objective_bound = 0.0
    for value, item in zip(outputs, outputs_def):
        if item['type'] == 'Objective':
            objective_bound += abs(value)
        else:
            target = float(item['val'])
            penalty_bound += abs(value-target) / (abs(target) if abs(target) > 1e-9 else 1.0)
    if not math.isfinite(penalty_bound) or not math.isfinite(objective_bound):
        raise OptimizationError('numeric_overflow', 'Evaluation exceeds finite fitness arithmetic')
    return list(outputs)


class Design:
    """A single design individual in the GA population."""

    def __init__(self, _id, des_num, gen_num, *, rng):
        if not isinstance(rng, Random):
            raise OptimizationError('invalid_rng', 'A per-run random.Random instance is required')
        self.rng = rng
        self.outputs = []
        self.rejections = []
        self.id = _id
        self.desNum = des_num
        self.genNum = gen_num
        self.parents = [None, None]
        self.inputs = []
        self.objectives = []
        self.feasible = True
        self.penalty = 0
        self.rank = 0
        self.elite = 0

    def generate_random(self, inputs_def):
        """Generate random input values based on input definitions."""
        validate_inputs(inputs_def)
        self.inputs = []
        for _i in inputs_def:
            if _i['type'] == 'Continuous':
                p = [remap(self.rng.random(), 0, 1, _i['Min'], _i['Max']) for _ in range(int(_i['Set length']))]
                self.inputs.append(p)

    def crossover(self, partner, inputs_def, gen_num, des_num, id_num, strategy: str='blx'):
        """Create child design through crossover with partner.

        Args:
            strategy: 'blx' (default, BLX-α 기존) | 'de' (Differential Evolution rand/1/bin).
                     B4 — Heterogeneous Island 에서 island별 전략 다르게 가능.
        """
        validate_inputs(inputs_def)
        if strategy not in ('blx', 'de'):
            raise OptimizationError('invalid_strategy', 'Unsupported crossover strategy')
        if len(self.inputs) != len(inputs_def) or len(partner.inputs) != len(inputs_def):
            raise OptimizationError('invalid_inputs', 'Parent gene count does not match specification')
        child = Design(id_num, des_num, gen_num, rng=self.rng)
        child_inputs = []
        for i in range(len(self.get_inputs())):
            if inputs_def[i]['type'] == 'Continuous':
                new_input = []
                inputs_1 = self.get_inputs()[i]
                inputs_2 = partner.get_inputs()[i]
                for j in range(len(inputs_1)):
                    x1 = inputs_1[j]
                    x2 = inputs_2[j]
                    if strategy == 'de':
                        F = 0.4 + 0.5 * self.rng.random()
                        new_val = x1 + F * (x2 - x1)
                    else:
                        d = abs(x1 - x2)
                        y1 = min(x1, x2) - d / 3
                        y2 = max(x1, x2) + d / 3
                        new_val = y1 + (y2 - y1) * self.rng.random()
                    clipped = float(max(float(inputs_def[i]['Min']), min(new_val, float(inputs_def[i]['Max']))))
                    new_input.append(clipped)
                child_inputs.append(new_input)
        child.set_inputs(child_inputs)
        return child

    def mutate(self, inputs_def, mutation_rate):
        """Mutate design inputs in-place."""
        validate_inputs(inputs_def)
        if not _finite(mutation_rate) or not 0 <= mutation_rate <= 1 or len(self.inputs) != len(inputs_def):
            raise OptimizationError('invalid_mutation', 'Mutation rate or gene count is invalid')
        inputs_out = []
        for i in range(len(self.get_inputs())):
            if inputs_def[i]['type'] == 'Continuous':
                input_set = self.get_inputs()[i]
                new_input_set = []
                goal_range = float(abs(float(inputs_def[i]['Max']) - float(inputs_def[i]['Min'])))
                for _input in input_set:
                    if self.rng.random() < mutation_rate:
                        new_input = _input + self.rng.gauss(0, goal_range / 5.0)
                        new_input_set.append(float(max(float(inputs_def[i]['Min']), min(new_input, float(inputs_def[i]['Max'])))))
                    else:
                        new_input_set.append(_input)
                inputs_out.append(new_input_set)
        self.set_inputs(inputs_out)

    def get_id(self):
        return self.id

    def set_inputs(self, inputs):
        if (not isinstance(inputs, list) or not 1 <= len(inputs) <= 256
                or any(not isinstance(row, list) or len(row) != 1 or not _finite(row[0]) for row in inputs)):
            raise OptimizationError('invalid_inputs', 'Genome must contain finite scalar gene lists')
        self.inputs = [list(row) for row in inputs]

    def get_inputs(self):
        return self.inputs

    def set_outputs(self, outputs, outputs_def, penalty_mode: str='normalized'):
        """
        Parse outputs, check constraints, compute penalty.

        A3 (2026-05-06) — penalty 정규화:
            normalized (default): 위반 거리 비례 (limit base 정규화)
            binary: 위반 개수 카운트 (legacy, exp004 비교용)

        예 BCR 한도 60%, 매스 BCR 80%:
            normalized: penalty += (80-60)/60 = 0.333
            binary:     penalty += 1
            매스 BCR 65%:
            normalized: penalty += 0.083
            binary:     penalty += 1
            → normalized 가 GA에게 *얼마나 위반했는지* signal 전달

        feasible 플래그는 두 모드 동일 (위반 1건이라도 False).
        """
        outputs = validate_outputs(outputs, outputs_def)
        if penalty_mode not in ('normalized', 'binary'):
            raise OptimizationError('invalid_penalty', 'Unsupported penalty mode')
        if isinstance(outputs, EvaluationRejected):
            self.outputs = []
            self.objectives = []
            self.rejections = list(outputs.rejections)
            self.penalty = 1e12
            self.feasible = False
            return
        self.outputs = list(outputs)
        self.rejections = []
        self.objectives = []
        self.penalty = 0.0
        self.feasible = True
        for i, _o in enumerate(outputs):
            _o = float(_o)
            if outputs_def[i]['type'] == 'Objective':
                self.objectives.append(_o)
            elif outputs_def[i]['type'] == 'Constraint':
                goal = outputs_def[i]['Requirement']
                goal_val = float(outputs_def[i]['val'])
                base = abs(goal_val) if abs(goal_val) > 1e-09 else 1.0
                violated = False
                raw_violation = 0.0
                if goal == 'Less than':
                    if _o > goal_val:
                        violated = True
                        raw_violation = (_o - goal_val) / base
                elif goal == 'Greater than':
                    if _o < goal_val:
                        violated = True
                        raw_violation = (goal_val - _o) / base
                elif goal == 'Equals':
                    if _o != goal_val:
                        violated = True
                        raw_violation = abs(_o - goal_val) / base
                if violated:
                    self.penalty += 1.0 if penalty_mode == 'binary' else raw_violation
                    self.feasible = False

    def get_objectives(self):
        return self.objectives

    def get_penalty(self):
        return self.penalty

    def get_data(self):
        """Return serializable dict of this design's data."""
        return {'id': self.id, 'generation': self.genNum, 'parents': list(self.parents), 'feasible': self.feasible,
                'inputs': [list(row) for row in self.inputs], 'objectives': list(self.objectives),
                'penalty': self.penalty, 'rank': self.rank, 'elite': self.elite,
                'outputs': list(self.outputs), 'rejections': list(self.rejections)}
