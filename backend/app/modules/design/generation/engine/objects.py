"""
Evolutionary optimization engines.

Design: Single individual in GA population.
Job: NSGA-II generational optimizer (legacy, preserved for backward compat).
SSIEAJob: Steady-State Island EA — 5 islands, ring migration, adaptive mutation.

Ported from AUA/discover/src/objects.py — removed Grasshopper dependencies.
SSIEAJob based on Nature Scientific Reports 2025 validated parameters.
"""

import logging
import math
import random

from backend.app.modules.design.generation.engine.utils import remap, rank, permutation2inversion, inversion2permutation

logger = logging.getLogger(__name__)


class Design:
    """A single design individual in the GA population."""

    def __init__(self, _id, des_num, gen_num):
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
        self.inputs = []

        for _i in inputs_def:
            if _i["type"] == "Continuous":
                p = [remap(random.random(), 0, 1, _i["Min"], _i["Max"])
                     for _ in range(int(_i["Set length"]))]
                self.inputs.append(p)

            elif _i["type"] == "Categorical":
                p = [int(math.floor(random.random() * 0.9999 * float(_i["Num options"])))
                     for _ in range(int(_i["Set length"]))]
                self.inputs.append(p)

            elif _i["type"] == "Series":
                depth = int(_i["Depth"])
                p = [int(math.floor(random.random() * 0.9999 * depth))
                     for _ in range(int(_i["Set length"]))]
                self.inputs.append(p)

            elif _i["type"] == "Sequence":
                seq = list(range(int(_i["Num options"])))
                random.shuffle(seq)
                self.inputs.append(seq)

    def crossover(self, partner, inputs_def, gen_num, des_num, id_num,
                  strategy: str = "blx"):
        """Create child design through crossover with partner.

        Args:
            strategy: 'blx' (default, BLX-α 기존) | 'de' (Differential Evolution rand/1/bin).
                     B4 — Heterogeneous Island 에서 island별 전략 다르게 가능.
        """
        child = Design(id_num, des_num, gen_num)
        child_inputs = []

        for i in range(len(self.get_inputs())):
            if inputs_def[i]["type"] == "Continuous":
                new_input = []
                inputs_1 = self.get_inputs()[i]
                inputs_2 = partner.get_inputs()[i]

                for j in range(len(inputs_1)):
                    x1 = inputs_1[j]
                    x2 = inputs_2[j]
                    if strategy == "de":
                        # DE rand/1: x_new = x1 + F * (x2 - x1), F ~ Uniform(0.4, 0.9)
                        F = 0.4 + 0.5 * random.random()
                        new_val = x1 + F * (x2 - x1)
                    else:
                        # BLX-α (기본)
                        d = abs(x1 - x2)
                        y1 = min(x1, x2) - d / 3
                        y2 = max(x1, x2) + d / 3
                        new_val = y1 + (y2 - y1) * random.random()
                    clipped = float(max(float(inputs_def[i]["Min"]),
                                        min(new_val, float(inputs_def[i]["Max"]))))
                    new_input.append(clipped)
                child_inputs.append(new_input)

            elif inputs_def[i]["type"] == "Categorical":
                a = self.get_inputs()[i]
                b = partner.get_inputs()[i]
                new_input = [a[j] if random.random() > 0.5 else b[j]
                             for j in range(len(a))]
                child_inputs.append(new_input)

            elif inputs_def[i]["type"] == "Series":
                a = self.get_inputs()[i]
                b = partner.get_inputs()[i]
                new_input = [a[j] if random.random() > 0.5 else b[j]
                             for j in range(len(a))]
                child_inputs.append(new_input)

            elif inputs_def[i]["type"] == "Sequence":
                a = permutation2inversion(self.get_inputs()[i])
                b = permutation2inversion(partner.get_inputs()[i])
                new_input = inversion2permutation(
                    [a[j] if random.random() > 0.5 else b[j] for j in range(len(a))]
                )
                child_inputs.append(new_input)

        child.set_inputs(child_inputs)
        return child

    def mutate(self, inputs_def, mutation_rate):
        """Mutate design inputs in-place."""
        inputs_out = []

        for i in range(len(self.get_inputs())):
            if inputs_def[i]["type"] == "Continuous":
                input_set = self.get_inputs()[i]
                new_input_set = []
                goal_range = float(abs(float(inputs_def[i]["Max"]) - float(inputs_def[i]["Min"])))
                for _input in input_set:
                    if random.random() < mutation_rate:
                        new_input = _input + random.gauss(0, goal_range / 5.0)
                        new_input_set.append(float(max(float(inputs_def[i]["Min"]),
                                                        min(new_input, float(inputs_def[i]["Max"])))))
                    else:
                        new_input_set.append(_input)
                inputs_out.append(new_input_set)

            elif inputs_def[i]["type"] == "Categorical":
                input_set = self.get_inputs()[i]
                new_input_set = []
                for _input in input_set:
                    if random.random() < mutation_rate:
                        new_input = int(math.floor(random.random() * 0.9999 * float(inputs_def[i]["Num options"])))
                        new_input_set.append(new_input)
                    else:
                        new_input_set.append(_input)
                inputs_out.append(new_input_set)

            elif inputs_def[i]["type"] == "Series":
                input_set = self.get_inputs()[i]
                new_input_set = []
                depth = int(inputs_def[i]["Depth"])
                elem_rate = float(inputs_def[i].get("Mutation rate", mutation_rate))
                for _input in input_set:
                    if random.random() < elem_rate:
                        new_input_set.append(int(math.floor(random.random() * 0.9999 * depth)))
                    else:
                        new_input_set.append(_input)
                inputs_out.append(new_input_set)

            elif inputs_def[i]["type"] == "Sequence":
                num_mutations = int(math.ceil(
                    float(inputs_def[i]["Num options"]) * (mutation_rate / 2.0)
                ))
                new_sequence = list(self.get_inputs()[i])
                for _ in range(num_mutations):
                    choices = list(range(len(new_sequence)))
                    choice1 = choices.pop(choices.index(random.choice(choices)))
                    choice2 = choices.pop(choices.index(random.choice(choices)))
                    new_sequence[choice1], new_sequence[choice2] = (
                        new_sequence[choice2], new_sequence[choice1]
                    )
                inputs_out.append(new_sequence)

        self.set_inputs(inputs_out)

    def get_id(self):
        return self.id

    def set_inputs(self, inputs):
        self.inputs = inputs

    def get_inputs(self):
        return self.inputs

    def set_outputs(self, outputs, outputs_def, penalty_mode: str = "normalized"):
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
        self.objectives = []
        self.penalty = 0.0
        self.feasible = True
        for i, _o in enumerate(outputs):
            _o = float(_o)

            if outputs_def[i]["type"] == "Objective":
                self.objectives.append(_o)

            elif outputs_def[i]["type"] == "Constraint":
                goal = outputs_def[i]["Requirement"]
                goal_val = float(outputs_def[i]["val"])
                base = abs(goal_val) if abs(goal_val) > 1e-9 else 1.0

                # 라벨이 "≤ 60%" / "≥ 1m" 라서 boundary는 feasible (strict < / strict >).
                violated = False
                raw_violation = 0.0
                if goal == "Less than":
                    if _o > goal_val:
                        violated = True
                        raw_violation = (_o - goal_val) / base
                elif goal == "Greater than":
                    if _o < goal_val:
                        violated = True
                        raw_violation = (goal_val - _o) / base
                elif goal == "Equals":
                    if _o != goal_val:
                        violated = True
                        raw_violation = abs(_o - goal_val) / base

                if violated:
                    self.penalty += 1.0 if penalty_mode == "binary" else raw_violation
                    self.feasible = False

    def check_duplicate(self, des):
        for i, _in in enumerate(self.get_inputs()):
            if str(_in) != str(des.get_inputs()[i]):
                return False
        return True

    def check_duplicates(self, other_designs):
        for des in other_designs:
            if self.check_duplicate(des):
                return True
        return False

    def get_objectives(self):
        return self.objectives

    def get_penalty(self):
        return self.penalty

    def set_elite(self):
        self.elite = 1

    def get_elite(self):
        return self.elite

    def set_parents(self, p1, p2):
        self.parents = [p1, p2]

    def get_parents(self):
        return self.parents

    def get_data(self):
        """Return serializable dict of this design's data."""
        return {
            "id": self.id,
            "generation": self.genNum,
            "parents": self.parents,
            "feasible": self.feasible,
            "inputs": self.inputs,
            "objectives": self.objectives,
            "penalty": self.penalty,
            "rank": self.rank,
            "elite": self.elite,
        }


