"""Verified NGII continuous B001 records to canonical buildings; no publication or GIS fallback."""
from dataclasses import dataclass
import hashlib
import json
import math

from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import transform
from source_polygon_identity import polygon_identity


@dataclass(frozen=True)
class HeightPolicy:
    floor_metres: float = 3.4
    default_metres: float = 3.4
    metric_field: str | None = None
    metric_field_contract: str | None = None

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in (self.floor_metres, self.default_metres)):
            raise ValueError("Height constants must be positive finite metres")
        if bool(self.metric_field) != bool(self.metric_field_contract):
            raise ValueError("Metric field requires an explicit verified contract")


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, TypeError):
        return None


class NgiiBuildingAdapter:
    def __init__(self, manifest: dict, policy: HeightPolicy = HeightPolicy()):
        product = manifest.get("productCode")
        if product not in ("B020", "B021") or manifest.get("family") != f"NGII-{product}" or manifest.get("layer") != "N3A_B0010000":
            raise ValueError("Only explicitly identified NGII B020/B021 building geometry is accepted")
        if manifest.get("productKind") != "continuous-topographic":
            raise ValueError("Individual map sheets cannot enter the continuous building pipeline")
        if manifest.get("crs") != "EPSG:5179":
            raise ValueError("Current verified continuous schema expects EPSG:5179")
        for field in ("edition", "sourceManifestSHA256", "file"):
            if not isinstance(manifest.get(field), str) or not manifest[field]:
                raise ValueError(f"Missing provenance {field}")
        for field in ("sourceManifestSHA256", "productReceiptSHA256"):
            value = manifest.get(field)
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"Invalid provenance SHA256: {field}")
        self.manifest = dict(manifest)
        self.policy = policy
        self.project = Transformer.from_crs(5179, 4326, always_xy=True).transform

    def adapt(self, properties: dict, geometry, *, row: int):
        provenance = {**self.manifest, "row": row}
        normalized, audit = polygon_identity(geometry)
        if normalized is None:
            return {"rejected": audit, "provenance": provenance}
        geographic = transform(self.project, normalized)
        if not all(math.isfinite(v) for v in geographic.bounds):
            raise ValueError("Source geometry cannot be projected")
        anchor = geographic.representative_point()
        return self.record(properties, audit, mapping(geographic), [anchor.x, anchor.y], row=row)

    def record(self, properties, audit, geographic_mapping, anchor, *, row):
        """Shared identity/height/provenance assembly for scalar and array geometry paths."""
        p = {str(k).upper(): v for k, v in properties.items()}
        provenance = {**self.manifest, "row": row}
        ufid = p.get("UFID")
        ufid = ufid.strip() if isinstance(ufid, str) else ""
        identity = [self.manifest["family"], ufid, audit["geometrySHA256"]]
        building_id = "ngii:" + hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        metric = positive(p.get(self.policy.metric_field.upper())) if self.policy.metric_field else None
        floors = positive(p.get("NMLY"))
        if metric is not None:
            height, source = metric, {"kind": "source-metric", "field": self.policy.metric_field,
                                      "contract": self.policy.metric_field_contract}
        elif floors is not None:
            height, source = floors * self.policy.floor_metres, {"kind": "source-floors", "field": "NMLY",
                "floors": floors, "floorMetres": self.policy.floor_metres}
        else:
            height, source = self.policy.default_metres, {"kind": "declared-default", "defaultMetres": self.policy.default_metres}
        if not math.isfinite(height):
            raise ValueError("Height calculation overflow")
        return {"canonicalBuildingId": building_id, "sourceUFID": ufid or None,
                "geomWGS84": geographic_mapping, "h": height, "heightSource": source,
                "anchorWGS84": anchor, "geometryAudit": audit, "provenance": provenance}

    def stream(self, records):
        """Input iterator yields (source-row-number, properties, native geometry); no buffering."""
        for row, properties, geometry in records:
            yield self.adapt(properties, geometry, row=row)
