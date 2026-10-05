'use client'

import { type ReactNode, useEffect } from 'react'
import { ProductNavigation } from '@/components/workspace/ProductNavigation'

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
  return <><ProductNavigation /><div className="editor-product-content">{children}</div></>
}