class Job:
    """
    NSGA-II optimization job manager (legacy).

    Preserved for backward compatibility.
    New optimizations should use SSIEAJob instead.
    """

    def __init__(self, job_spec):
        self.spec = job_spec
        self.des_count = 0
        self.num_designs = int(job_spec["options"].get("Designs per generation", 30))
        self.gen = 0
        self.max_gen = int(job_spec["options"].get("Number of generations", 50))
        self.save_elites = int(job_spec["options"].get("Elites", 2))
        self.mutation_rate = float(job_spec["options"].get("Mutation rate", 0.05))

        self.design_queue = []
        self.design_log = []
        self.all_designs = []

    def init_designs(self):
        """Create initial random population."""
        designs = []
        for i in range(self.num_designs):
            des = Design(self.des_count, i, self.gen)
            des.generate_random(self.spec["inputs"])
            self.des_count += 1
            designs.append(des)
        self.design_queue = designs
        return designs

    def next_generation(self, population):
        """Create next generation via selection, crossover, mutation."""
        children = []

        ranking, crowding, penalties = rank(population, self.spec["outputs"])
        stats = [[penalties[i], ranking[i], crowding[i]] for i in range(len(ranking))]

        self.gen += 1

        # Elitism: carry over best individuals
        if self.save_elites > 0:
            elites = [i[0] for i in sorted(
                enumerate(stats),
                key=lambda x: (x[1][0], -x[1][1], -x[1][2])
            )][:self.save_elites]

            for i, elite_num in enumerate(elites):
                child = Design(self.des_count, i, self.gen)
                child.set_inputs(population[elite_num].get_inputs())
                child.set_elite()
                child.set_parents(population[elite_num].get_id(), None)
                children.append(child)
                self.des_count += 1

        # Fill rest via tournament selection + crossover + mutation
        child_num = self.save_elites
        max_attempts = self.num_designs * 10  # prevent infinite loop on duplicates
        attempts = 0
        while child_num < len(population) and attempts < max_attempts:
            attempts += 1
            pool = list(range(len(population)))
            parents = []
            for _ in range(2):
                candidate1 = random.choice(pool)
                pool.pop(pool.index(candidate1))
                candidate2 = random.choice(pool)
                pool.pop(pool.index(candidate2))

                candidates = [[x, stats[x]] for x in [candidate1, candidate2]]
                standings = sorted(candidates, key=lambda x: (x[1][0], -x[1][1], -x[1][2]))
                parents.append(standings[0][0])
                pool.append(standings[1][0])

            child = population[parents[0]].crossover(
                population[parents[1]], self.spec["inputs"],
                self.gen, child_num, self.des_count
            )
            child.mutate(self.spec["inputs"], self.mutation_rate)
            child.set_parents(population[parents[0]].get_id(), population[parents[1]].get_id())

            if not child.check_duplicates(children):
                children.append(child)
                self.des_count += 1
                child_num += 1

        return children

    def step(self, evaluate_fn):
        """
        Run one generation: evaluate current queue, then create next gen.

        Args:
            evaluate_fn: callable(designs) -> list[list[float]]
                Takes list of Design objects, returns list of output value lists.

        Returns:
            (continue: bool, generation: int, population: list[Design])
        """
        # Evaluate current designs
        results = evaluate_fn(self.design_queue)
        for des, outputs in zip(self.design_queue, results):
            des.set_outputs(outputs, self.spec["outputs"])

        # Add to log and history
        self.design_log.extend(self.design_queue)
        self.all_designs.extend(self.design_queue)

        # Check if done
        if self.gen >= self.max_gen:
            return False, self.gen, self.design_log

        # Create next generation
        self.design_queue = self.next_generation(self.design_log)
        population = self.design_log
        self.design_log = []

        return True, self.gen, population

    def get_pareto_front(self):
        """Get current Pareto-optimal designs (feasible only)."""
        feasible = [d for d in self.all_designs
                    if d.get_objectives() and d.get_penalty() == 0]
        if not feasible:
            return []

        ranking, _, _ = rank(feasible, self.spec["outputs"])
        best_rank = max(ranking)
        return [d for d, r in zip(feasible, ranking) if r == best_rank]

    def get_best(self):
        """Get best design (lowest penalty, then best Pareto rank)."""
        evaluated = [d for d in self.all_designs if d.get_objectives()]
        if not evaluated:
            return None

        ranking, _, _ = rank(evaluated, self.spec["outputs"])
        # Lower penalty first, then higher rank (= better Pareto front)
        pairs = list(zip(evaluated, ranking))
        return min(pairs, key=lambda p: (p[0].get_penalty(), -p[1]))[0]


