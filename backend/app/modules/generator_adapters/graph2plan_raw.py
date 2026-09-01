from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import pickle
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit
import uuid

import numpy as np

_TEST_DATA = "data_test_converted.pkl"
_TRAIN_DATA = "data_train_converted.pkl"
_SEED = 0
_WORKER_TIMEOUT_SECONDS = 180.0
_WORKER_PROTOCOL_VERSION = 1
_MAX_WORKER_RESPONSE_BYTES = 65_536
_MAX_ARTIFACT_METADATA_BYTES = 1_048_576
_PUBLISH_LOCK_TIMEOUT_SECONDS = 15.0
_ARTIFACT_NAMES = frozenset(
    {
        "graph2plan-raw-forward.npz",
        "graph2plan-input-condition.npz",
        "graph2plan-raw-preview.png",
        "graph2plan-raw-metadata.json",
    }
)


class Graph2PlanRawError(RuntimeError):
    """Bounded failure from the raw Graph2Plan benchmark runner."""


@dataclass(frozen=True)
class Graph2PlanRawConfig:
    repository_path: Path
    checkpoint_path: Path
    data_path: Path
    output_path: Path
    record_index: int
    device: str = "cpu"
    timeout_seconds: float = _WORKER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        for name in (
            "repository_path",
            "checkpoint_path",
            "data_path",
            "output_path",
        ):
            path = Path(getattr(self, name))
            if not path.is_absolute():
                raise ValueError(f"{name} must be absolute")
            object.__setattr__(self, name, path.resolve(strict=False))
        if (
            not isinstance(self.record_index, int)
            or isinstance(self.record_index, bool)
            or self.record_index < 0
        ):
            raise ValueError("record_index must be a nonnegative integer")
        if self.device not in {"cpu", "cuda"}:
            raise ValueError("device must be cpu or cuda")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not np.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")


@dataclass(frozen=True)
class RawForwardOutput:
    input_id: str
    query_record_index: int
    retrieved_record_index: int
    gene: np.ndarray
    pred_box: np.ndarray
    refine_box: np.ndarray
    input_boundary: np.ndarray
    input_boundary_raster: np.ndarray
    inside_box: np.ndarray
    input_graph_boxes: np.ndarray
    input_graph_edges: np.ndarray
    room_types: np.ndarray
    attributes: np.ndarray
    triples: np.ndarray
    input_shapes: dict[str, list[int]]
    class_legend: tuple[tuple[int, str, tuple[int, int, int]], ...]
    torch_version: str
    model_load_seconds: float
    forward_seconds: float


@dataclass(frozen=True)
class Graph2PlanRawArtifacts:
    scope: str
    arrays_path: Path
    input_path: Path
    png_path: Path
    metadata_path: Path
    metadata_sha256: str


@dataclass(frozen=True)
class _RepositoryProvenance:
    revision: str
    remote_url: str
    tracked_worktree_clean: bool
    tracked_changes: tuple[str, ...]
    tracked_source_sha256: str


@dataclass(frozen=True)
class _OfficialRuntime:
    torch: object
    model_type: type
    floorplan_type: type
    centers_to_extents: object
    room_label: object
    colormap_255: object


def run_graph2plan_raw_benchmark(
    config: Graph2PlanRawConfig,
) -> Graph2PlanRawArtifacts:
    _validate_assets(config)
    started = time.perf_counter()
    repository = _repository_provenance(config.repository_path)
    checkpoint_sha256 = _sha256_file(config.checkpoint_path)
    dataset_files = _dataset_files(config.data_path)
    dataset_hashes = {
        path.name: _sha256_file(path)
        for path in dataset_files
    }
    dataset_sha256 = _aggregate_hash(dataset_hashes)
    try:
        output = _run_isolated_raw_forward(config)
    except Graph2PlanRawError:
        raise
    except Exception as error:
        raise Graph2PlanRawError(
            f"raw forward failed: {type(error).__name__}: {error}"
        ) from None
    repository_after = _repository_provenance(config.repository_path)
    if (
        repository_after.revision != repository.revision
        or repository_after.tracked_source_sha256
        != repository.tracked_source_sha256
    ):
        raise Graph2PlanRawError(
            "repository tracked source changed during raw forward"
        )
    if _sha256_file(config.checkpoint_path) != checkpoint_sha256:
        raise Graph2PlanRawError("checkpoint changed during raw forward")
    dataset_hashes_after = {
        path.name: _sha256_file(path)
        for path in dataset_files
    }
    if dataset_hashes_after != dataset_hashes:
        raise Graph2PlanRawError("dataset changed during raw forward")

    target = config.output_path
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.staging-",
            dir=target.parent,
        )
    )
    arrays_path = staging / "graph2plan-raw-forward.npz"
    input_path = staging / "graph2plan-input-condition.npz"
    png_path = staging / "graph2plan-raw-preview.png"
    metadata_path = staging / "graph2plan-raw-metadata.json"
    try:
        np.savez_compressed(
            arrays_path,
            gene=output.gene,
            predBox=output.pred_box,
            refineBox=output.refine_box,
        )
        np.savez_compressed(
            input_path,
            rawBoundary=output.input_boundary,
            boundary=output.input_boundary_raster,
            insideBox=output.inside_box,
            graphBoxes=output.input_graph_boxes,
            graphEdges=output.input_graph_edges,
            rooms=output.room_types,
            attributes=output.attributes,
            triples=output.triples,
        )
        _render_preview(output, png_path)
        raw_artifacts = {
            arrays_path.name: _sha256_file(arrays_path),
            input_path.name: _sha256_file(input_path),
            png_path.name: _sha256_file(png_path),
        }
        metadata = _metadata(
            config=config,
            output=output,
            repository=repository,
            checkpoint_sha256=checkpoint_sha256,
            dataset_sha256=dataset_sha256,
            dataset_hashes=dataset_hashes,
            raw_artifacts=raw_artifacts,
            total_seconds=time.perf_counter() - started,
        )
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        _verify_staged_artifacts(staging, metadata)
        _publish_directory_locked(staging, target)
    except Exception as error:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if isinstance(error, Graph2PlanRawError):
            raise
        raise Graph2PlanRawError(
            f"artifact write failed: {type(error).__name__}: {error}"
        ) from None
    arrays_path = target / arrays_path.name
    input_path = target / input_path.name
    png_path = target / png_path.name
    metadata_path = target / metadata_path.name
    return Graph2PlanRawArtifacts(
        scope="raw_forward_only",
        arrays_path=arrays_path,
        input_path=input_path,
        png_path=png_path,
        metadata_path=metadata_path,
        metadata_sha256=_sha256_file(metadata_path),
    )


