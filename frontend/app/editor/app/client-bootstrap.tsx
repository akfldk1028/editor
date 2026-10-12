'use client'

import { usePathname } from 'next/navigation'
import { type ReactNode, useEffect } from 'react'
import { ProductNavigation } from '@/components/workspace/ProductNavigation'

/** The /dwg shell is the product and carries its own sidebar; the old product header stays only on the legacy pages until each is folded in. */
const standalone = (pathname: string | null) => pathname === '/dwg' || pathname?.startsWith('/dwg/') === true

export function ClientBootstrap({
  children,
  enableDevDiagnostics,
}: {
  children: ReactNode
  enableDevDiagnostics: boolean
}) {
  const pathname = usePathname()
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_PASCAL_DEV_DIAGNOSTICS === '1') {
      if (enableDevDiagnostics) import('react-scan').then(({ scan }) => scan({ enabled: true }))
    }
  }, [enableDevDiagnostics])
  if (standalone(pathname)) return <div className="editor-standalone">{children}</div>
  return <><ProductNavigation /><div className="editor-product-content">{children}</div></>
}