class SSIEAJob:
    """
    Steady-State Island Evolutionary Algorithm.

    5 islands with ring migration, adaptive mutation rate,
    tournament selection (size=8), steady-state replacement.

    Based on Nature Scientific Reports 2025:
    "Multi-objective optimization of daylighting & solar radiation
    for building geometry using SSIEA"
    """

    def __init__(self, job_spec):
        self.spec = job_spec
        opts = job_spec.get("options", {})

        self.num_islands = int(opts.get("num_islands", 5))
        self.pop_per_island = int(opts.get("pop_per_island", 15))
        self.max_gen = int(opts.get("Number of generations", 50))
        self.migration_interval = int(opts.get("migration_interval", 10))
        self.migrants_count = int(opts.get("migrants_count", 2))
        self.tournament_size = int(opts.get("tournament_size", 8))
        self.initial_mutation = float(opts.get("initial_mutation_rate", 0.35))
        self.final_mutation = float(opts.get("final_mutation_rate", 0.10))
        self.penalty_mode = opts.get("penalty_mode", "normalized")  # exp004

        # B4 — Heterogeneous Island: 각 island 마다 crossover strategy 다르게.
        # 'homogeneous' (default, 모두 BLX-α) | 'heterogeneous' (BLX/DE 교차).
        self.island_mode = opts.get("island_mode", "homogeneous")
        # island_strategies: 길이 == num_islands. None이면 자동 생성.
        explicit_strategies = opts.get("island_strategies")
        if explicit_strategies is not None:
            self.island_strategies = list(explicit_strategies)
        elif self.island_mode == "heterogeneous":
            # 절반 BLX, 나머지 DE
            self.island_strategies = ["blx" if i % 2 == 0 else "de"
                                      for i in range(self.num_islands)]
        else:
            self.island_strategies = ["blx"] * self.num_islands

        self.islands: list[list[Design]] = []
        self.gen = 0
        self.des_count = 0
        self.all_designs: list[Design] = []
        self.num_designs = self.num_islands * self.pop_per_island
        self._initialized = False
        self._pareto_cache: list[Design] | None = None
        self._pareto_cache_size = 0  # all_designs length when cache was built

    def init_designs(self):
        """Create initial random population across all islands."""
        designs = []
        for _ in range(self.num_islands):
            island = []
            for j in range(self.pop_per_island):
                des = Design(self.des_count, j, 0)
                des.generate_random(self.spec["inputs"])
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
        if not self._initialized:
            # First step: evaluate all initial designs
            all_initial = [d for island in self.islands for d in island]
            results = evaluate_fn(all_initial)
            for des, outputs in zip(all_initial, results):
                des.set_outputs(outputs, self.spec["outputs"], self.penalty_mode)
            self.all_designs.extend(all_initial)
            self._initialized = True
        else:
            # Steady-state: one offspring per island
            self._evolve_step(evaluate_fn)

        all_pop = [d for island in self.islands for d in island]

        if self.gen >= self.max_gen:
            return False, self.gen, all_pop

        self.gen += 1
        return True, self.gen, all_pop

    def _evolve_step(self, evaluate_fn):
        """One steady-state step: create and evaluate children, replace worst."""
        mutation_rate = self.initial_mutation - (
            (self.initial_mutation - self.final_mutation)
            * self.gen / max(1, self.max_gen)
        )

        children = []
        child_islands = []
        for island_idx, island in enumerate(self.islands):
            parents = self._tournament_select(island, k=2)
            strategy = self.island_strategies[island_idx]  # B4 island 전략
            child = parents[0].crossover(
                parents[1], self.spec["inputs"],
                self.gen, 0, self.des_count,
                strategy=strategy,
            )
            child.mutate(self.spec["inputs"], mutation_rate)
            self.des_count += 1
            children.append(child)
            child_islands.append(island)

        # Batch evaluate all children at once
        results = evaluate_fn(children)
        for child, outputs, island in zip(children, results, child_islands):
            child.set_outputs(outputs, self.spec["outputs"], self.penalty_mode)
            self.all_designs.append(child)

            # Replace worst in island (steady-state)
            worst_idx = self._find_worst(island)
            if self._should_replace(child, island[worst_idx]):
                island[worst_idx] = child

        # Ring migration
        if self.gen > 0 and self.gen % self.migration_interval == 0:
            self._migrate()

    def _fitness_key(self, d: Design):
        """
        Fitness sort key: lower is better.

        Sorts by (penalty, direction-aware objective score).
        Respects Minimize/Maximize from spec outputs.
        """
        if not d.objectives:
            return (d.penalty, float('inf'))
        score = 0.0
        obj_idx = 0
        for out_def in self.spec.get("outputs", []):
            if out_def["type"] != "Objective":
                continue
            if obj_idx >= len(d.objectives):
                break
            val = d.objectives[obj_idx]
            if out_def.get("Goal") == "Maximize":
                score -= val  # negate so lower key = better (higher original)
            else:
                score += val
            obj_idx += 1
        return (d.penalty, score)

    def _find_worst(self, island: list[Design]) -> int:
        """Find index of worst individual (highest fitness key = worst)."""
        return max(range(len(island)), key=lambda j: self._fitness_key(island[j]))

    def _should_replace(self, child: Design, worst: Design) -> bool:
        """Decide if child should replace worst."""
        if child.penalty < worst.penalty:
            return True
        if child.penalty > worst.penalty:
            return False
        # Same penalty — compare objective fitness
        return self._fitness_key(child) < self._fitness_key(worst)

    def _tournament_select(self, island: list[Design], k: int = 2) -> list[Design]:
        """Tournament selection from an island."""
        selected = []
        for _ in range(k):
            candidates = random.sample(island, min(self.tournament_size, len(island)))
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
                    # Copy migrant into destination
                    new_des = Design(self.des_count, 0, self.gen)
                    new_des.set_inputs([list(inp) for inp in migrant.get_inputs()])
                    new_des.objectives = list(migrant.objectives)
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

        feasible = [d for d in self.all_designs
                    if d.objectives and d.penalty == 0]
        if not feasible:
            self._pareto_cache = []
            self._pareto_cache_size = len(self.all_designs)
            return []

        ranking, _, _ = rank(feasible, self.spec["outputs"])
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

        # Fallback: no feasible designs yet, pick least-penalized
        all_evaluated = [d for island in self.islands
                         for d in island if d.objectives]
        if not all_evaluated:
            return None
        return min(all_evaluated, key=self._fitness_key)


