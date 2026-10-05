'use client'

import dynamic from 'next/dynamic'

const BookLanguagePage = dynamic(() => import('@/features/design/BookLanguagePage'), { ssr: false })

export default function Page() { return <BookLanguagePage /> }
