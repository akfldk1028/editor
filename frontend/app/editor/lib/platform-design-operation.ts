export function isPlatformDesignOperation(method: string, path: string): boolean {
  const id = '[A-Za-z0-9_-]{1,200}'
  const prefix = `projects/${id}/design/`
  const reads = `archive/(jobs|executions)|jobs(/${id}/${id}(/results(/[0-9]+)?)?)?|selection(/mass)?|executions(/${id}(/artifacts/${id}(/download)?)?)?|native-jobs(/${id}(/attempts(/${id}(/(events|result))?)?)?)?`
  const writes = `jobs|selection|executions|native-jobs(/${id}/attempts(/${id}/cancel)?)?`
  return (method === 'GET' || method === 'POST') && new RegExp(`^${prefix}(${method === 'GET' ? reads : writes})$`).test(path)
}
