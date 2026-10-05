'use client'

import { usePathname } from 'next/navigation'
import { isProductRouteActive, productRoutes } from './product-routes'
import './product-navigation.css'

export function ProductNavigation() {
  const pathname = usePathname()
  return <nav aria-label="제품 작업 공간" className="editor-product-navigation">
    {productRoutes.map(({href, label}) => <a key={href}
      href={`${process.env.NEXT_PUBLIC_BASE_PATH || ''}${href}`}
      aria-current={isProductRouteActive(href, pathname) ? 'page' : undefined}
    >{label}</a>)}
  </nav>
}
