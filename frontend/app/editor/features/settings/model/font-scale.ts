import { useTheme } from '@/components/workspace/theme/useTheme'
const reset = () => useTheme.getState().setScale(1)
export function useFontScaleStore<T>(
  selector: (state: { scale: number; setScale: (value: number) => void; reset: () => void }) => T,
): T {
  return useTheme((state) => selector({ scale: state.scale, setScale: state.setScale, reset }))
}