def _validate_assets(config: Graph2PlanRawConfig) -> None:
    if not config.repository_path.is_dir():
        raise Graph2PlanRawError(
            f"repository does not exist: {config.repository_path}"
        )
    if not config.checkpoint_path.is_file():
        raise Graph2PlanRawError(
            f"checkpoint does not exist: {config.checkpoint_path}"
        )
    if not config.data_path.is_dir():
        raise Graph2PlanRawError(
            f"data directory does not exist: {config.data_path}"
        )
    output = config.output_path
    if output == Path(output.anchor):
        raise Graph2PlanRawError("output directory cannot be a filesystem root")
    protected = (
        config.repository_path,
        config.data_path,
        config.checkpoint_path,
    )
    if any(
        output == path
        or output in path.parents
        or path in output.parents
        for path in protected
    ):
        raise Graph2PlanRawError(
            "output directory must not overlap repository, checkpoint, or data"
        )
    if output.exists():
        _validate_owned_output_directory(output)
    for path in _dataset_files(config.data_path):
        if not path.is_file():
            raise Graph2PlanRawError(
                f"dataset file does not exist: {path}"
            )
    if config.device == "cuda":
        try:
            import torch
        except ImportError:
            raise Graph2PlanRawError("PyTorch is unavailable") from None
        if not torch.cuda.is_available():
            raise Graph2PlanRawError("CUDA device requested but unavailable")


def _dataset_files(data_path: Path) -> tuple[Path, Path]:
    return data_path / _TEST_DATA, data_path / _TRAIN_DATA


