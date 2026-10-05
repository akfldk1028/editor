'use client'

import { type ReactNode, useEffect } from 'react'

export function ClientBootstrap({
  children,
  enableDevDiagnostics,
}: {
  children: ReactNode
  enableDevDiagnostics: boolean
}) {
  useEffect(() => {
    if (!enableDevDiagnostics) return
    import('react-scan').then(({ scan }) => scan({ enabled: true }))
  }, [enableDevDiagnostics])
  return children
}
