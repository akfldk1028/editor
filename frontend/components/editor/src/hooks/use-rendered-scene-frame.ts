'use client'

import { emitter, sceneRegistry, useScene } from '@pascal-app/core'
import { SCENE_LAYER } from '@pascal-app/viewer'
import { type CameraControlsImpl, useProgress } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useRef, type RefObject } from 'react'
import { Layers } from 'three'
import { renderedSceneBounds } from '../lib/rendered-scene-bounds'

const sceneLayers = new Layers()
sceneLayers.set(SCENE_LAYER)

export function useRenderedSceneFrame(controls: RefObject<CameraControlsImpl | null>, disabled: boolean) {
  const pending = useRef(true)
  const settled = useRef(0)
  const rootIdentity = useRef('')

  useEffect(() => {
    const cancel = () => { pending.current = false }
    emitter.on('camera-controls:interaction-start', cancel)
    emitter.on('camera-controls:view', cancel)
    emitter.on('camera-controls:apply-pose', cancel)
    return () => {
      emitter.off('camera-controls:interaction-start', cancel)
      emitter.off('camera-controls:view', cancel)
      emitter.off('camera-controls:apply-pose', cancel)
    }
  }, [])

  useFrame((_, delta) => {
    const state = useScene.getState()
    const identity = state.rootNodeIds.join('|')
    if (identity !== rootIdentity.current) {
      rootIdentity.current = identity
      pending.current = true
      settled.current = 0
    }
    if (!pending.current || disabled || !controls.current || !identity) return
    if (useProgress.getState().active) { settled.current = 0; return }
    // URL-backed renderers mount their group before the asynchronous asset exists.
    for (const node of Object.values(state.nodes)) {
      if ('url' in node && node.url && node.visible !== false) {
        const object = sceneRegistry.nodes.get(node.id)
        if (object?.visible && !renderedSceneBounds([object], sceneLayers)) return
      }
    }
    const roots = state.rootNodeIds.flatMap(id => {
      const object = sceneRegistry.nodes.get(id)
      return object ? [object] : []
    })
    const bounds = renderedSceneBounds(roots, sceneLayers)
    if (!bounds) return
    settled.current += Math.min(delta, 0.05)
    if (settled.current < 0.2) return
    pending.current = false
    const control = controls.current
    // Large imported models must not be cropped by the default 100 m orbit limit.
    control.maxDistance = Math.max(control.maxDistance, bounds.min.distanceTo(bounds.max) * 4)
    void control.fitToBox(bounds, true, { paddingLeft: 2, paddingRight: 2, paddingTop: 2, paddingBottom: 2 })
  })
}