def _run_isolated_raw_forward(config: Graph2PlanRawConfig) -> RawForwardOutput:
    with tempfile.TemporaryDirectory(prefix="plan-graph2plan-worker-") as temporary:
        exchange = Path(temporary)
        nonce = uuid.uuid4().hex
        request_path = exchange / "request.json"
        response_path = exchange / "response.json"
        arrays_path = exchange / "worker-output.npz"
        stderr_path = exchange / "worker-stderr.log"
        request_path.write_text(
            json.dumps(
                {
                    "protocol_version": _WORKER_PROTOCOL_VERSION,
                    "nonce": nonce,
                    "repository_path": str(config.repository_path),
                    "checkpoint_path": str(config.checkpoint_path),
                    "data_path": str(config.data_path),
                    "record_index": config.record_index,
                    "device": config.device,
                    "response_path": str(response_path),
                    "arrays_path": str(arrays_path),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            with stderr_path.open("wb") as stderr:
                completed = subprocess.run(
                    (
                        sys.executable,
                        "-m",
                        "backend.app.modules.generator_adapters.graph2plan_raw",
                        "--worker",
                        str(request_path),
                    ),
                    cwd=Path(__file__).resolve().parents[4],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                    timeout=config.timeout_seconds,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            raise Graph2PlanRawError(
                f"raw forward worker timed out after "
                f"{config.timeout_seconds:g} seconds"
            ) from None
        except OSError as error:
            raise Graph2PlanRawError(
                f"raw forward worker failed to start: {error}"
            ) from None
        if completed.returncode != 0:
            detail = _bounded_text(stderr_path, 65_536)
            if response_path.is_file():
                try:
                    response = _load_bounded_json(response_path)
                    detail = str(response.get("error") or detail)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            raise Graph2PlanRawError(
                f"raw forward worker exited with code "
                f"{completed.returncode}: {detail or 'no error detail'}"
            )
        if not response_path.is_file() or not arrays_path.is_file():
            raise Graph2PlanRawError(
                "raw forward worker did not produce JSON/NPZ exchange"
            )
        try:
            response = _load_bounded_json(response_path)
            if response.get("protocol_version") != _WORKER_PROTOCOL_VERSION:
                raise ValueError("worker protocol_version mismatch")
            if response.get("nonce") != nonce:
                raise ValueError("worker nonce mismatch")
            if response.get("status") != "executed":
                raise ValueError("worker status is not executed")
            with np.load(arrays_path, allow_pickle=False) as arrays:
                expected = {
                    "gene",
                    "predBox",
                    "refineBox",
                    "rawBoundary",
                    "boundary",
                    "insideBox",
                    "graphBoxes",
                    "graphEdges",
                    "rooms",
                    "attributes",
                    "triples",
                }
                if set(arrays.files) != expected:
                    raise ValueError("worker NPZ has unexpected array members")
                copied = {name: arrays[name].copy() for name in expected}
            _validate_worker_arrays(copied)
            return RawForwardOutput(
                input_id=str(response["input_id"]),
                query_record_index=int(response["query_record_index"]),
                retrieved_record_index=int(response["retrieved_record_index"]),
                gene=copied["gene"],
                pred_box=copied["predBox"],
                refine_box=copied["refineBox"],
                input_boundary=copied["rawBoundary"],
                input_boundary_raster=copied["boundary"],
                inside_box=copied["insideBox"],
                input_graph_boxes=copied["graphBoxes"],
                input_graph_edges=copied["graphEdges"],
                room_types=copied["rooms"],
                attributes=copied["attributes"],
                triples=copied["triples"],
                input_shapes={
                    str(name): [int(value) for value in shape]
                    for name, shape in response["input_shapes"].items()
                },
                class_legend=tuple(
                    (
                        int(item[0]),
                        str(item[1]),
                        tuple(int(channel) for channel in item[2]),
                    )
                    for item in response["class_legend"]
                ),
                torch_version=str(response["torch_version"]),
                model_load_seconds=float(response["model_load_seconds"]),
                forward_seconds=float(response["forward_seconds"]),
            )
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise Graph2PlanRawError(
                f"invalid raw forward worker exchange: {error}"
            ) from None


def _execute_official_raw_forward(
    config: Graph2PlanRawConfig,
) -> RawForwardOutput:
    with _official_runtime(config.repository_path) as runtime:
        torch = runtime.torch
        torch.manual_seed(_SEED)
        np.random.seed(_SEED)
        if config.device == "cuda":
            torch.cuda.manual_seed_all(_SEED)
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True

        query, graph, retrieved_index = _load_record_pair(
            config.data_path,
            config.record_index,
        )
        floorplan_boundary = runtime.floorplan_type(query)
        floorplan_graph = runtime.floorplan_type(graph)
        transferred = floorplan_boundary.adapt_graph(floorplan_graph)
        transferred.adjust_graph()
        transferred.data.rType = transferred.get_rooms(tensor=False)
        transferred.data.rEdge = transferred.get_triples(
            tensor=False,
        )[:, [0, 2, 1]]
        boundary, inside_box, rooms, attributes, triples = (
            transferred.get_test_data()
        )
        boundary = boundary.unsqueeze(0).to(config.device)
        inside_box = inside_box.to(config.device)
        rooms = rooms.to(config.device)
        attributes = attributes.to(config.device)
        triples = triples.to(config.device)

        load_started = time.perf_counter()
        model = runtime.model_type()
        state = torch.load(
            config.checkpoint_path,
            map_location="cpu",
            weights_only=True,
        )
        model.load_state_dict(state, strict=True)
        model.to(config.device)
        model.eval()
        model_load_seconds = time.perf_counter() - load_started

        forward_started = time.perf_counter()
        with torch.no_grad():
            boxes_pred, gene_layout, boxes_refine = model(
                rooms,
                triples,
                boundary,
                obj_to_img=None,
                attributes=attributes,
                boxes_gt=None,
                generate=True,
                refine=True,
                relative=True,
                inside_box=inside_box,
            )
        if config.device == "cuda":
            torch.cuda.synchronize()
        forward_seconds = time.perf_counter() - forward_started

        pred_box = (
            runtime.centers_to_extents(boxes_pred)
            .mul(255)
            .squeeze()
            .detach()
            .cpu()
            .numpy()
            .astype(np.int64)
        )
        refine_box = (
            runtime.centers_to_extents(boxes_refine)
            .mul(255)
            .squeeze()
            .detach()
            .cpu()
            .numpy()
            .astype(np.int64)
        )
        if pred_box.ndim == 1:
            pred_box = pred_box.reshape(1, 4)
        if refine_box.ndim == 1:
            refine_box = refine_box.reshape(1, 4)
        gene = torch.argmax(
            gene_layout.softmax(1).detach(),
            dim=1,
        )[0]
        gene[boundary[0, 0] == 0] = 13
        gene_array = gene.cpu().numpy().astype(np.int64)
        graph_name = str(getattr(graph, "name", retrieved_index))
        legend = tuple(
            (
                int(index),
                str(label[1]),
                tuple(int(channel) for channel in runtime.colormap_255[index]),
            )
            for index, label in enumerate(runtime.room_label)
            if index < len(runtime.colormap_255)
        )
        return RawForwardOutput(
            input_id=(
                f"test:{config.record_index}/"
                f"train:{retrieved_index}:{graph_name}"
            ),
            query_record_index=config.record_index,
            retrieved_record_index=retrieved_index,
            gene=gene_array,
            pred_box=pred_box,
            refine_box=refine_box,
            input_boundary=np.asarray(query.boundary),
            input_boundary_raster=boundary.detach().cpu().numpy(),
            inside_box=inside_box.detach().cpu().numpy(),
            input_graph_boxes=np.asarray(transferred.data.box),
            input_graph_edges=np.asarray(transferred.data.edge),
            room_types=rooms.detach().cpu().numpy(),
            attributes=attributes.detach().cpu().numpy(),
            triples=triples.detach().cpu().numpy(),
            input_shapes={
                "boundary": list(boundary.shape),
                "inside_box": list(inside_box.shape),
                "rooms": list(rooms.shape),
                "attributes": list(attributes.shape),
                "triples": list(triples.shape),
            },
            class_legend=legend,
            torch_version=str(torch.__version__),
            model_load_seconds=model_load_seconds,
            forward_seconds=forward_seconds,
        )


def _load_record_pair(
    data_path: Path,
    record_index: int,
) -> tuple[object, object, int]:
    test_path, train_path = _dataset_files(data_path)
    with test_path.open("rb") as stream:
        test_payload = pickle.load(stream)
    with train_path.open("rb") as stream:
        train_payload = pickle.load(stream)
    test_records = test_payload.get("data")
    train_records = train_payload.get("data")
    if test_records is None or train_records is None:
        raise Graph2PlanRawError("dataset payload has no data records")
    if record_index >= len(test_records):
        raise Graph2PlanRawError(
            f"record_index {record_index} is outside test dataset "
            f"length {len(test_records)}"
        )
    query = test_records[record_index]
    top_k = np.asarray(getattr(query, "topK", ())).reshape(-1)
    if not len(top_k):
        raise Graph2PlanRawError(
            f"test record {record_index} has no retrieved graph indexes"
        )
    retrieved_index = int(top_k[0])
    if retrieved_index < 0 or retrieved_index >= len(train_records):
        raise Graph2PlanRawError(
            f"retrieved graph index {retrieved_index} is outside training "
            f"dataset length {len(train_records)}"
        )
    return query, train_records[retrieved_index], retrieved_index


@contextmanager
def _official_runtime(
    repository_path: Path,
) -> Iterator[_OfficialRuntime]:
    postprocess = (repository_path / "PostProcess").resolve()
    if not (postprocess / "g2p").is_dir():
        raise Graph2PlanRawError(
            f"official PostProcess/g2p package does not exist: {postprocess}"
        )
    previous = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name == "g2p" or name.startswith("g2p.")
    }
    for name in previous:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(postprocess))
    try:
        torch = importlib.import_module("torch")
        model_module = importlib.import_module("g2p.model")
        floorplan_module = importlib.import_module("g2p.floorplan")
        box_module = importlib.import_module("g2p.box_utils")
        utils_module = importlib.import_module("g2p.utils")
        for module in (
            model_module,
            floorplan_module,
            box_module,
            utils_module,
        ):
            module_path = Path(module.__file__).resolve()
            if postprocess not in module_path.parents:
                raise Graph2PlanRawError(
                    f"official import escaped repository: {module_path}"
                )
        yield _OfficialRuntime(
            torch=torch,
            model_type=model_module.Model,
            floorplan_type=floorplan_module.FloorPlan,
            centers_to_extents=box_module.centers_to_extents,
            room_label=utils_module.room_label,
            colormap_255=utils_module.colormap_255,
        )
    finally:
        if sys.path and sys.path[0] == str(postprocess):
            sys.path.pop(0)
        else:
            try:
                sys.path.remove(str(postprocess))
            except ValueError:
                pass
        for name in tuple(sys.modules):
            if name == "g2p" or name.startswith("g2p."):
                sys.modules.pop(name, None)
        sys.modules.update(previous)


def _render_preview(output: RawForwardOutput, path: Path) -> None:
    from PIL import Image, ImageDraw

    palette = {
        index: color
        for index, _name, color in output.class_legend
    }
    fallback = (220, 220, 220)
    rgb = np.empty((*output.gene.shape, 3), dtype=np.uint8)
    for value in np.unique(output.gene):
        rgb[output.gene == value] = palette.get(int(value), fallback)
    image = Image.fromarray(rgb, mode="RGB").resize(
        (512, 512),
        resample=Image.Resampling.NEAREST,
    )
    draw = ImageDraw.Draw(image)
    for box in output.pred_box:
        _draw_dotted_rectangle(
            draw,
            _scaled_box(box),
            fill=(30, 80, 210),
            width=2,
        )
    for box in output.refine_box:
        draw.rectangle(
            _scaled_box(box),
            outline=(220, 35, 35),
            width=3,
        )
    image.save(path, format="PNG")


def _scaled_box(box: np.ndarray) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = (int(value) for value in box)
    return (
        min(x0, x1) * 2,
        min(y0, y1) * 2,
        max(x0, x1) * 2,
        max(y0, y1) * 2,
    )


def _draw_dotted_rectangle(
    draw,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int],
    width: int,
) -> None:
    x0, y0, x1, y1 = box
    dash = 8
    gap = 6
    for start, end, horizontal in (
        ((x0, y0), (x1, y0), True),
        ((x0, y1), (x1, y1), True),
        ((x0, y0), (x0, y1), False),
        ((x1, y0), (x1, y1), False),
    ):
        length = end[0] - start[0] if horizontal else end[1] - start[1]
        for offset in range(0, max(0, length) + 1, dash + gap):
            stop = min(length, offset + dash)
            if horizontal:
                segment = (
                    start[0] + offset,
                    start[1],
                    start[0] + stop,
                    start[1],
                )
            else:
                segment = (
                    start[0],
                    start[1] + offset,
                    start[0],
                    start[1] + stop,
                )
            draw.line(segment, fill=fill, width=width)


def _metadata(
    *,
    config: Graph2PlanRawConfig,
    output: RawForwardOutput,
    repository: _RepositoryProvenance,
    checkpoint_sha256: str,
    dataset_sha256: str,
    dataset_hashes: dict[str, str],
    raw_artifacts: dict[str, str],
    total_seconds: float,
) -> dict:
    return {
        "artifact_schema_version": 1,
        "artifact_owner": "PLAN:graph2plan_raw",
        "backend": "graph2plan",
        "scope": "raw_forward_only",
        "candidate_status": "RAW_OUTPUT_NOT_VALIDATED",
        "paper_pipeline_complete": False,
        "candidate_emitted": False,
        "raw_forward": {
            "completed": True,
            "generate": True,
            "refine": True,
        },
        "postprocess": {
            "status": "not_run",
            "stages": ["align", "decorate"],
        },
        "normalization": {"status": "not_run"},
        "validation": {"status": "not_run"},
        "security": {
            "process_isolation": True,
            "sandbox": False,
            "asset_trust": (
                "Repository, checkpoint, and dataset are trusted caller-"
                "supplied assets pinned by recorded hashes. Process isolation "
                "does not prevent filesystem or network access."
            ),
        },
        "publication": {
            "method": (
                "windows_named_mutex_or_posix_flock_directory_swap"
            ),
            "atomic": False,
            "crash_recovery": "owned backup restore on the next publication",
        },
        "determinism": {
            "seed": _SEED,
            "note": (
                "Fixed NumPy/PyTorch seeds and eval mode were requested. "
                "Repeat-run tensor equality has not been verified."
            ),
            "repeat_run_verified": False,
        },
        "environment": {
            "python": platform.python_version(),
            "torch": output.torch_version,
            "device": config.device,
            "platform": platform.platform(),
        },
        "repository": {
            "path": str(config.repository_path),
            "revision": repository.revision,
            "remote_url": repository.remote_url,
            "tracked_worktree_clean": repository.tracked_worktree_clean,
            "tracked_changes": list(repository.tracked_changes),
            "tracked_source_sha256": repository.tracked_source_sha256,
        },
        "checkpoint": {
            "path": str(config.checkpoint_path),
            "sha256": checkpoint_sha256,
            "strict_load": True,
        },
        "dataset": {
            "path": str(config.data_path),
            "sha256": dataset_sha256,
            "files": dataset_hashes,
        },
        "input": {
            "id": output.input_id,
            "query_record_index": output.query_record_index,
            "retrieved_record_index": output.retrieved_record_index,
            "shapes": output.input_shapes,
            "artifact_arrays": {
                "rawBoundary": list(output.input_boundary.shape),
                "boundary": list(output.input_boundary_raster.shape),
                "insideBox": list(output.inside_box.shape),
                "graphBoxes": list(output.input_graph_boxes.shape),
                "graphEdges": list(output.input_graph_edges.shape),
                "rooms": list(output.room_types.shape),
                "attributes": list(output.attributes.shape),
                "triples": list(output.triples.shape),
            },
        },
        "outputs": {
            "representation": (
                "derived_forward_outputs: boxes converted to integer extents in "
                "0..255 coordinates; gene is argmax class map with exterior mask"
            ),
            "gene_shape": list(output.gene.shape),
            "predBox_shape": list(output.pred_box.shape),
            "refineBox_shape": list(output.refine_box.shape),
        },
        "quality_observations": {
            "predBox_overlap": _box_overlap_metrics(output.pred_box),
            "refineBox_overlap": _box_overlap_metrics(output.refine_box),
            "note": (
                "Raw overlap metrics are observations only; geometry has not "
                "been aligned, decorated, normalized, or validated."
            ),
        },
        "legend": {
            "classes": [
                {"index": index, "name": name, "rgb": list(color)}
                for index, name, color in output.class_legend
            ],
            "boxes": {
                "predBox": "blue dotted",
                "refineBox": "red solid",
            },
        },
        "artifacts": {
            name: {"sha256": digest}
            for name, digest in raw_artifacts.items()
        },
        "timing_seconds": {
            "model_load": output.model_load_seconds,
            "forward": output.forward_seconds,
            "total": total_seconds,
        },
    }


def _box_overlap_metrics(boxes: np.ndarray) -> dict[str, int]:
    normalized = [
        (
            min(int(box[0]), int(box[2])),
            min(int(box[1]), int(box[3])),
            max(int(box[0]), int(box[2])),
            max(int(box[1]), int(box[3])),
        )
        for box in boxes
    ]
    intersecting = 0
    area = 0
    for index, left in enumerate(normalized):
        for right in normalized[index + 1 :]:
            width = max(
                0,
                min(left[2], right[2]) - max(left[0], right[0]),
            )
            height = max(
                0,
                min(left[3], right[3]) - max(left[1], right[1]),
            )
            intersection = width * height
            if intersection > 0:
                intersecting += 1
                area += intersection
    return {
        "box_count": len(normalized),
        "pair_count": len(normalized) * (len(normalized) - 1) // 2,
        "intersecting_pair_count": intersecting,
        "total_intersection_area_coordinate_units2": area,
    }


def _repository_provenance(repository_path: Path) -> _RepositoryProvenance:
    revision = _git_output(
        repository_path,
        ("rev-parse", "HEAD"),
        "revision",
    ).strip()
    remote_url = _sanitize_remote_url(_git_output(
        repository_path,
        ("remote", "get-url", "origin"),
        "origin remote",
    ).strip())
    status = _git_output(
        repository_path,
        ("status", "--porcelain", "--untracked-files=no"),
        "tracked worktree status",
    )
    tracked_changes = tuple(
        line for line in status.splitlines() if line.strip()
    )
    tracked = _git_output(
        repository_path,
        ("ls-files", "-z"),
        "tracked source listing",
    )
    source_hashes: dict[str, str] = {}
    for relative in (name for name in tracked.split("\0") if name):
        path = repository_path / relative
        resolved = path.resolve(strict=False)
        if repository_path not in resolved.parents and resolved != repository_path:
            raise Graph2PlanRawError(
                f"tracked source path escapes repository: {relative}"
            )
        if path.is_symlink():
            digest = hashlib.sha256(
                os.readlink(path).encode("utf-8")
            ).hexdigest()
        elif path.is_file():
            digest = _sha256_file(path)
        else:
            raise Graph2PlanRawError(
                f"tracked source file does not exist: {relative}"
            )
        source_hashes[relative.replace("\\", "/")] = digest
    if not source_hashes:
        raise Graph2PlanRawError("repository has no tracked source files")
    return _RepositoryProvenance(
        revision=revision,
        remote_url=remote_url,
        tracked_worktree_clean=not tracked_changes,
        tracked_changes=tracked_changes,
        tracked_source_sha256=_aggregate_hash(source_hashes),
    )


def _sanitize_remote_url(value: str) -> str:
    if not value or "\n" in value or "\r" in value:
        raise Graph2PlanRawError("repository origin remote is invalid")
    if "://" in value:
        parsed = urlsplit(value)
        if not parsed.hostname:
            raise Graph2PlanRawError("repository origin remote has no host")
        host = parsed.hostname
        try:
            if parsed.port is not None:
                host = f"{host}:{parsed.port}"
        except ValueError:
            raise Graph2PlanRawError(
                "repository origin remote has an invalid port"
            ) from None
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    if "@" in value:
        return value.rsplit("@", 1)[1]
    return value


def _git_output(
    repository_path: Path,
    arguments: tuple[str, ...],
    label: str,
) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_path), *arguments),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
        raise Graph2PlanRawError(
            f"repository {label} check failed: {error}"
        ) from None
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "no output returned"
        raise Graph2PlanRawError(
            f"repository {label} check failed: {detail}"
        )
    return completed.stdout


