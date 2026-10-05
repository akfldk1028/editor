from copy import deepcopy
from random import Random
from .genome import Design, EvaluationRejected, OptimizationError, validate_inputs, validate_outputs, validate_definitions
from .ranking import rank
from ..job_spec import _options, JobSpecError


def resolve_options(options):
    if not isinstance(options, dict):
        raise OptimizationError('invalid_options', 'Optimizer options must be an object')
    effective = {
        'num_islands': 5, 'pop_per_island': 15, 'Number of generations': 50,
        'migration_interval': 10, 'migrants_count': 2, 'tournament_size': 8,
        'initial_mutation_rate': .35, 'final_mutation_rate': .10,
        'penalty_mode': 'normalized', 'island_mode': 'homogeneous',
    }
    effective.update(deepcopy(options))
    try:
        _options(effective)
    except JobSpecError as error:
        raise OptimizationError(error.code, error.message) from None
    if effective.get('island_strategies') is None:
        effective['island_strategies'] = [
            'de' if effective['island_mode'] == 'heterogeneous' and index % 2 else 'blx'
            for index in range(effective['num_islands'])
        ]
    return effective


class SSIEAJob:
    """
    Steady-State Island Evolutionary Algorithm.

    5 islands with ring migration, adaptive mutation rate,
    tournament selection (size=8), steady-state replacement.

    Based on Nature Scientific Reports 2025:
    "Multi-objective optimization of daylighting & solar radiation
    for building geometry using SSIEA"
    """

    def __init__(self, job_spec, *, rng):
        if not isinstance(rng, Random) or not isinstance(job_spec, dict):
            raise OptimizationError('invalid_job', 'Expected specification and per-run Random instance')
        validate_inputs(job_spec.get('inputs'))
        validate_definitions(job_spec.get('outputs'))
        self.rng = rng
        self.spec = deepcopy(job_spec)
        opts = resolve_options(job_spec.get('options', {}))
        self.spec['options'] = opts
        self.num_islands = int(opts.get('num_islands', 5))
        self.pop_per_island = int(opts.get('pop_per_island', 15))
        self.max_gen = int(opts.get('Number of generations', 50))
        self.migration_interval = int(opts.get('migration_interval', 10))
        self.migrants_count = int(opts.get('migrants_count', 2))
        self.tournament_size = int(opts.get('tournament_size', 8))
        self.initial_mutation = float(opts.get('initial_mutation_rate', 0.35))
        self.final_mutation = float(opts.get('final_mutation_rate', 0.1))
        self.penalty_mode = opts.get('penalty_mode', 'normalized')
        self.island_mode = opts.get('island_mode', 'homogeneous')
        explicit_strategies = opts.get('island_strategies')
        if explicit_strategies is not None:
            self.island_strategies = list(explicit_strategies)
        elif self.island_mode == 'heterogeneous':
            self.island_strategies = ['blx' if i % 2 == 0 else 'de' for i in range(self.num_islands)]
        else:
            self.island_strategies = ['blx'] * self.num_islands
        self.islands: list[list[Design]] = []
        self.gen = 0
        self.des_count = 0
        self.all_designs: list[Design] = []
        self.num_designs = self.num_islands * self.pop_per_island
        self._initialized = False
        self._pareto_cache: list[Design] | None = None
        self._pareto_cache_size = 0
        self._finished = False

    def init_designs(self):
        """Create initial random population across all islands."""
        if self.islands:
            raise OptimizationError('already_initialized', 'Initial population already exists')
        designs = []
        for _ in range(self.num_islands):
            island = []
            for j in range(self.pop_per_island):
                des = Design(self.des_count, j, 0, rng=self.rng)
                des.generate_random(self.spec['inputs'])
                self.des_count += 1
                island.append(des)
                designs.append(des)
            self.islands.append(island)
        return designs

    def step(self, evaluate_fn):
        """
        Run one generation step.

        First call evaluates the initial population.
        Subsequent calls evolve via steady-state replacement.

        Returns:
            (continue: bool, generation: int, population: list[Design])
        """
        if not self.islands or self._finished:
            raise OptimizationError('invalid_state', 'Initialize once and stop when step returns false')
        if not self._initialized:
            all_initial = [d for island in self.islands for d in island]
            results = self._evaluate(evaluate_fn, all_initial)
            for des, outputs in zip(all_initial, results):
                des.set_outputs(outputs, self.spec['outputs'], self.penalty_mode)
            self.all_designs.extend(all_initial)
            self._initialized = True
        else:
            self._evolve_step(evaluate_fn)
        all_pop = [d for island in self.islands for d in island]
        if self.gen >= self.max_gen:
            self._finished = True
            return (False, self.gen, all_pop)
        self.gen += 1
        return (True, self.gen, all_pop)

    def _evolve_step(self, evaluate_fn):
        """One steady-state step: create and evaluate children, replace worst."""
        mutation_rate = self.initial_mutation - (self.initial_mutation - self.final_mutation) * self.gen / max(1, self.max_gen)
        children = []
        child_islands = []
        for island_idx, island in enumerate(self.islands):
            parents = self._tournament_select(island, k=2)
            strategy = self.island_strategies[island_idx]
            child = parents[0].crossover(parents[1], self.spec['inputs'], self.gen, 0, self.des_count, strategy=strategy)
            child.mutate(self.spec['inputs'], mutation_rate)
            self.des_count += 1
            children.append(child)
            child_islands.append(island)
        results = self._evaluate(evaluate_fn, children)
        for child, outputs, island in zip(children, results, child_islands):
            child.set_outputs(outputs, self.spec['outputs'], self.penalty_mode)
            self.all_designs.append(child)
            worst_idx = self._find_worst(island)
            if self._should_replace(child, island[worst_idx]):
                island[worst_idx] = child
        if self.gen > 0 and self.gen % self.migration_interval == 0:
            self._migrate()

    def _fitness_key(self, d: Design):
        """
        Fitness sort key: lower is better.

        Sorts by (penalty, direction-aware objective score).
        Respects Minimize/Maximize from spec outputs.
        """
        if not d.objectives:
            return (1, d.penalty, 0.0)
        score = 0.0
        obj_idx = 0
        for out_def in self.spec.get('outputs', []):
            if out_def['type'] != 'Objective':
                continue
            if obj_idx >= len(d.objectives):
                break
            val = d.objectives[obj_idx]
            if out_def.get('Goal') == 'Maximize':
                score -= val
            else:
                score += val
            obj_idx += 1
        return (0, d.penalty, score)

    def _find_worst(self, island: list[Design]) -> int:
        """Find index of worst individual (highest fitness key = worst)."""
        return max(range(len(island)), key=lambda j: self._fitness_key(island[j]))

    def _should_replace(self, child: Design, worst: Design) -> bool:
        """Decide if child should replace worst."""
        if bool(child.rejections) != bool(worst.rejections):
            return not child.rejections
        if child.penalty < worst.penalty:
            return True
        if child.penalty > worst.penalty:
            return False
        return self._fitness_key(child) < self._fitness_key(worst)

    def _tournament_select(self, island: list[Design], k: int=2) -> list[Design]:
        """Tournament selection from an island."""
        selected = []
        for _ in range(k):
            candidates = self.rng.sample(island, min(self.tournament_size, len(island)))
            best = min(candidates, key=self._fitness_key)
            selected.append(best)
        return selected

    def _migrate(self):
        """Ring migration: best from island i -> replace worst in island (i+1)."""
        n = len(self.islands)
        migrants_per_island = []
        for i in range(n):
            sorted_island = sorted(self.islands[i], key=self._fitness_key)
            migrants_per_island.append(sorted_island[:self.migrants_count])
        for i in range(n):
            dst = self.islands[(i + 1) % n]
            sorted_dst = sorted(dst, key=self._fitness_key)
            worst_list = sorted_dst[-self.migrants_count:]
            for migrant, w in zip(migrants_per_island[i], worst_list):
                if w in dst:
                    idx = dst.index(w)
                    new_des = Design(self.des_count, 0, self.gen, rng=self.rng)
                    new_des.set_inputs([list(inp) for inp in migrant.get_inputs()])
                    new_des.objectives = list(migrant.objectives)
                    new_des.outputs = list(migrant.outputs)
                    new_des.rejections = list(migrant.rejections)
                    new_des.feasible = migrant.feasible
                    new_des.penalty = migrant.penalty
                    new_des.rank = migrant.rank
                    self.des_count += 1
                    dst[idx] = new_des

    def get_pareto_front(self):
        """Get Pareto-optimal designs from ALL evaluated designs (feasible only).

        Uses self.all_designs (full history) not just current island members,
        so the Pareto front grows over generations as more designs are explored.
        Cached: only recomputes when new designs have been added.
        """
        if self._pareto_cache is not None and self._pareto_cache_size == len(self.all_designs):
            return self._pareto_cache
        feasible = [d for d in self.all_designs if d.objectives and d.penalty == 0]
        if not feasible:
            self._pareto_cache = []
            self._pareto_cache_size = len(self.all_designs)
            return []
        ranking, _, _ = rank(feasible, self.spec['outputs'])
        best_rank = max(ranking)
        result = [d for d, r in zip(feasible, ranking) if r == best_rank]
        self._pareto_cache = result
        self._pareto_cache_size = len(self.all_designs)
        return result

    def get_best(self):
        """Get best design across all islands (uses cached pareto when available)."""
        pareto = self.get_pareto_front()
        if pareto:
            return min(pareto, key=self._fitness_key)
        all_evaluated = [d for island in self.islands for d in island if d.objectives]
        if not all_evaluated:
            return None
        return min(all_evaluated, key=self._fitness_key)

    def _evaluate(self, evaluate_fn, designs):
        results = evaluate_fn(designs)
        if not isinstance(results, (list, tuple)) or len(results) != len(designs):
            raise OptimizationError('invalid_evaluation_batch', 'Evaluator must return one result per design')
        return [validate_outputs(result, self.spec['outputs']) for result in results]
