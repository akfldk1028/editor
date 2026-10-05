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
    if (process.env.NEXT_PUBLIC_PASCAL_DEV_DIAGNOSTICS === '1') {
      if (enableDevDiagnostics) import('react-scan').then(({ scan }) => scan({ enabled: true }))
    }
  }, [enableDevDiagnostics])
  return children
}
