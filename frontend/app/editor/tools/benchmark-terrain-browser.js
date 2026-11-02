async (page) => {
  const existing = page.context().pages().find(p => p.url().includes('3003/dwg'));
  if (!existing) throw new Error('Open the 684-1 /dwg page first');
  const p = await page.context().newPage();
  await p.goto(existing.url(), { waitUntil: 'domcontentloaded' });
  await p.addInitScript(() => {
    performance.setResourceTimingBufferSize(10000);
    const openCache = caches.open.bind(caches);
    caches.open = name => name === 'world-source-v1-terrain' ? Promise.reject(new Error('cold terrain benchmark')) : openCache(name);
    const m = window.__terrainBench = { longTasks: [], tiles: [], viewerAt: null, focusTileAt: null, focusRenderedAt: null };
    new PerformanceObserver(list => { for (const e of list.getEntries()) m.longTasks.push({ start: e.startTime, duration: e.duration }); }).observe({ type: 'longtask', buffered: true });
    let current;
    const seen = new WeakSet();
    Object.defineProperty(window, 'Cesium', { configurable: true, get: () => current, set: C => {
      current = C;
      if (!C || seen.has(C) || !C.Viewer || !C.CustomHeightmapTerrainProvider) return;
      seen.add(C);
      const Provider = C.CustomHeightmapTerrainProvider;
      const wrappedProvider = new Proxy(Provider, { construct(Target, args) {
        const options = { ...args[0] }, original = options.callback;
        options.callback = (x, y, z) => {
          const at = performance.now(), result = original(x, y, z);
          if (result === undefined) return result;
          return Promise.resolve(result).then(h => {
            const width = 180 / 2 ** z, west = x * width - 180, north = 90 - y * width;
            const focus = west <= 127.1081 && 127.1081 <= west + width && north - width <= 37.73002 && 37.73002 <= north;
            const variable = h && Math.max(...h) - Math.min(...h) > .01;
            m.tiles.push({ z, x, y, at, duration: performance.now() - at, focus, variable });
            if (focus && variable && z >= 12 && m.focusTileAt === null) m.focusTileAt = performance.now();
            return h;
          });
        };
        return new Target(options);
      }});
      const wrappedViewer = new Proxy(C.Viewer, { construct(Target, args) {
        const viewer = new Target(...args);
        m.viewerAt = performance.now();
        window.__terrainBenchViewer = viewer;
        viewer.scene.postRender.addEventListener(() => {
          if (m.focusTileAt === null || m.focusRenderedAt !== null) return;
          const point = C.Cartographic.fromDegrees(127.1081, 37.73002);
          const tiles = viewer.scene.globe._surface?._tilesToRender || [];
          if (tiles.some(t => t.level >= 12 && C.Rectangle.contains(t.rectangle, point)) && Number.isFinite(viewer.scene.globe.getHeight(point))) m.focusRenderedAt = performance.now();
        });
        return viewer;
      }});
      current = new Proxy(C, { get(target,key) { return key === 'Viewer' ? wrappedViewer : key === 'CustomHeightmapTerrainProvider' ? wrappedProvider : Reflect.get(target,key); } });
    }});
  });
  await p.evaluate(async () => { await caches.delete('world-source-v1-terrain'); });
  const cdp = await p.context().newCDPSession(p);
  await cdp.send('Network.enable');
  await cdp.send('Network.clearBrowserCache');
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
  await p.reload({ waitUntil: 'domcontentloaded' });
  await p.waitForTimeout(2500);
  if (!await p.evaluate(() => window.__terrainBench?.viewerAt)) await p.getByRole('button', { name: '3D', exact: true }).click();
  await p.waitForTimeout(22000);
  const result = await p.evaluate(() => {
    const m = window.__terrainBench, start = m.viewerAt ?? 0;
    const tasks = m.longTasks.filter(e => e.start >= start && e.start < start + 20000);
    return { viewerAt: m.viewerAt, firstFocusTileMs: m.focusTileAt === null ? null : m.focusTileAt - start,
      firstGroundRenderedMs: m.focusRenderedAt === null ? null : m.focusRenderedAt - start,
      navigationToGroundMs: m.focusRenderedAt, longTask20sMs: tasks.reduce((s,e)=>s+e.duration,0), longTasks: tasks.length,
      tileRequests: m.tiles.length, focusTiles: m.tiles.filter(t=>t.focus), resources: performance.getEntriesByType('resource')
        .filter(e=>/terrain-heights|terrain-revision|world-terrain|world-buildings|releases\/current.json|\.pmtiles/.test(e.name)).map(e=>({url:e.name,duration:e.duration,bytes:e.transferSize})),
      siteVisible: document.body.innerText.includes('684-1') };
  });
  await cdp.send('Network.setCacheDisabled', { cacheDisabled: false });
  await cdp.detach();
  await p.close();
  return result;
}