# ───────────────────────────────────────────────────────────
# A1 — NSGA-III Job (Phase 1, 2026-05-06)
# ───────────────────────────────────────────────────────────
# Many-objective optimization (4+ objectives) using pymoo NSGA-III.
# Reference-point based selection. SSIEAJob과 동일 인터페이스 (step/init_designs/get_pareto_front).

class NSGA3Job:
    """
    NSGA-III-inspired job (현재는 NSGA-II rank+crowding fallback).

    Code review (2026-05-06):
        실제 das-dennis reference point 알고리즘 미구현 (pymoo 미통합).
        rank+crowding 기반 selection 사용 — NSGA-II 와 거의 동등.
        그럼에도 exp006 4-obj 에서 SSIEA 대비 HV +189~375% 결과는
        *pop_size 차이 + replacement 정책 차이* 에 기인. 진짜 NSGA-III 통합은 follow-up.

    SSIEAJob 대비 차이:
        - pop_size 75 (default), max_gen 50
        - rank+crowding 기반 선택 (vs SSIEA 의 tournament + island migration)
        - 모든 children 한 번에 평가 (batch) — Radiance 환경에서 유리

    Interface는 SSIEAJob과 동일.
    """

    def __init__(self, job_spec):
        self.spec = job_spec
        opts = job_spec.get("options", {})

        self.pop_size = int(opts.get("pop_size", 75))
        self.max_gen = int(opts.get("Number of generations", 50))
        self.n_partitions = int(opts.get("ref_point_partitions", 12))
        self.penalty_mode = opts.get("penalty_mode", "normalized")  # exp004

        # Count objectives from outputs spec
        self.n_obj = sum(1 for o in job_spec.get("outputs", []) if o.get("type") == "Objective")
        if self.n_obj < 2:
            raise ValueError(f"NSGA-III requires ≥2 objectives, got {self.n_obj}")

        self.designs: list[Design] = []
        self.gen = 0
        self.des_count = 0
        self.all_designs: list[Design] = []
        self._initialized = False
        self._pareto_cache: list[Design] | None = None
        self._pareto_cache_size = 0

    def init_designs(self):
        """Create initial random population."""
        designs = []
        for j in range(self.pop_size):
            des = Design(self.des_count, j, 0)
            des.generate_random(self.spec["inputs"])
            self.des_count += 1
            designs.append(des)
        self.designs = designs
        return designs

    def step(self, evaluate_fn):
        """
        One generation step using pymoo NSGA-III.

        First call: evaluate initial population.
        Subsequent: select via reference points, crossover+mutate, evaluate.
        """
        if not self._initialized:
            results = evaluate_fn(self.designs)
            for des, outputs in zip(self.designs, results):
                des.set_outputs(outputs, self.spec["outputs"], self.penalty_mode)
            self.all_designs.extend(self.designs)
            self._initialized = True
        else:
            self._evolve_step(evaluate_fn)

        if self.gen >= self.max_gen:
            return False, self.gen, self.designs

        self.gen += 1
        return True, self.gen, self.designs

    def _evolve_step(self, evaluate_fn):
        """One NSGA-III generation: ref-point selection + crossover + mutate."""
        # Selection: NSGA-III ref-point based (simplified — uses _fitness_key)
        # TODO Phase 1: integrate pymoo NSGA-III when pymoo installed
        # 현재는 간단한 fitness 기반 tournament + crossover/mutate fallback

        ranking, _crowding, _pen = rank(self.designs, self.spec["outputs"])
        # Sort by rank (higher = better Pareto)
        sorted_idx = sorted(range(len(self.designs)),
                            key=lambda i: -ranking[i])

        # Top half = parents
        n_parents = max(2, self.pop_size // 2)
        parents = [self.designs[i] for i in sorted_idx[:n_parents]]

        # Crossover + mutation (mutation_rate = 0.1)
        children = []
        attempts = 0
        max_attempts = self.pop_size * 5
        while len(children) < self.pop_size and attempts < max_attempts:
            attempts += 1
            p1 = random.choice(parents)
            p2 = random.choice(parents)
            child = p1.crossover(p2, self.spec["inputs"], self.gen, len(children), self.des_count)
            child.mutate(self.spec["inputs"], 0.1)
            self.des_count += 1
            children.append(child)

        # Evaluate children
        results = evaluate_fn(children)
        for child, outputs in zip(children, results):
            child.set_outputs(outputs, self.spec["outputs"], self.penalty_mode)

        # NSGA-III replacement: combine parents+children, select pop_size by rank
        combined = self.designs + children
        ranking, crowding, _pen = rank(combined, self.spec["outputs"])
        # Sort: higher rank first, then higher crowding (diversity)
        sorted_combined = sorted(zip(combined, ranking, crowding),
                                 key=lambda t: (-t[1], -t[2]))
        self.designs = [t[0] for t in sorted_combined[:self.pop_size]]
        self.all_designs.extend(children)

    def get_pareto_front(self):
        """Cached Pareto front from all evaluated designs."""
        if self._pareto_cache is not None and self._pareto_cache_size == len(self.all_designs):
            return self._pareto_cache

        feasible = [d for d in self.all_designs if d.objectives and d.penalty == 0]
        if not feasible:
            self._pareto_cache = []
            self._pareto_cache_size = len(self.all_designs)
            return []

        ranking, _, _ = rank(feasible, self.spec["outputs"])
        best_rank = max(ranking)
        result = [d for d, r in zip(feasible, ranking) if r == best_rank]
        self._pareto_cache = result
        self._pareto_cache_size = len(self.all_designs)
        return result
