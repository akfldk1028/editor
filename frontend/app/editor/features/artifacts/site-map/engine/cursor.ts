/**
 * The map cursor as a data attribute on the engine's element; site-map.css
 * maps it to pointer / grabbing / progress over the provider's own cursors.
 */
export function mapCursor(element: HTMLElement) {
  let busy = false
  let dragging = false
  const apply = () => { element.dataset.cursor = busy ? 'busy' : dragging ? 'drag' : 'pick' }
  apply()
  return {
    busy(value: boolean) { busy = value; apply() },
    dragging(value: boolean) { dragging = value; apply() },
  }
}