def _verify_staged_artifacts(staging: Path, metadata: dict) -> None:
    actual_names = {path.name for path in staging.iterdir() if path.is_file()}
    if actual_names != _ARTIFACT_NAMES:
        raise Graph2PlanRawError(
            "staged Graph2Plan artifacts are incomplete or unexpected"
        )
    for name, record in metadata["artifacts"].items():
        if _sha256_file(staging / name) != record["sha256"]:
            raise Graph2PlanRawError(
                f"staged artifact hash mismatch: {name}"
            )


def _validate_owned_output_directory(target: Path) -> dict:
    if target.is_symlink() or not target.is_dir():
        raise Graph2PlanRawError(
            f"output path exists and is not an owned directory: {target}"
        )
    entries = list(target.iterdir())
    if (
        {entry.name for entry in entries} != _ARTIFACT_NAMES
        or any(entry.is_symlink() or not entry.is_file() for entry in entries)
    ):
        raise Graph2PlanRawError(
            "existing output is not a recognized Graph2Plan raw artifact "
            "directory"
        )
    metadata_path = target / "graph2plan-raw-metadata.json"
    try:
        metadata = _load_json_with_limit(
            metadata_path,
            _MAX_ARTIFACT_METADATA_BYTES,
            "artifact metadata",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise Graph2PlanRawError(
            f"existing output has invalid Graph2Plan metadata: {error}"
        ) from None
    if (
        metadata.get("artifact_schema_version") != 1
        or metadata.get("artifact_owner") != "PLAN:graph2plan_raw"
        or metadata.get("backend") != "graph2plan"
        or metadata.get("scope") != "raw_forward_only"
    ):
        raise Graph2PlanRawError(
            "existing output is not owned by this Graph2Plan raw publisher"
        )
    expected_artifacts = _ARTIFACT_NAMES - {
        "graph2plan-raw-metadata.json"
    }
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != expected_artifacts:
        raise Graph2PlanRawError(
            "existing output Graph2Plan artifact manifest is invalid"
        )
    for name in expected_artifacts:
        record = artifacts[name]
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
            or _sha256_file(target / name) != record["sha256"]
        ):
            raise Graph2PlanRawError(
                f"existing output Graph2Plan artifact hash mismatch: {name}"
            )
    return metadata


