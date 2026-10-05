"""Reference image corpus helpers for MAAS preference distillation."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
import hashlib
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REFERENCE_SCHEMA_VERSION = "arr.maas.reference_corpus.v1"

DEFAULT_HF_DATASETS: tuple[dict[str, Any], ...] = (
    {
        "dataset_id": "terminusresearch/photo-architecture",
        "role": "primary_architecture_photo_corpus",
        "source_url": "https://huggingface.co/datasets/terminusresearch/photo-architecture",
        "notes": "Architecture/building image corpus with CogVLM captions.",
        "tags": ["architecture", "building", "photo", "captioned"],
    },
    {
        "dataset_id": "Morris0401/Year-Guessr-Dataset",
        "role": "building_metadata_prior",
        "source_url": "https://huggingface.co/datasets/Morris0401/Year-Guessr-Dataset",
        "notes": "Architecture images with age/region metadata.",
        "tags": ["architecture", "building_age", "region", "metadata"],
    },
    {
        "dataset_id": "gatecitypreservation/architectural_styles",
        "role": "style_label_prior",
        "source_url": "https://huggingface.co/gatecitypreservation/architectural_styles",
        "notes": "Small style classifier reference for architectural style labels.",
        "tags": ["architectural_style", "facade", "style"],
    },
)

MASSING_TAGS = {
    "courtyard": {"courtyard", "atrium", "void", "court"},
    "void_notch": {"void", "notch", "carve", "undercut"},
    "split": {"split", "bridge", "connector", "gap"},
    "diagonal_connect": {"diagonal", "bridge", "connector"},
    "array_cluster": {"cluster", "array", "field", "campus"},
    "offset": {"offset", "shift", "shifted", "platform"},
    "reflected_pair": {"pair", "twin", "mirror", "reflected"},
    "slender_bar": {"bar", "slender", "linear"},
    "bend": {"bend", "fold", "curved", "ribbon"},
    "interlock": {"interlock", "cross", "woven"},
    "overlap": {"overlap", "slab", "stacked"},
    "branch": {"branch", "fork", "y-shape"},
    "pinch": {"pinch", "waist", "hourglass"},
    "embed": {"embed", "insert", "inner"},
    "extrude": {"extrude", "fin", "projection"},
    "nest": {"nested", "nest", "inner", "atrium"},
    "sloped_roof": {"sloped", "roof", "folded", "section"},
    "torqued_stack": {"torque", "torqued", "twist", "twisted", "curvilinear", "vancouver", "undercut", "tower"},
    "stacked_platform": {"stack", "stacked", "platform", "platforms", "shift", "shifted", "oma", "library"},
    "terrace_ribbon": {"terrace", "terraced", "ramp", "mountain", "stepped", "sectional"},
}

# A reference set made only of nearest neighbours creates a closed aesthetic
# loop: a box-like candidate retrieves more box-like precedents and the VLM
# learns no alternative spatial move.  These are generic formal principles,
# not named-building templates.  They are used only to reserve one image slot
# for a contrasting precedent; geometry still comes from the editable graph.
ASPIRATIONAL_MASSING_TAGS = frozenset({
    "atrium", "bend", "branch", "bridge", "campus", "carve", "connector",
    "court", "courtyard", "curved", "diagonal", "field", "fold", "folded",
    "gap", "interlock", "loop", "mountain", "notch", "ramp", "ribbon",
    "section", "sectional", "shift", "shifted", "sloped", "split", "stack",
    "stacked", "stepped", "terrace", "terraced", "torque", "torqued",
    "twist", "twisted", "undercut", "void", "woven",
})

PRECEDENT_TAG_HINTS = {
    "seattle-central-library": {"oma", "library", "stack", "stacked", "platform", "platforms", "shift", "shifted", "section", "diagonal", "folded", "stacked_platform"},
    "qatar-national-library": {"oma", "library", "folded", "section", "sloped", "roof", "sloped_roof", "stacked_platform"},
    "vancouver-house": {"big", "vancouver", "torque", "torqued", "twist", "twisted", "curvilinear", "undercut", "tower", "torqued_stack"},
    "mountain-dwellings": {"big", "mountain", "terrace", "terraced", "sectional", "stacked", "terrace_ribbon"},
    "8-house": {"big", "courtyard", "terrace", "ramp", "loop", "sectional", "terrace_ribbon"},
    "vm-houses": {"big", "split", "pair", "slender", "bar", "slender_bar", "reflected_pair"},
    "hualien-residences": {"big", "mountain", "terraced", "stacked", "nested", "nest", "terrace_ribbon"},
    "lego-house": {"big", "stack", "stacked", "block", "courtyard", "overlap", "overlap_slabs"},
}

REFERENCE_STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "all",
    "also",
    "an",
    "and",
    "apartment",
    "apartments",
    "architect",
    "architects",
    "architecture",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "between",
    "build",
    "building",
    "buildings",
    "built",
    "by",
    "can",
    "center",
    "city",
    "completed",
    "conceived",
    "development",
    "design",
    "designed",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "images",
    "located",
    "new",
    "one",
    "of",
    "on",
    "or",
    "project",
    "residence",
    "residential",
    "s",
    "site",
    "studio",
    "that",
    "the",
    "their",
    "this",
    "through",
    "to",
    "urban",
    "use",
    "was",
    "were",
    "where",
    "with",
    "within",
}


@dataclass(frozen=True)
class ReferenceItem:
    source: str
    source_id: str
    title: str
    image_url: str = ""
    local_path: str = ""
    page_url: str = ""
    tags: tuple[str, ...] = ()
    caption: str = ""
    paper_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REFERENCE_SCHEMA_VERSION,
            "source": self.source,
            "source_id": self.source_id,
            "title": self.title,
            "image_url": self.image_url,
            "local_path": self.local_path,
            "page_url": self.page_url,
            "tags": list(self.tags),
            "caption": self.caption,
            "paper_source": self.paper_source,
        }


def default_reference_root() -> Path:
    # Never depend on the server/test process cwd. The canonical corpus lives
    # at the repository root; a stale backend-local copy previously made live
    # VLM runs silently report zero reference matches.
    return _design_paths.workspace_root() / "docs" / "ai-session-memory" / "reference-corpus"


def ensure_reference_seed_files(root: Path | None = None) -> dict[str, str]:
    root = root or default_reference_root()
    hf_dir = root / "huggingface"
    archdaily_dir = root / "archdaily"
    hf_dir.mkdir(parents=True, exist_ok=True)
    archdaily_dir.mkdir(parents=True, exist_ok=True)
    hf_manifest = hf_dir / "datasets.json"
    archdaily_seed = archdaily_dir / "seed_urls.txt"
    if not hf_manifest.exists():
        hf_manifest.write_text(json.dumps({
            "schema_version": "arr.maas.hf_reference_manifest.v1",
            "datasets": list(DEFAULT_HF_DATASETS),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not archdaily_seed.exists():
        archdaily_seed.write_text(
            "# Add ArchDaily project/image URLs here, one per line.\n",
            encoding="utf-8",
        )
    return {
        "hf_manifest": str(hf_manifest),
        "archdaily_seed": str(archdaily_seed),
    }


def load_reference_items(path: Path) -> list[ReferenceItem]:
    if not path.exists():
        return []
    items: list[ReferenceItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        tags = tuple(sorted(_clean_tags(str(item) for item in data.get("tags") or [])))
        items.append(ReferenceItem(
            source=str(data.get("source") or ""),
            source_id=str(data.get("source_id") or data.get("id") or ""),
            title=str(data.get("title") or ""),
            image_url=str(data.get("image_url") or ""),
            local_path=str(data.get("local_path") or ""),
            page_url=str(data.get("page_url") or ""),
            tags=tags,
            caption=str(data.get("caption") or ""),
            paper_source=str(data.get("paper_source") or ""),
        ))
    return items


def load_reference_tree(root: Path) -> list[ReferenceItem]:
    """Load every metadata.jsonl below a reference root, de-duplicated by source id."""
    items: list[ReferenceItem] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("metadata.jsonl")):
        for item in load_reference_items(path):
            key = (item.source, item.source_id)
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def write_reference_items(path: Path, items: Iterable[ReferenceItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def refresh_archdaily_db_manifest(root: Path) -> dict[str, Any]:
    """Rebuild the ArchDaily DB index from collection manifests and metadata.

    Collection crawls are append-only folders.  Rebuilding here prevents the
    root manifest from silently understating the corpus after a new program
    slice (for example sports or cafes) is collected.
    """
    archdaily = root / "archdaily"
    collections: list[dict[str, Any]] = []
    for manifest_path in sorted(archdaily.rglob("manifest.json")):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(manifest_path)
        collections.append(payload)
    items = load_reference_tree(archdaily)
    image_count = sum(
        1
        for path in archdaily.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    payload = {
        "schema_version": "arr.maas.archdaily_reference_db.v1",
        "source": "archdaily",
        "collection_count": len(collections),
        "metadata_file_count": len(list(archdaily.rglob("metadata.jsonl"))),
        "unique_item_count": len(items),
        "image_file_count": image_count,
        "loader": 'backend.app.modules.design.generation.maas.preference.reference_corpus.load_reference_tree',
        "collections": collections,
        "storage_contract": {
            "api": "archdaily/api/<collection>/metadata.jsonl + images/ + manifest.json",
            "seeded": "archdaily/seeded/<collection>/metadata.jsonl + images/ + manifest.json",
        },
    }
    write_reference_manifest(archdaily / "DB_MANIFEST.json", payload)
    return payload


def collect_archdaily_metadata(urls: Iterable[str], *, timeout: float = 20.0) -> list[ReferenceItem]:
    items: list[ReferenceItem] = []
    for index, url in enumerate(urls, start=1):
        clean_url = str(url).strip()
        if not clean_url or clean_url.startswith("#"):
            continue
        html = _fetch_text(clean_url, timeout=timeout)
        title = _meta_content(html, "og:title") or _title_from_url(clean_url)
        image_url = _meta_content(html, "og:image")
        description = _meta_content(html, "og:description")
        tags = tuple(sorted(_infer_tags(f"{title} {description} {clean_url}")))
        items.append(ReferenceItem(
            source="archdaily",
            source_id=f"archdaily_{index:04d}",
            title=title,
            image_url=image_url,
            page_url=clean_url,
            tags=tags,
            caption=description,
            paper_source="external_precedent_corpus",
        ))
    return items


def discover_archdaily_project_urls(
    *,
    start_url: str = "https://www.archdaily.com/search/projects",
    pages: int = 1,
    timeout: float = 20.0,
    delay_seconds: float = 0.8,
) -> list[str]:
    """Discover project URLs from ArchDaily search/category pages."""
    discovered: list[str] = []
    seen: set[str] = set()
    for page in range(1, max(1, int(pages)) + 1):
        page_url = _with_page(start_url, page)
        html = _fetch_text(page_url, timeout=timeout)
        for url in _extract_archdaily_project_links(html):
            if url not in seen:
                seen.add(url)
                discovered.append(url)
        if delay_seconds > 0 and page < pages:
            time.sleep(delay_seconds)
    return discovered


def collect_archdaily_from_search(
    *,
    start_url: str = "https://www.archdaily.com/search/projects",
    pages: int = 1,
    limit: int = 40,
    timeout: float = 20.0,
    delay_seconds: float = 0.8,
    download_images: bool = False,
    image_dir: Path | None = None,
) -> list[ReferenceItem]:
    urls = discover_archdaily_project_urls(
        start_url=start_url,
        pages=pages,
        timeout=timeout,
        delay_seconds=delay_seconds,
    )[: max(1, int(limit))]
    items = collect_archdaily_metadata(urls, timeout=timeout)
    if download_images:
        items = download_reference_images(items, image_dir=image_dir or default_reference_root() / "archdaily" / "images", timeout=timeout)
    return items


def collect_archdaily_from_api(
    *,
    start_path: str = "/projects",
    site: str = "us",
    query: str = "",
    pages: int = 1,
    limit: int = 40,
    timeout: float = 20.0,
    delay_seconds: float = 0.8,
    download_images: bool = False,
    image_dir: Path | None = None,
) -> list[ReferenceItem]:
    """Collect ArchDaily search results through the JSON API used by the search app."""
    items: list[ReferenceItem] = []
    seen: set[str] = set()
    for page in range(1, max(1, int(pages)) + 1):
        api_url = _archdaily_api_url(start_path=start_path, site=site, query=query, page=page)
        data = _fetch_json(api_url, timeout=timeout)
        for row in data.get("results") or []:
            if not isinstance(row, dict):
                continue
            item = _archdaily_result_to_reference(row)
            key = item.page_url or item.source_id
            if key and key not in seen:
                seen.add(key)
                items.append(item)
            if len(items) >= max(1, int(limit)):
                break
        if len(items) >= max(1, int(limit)):
            break
        if delay_seconds > 0 and page < pages:
            time.sleep(delay_seconds)
    if download_images:
        items = download_reference_images(items, image_dir=image_dir or default_reference_root() / "archdaily" / "images", timeout=timeout)
    return items


def archdaily_api_collection_slug(*, start_path: str = "/projects", query: str = "", site: str = "us") -> str:
    """Stable folder slug for an ArchDaily API corpus slice."""
    path = start_path.strip() or "/projects"
    if path.startswith("https://"):
        path = urllib.parse.urlparse(path).path
    path = path.replace("/search/api/v1/", "/")
    path = path.replace(f"/{site}/", "/")
    path = path.replace("/search/", "/")
    if path.startswith("/"):
        path = path[1:]
    base = path.replace("/", "_") or "projects"
    if query.strip():
        base = f"{base}_q_{query.strip()}"
    return _safe_slug(base.lower())


def archdaily_api_collection_dir(
    root: Path,
    *,
    start_path: str = "/projects",
    query: str = "",
    site: str = "us",
    collection_name: str = "",
) -> Path:
    slug = _safe_slug(collection_name.strip()) if collection_name.strip() else archdaily_api_collection_slug(
        start_path=start_path,
        query=query,
        site=site,
    )
    return root / "archdaily" / "api" / slug


def archdaily_seed_collection_dir(root: Path, *, collection_name: str = "manual_seed") -> Path:
    slug = _safe_slug(collection_name.strip() or "manual_seed")
    return root / "archdaily" / "seeded" / slug


def write_reference_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def download_reference_images(
    items: Iterable[ReferenceItem],
    *,
    image_dir: Path,
    timeout: float = 30.0,
) -> list[ReferenceItem]:
    image_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[ReferenceItem] = []
    for item in items:
        local_path = item.local_path
        target: Path | None = None
        if item.image_url:
            suffix = _image_suffix(item.image_url)
            filename = f"{_safe_slug(item.source_id or item.title)}{suffix}"
            target = image_dir / filename
            if not target.exists():
                try:
                    request = urllib.request.Request(
                        item.image_url,
                        headers={"User-Agent": "Mozilla/5.0 MAAS research reference collector"},
                    )
                    with urllib.request.urlopen(request, timeout=timeout) as response:
                        target.write_bytes(response.read())
                except Exception:
                    target = None
            if target is not None and target.exists():
                local_path = str(target)
        downloaded.append(ReferenceItem(
            source=item.source,
            source_id=item.source_id,
            title=item.title,
            image_url=item.image_url,
            local_path=local_path,
            page_url=item.page_url,
            tags=item.tags,
            caption=item.caption,
            paper_source=item.paper_source,
        ))
    return downloaded


def _archdaily_api_url(*, start_path: str, site: str, query: str, page: int) -> str:
    path = start_path.strip() or "/projects"
    if path.startswith("https://"):
        parsed = urllib.parse.urlparse(path)
        path = parsed.path
        if path.startswith("/search/api/v1/"):
            url = path
        elif path.startswith("/search/"):
            url = path.replace("/search", f"/search/api/v1/{site}", 1)
        else:
            url = f"/search/api/v1/{site}/projects"
    elif path.startswith("/search/api/v1/"):
        url = path
    else:
        if path.startswith("/search/"):
            path = path.replace("/search", "", 1)
        if not path.startswith("/"):
            path = "/" + path
        url = f"/search/api/v1/{site}{path}"
    params: dict[str, str] = {}
    if query:
        params["q"] = query
    if page > 1:
        params["page"] = str(page)
    query_string = urllib.parse.urlencode(params)
    return f"https://www.archdaily.com{url}" + (f"?{query_string}" if query_string else "")


def _fetch_json(url: str, *, timeout: float) -> dict[str, Any]:
    text = _fetch_text(url, timeout=timeout)
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _archdaily_result_to_reference(row: dict[str, Any]) -> ReferenceItem:
    title = str(row.get("title") or _title_from_url(str(row.get("url") or "")))
    page_url = str(row.get("url") or "").split("?")[0]
    source_id = str(row.get("document_id") or _safe_slug(page_url or title))
    image_url = _preferred_archdaily_image(row)
    category_tags = [
        str(category.get("name") or "")
        for category in row.get("categories") or []
        if isinstance(category, dict)
    ]
    office_tags = [
        str(office.get("name") or "")
        for office in row.get("offices") or []
        if isinstance(office, dict)
    ]
    tag_names = [
        str(tag.get("name") or "")
        for tag in row.get("tags") or []
        if isinstance(tag, dict)
    ]
    caption = str(row.get("meta_description") or "")
    tags = tuple(sorted(_infer_tags(" ".join([
        title,
        caption,
        str(row.get("location") or ""),
        " ".join(category_tags),
        " ".join(office_tags),
        " ".join(tag_names),
    ]))))
    return ReferenceItem(
        source="archdaily_api",
        source_id=f"archdaily_{source_id}",
        title=title,
        image_url=image_url,
        page_url=page_url,
        tags=tags,
        caption=caption,
        paper_source="external_precedent_corpus_archdaily_api",
    )


def _preferred_archdaily_image(row: dict[str, Any]) -> str:
    featured = row.get("featured_images")
    if isinstance(featured, dict):
        for key in ("url_medium", "url_large", "url_small", "url_slideshow", "url_thumb"):
            if featured.get(key):
                return str(featured[key])
    miniatures = row.get("miniatures")
    if isinstance(miniatures, list):
        for item in miniatures:
            if not isinstance(item, dict):
                continue
            for key in ("url_medium", "url_large", "url_small", "url_slideshow", "url_thumb"):
                if item.get(key):
                    return str(item[key])
    return ""


def match_reference_context(
    feature: dict[str, Any],
    references: Iterable[ReferenceItem],
    *,
    limit: int = 5,
    program_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    tags = _feature_tags(feature)
    reference_items = list(references)
    program_evidence: dict[tuple[str, str], dict[str, Any]] = {}
    if isinstance(program_contract, dict) and str(program_contract.get("program_id") or "generic") != "generic":
        eligible_items: list[ReferenceItem] = []
        for item in reference_items:
            evidence = _program_reference_evidence(item, program_contract)
            if not evidence["hard_match"]:
                continue
            key = (item.source, item.source_id or item.title)
            program_evidence[key] = evidence
            eligible_items.append(item)
        reference_items = eligible_items
    scored: list[tuple[int, ReferenceItem]] = []
    for item in reference_items:
        haystack = _clean_tags(item.tags)
        haystack.update(_infer_tags(f"{item.title} {item.caption}"))
        haystack.update(_precedent_hint_tags(item))
        evidence = program_evidence.get((item.source, item.source_id or item.title), {})
        score = len(tags & haystack) + int(evidence.get("score") or 0)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].source, pair[1].title))
    selected = _select_diverse_references(
        scored,
        references=reference_items,
        feature_tags=tags,
        limit=limit,
    )
    result = []
    program_specific = bool(
        isinstance(program_contract, dict)
        and str(program_contract.get("program_id") or "generic") != "generic"
    )
    for index, (score, item, selection_role) in enumerate(selected):
        evidence = program_evidence.get((item.source, item.source_id or item.title), {})
        resolved_role = "program" if index == 0 and program_specific and evidence.get("hard_match") else selection_role
        result.append({
            "source": item.source,
            "source_id": item.source_id,
            "title": item.title,
            "page_url": item.page_url,
            "image_url": item.image_url,
            "local_path": item.local_path,
            "matched_tags": sorted(tags & (_clean_tags(item.tags) | _infer_tags(f"{item.title} {item.caption}") | _precedent_hint_tags(item))),
            "score": score,
            "selection_role": resolved_role,
            "image_sha256": _reference_image_digest(item),
            "program_id": str((program_contract or {}).get("program_id") or "generic"),
            "program_match_tier": str(evidence.get("tier") or "unconditioned"),
            "program_matched_terms": list(evidence.get("matched_terms") or ()),
            "reference_collection": str(evidence.get("collection") or ""),
            "program_relevance_score": int(evidence.get("score") or 0),
        })
    return result


def _program_reference_evidence(item: ReferenceItem, contract: dict[str, Any]) -> dict[str, Any]:
    """Measure program relevance without treating a precedent as a template."""
    path_text = " ".join((item.local_path, item.page_url)).replace("\\", "/").lower()
    preferred_collections = [
        str(value).strip().lower()
        for value in contract.get("preferred_collections") or ()
        if str(value).strip()
    ]
    collection = next(
        (value for value in preferred_collections if f"/{value}/" in f"/{path_text}/"),
        "",
    )
    normalized = re.sub(
        r"[^a-z0-9_ -]+",
        " ",
        " ".join((item.title, item.caption, " ".join(item.tags), path_text)).lower(),
    )
    normalized = " ".join(normalized.replace("_", " ").replace("-", " ").split())

    def matches(term: str) -> bool:
        needle = " ".join(str(term).lower().replace("_", " ").replace("-", " ").split())
        if not needle:
            return False
        if " " in needle:
            return needle in normalized
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", normalized))

    required = sorted({
        str(term).lower()
        for term in contract.get("required_any_terms") or ()
        if matches(str(term))
    })
    supporting = sorted({
        str(term).lower()
        for term in contract.get("supporting_terms") or ()
        if matches(str(term))
    })
    excluded = sorted({
        str(term).lower()
        for term in contract.get("excluded_terms") or ()
        if matches(str(term))
    })
    # A preferred collection is a coarse corpus partition, not proof of
    # typological relevance.  For example, a 230 m office tower is still the
    # wrong reference for a 2--8 floor neighborhood building even when both
    # live under mixed-use/offices.  Program-owned negative vocabulary keeps
    # this data-driven and avoids hard-coding individual precedent IDs.
    hard_match = bool(collection or required) and not excluded
    return {
        "hard_match": hard_match,
        "tier": "preferred_collection" if collection else ("semantic_program_match" if required else "mismatch"),
        "collection": collection,
        "matched_terms": [*required, *supporting],
        "excluded_terms": excluded,
        "score": (6 if collection else 0) + len(required) * 3 + len(supporting),
    }


def _select_diverse_references(
    scored: list[tuple[int, ReferenceItem]],
    *,
    references: list[ReferenceItem],
    feature_tags: set[str],
    limit: int,
) -> list[tuple[int, ReferenceItem, str]]:
    if limit <= 0:
        return []
    selected: list[tuple[int, ReferenceItem, str]] = []
    seen: set[tuple[str, str]] = set()
    seen_images: set[str] = set()

    def add(pair: tuple[int, ReferenceItem], role: str) -> None:
        key = (pair[1].source, pair[1].source_id or pair[1].title)
        image_digest = _reference_image_digest(pair[1])
        if key in seen or (image_digest and image_digest in seen_images) or len(selected) >= limit:
            return
        seen.add(key)
        if image_digest:
            seen_images.add(image_digest)
        selected.append((pair[0], pair[1], role))

    for pair in scored[:2]:
        add(pair, "similar")

    # The VLM currently receives three reference images.  Reserve the third
    # position for an image-backed precedent that contributes a formal
    # principle absent from the candidate.  This is counterfactual retrieval,
    # not geometry copying or a handcrafted building recipe.
    if limit >= 3:
        contrast: list[tuple[int, int, int, str, ReferenceItem]] = []
        for item in references:
            key = (item.source, item.source_id or item.title)
            if key in seen or not (item.local_path or item.image_url):
                continue
            item_tags = _clean_tags(item.tags)
            item_tags.update(_infer_tags(f"{item.title} {item.caption}"))
            item_tags.update(_precedent_hint_tags(item))
            signature = item_tags & ASPIRATIONAL_MASSING_TAGS
            novel = signature - feature_tags
            if not novel:
                continue
            source_priority = 1 if item.source in {"archdaily", "archdaily_api"} else 0
            contrast.append((len(novel), len(signature), source_priority, item.title, item))
        contrast.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))
        if contrast:
            item = contrast[0][-1]
            overlap = len(feature_tags & (
                _clean_tags(item.tags)
                | _infer_tags(f"{item.title} {item.caption}")
                | _precedent_hint_tags(item)
            ))
            add((overlap, item), "counterfactual")

    if limit >= 4 and not any(item.source == "archdaily_api" for _, item, _ in selected):
        for pair in scored:
            if pair[1].source == "archdaily_api":
                add(pair, "similar")
                break
    for pair in scored:
        add(pair, "similar")
    return selected[:limit]


def _reference_image_digest(item: ReferenceItem) -> str:
    if item.local_path:
        path = Path(item.local_path)
        # Zero-byte files are corpus/test placeholders, not image evidence.
        # Hashing their bytes would collapse every placeholder into one fake
        # duplicate, so only content-backed files participate in byte dedup.
        try:
            if path.is_file() and path.stat().st_size > 0:
                return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    locator = str(item.image_url or item.local_path or "").strip()
    return hashlib.sha256(locator.encode("utf-8")).hexdigest() if locator else ""


def _feature_tags(feature: dict[str, Any]) -> set[str]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    source = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    visual = props.get("visual_diversity_evidence") if isinstance(props.get("visual_diversity_evidence"), dict) else {}
    values = [
        props.get("operator_family"),
        source.get("family"),
        source.get("formal_principle"),
        source.get("primary_language"),
        source.get("secondary_language"),
        visual.get("mass_language"),
    ]
    tags = _infer_tags(" ".join(str(value or "") for value in values))
    family = str(source.get("family") or props.get("operator_family") or "")
    tags.update(MASSING_TAGS.get(family, set()))
    for key, aliases in MASSING_TAGS.items():
        if key in tags or tags & aliases:
            tags.add(key)
            tags.update(aliases)
    return tags


def _precedent_hint_tags(item: ReferenceItem) -> set[str]:
    text = f"{item.title} {item.page_url}".lower()
    tags: set[str] = set()
    for needle, hints in PRECEDENT_TAG_HINTS.items():
        if needle in text:
            tags.update(hints)
    return tags


def _infer_tags(text: str) -> set[str]:
    normalized = re.sub(r"[^a-zA-Z0-9_ -]+", " ", text).lower()
    tokens = _clean_tags(normalized.replace("_", " ").replace("-", " ").split())
    tags = set(tokens)
    for key, aliases in MASSING_TAGS.items():
        if key in normalized or tokens & aliases:
            tags.add(key)
            tags.update(aliases & tokens)
    return tags


def _clean_tags(values: Iterable[str]) -> set[str]:
    tags: set[str] = set()
    for value in values:
        token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not token:
            continue
        if token in REFERENCE_STOPWORDS:
            continue
        if len(token) < 3 and token not in {"8_house", "big", "oma"}:
            continue
        if token.isdigit() and 1900 <= int(token) <= 2100:
            continue
        tags.add(token)
    return tags


def _meta_content(html: str, prop: str) -> str:
    if not html:
        return ""
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(prop)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _fetch_text(url: str, *, timeout: float) -> str:
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 MAAS research reference collector"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_archdaily_project_links(html: str) -> list[str]:
    if not html:
        return []
    urls: list[str] = []
    pattern = r'href=["\'](https?://www\.archdaily\.com/\d+/[^"\']+|/\d+/[^"\']+)["\']'
    for match in re.finditer(pattern, html):
        raw = match.group(1)
        if raw.startswith("/"):
            raw = f"https://www.archdaily.com{raw}"
        parsed = urllib.parse.urlparse(raw)
        clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        if _is_project_url(clean):
            urls.append(clean)
    return urls


def _is_project_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.netloc.endswith("archdaily.com")
        and re.match(r"^/\d+/", parsed.path) is not None
        and "/search/" not in parsed.path
        and "/tag/" not in parsed.path
    )


def _with_page(url: str, page: int) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    if page > 1:
        query["page"] = str(page)
    elif "page" in query:
        query.pop("page", None)
    return urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urllib.parse.urlencode(query),
        parsed.fragment,
    ))


def _title_from_url(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    return tail.replace("-", " ").replace("_", " ").strip() or url


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())[:80].strip("_")
    return slug or "archdaily_reference"


def _image_suffix(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(suffix):
            return suffix
    return ".jpg"


__all__ = [
    "DEFAULT_HF_DATASETS",
    "REFERENCE_SCHEMA_VERSION",
    "ReferenceItem",
    "collect_archdaily_from_api",
    "collect_archdaily_from_search",
    "collect_archdaily_metadata",
    "discover_archdaily_project_urls",
    "download_reference_images",
    "ensure_reference_seed_files",
    "archdaily_api_collection_dir",
    "archdaily_api_collection_slug",
    "archdaily_seed_collection_dir",
    "load_reference_items",
    "load_reference_tree",
    "refresh_archdaily_db_manifest",
    "match_reference_context",
    "write_reference_manifest",
    "write_reference_items",
]


# The lead image of an ArchDaily entry is the photograph the article opens with
# - an interior, a street corner, a pond. Sampled by hand across four
# collections, roughly one in three showed a whole building and none showed a
# massing diagram, which is why enlarging the corpus by collection did not
# enlarge the massing signal.
#
# The diagrams are on the project page, in the gallery: axonometrics, massing
# sequences, sections. `og:image` never points at them. This reaches them.
_ARCHDAILY_MEDIA = re.compile(
    r"https://images\.adsttc\.com/media/images/[A-Za-z0-9/_%-]+\.(?:jpg|jpeg|png)",
    re.IGNORECASE,
)


def collect_archdaily_gallery(
    page_url: str,
    *,
    limit: int = 12,
    timeout: float = 20.0,
) -> list[str]:
    """Every gallery image URL on one ArchDaily project page, in page order.

    Page order matters: ArchDaily puts photographs first and drawings last, so
    the diagrams a massing corpus wants are at the end of the list, not the
    start. Take from the tail when sampling.
    """

    html = _fetch_text(page_url, timeout=timeout)
    seen: list[str] = []
    for match in _ARCHDAILY_MEDIA.finditer(html):
        url = match.group(0)
        if url not in seen:
            seen.append(url)
    return seen[: max(1, int(limit))] if limit > 0 else seen
