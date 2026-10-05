"""One owner for the clients land analysis runs on.

The route builds this from the environment; tools and tests inject their own.
"""
import os
from dataclasses import dataclass

from backend.app.adapters.vworld import VworldClient
from backend.app.adapters.vworld_land import VworldLandClient
from backend.app.adapters.vworld_geometry import VworldGeometryClient
from backend.app.adapters.law_search import LawSearchClient
from backend.app.adapters.regulation_extraction import RegulationExtractionClient
from backend.app.adapters.elevation import ElevationClient
from backend.app.modules.land.datum import DatumService, DatumSettings
from backend.app.modules.land.analysis import analyze_land
from backend.app.modules.land.analysis_request import normalize_program_request
from backend.app.modules.land.attributes import LandAttributes
from backend.app.modules.land.pnu import normalize_pnu
from backend.app.modules.land.repository import LandRepository


class DatumConfigurationError(Exception):
    pass


DATUM_DEFAULTS = {
    'ELEVATION_PROVIDER': 'open_meteo', 'NGII_LIDAR_URL': 'http://localhost:5000',
    'NGII_DEM_LOCAL_PATH': '', 'DATUM_EDGE_SUBSAMPLE': 'true',
    'DATUM_EDGE_SUBSAMPLE_THRESHOLD_M': '10.0', 'DATUM_EDGE_SUBSAMPLE_STEP_M': '5.0',
    'DATUM_MEDIAN_FILTER': 'true', 'DATUM_MEDIAN_FILTER_WINDOW': '3',
}


@dataclass
class LandServices:
    addresses: object
    attributes: object
    geometries: object
    laws: object
    extraction: object
    repository: object = None
    datum_enabled: bool = False
    datum_environment: dict | None = None
    datum_service_factory: object = None

    @classmethod
    def from_environment(cls, *, address_client=None, repository=None, attribute_client=None,
                         geometry_client=None, law_client=None, extraction_client=None,
                         datum_service_factory=None):
        key = os.environ.get('VWORLD_API_KEY', '')
        laws = law_client or LawSearchClient(os.environ.get('LAW_BACKEND_URL'), os.environ.get('AG_LIGHT_URL'))
        return cls(
            addresses=address_client or VworldClient(key),
            attributes=attribute_client or VworldLandClient(key),
            geometries=geometry_client or VworldGeometryClient(key),
            laws=laws,
            extraction=extraction_client or RegulationExtractionClient(laws,
                enabled=os.environ.get('LLM_EXTRACTION_ENABLED', 'false').lower() == 'true',
                api_key=os.environ.get('OPENAI_API_KEY', ''),
                model=os.environ.get('LLM_EXTRACTION_MODEL', 'gpt-4o-mini')),
            repository=repository,
            datum_enabled=os.environ.get('ENABLE_DATUM_ELEVATION', 'false').lower() == 'true',
            datum_environment={name: os.environ.get(name, default) for name, default in DATUM_DEFAULTS.items()},
            datum_service_factory=datum_service_factory)

    def local_repository(self):
        if self.repository is not None:
            return self.repository
        # Read per request, so storage can appear or vanish while the server runs.
        directory = os.environ.get('EDITOR_LAND_DATA_DIR')
        return LandRepository(directory) if directory else None

    def new_datum_service(self):
        if not self.datum_enabled:
            return None
        if self.datum_service_factory is not None:
            return self.datum_service_factory()
        env = self.datum_environment or DATUM_DEFAULTS
        settings = DatumSettings(
            edge_subsample=env['DATUM_EDGE_SUBSAMPLE'].lower() == 'true',
            edge_subsample_threshold_m=float(env['DATUM_EDGE_SUBSAMPLE_THRESHOLD_M']),
            edge_subsample_step_m=float(env['DATUM_EDGE_SUBSAMPLE_STEP_M']),
            median_filter=env['DATUM_MEDIAN_FILTER'].lower() == 'true',
            median_filter_window=int(env['DATUM_MEDIAN_FILTER_WINDOW']))
        provider = ElevationClient(env['ELEVATION_PROVIDER'], opentopodata_url=env['NGII_LIDAR_URL'],
                                   local_dem_path=env['NGII_DEM_LOCAL_PATH'], timeout=5)
        return DatumService(provider, settings)

    async def analyze(self, body):
        """Run the land analysis for an already-validated request body."""
        try:
            local = self.local_repository()
        except (OSError, ValueError):
            local = None
        try:
            datum_service = self.new_datum_service()
        except (ValueError, OSError) as error:
            raise DatumConfigurationError(str(error)) from None
        return await analyze_land(body, self.addresses, LandAttributes(self.attributes, local),
                                  self.geometries, local, law_client=self.laws,
                                  extraction_client=self.extraction, datum_service=datum_service)

    async def analyze_land(self, pnu, address, zones):
        """The tool-facing entry: a PNU or an address, optional zone override."""
        pnu, address = (pnu or '').strip(), (address or '').strip()
        if not pnu and not address:
            raise ValueError('pnu or address is required')
        body = {'input': normalize_pnu(pnu) if pnu else address, 'input_type': 'pnu' if pnu else 'address',
                'zones': [zone for zone in zones if isinstance(zone, str) and zone.strip()],
                'include_law': True, 'geometry': None}
        body.update(normalize_program_request({}))
        return await self.analyze(body)

    async def search_laws(self, query, limit=5):
        return await self.laws.search_queries([query], limit=limit, filter_results=True)
