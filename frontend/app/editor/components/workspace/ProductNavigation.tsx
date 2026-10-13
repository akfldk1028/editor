'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { isProductRouteActive, productRoutes } from './product-routes'
import './product-navigation.css'

// Next's <Link> moves inside the app (and prefetches) instead of reloading the whole page; it adds the base path itself.
export function ProductNavigation() {
  const pathname = usePathname()
  return <nav aria-label="제품 작업 공간" className="editor-product-navigation">
    {productRoutes.map(({href, label}) => <Link key={href}
      href={href}
      aria-current={isProductRouteActive(href, pathname) ? 'page' : undefined}
    >{label}</Link>)}
  </nav>
}
