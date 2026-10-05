"""
GA optimization runner with SSE event publishing.

Manages the optimization loop in a background thread,
publishing progress events via a queue.Queue for SSE streaming.

Two modes:
  - Single algorithm: SSIEAJob for one specific algorithm
  - All algorithms: 10 parallel SSIEAJobs, combined Pareto front
"""

import logging
import queue
import threading
import traceback

from backend.app.modules.design.generation.engine.objects import SSIEAJob
from backend.app.modules.design.generation.engine.utils import rank

logger = logging.getLogger(__name__)


class JobRunner:
    """Runs GA optimization for a single algorithm."""

    def __init__(self, job_spec: dict, evaluate_fn, event_queue: queue.Queue):
        self.job = SSIEAJob(job_spec)
        self.evaluate_fn = evaluate_fn
        self.queue = event_queue
        self.cancelled = False

    def run(self):
        """Synchronous execution (call from threading.Thread)."""
        try:
            self.job.init_designs()
            objectives = [o for o in self.job.spec.get("outputs", [])
                          if o.get("type") == "Objective"]
            self.queue.put({
                "type": "started",
                "max_generations": self.job.max_gen,
                "population_size": self.job.num_designs,
                "objectives": [{"name": o["name"], "goal": o.get("Goal", "Maximize")}
                               for o in objectives],
            })

            while True:
                if self.cancelled:
                    self.queue.put({"type": "cancelled"})
                    return

                prev_count = len(self.job.all_designs)
                cont, gen, population = self.job.step(self.evaluate_fn)
                new_designs = self.job.all_designs[prev_count:]

                pareto = self.job.get_pareto_front()
                pareto_data = [d.get_data() for d in pareto]

                best = self.job.get_best()
                best_data = best.get_data() if best else None

                scatter = [
                    [d.objectives[0], d.objectives[1], d.feasible, d.genNum]
                    for d in new_designs
                    if len(d.objectives) >= 2
                ]

                self.queue.put({
                    "type": "generation",
                    "generation": gen,
                    "population_size": len(population),
                    "pareto_count": len(pareto),
                    "pareto_front": pareto_data,
                    "best": best_data,
                    "feasible_count": sum(1 for d in population if d.feasible),
                    "total_evaluated": len(self.job.all_designs),
                    "scatter": scatter,
                })

                if not cont:
                    break

            if self.cancelled:
                self.queue.put({"type": "cancelled"})
                return
            all_data = [d.get_data() for d in self.job.all_designs]
            pareto = self.job.get_pareto_front()
            pareto_data = [d.get_data() for d in pareto]

            self.queue.put({
                "type": "complete",
                "total_designs": len(all_data),
                "pareto_count": len(pareto_data),
                "pareto_front": pareto_data,
                "generations": self.job.gen,
            })

        except Exception as e:
            if self.cancelled:
                self.queue.put({"type": "cancelled"})
                return
            logger.error(f"JobRunner error: {e}")
            self.queue.put({
                "type": "error",
                "message": str(e),
                "traceback": traceback.format_exc(),
            })

    def cancel(self):
        """Signal the runner to stop after current generation."""
        self.cancelled = True


