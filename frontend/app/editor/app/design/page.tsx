'use client'

import dynamic from 'next/dynamic'

const DesignPage = dynamic(() => import('@/features/design/DesignPage'), { ssr: false })

export default function Page() { return <DesignPage /> }
