/* eslint-disable @typescript-eslint/no-explicit-any */

export function attachTexturedGltfModel({
  viewer,
  Cesium,
  entityPrefix,
  designId,
  ring,
  groundH,
  gltfUrl,
  debug,
}: {
  viewer: any;
  Cesium: any;
  entityPrefix: string;
  designId: number;
  ring: number[][];
  groundH: number;
  gltfUrl: string;
  debug: { gltfStatus: string };
}) {
  const origin = ring[0];
  if (!origin || origin.length < 2) {
    debug.gltfStatus = 'missing-origin';
    return;
  }
  const tokenKey = '__arrMassGltfToken';
  const token = ((viewer as any)[tokenKey] || 0) + 1;
  (viewer as any)[tokenKey] = token;

  const originCartesian = Cesium.Cartesian3.fromDegrees(origin[0], origin[1], groundH);
  const modelMatrix = Cesium.Transforms.eastNorthUpToFixedFrame(originCartesian);
  const primitives = viewer.scene?.primitives;
  if (!primitives) {
    debug.gltfStatus = 'missing-primitives';
    return;
  }

  const markAndAdd = (model: any) => {
    if ((viewer as any)[tokenKey] !== token) {
      model?.destroy?.();
      return;
    }
    model.__arrEntityPrefix = entityPrefix;
    model.__arrDesignId = designId;
    primitives.add(model);
    debug.gltfStatus = 'added';
    try {
      viewer.scene?.requestRender?.();
    } catch { /* ignore */ }
  };

  try {
    if (typeof Cesium.Model?.fromGltfAsync === 'function') {
      debug.gltfStatus = 'loading-async';
      Cesium.Model.fromGltfAsync({
        url: gltfUrl,
        modelMatrix,
        scale: 1.0,
      }).then(markAndAdd).catch((error: unknown) => {
        debug.gltfStatus = `error:${error instanceof Error ? error.message : 'load-failed'}`;
      });
    } else if (typeof Cesium.Model?.fromGltf === 'function') {
      debug.gltfStatus = 'loading-sync';
      markAndAdd(Cesium.Model.fromGltf({
        url: gltfUrl,
        modelMatrix,
        scale: 1.0,
      }));
    } else {
      debug.gltfStatus = 'missing-model-api';
    }
  } catch (error) {
    debug.gltfStatus = `error:${error instanceof Error ? error.message : 'load-failed'}`;
  }
}

export function clearMassEntities(viewer: any, entityPrefix: string) {
  const toRemove: any[] = [];
  for (const e of viewer.entities.values) {
    if (typeof e.id === 'string' && e.id.startsWith(entityPrefix)) {
      toRemove.push(e);
    }
  }
  for (const e of toRemove) viewer.entities.remove(e);
  clearMassPrimitives(viewer, entityPrefix);
  try {
    viewer.scene?.requestRender?.();
  } catch { /* ignore */ }
}

function clearMassPrimitives(viewer: any, entityPrefix: string) {
  const primitives = viewer.scene?.primitives;
  if (!primitives || typeof primitives.length !== 'number' || typeof primitives.get !== 'function') return;
  for (let i = primitives.length - 1; i >= 0; i--) {
    const primitive = primitives.get(i);
    if (primitive?.__arrEntityPrefix === entityPrefix) {
      primitives.remove(primitive);
    }
  }
}
