import math
from shapely.geometry import LineString, Polygon
from ..projection import wgs84_to_utm as _wgs_to_utm
from backend.app.adapters.elevation import ElevationFetchError
from .settings import DatumSettings


class DatumCalculator:
    MAX_SAMPLES = 10000

    def __init__(self, fetch_elevations, settings=None):
        self.fetch_elevations = fetch_elevations
        self.settings = settings if settings is not None else DatumSettings()

    def _fetch(self, points):
        self._check_sample_budget(len(points))
        if not points:
            raise ElevationFetchError('No elevation samples')
        values = self.fetch_elevations(points)
        if not isinstance(values, (list, tuple)) or len(values) != len(points):
            raise ElevationFetchError('Elevation sample count mismatch')
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            raise ElevationFetchError('Invalid elevation sample')
        return list(values)

    def _check_sample_budget(self, count):
        if not math.isfinite(count) or count > self.MAX_SAMPLES:
            raise ElevationFetchError('Elevation sample budget exceeded')

    def _denoise_median_filter(self, values: list[float], window: int=3) -> list[float]:
        """1D circular median filter (polygon ring 가정).

        각 점을 자신과 좌우 (window-1)/2 이웃의 중앙값으로 대체. 90m DEM 격자 인접
        셀 차이는 spike 형태(한 점만 튐)라 median이 흡수하고, 실제 경사면(점진적
        증가)은 그대로 유지된다.

        window<2 또는 len(values)<window면 원본 그대로 반환.
        """
        if window < 2 or len(values) < window:
            return list(values)
        n = len(values)
        radius = window // 2
        out: list[float] = []
        for i in range(n):
            nb = sorted((values[(i + k - radius) % n] for k in range(window)))
            out.append(nb[len(nb) // 2])
        return out

    def parcel_datum_119(self, parcel_wgs: Polygon) -> tuple[float, list[dict]]:
        """
        §119②: 외벽 둘레 가중평균 datum.

        각 polygon edge에서 표고를 sample → segment 길이 가중평균.

        `config.DATUM_EDGE_SUBSAMPLE=true` (default) 면 길이 > THRESHOLD_M(10m)인 edge를
        STEP_M(5m) 간격 sub-segment로 분할하고 각 sub-segment 중점에서 sample. §119②
        "수평거리에 따라 가중평균"의 수치적분 정밀도가 향상됨 (큰 필지에서 edge 1점
        대표의 손실 제거).

        `config.DATUM_MEDIAN_FILTER=true` (default) 면 fetch 직후 ring 형태로 median
        filter 적용 (window=3). 90m DEM 격자 인접 셀 spike noise 흡수, 실제 경사 유지.

        Args:
            parcel_wgs: 필지 polygon (WGS84 lng,lat)

        Returns:
            (datum_m, segments)
            segments[i] = {"edge_idx", "length_m", "midpoint_lng", "midpoint_lat",
                           "midpoint_elev_m"}
            sub-sample 활성시 같은 edge_idx가 여러 segment에 나타날 수 있음.
        """
        parcel_utm = _wgs_to_utm(parcel_wgs)
        coords_wgs = list(parcel_wgs.exterior.coords)
        coords_utm = list(parcel_utm.exterior.coords)
        use_subsample = self.settings.edge_subsample
        sub_threshold = self.settings.edge_subsample_threshold_m
        sub_step = self.settings.edge_subsample_step_m
        use_median = self.settings.median_filter
        median_window = self.settings.median_filter_window
        midpoints_wgs: list[tuple[float, float]] = []
        sample_lengths_m: list[float] = []
        sample_midpoints_lnglat: list[tuple[float, float]] = []
        sample_edge_indices: list[int] = []
        for i in range(len(coords_utm) - 1):
            x1, y1 = (coords_utm[i][0], coords_utm[i][1])
            x2, y2 = (coords_utm[i + 1][0], coords_utm[i + 1][1])
            L_total = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if not math.isfinite(L_total):
                raise ElevationFetchError('Invalid projected edge length')
            if L_total < 0.1:
                continue
            lng1, lat1 = (coords_wgs[i][0], coords_wgs[i][1])
            lng2, lat2 = (coords_wgs[i + 1][0], coords_wgs[i + 1][1])
            if not use_subsample or L_total <= sub_threshold:
                self._check_sample_budget(len(midpoints_wgs) + 1)
                mlng = (lng1 + lng2) / 2.0
                mlat = (lat1 + lat2) / 2.0
                sample_lengths_m.append(L_total)
                sample_midpoints_lnglat.append((mlng, mlat))
                midpoints_wgs.append((mlat, mlng))
                sample_edge_indices.append(i)
            else:
                self._check_sample_budget(len(midpoints_wgs) + L_total / sub_step)
                n_sub = max(2, int(round(L_total / sub_step)))
                self._check_sample_budget(len(midpoints_wgs) + n_sub)
                seg_len = L_total / n_sub
                for k in range(n_sub):
                    t = (k + 0.5) / n_sub
                    slng = lng1 + (lng2 - lng1) * t
                    slat = lat1 + (lat2 - lat1) * t
                    sample_lengths_m.append(seg_len)
                    sample_midpoints_lnglat.append((slng, slat))
                    midpoints_wgs.append((slat, slng))
                    sample_edge_indices.append(i)
        if not sample_lengths_m:
            raise ValueError('parcel_datum_119: polygon has no usable edges (all edges < 0.1m or empty). Provide a valid Polygon.')
        elevations = self._fetch(midpoints_wgs)
        if use_median:
            elevations = self._denoise_median_filter(list(elevations), window=median_window)
        total_length = sum(sample_lengths_m)
        if total_length <= 0:
            return (0.0, [])
        weighted_sum = sum((L * h for L, h in zip(sample_lengths_m, elevations)))
        datum_m = weighted_sum / total_length
        segments = [{'edge_idx': ei, 'length_m': round(L, 3), 'midpoint_lng': round(mp[0], 6), 'midpoint_lat': round(mp[1], 6), 'midpoint_elev_m': round(h, 3)} for ei, L, mp, h in zip(sample_edge_indices, sample_lengths_m, sample_midpoints_lnglat, elevations)]
        return (datum_m, segments)

    def road_datum_119(self, road_centerline_wgs: LineString, sample_step_m: float=5.0) -> tuple[float, list[dict]]:
        """
        §119① 5호 가목: 전면도로 중심선 가중평균 datum.

        Centerline 위 sample_step_m 간격으로 점 sample → segment 길이 가중평균.

        Args:
            road_centerline_wgs: 도로 중심선 LineString (WGS84)
            sample_step_m: sample 간격 (기본 5m)

        Returns:
            (datum_m, samples)
        """
        line_utm = _wgs_to_utm(road_centerline_wgs)
        total_len_m = line_utm.length
        if not math.isfinite(total_len_m) or total_len_m <= 0:
            raise ElevationFetchError('Road centerline has no usable length')
        if not math.isfinite(sample_step_m) or sample_step_m <= 0:
            raise ElevationFetchError('Invalid road sample step')
        self._check_sample_budget(total_len_m / sample_step_m + 1)
        n_samples = max(2, int(total_len_m / sample_step_m) + 1)
        sample_distances = [i * total_len_m / (n_samples - 1) for i in range(n_samples)]
        points_wgs: list[tuple[float, float]] = []
        points_lnglat: list[tuple[float, float]] = []
        for d in sample_distances:
            pt = road_centerline_wgs.interpolate(d / total_len_m, normalized=True)
            points_wgs.append((pt.y, pt.x))
            points_lnglat.append((pt.x, pt.y))
        elevations = self._fetch(points_wgs)
        if len(elevations) < 2:
            datum_m = elevations[0] if elevations else 0.0
            samples = [{'dist_m': 0.0, 'elev_m': datum_m}]
            return (datum_m, samples)
        seg_lens: list[float] = []
        weighted_sum = 0.0
        for i in range(len(elevations)):
            if i == 0:
                w = (sample_distances[1] - sample_distances[0]) / 2.0
            elif i == len(elevations) - 1:
                w = (sample_distances[-1] - sample_distances[-2]) / 2.0
            else:
                w = (sample_distances[i + 1] - sample_distances[i - 1]) / 2.0
            seg_lens.append(w)
            weighted_sum += w * elevations[i]
        total_w = sum(seg_lens)
        datum_m = weighted_sum / total_w if total_w > 0 else 0.0
        samples = [{'dist_m': round(d, 3), 'lng': round(p[0], 6), 'lat': round(p[1], 6), 'elev_m': round(h, 3)} for d, p, h in zip(sample_distances, points_lnglat, elevations)]
        return (datum_m, samples)

    def neighbor_avg_datum_86(self, my_datum_m: float, neighbor_datum_m: float) -> float:
        """§86: 정북인접지와 고저차 있는 경우 두 가중평균면의 평균."""
        return (my_datum_m + neighbor_datum_m) / 2.0

    def site_above_road_119(self, parcel_datum_m: float, road_datum_m: float) -> float:
        """
        §119① 5호 나목: 대지가 전면도로보다 높을 때
        "고저차의 1/2의 높이만큼 올라온 위치에 도로면이 있다고 봄"

        → effective road datum = road_datum + (parcel_datum - road_datum) / 2
                               = (parcel_datum + road_datum) / 2

        대지가 도로보다 낮으면(parcel_datum < road_datum) 그대로 도로 datum 사용.
        """
        if parcel_datum_m <= road_datum_m:
            return road_datum_m
        return (parcel_datum_m + road_datum_m) / 2.0

    def split_3m_segments(self, parcel_wgs: Polygon, max_diff_m: float=3.0) -> list[dict] | None:
        """
        §119② 단서: 고저차 >3m면 3m 이내 영역마다 datum 분할.

        런타임에는 raw contour SHP가 아니라 DEM raster를 sample하므로, 여기서는
        필지 외곽 표고 프로파일을 3m 이하 elevation band로 나누고 각 band별 외곽
        길이 가중평균 datum을 산출한다.

        주의: 이 함수는 아직 등고선으로 실제 면 polygon을 절단하지 않는다. 대신
        "SLOPE_GT3M인데 단일 평균만 반환"하던 기존 상태를 개선해, API/CLI가
        3m band별 datum과 길이 근거를 검증할 수 있게 하는 중간 산출물이다.

        Returns:
            None: 고저차가 max_diff_m 이하이거나 산출 불가.
            list[dict]: band별 datum metadata.
        """
        if not math.isfinite(max_diff_m) or max_diff_m <= 0:
            raise ValueError('max_diff_m must be > 0')
        profile = self._boundary_elevation_profile(parcel_wgs)
        if len(profile) < 2:
            return None
        elevs = [p['elev_m'] for p in profile]
        min_e = min(elevs)
        max_e = max(elevs)
        if max_e - min_e <= max_diff_m:
            return None
        self._check_sample_budget((max_e - min_e) / max_diff_m)
        bands: list[dict] = []
        lower = min_e
        idx = 0
        while lower < max_e - 1e-09:
            upper = min(lower + max_diff_m, max_e)
            if upper <= lower:
                raise ElevationFetchError('Elevation band resolution unavailable')
            bands.append({'band_index': idx, 'min_elevation_m': lower, 'max_elevation_m': upper, 'length_m': 0.0, 'weighted_sum': 0.0, 'sample_count': 0, 'basis': 'boundary_elevation_band_3m'})
            lower = upper
            idx += 1
        for i in range(len(profile) - 1):
            p0 = profile[i]
            p1 = profile[i + 1]
            self._accumulate_segment_bands(p0, p1, bands)
        out: list[dict] = []
        for band in bands:
            length_m = band['length_m']
            if length_m <= 0.01:
                continue
            datum_m = band['weighted_sum'] / length_m
            out.append({'band_index': band['band_index'], 'min_elevation_m': round(band['min_elevation_m'], 3), 'max_elevation_m': round(band['max_elevation_m'], 3), 'datum_m': round(datum_m, 3), 'length_m': round(length_m, 3), 'sample_count': band['sample_count'], 'basis': band['basis']})
        return out or None

    def _boundary_elevation_profile(self, parcel_wgs: Polygon) -> list[dict]:
        """외곽선을 5m 내외 간격으로 sample한 표고 profile."""
        parcel_utm = _wgs_to_utm(parcel_wgs)
        coords_wgs = list(parcel_wgs.exterior.coords)
        coords_utm = list(parcel_utm.exterior.coords)
        if len(coords_wgs) < 2 or len(coords_utm) < 2:
            return []
        step_m = max(1.0, self.settings.edge_subsample_step_m)
        points_lnglat: list[tuple[float, float]] = []
        distance_m: list[float] = []
        cumulative = 0.0
        for i in range(len(coords_utm) - 1):
            x1, y1 = (coords_utm[i][0], coords_utm[i][1])
            x2, y2 = (coords_utm[i + 1][0], coords_utm[i + 1][1])
            length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            if not math.isfinite(length):
                raise ElevationFetchError('Invalid projected edge length')
            if length < 0.1:
                continue
            lng1, lat1 = (coords_wgs[i][0], coords_wgs[i][1])
            lng2, lat2 = (coords_wgs[i + 1][0], coords_wgs[i + 1][1])
            self._check_sample_budget(len(points_lnglat) + length / step_m + 1)
            n_sub = max(1, int(round(length / step_m)))
            if not points_lnglat:
                points_lnglat.append((lng1, lat1))
                distance_m.append(cumulative)
            for k in range(1, n_sub + 1):
                t = k / n_sub
                points_lnglat.append((lng1 + (lng2 - lng1) * t, lat1 + (lat2 - lat1) * t))
                distance_m.append(cumulative + length * t)
            cumulative += length
        if len(points_lnglat) < 2:
            return []
        elevations = self._fetch([(lat, lng) for lng, lat in points_lnglat])
        if self.settings.median_filter:
            elevations = self._denoise_median_filter(list(elevations), window=self.settings.median_filter_window)
        return [{'lng': lng, 'lat': lat, 'dist_m': dist, 'elev_m': float(elev)} for (lng, lat), dist, elev in zip(points_lnglat, distance_m, elevations)]

    def _accumulate_segment_bands(self, p0: dict, p1: dict, bands: list[dict]) -> None:
        length = float(p1['dist_m'] - p0['dist_m'])
        if length <= 0.01:
            return
        e0 = float(p0['elev_m'])
        e1 = float(p1['elev_m'])
        if abs(e1 - e0) < 1e-09:
            band = self._band_for_elevation(e0, bands)
            if band is None:
                return
            band['length_m'] += length
            band['weighted_sum'] += length * e0
            band['sample_count'] += 1
            return
        lo_e = min(e0, e1)
        hi_e = max(e0, e1)
        for band in bands:
            overlap_lo = max(lo_e, band['min_elevation_m'])
            overlap_hi = min(hi_e, band['max_elevation_m'])
            if overlap_hi <= overlap_lo:
                continue
            t_a = (overlap_lo - e0) / (e1 - e0)
            t_b = (overlap_hi - e0) / (e1 - e0)
            t0 = max(0.0, min(t_a, t_b))
            t1 = min(1.0, max(t_a, t_b))
            if t1 <= t0:
                continue
            piece_len = length * (t1 - t0)
            e_start = e0 + (e1 - e0) * t0
            e_end = e0 + (e1 - e0) * t1
            avg_e = (e_start + e_end) / 2.0
            band['length_m'] += piece_len
            band['weighted_sum'] += piece_len * avg_e
            band['sample_count'] += 1

    def _band_for_elevation(self, elev: float, bands: list[dict]) -> dict | None:
        for band in bands:
            if band['min_elevation_m'] <= elev <= band['max_elevation_m']:
                return band
        return None