class MultiAlgoRunner:
    """
    Runs ALL algorithms in parallel, combining results into a single
    Pareto front. Each algorithm gets its own SSIEA with reduced budget.

    SSE events are interleaved from all algorithms with algorithm tags.
    """

    def __init__(self, algo_specs: dict, evaluate_fns: dict,
                 event_queue: queue.Queue):
        """
        Args:
            algo_specs: {algorithm_name: job_spec, ...}
            evaluate_fns: {algorithm_name: evaluate_fn, ...}
            event_queue: shared SSE event queue
        """
        self.algo_specs = algo_specs
        self.evaluate_fns = evaluate_fns
        self.queue = event_queue
        self.cancelled = False
        self.jobs: dict[str, SSIEAJob] = {}
        self._lock = threading.Lock()

    def run(self):
        """Run all algorithms in parallel threads, merge results."""
        try:
            algorithms = list(self.algo_specs.keys())
            total_max_gen = 0

            # Initialize all jobs
            for algo in algorithms:
                spec = self.algo_specs[algo]
                job = SSIEAJob(spec)
                job.init_designs()
                self.jobs[algo] = job
                total_max_gen = max(total_max_gen, job.max_gen)

            # Extract objectives from first spec (same for all)
            first_spec = list(self.algo_specs.values())[0]
            objectives = [o for o in first_spec.get("outputs", [])
                          if o.get("type") == "Objective"]

            self.queue.put({
                "type": "started",
                "max_generations": total_max_gen,
                "population_size": sum(j.num_designs for j in self.jobs.values()),
                "objectives": [{"name": o["name"], "goal": o.get("Goal", "Maximize")}
                               for o in objectives],
                "algorithms": algorithms,
            })

            # Run all algorithms in parallel threads
            errors: dict[str, str] = {}
            threads = []

            for algo in algorithms:
                t = threading.Thread(
                    target=self._run_single,
                    args=(algo, errors),
                    daemon=True,
                )
                threads.append(t)
                t.start()

            # Track how many designs we've already sent as scatter
            scatter_cursor: dict[str, int] = {a: 0 for a in algorithms}

            # Poll progress from all jobs until all complete
            gen_counter = 0
            while any(t.is_alive() for t in threads):
                if self.cancelled:
                    self.queue.put({"type": "cancelled"})
                    return

                threading.Event().wait(0.5)  # 500ms poll interval
                gen_counter += 1

                # Collect combined stats
                total_evaluated = 0
                total_feasible = 0
                algo_progress = {}

                for algo, job in self.jobs.items():
                    total_evaluated += len(job.all_designs)
                    total_feasible += sum(
                        1 for d in job.all_designs if d.feasible
                    )
                    algo_progress[algo] = {
                        "gen": job.gen,
                        "max_gen": job.max_gen,
                        "designs": len(job.all_designs),
                    }

                # Emit progress every ~2 seconds (every 4th poll)
                if gen_counter % 4 == 0:
                    combined_pareto = self._combined_pareto(first_spec)
                    pareto_data = [d["data"] for d in combined_pareto]
                    best = pareto_data[0] if pareto_data else None

                    # Delta scatter: only NEW designs since last event
                    scatter = []
                    for algo, job in self.jobs.items():
                        prev = scatter_cursor[algo]
                        current = len(job.all_designs)
                        for d in job.all_designs[prev:current]:
                            if len(d.objectives) >= 2:
                                scatter.append([
                                    d.objectives[0], d.objectives[1],
                                    d.feasible, d.genNum,
                                ])
                        scatter_cursor[algo] = current

                    avg_gen = sum(
                        p["gen"] for p in algo_progress.values()
                    ) // max(1, len(algo_progress))

                    self.queue.put({
                        "type": "generation",
                        "generation": avg_gen,
                        "max_generations": total_max_gen,
                        "pareto_count": len(pareto_data),
                        "pareto_front": pareto_data,
                        "best": best,
                        "feasible_count": total_feasible,
                        "total_evaluated": total_evaluated,
                        "scatter": scatter,
                        "algo_progress": algo_progress,
                    })

            # Wait for all threads
            for t in threads:
                t.join(timeout=5)

            if self.cancelled:
                self.queue.put({"type": "cancelled"})
                return
            if errors:
                self.queue.put({
                    "type": "error",
                    "message": "Algorithm execution failed: " + "; ".join(
                        f"{algo}: {error}" for algo, error in sorted(errors.items())
                    ),
                    "algorithm_errors": dict(errors),
                })
                return

            # Final combined Pareto
            combined_pareto = self._combined_pareto(first_spec)
            pareto_data = [d["data"] for d in combined_pareto]
            total_designs = sum(len(j.all_designs) for j in self.jobs.values())

            self.queue.put({
                "type": "complete",
                "total_designs": total_designs,
                "pareto_count": len(pareto_data),
                "pareto_front": pareto_data,
                "generations": total_max_gen,
                "algorithms": algorithms,
            })

        except Exception as e:
            if self.cancelled:
                self.queue.put({"type": "cancelled"})
                return
            logger.error(f"MultiAlgoRunner error: {e}")
            self.queue.put({
                "type": "error",
                "message": str(e),
                "traceback": traceback.format_exc(),
            })

    def _run_single(self, algo: str, errors: dict):
        """Run a single algorithm's SSIEA to completion.

        No lock needed here — each job has its own independent state.
        Worker errors are shared with the parent after all threads finish.
        """
        try:
            job = self.jobs[algo]
            evaluate_fn = self.evaluate_fns[algo]

            while True:
                if self.cancelled:
                    return

                # No lock: each SSIEAJob is independent (own population, own designs)
                cont, gen, population = job.step(evaluate_fn)

                if not cont:
                    break

            logger.info(f"Algorithm {algo} complete: {len(job.all_designs)} designs, gen {job.gen}")

        except Exception as e:
            with self._lock:
                errors[algo] = f"{type(e).__name__}: {e}"
            logger.error(f"Algorithm {algo} failed: {e}")

    def _combined_pareto(self, ref_spec: dict) -> list[dict]:
        """
        Compute combined Pareto front across all algorithms.

        Returns list of {data: design_data, algorithm: str} dicts.
        Lock protects against concurrent reads while _run_single appends.
        """
        all_feasible = []
        with self._lock:
            for algo, job in self.jobs.items():
                for d in list(job.all_designs):  # snapshot via list()
                    if d.objectives and d.penalty == 0:
                        all_feasible.append((algo, d))

        if not all_feasible:
            return []

        outputs_def = ref_spec.get("outputs", [])
        feasible_designs = [d for _, d in all_feasible]
        ranking, _, _ = rank(feasible_designs, outputs_def)
        best_rank = max(ranking)

        result = []
        for (algo, d), r in zip(all_feasible, ranking):
            if r == best_rank:
                data = d.get_data()
                data["algorithm"] = algo
                data["uid"] = f"{algo}:{d.id}"
                result.append({"data": data, "algorithm": data["algorithm"]})

        return result

    def cancel(self):
        self.cancelled = True
