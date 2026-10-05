import { test, expect } from 'bun:test'
import { isPlatformDesignOperation } from './platform-design-operation'

test('project design proxy allows only existing bounded operations', () => {
  const root = 'projects/native-binding/design/'
  for (const path of ['archive/jobs','jobs','jobs/source/job/results/7','selection/mass','archive/executions',
    'executions/hash/artifacts/hash/download','native-jobs/job/attempts/attempt/events','native-jobs/job/attempts/attempt/result'])
    expect(isPlatformDesignOperation('GET', root + path)).toBe(true)
  for (const path of ['jobs','selection','executions','native-jobs','native-jobs/job/attempts','native-jobs/job/attempts/attempt/cancel'])
    expect(isPlatformDesignOperation('POST', root + path)).toBe(true)
  for (const path of ['selection/mass','archive/jobs','native-jobs/job/delete','executions/hash/artifacts/hash/download'])
    expect(isPlatformDesignOperation('POST', root + path)).toBe(false)
  for (const path of ['projects/p/design/../../agents','projects/p/design/jobs/a/b/results/-1','design/jobs','projects/p/design/jobs/a/b/results/1/extra'])
    expect(isPlatformDesignOperation('GET', path)).toBe(false)
  expect(isPlatformDesignOperation('DELETE', root + 'jobs')).toBe(false)
})