@contextmanager
def _publication_lock(target: Path) -> Iterator[None]:
    if os.name == "nt":
        with _windows_named_mutex(target):
            yield
        return
    with _posix_file_lock(target):
        yield


@contextmanager
def _windows_named_mutex(target: Path) -> Iterator[None]:
    from ctypes import wintypes

    normalized = os.path.normcase(
        str(target.resolve(strict=False))
    ).replace("\\", "/")
    key = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    mutex_name = f"Local\\PLAN_graph2plan_raw_{key}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
    )
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        raise Graph2PlanRawError(
            "cannot create output publication mutex: "
            f"Windows error {ctypes.get_last_error()}"
        )
    wait_object_0 = 0
    wait_abandoned = 0x80
    wait_timeout = 0x102
    wait_failed = 0xFFFFFFFF
    timeout_ms = max(1, int(_PUBLISH_LOCK_TIMEOUT_SECONDS * 1000))
    acquired = False
    try:
        result = kernel32.WaitForSingleObject(handle, timeout_ms)
        if result in {wait_object_0, wait_abandoned}:
            acquired = True
        elif result == wait_timeout:
            raise Graph2PlanRawError(
                f"timed out waiting for output publication lock: {target}"
            )
        elif result == wait_failed:
            raise Graph2PlanRawError(
                "output publication mutex wait failed: "
                f"Windows error {ctypes.get_last_error()}"
            )
        else:
            raise Graph2PlanRawError(
                f"unexpected output publication mutex result: {result}"
            )
        yield
    finally:
        if acquired:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


