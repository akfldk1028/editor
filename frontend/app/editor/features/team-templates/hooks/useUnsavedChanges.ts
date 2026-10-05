import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

type NavigationEvent = Event & { navigationType: string; destination: { url: string; key: string } }
type BrowserNavigation = EventTarget & { traverseTo: (key: string) => unknown }

export function useUnsavedChanges(dirty: boolean) {
  const router = useRouter()
  const [pending, setPending] = useState<{ url: string; key?: string } | null>(null)
  const allowNext = useRef(false)
  useEffect(() => {
    if (!dirty) return
    const onClick = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.ctrlKey ||
        event.metaKey ||
        event.shiftKey ||
        event.altKey
      )
        return
      const anchor = (event.target as Element).closest?.('a[href]') as HTMLAnchorElement | null
      if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return
      const url = new URL(anchor.href)
      if (url.origin !== location.origin || url.href === location.href) return
      event.preventDefault()
      event.stopPropagation()
      setPending({ url: url.pathname + url.search + url.hash })
    }
    const navigation = (window as unknown as { navigation?: BrowserNavigation }).navigation
    const onNavigate = (event: Event) => {
      const next = event as NavigationEvent
      if (allowNext.current) {
        allowNext.current = false
        return
      }
      if (next.navigationType !== 'traverse' || !event.cancelable) return
      event.preventDefault()
      setPending({ url: next.destination.url, key: next.destination.key })
    }
    document.addEventListener('click', onClick, true)
    navigation?.addEventListener('navigate', onNavigate)
    return () => {
      document.removeEventListener('click', onClick, true)
      navigation?.removeEventListener('navigate', onNavigate)
    }
  }, [dirty])
  return {
    state: pending ? 'blocked' : 'unblocked',
    reset: () => setPending(null),
    proceed: () => {
      if (!pending) return
      const navigation = (window as unknown as { navigation?: BrowserNavigation }).navigation
      if (pending.key && navigation) {
        allowNext.current = true
        navigation.traverseTo(pending.key)
      } else router.push(pending.url)
      setPending(null)
    },
  }
}
