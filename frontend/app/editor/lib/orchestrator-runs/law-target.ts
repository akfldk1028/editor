/** Where 법규 보기 lands: the law artifact on this site, under the run's binding. */
export interface LawTarget {
  pnu: string
  address?: string
  project?: string
}

export const lawParams = (target: LawTarget, tab: string) => ({ pnu: target.pnu, tab, ...(target.address ? { address: target.address } : {}), ...(target.project ? { project: target.project } : {}) })