@contextmanager
def _posix_file_lock(target: Path) -> Iterator[None]:
    import fcntl
    import stat

    lock_path = target.with_name(f".{target.name}.publish.lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise Graph2PlanRawError(
            f"cannot open output publication lock: {error}"
        ) from None
    deadline = time.monotonic() + _PUBLISH_LOCK_TIMEOUT_SECONDS
    acquired = False
    try:
        opened = os.fstat(descriptor)
        linked = os.lstat(lock_path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino)
            != (linked.st_dev, linked.st_ino)
        ):
            raise Graph2PlanRawError(
                f"unsafe output publication lock path: {lock_path}"
            )
        while True:
            try:
                fcntl.flock(
                    descriptor,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise Graph2PlanRawError(
                        f"timed out waiting for output publication lock: "
                        f"{target}"
                    ) from None
                time.sleep(0.05)
        linked_after = os.lstat(lock_path)
        if (
            opened.st_dev,
            opened.st_ino,
        ) != (
            linked_after.st_dev,
            linked_after.st_ino,
        ):
            raise Graph2PlanRawError(
                f"output publication lock path changed: {lock_path}"
            )
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _recover_publication_state(target: Path) -> None:
    backups = sorted(
        target.parent.glob(f".{target.name}.backup-*"),
        key=lambda path: path.name,
    )
    for backup in backups:
        _validate_owned_output_directory(backup)
    if target.exists():
        _validate_owned_output_directory(target)
        for backup in backups:
            shutil.rmtree(backup)
        return
    if len(backups) > 1:
        raise Graph2PlanRawError(
            f"multiple recoverable output backups exist for: {target}"
        )
    if backups:
        backups[0].rename(target)


def _publish_directory_locked(staging: Path, target: Path) -> None:
    with _publication_lock(target):
        _recover_publication_state(target)
        _publish_directory_swap(staging, target)


def _publish_directory_swap(staging: Path, target: Path) -> None:
    backup = target.with_name(
        f".{target.name}.backup-{uuid.uuid4().hex}"
    )
    moved_existing = False
    try:
        if target.exists():
            _validate_owned_output_directory(target)
            target.rename(backup)
            moved_existing = True
        staging.rename(target)
    except Exception:
        if moved_existing and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _bounded_text(path: Path, limit: int) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace").strip()


def _load_bounded_json(path: Path) -> dict:
    return _load_json_with_limit(
        path,
        _MAX_WORKER_RESPONSE_BYTES,
        "worker JSON response",
    )


def _load_json_with_limit(path: Path, limit: int, label: str) -> dict:
    size = path.stat().st_size
    if size > limit:
        raise ValueError(f"{label} exceeds size limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object")
    return payload


def _validate_worker_arrays(arrays: dict[str, np.ndarray]) -> None:
    for name, value in arrays.items():
        if value.dtype.hasobject:
            raise ValueError(f"worker array {name} has object dtype")
        if not np.issubdtype(value.dtype, np.number):
            raise ValueError(f"worker array {name} is not numeric")
        if not np.isfinite(value).all():
            raise ValueError(f"worker array {name} contains non-finite values")
    gene = arrays["gene"]
    rooms = arrays["rooms"]
    boxes = (arrays["predBox"], arrays["refineBox"])
    if gene.ndim != 2 or not np.issubdtype(gene.dtype, np.integer):
        raise ValueError("worker gene must be a 2D integer array")
    if gene.size == 0 or int(gene.min()) < 0 or int(gene.max()) > 255:
        raise ValueError("worker gene class values are outside 0..255")
    if rooms.ndim != 1 or not np.issubdtype(rooms.dtype, np.integer):
        raise ValueError("worker rooms must be a 1D integer array")
    if rooms.size and (int(rooms.min()) < 0 or int(rooms.max()) > 255):
        raise ValueError("worker room values are outside 0..255")
    for name, value in zip(("predBox", "refineBox"), boxes):
        if (
            value.ndim != 2
            or value.shape != (len(rooms), 4)
            or not np.issubdtype(value.dtype, np.integer)
        ):
            raise ValueError(
                f"worker {name} must be an integer room_count x 4 array"
            )
        if value.size and (int(value.min()) < 0 or int(value.max()) > 255):
            raise ValueError(f"worker {name} coordinates are outside 0..255")
    expected_shapes = {
        "rawBoundary": (2, 4),
        "boundary": (4, None),
        "insideBox": (2, 4),
        "graphBoxes": (2, 5),
        "graphEdges": (2, 3),
        "attributes": (2, None),
        "triples": (2, 3),
    }
    for name, (ndim, last) in expected_shapes.items():
        value = arrays[name]
        if value.ndim != ndim or (last is not None and value.shape[-1] != last):
            raise ValueError(f"worker {name} has invalid shape")
    if arrays["boundary"].shape[0] != 1:
        raise ValueError("worker boundary batch size must be one")
    if arrays["attributes"].shape[0] != len(rooms):
        raise ValueError("worker attributes row count must match rooms")
    if arrays["insideBox"].shape[0] != 1:
        raise ValueError("worker insideBox must contain one bounding box")
    for name in (
        "rawBoundary",
        "graphBoxes",
        "rooms",
        "triples",
        "graphEdges",
    ):
        if not np.issubdtype(arrays[name].dtype, np.integer):
            raise ValueError(f"worker {name} must use an integer dtype")
    for name in ("rawBoundary", "graphBoxes", "triples", "graphEdges"):
        value = arrays[name]
        if value.size and (int(value.min()) < 0 or int(value.max()) > 255):
            raise ValueError(f"worker {name} values are outside 0..255")
    for name in ("boundary", "insideBox", "attributes"):
        value = arrays[name]
        if value.size and (float(value.min()) < 0 or float(value.max()) > 1):
            raise ValueError(f"worker {name} values are outside 0..1")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _aggregate_hash(hashes: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(hashes.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _write_worker_exchange(
    output: RawForwardOutput,
    arrays_path: Path,
    response_path: Path,
    *,
    nonce: str,
) -> None:
    np.savez_compressed(
        arrays_path,
        gene=output.gene,
        predBox=output.pred_box,
        refineBox=output.refine_box,
        rawBoundary=output.input_boundary,
        boundary=output.input_boundary_raster,
        insideBox=output.inside_box,
        graphBoxes=output.input_graph_boxes,
        graphEdges=output.input_graph_edges,
        rooms=output.room_types,
        attributes=output.attributes,
        triples=output.triples,
    )
    response_path.write_text(
        json.dumps(
            {
                "protocol_version": _WORKER_PROTOCOL_VERSION,
                "nonce": nonce,
                "status": "executed",
                "input_id": output.input_id,
                "query_record_index": output.query_record_index,
                "retrieved_record_index": output.retrieved_record_index,
                "input_shapes": output.input_shapes,
                "class_legend": output.class_legend,
                "torch_version": output.torch_version,
                "model_load_seconds": output.model_load_seconds,
                "forward_seconds": output.forward_seconds,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _worker_entry(request_path: Path) -> int:
    response_path: Path | None = None
    nonce: str | None = None
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request.get("protocol_version") != _WORKER_PROTOCOL_VERSION:
            raise ValueError("unsupported worker protocol_version")
        nonce = request.get("nonce")
        if not isinstance(nonce, str) or len(nonce) != 32:
            raise ValueError("worker nonce is invalid")
        response_path = Path(request["response_path"]).resolve(strict=False)
        arrays_path = Path(request["arrays_path"]).resolve(strict=False)
        exchange = request_path.parent.resolve()
        if (
            response_path.parent != exchange
            or arrays_path.parent != exchange
        ):
            raise ValueError("worker exchange paths must stay in request directory")
        config = Graph2PlanRawConfig(
            repository_path=Path(request["repository_path"]),
            checkpoint_path=Path(request["checkpoint_path"]),
            data_path=Path(request["data_path"]),
            output_path=exchange / "unused-output",
            record_index=request["record_index"],
            device=request["device"],
        )
        _validate_assets(config)
        output = _execute_official_raw_forward(config)
        _write_worker_exchange(
            output,
            arrays_path,
            response_path,
            nonce=nonce,
        )
        return 0
    except Exception as error:
        if response_path is not None:
            try:
                response_path.write_text(
                    json.dumps(
                        {
                            "protocol_version": _WORKER_PROTOCOL_VERSION,
                            "nonce": nonce,
                            "status": "failed",
                            "error": f"{type(error).__name__}: {error}",
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
            except OSError:
                pass
        return 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        raise SystemExit(_worker_entry(Path(sys.argv[2]).resolve(strict=False)))
    raise SystemExit("graph2plan_raw is an internal worker module")
