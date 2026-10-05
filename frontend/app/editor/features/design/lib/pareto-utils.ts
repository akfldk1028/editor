import { requiredValue } from './required-value';
import type { DesignData } from './types';

/** Check if design A dominates design B (all objectives better or equal, at least one strictly better) */
function dominates(a: number[], b: number[], goals: ('Minimize' | 'Maximize')[]): boolean {
  let dominated = true;
  let strictlyBetter = false;
  for (let i = 0; i < a.length; i++) {
    const fac = goals[i] === 'Minimize' ? 1 : -1;
    if (fac * requiredValue(a[i]) > fac * requiredValue(b[i])) {
      dominated = false;
      break;
    }
    if (fac * requiredValue(a[i]) < fac * requiredValue(b[i])) {
      strictlyBetter = true;
    }
  }
  return dominated && strictlyBetter;
}

/** Extract Pareto front from a set of designs */
export function getParetoFront(
  designs: DesignData[],
  goals: ('Minimize' | 'Maximize')[] = ['Maximize', 'Maximize'],
): DesignData[] {
  const feasible = designs.filter(d => d.feasible && d.objectives.length >= goals.length);
  const front: DesignData[] = [];

  for (const d of feasible) {
    const isDominated = feasible.some(
      other => other !== d && dominates(other.objectives, d.objectives, goals),
    );
    if (!isDominated) {
      front.push(d);
    }
  }

  return front;
}

/** Normalize values to 0-1 range */
export function normalize(values: number[]): number[] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (max === min) return values.map(() => 0.5);
  return values.map(v => (v - min) / (max - min));
}
