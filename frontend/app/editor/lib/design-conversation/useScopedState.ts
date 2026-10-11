'use client'

import { useCallback, useRef, useState, type SetStateAction } from 'react'

export function scopedValue<T>(stored: { scope: string; value: T }, scope: string, initial: T): T {
  return stored.scope === scope ? stored.value : initial
}

export function useScopedState<T>(scope: string, initial: T) {
  const initialValue = useRef(initial).current
  const [stored, setStored] = useState({ scope, value: initial })
  const setValue = useCallback((next: SetStateAction<T>) => {
    setStored((previous) => ({ scope, value: typeof next === 'function'
      ? (next as (value: T) => T)(scopedValue(previous, scope, initialValue)) : next }))
  }, [scope, initialValue])
  return [scopedValue(stored, scope, initialValue), setValue] as const
}
