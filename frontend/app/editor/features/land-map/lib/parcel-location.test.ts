import { afterAll, afterEach, expect, spyOn, test } from 'bun:test';
import { locateParcel } from './land-api-client';

const fetchSpy = spyOn(globalThis, 'fetch');
afterEach(() => fetchSpy.mockReset());
afterAll(() => fetchSpy.mockRestore());
const geometry = { type: 'Polygon', coordinates: [[[127, 37], [127.01, 37], [127.01, 37.01], [127, 37]]] };

test('PNU search obtains the parcel boundary instead of leaving the map on the previous parcel', async () => {
  const controller = new AbortController();
  fetchSpy.mockResolvedValue(Response.json({ success: true, geometry }));
  expect((await locateParcel(' 1111010100100010000 ', controller.signal)).geometry).toEqual(geometry);
  const [url, options] = fetchSpy.mock.calls[0]!;
  expect(String(url)).toEndWith('/api/v1/land/parcel-geometry');
  expect(JSON.parse(String(options?.body))).toEqual({ pnu: '1111010100100010000' });
  expect(options?.signal).toBe(controller.signal);
});

test('an address resolved without PNU still obtains the parcel from its coordinates', async () => {
  fetchSpy.mockResolvedValueOnce(Response.json({ success: true, pnu: null, coordinates: { x: 127, y: 37 } }))
    .mockResolvedValueOnce(Response.json({ success: true, pnu: '1111010100100010000', geometry }));
  expect(await locateParcel('검증용 주소')).toEqual({ geometry, coordinates: { x: 127, y: 37 } });
});

test('missing geometry is reported instead of being treated as a successful location', async () => {
  fetchSpy.mockResolvedValue(Response.json({ success: false, geometry: null, error: 'Parcel lookup is not configured' }));
  await expect(locateParcel('1111010100100010000')).rejects.toThrow('Parcel lookup is not configured');
});
