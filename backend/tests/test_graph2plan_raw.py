from __future__ import annotations

import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

import backend.app.cli as cli_module
import backend.app.modules.generator_adapters.graph2plan_raw as raw_module
from backend.app.modules.generator_adapters.graph2plan_raw import (
    Graph2PlanRawConfig,
    Graph2PlanRawError,
    RawForwardOutput,
    run_graph2plan_raw_benchmark,
)


def _configured_paths(tmp_path: Path) -> Graph2PlanRawConfig:
    repository = tmp_path / "Graph2plan"
    data = tmp_path / "data"
    output = tmp_path / "output"
    checkpoint = repository / "model.pth"
    repository.mkdir()
    data.mkdir()
    checkpoint.write_bytes(b"checkpoint")
    (data / "data_test_converted.pkl").write_bytes(b"test")
    (data / "data_train_converted.pkl").write_bytes(b"train")
    return Graph2PlanRawConfig(
        repository_path=repository,
        checkpoint_path=checkpoint,
        data_path=data,
        output_path=output,
        record_index=7,
        device="cpu",
    )


def _raw_output() -> RawForwardOutput:
    gene = np.zeros((128, 128), dtype=np.int64)
    gene[24:96, 30:98] = 2
    return RawForwardOutput(
        input_id="test:7/train:19",
        query_record_index=7,
        retrieved_record_index=19,
        gene=gene,
        pred_box=np.array([[20, 24, 72, 80]], dtype=np.int64),
        refine_box=np.array([[22, 26, 74, 82]], dtype=np.int64),
        input_boundary=np.array(
            [[0, 0, 0, 1], [255, 0, 0, 0], [255, 255, 0, 0]],
            dtype=np.int64,
        ),
        input_boundary_raster=np.zeros((1, 3, 128, 128), dtype=np.float32),
        inside_box=np.array([[0.1, 0.2, 0.8, 0.9]], dtype=np.float32),
        input_graph_boxes=np.array([[20, 24, 72, 80, 2]], dtype=np.int64),
        input_graph_edges=np.empty((0, 3), dtype=np.int64),
        room_types=np.array([2], dtype=np.int64),
        attributes=np.zeros((1, 35), dtype=np.float32),
        triples=np.empty((0, 3), dtype=np.int64),
        input_shapes={
            "boundary": [1, 3, 128, 128],
            "inside_box": [1, 4],
            "rooms": [1],
            "attributes": [1, 35],
            "triples": [0, 3],
        },
        class_legend=(
            (0, "LivingRoom", (230, 25, 75)),
            (2, "Kitchen", (170, 255, 195)),
            (13, "External", (255, 255, 255)),
        ),
        torch_version="2.8.0-test",
        model_load_seconds=0.125,
        forward_seconds=0.25,
    )


def _repository_provenance() -> raw_module._RepositoryProvenance:
    return raw_module._RepositoryProvenance(
        revision="abc123",
        remote_url="https://github.com/HanHan55/Graph2plan.git",
        tracked_worktree_clean=True,
        tracked_changes=(),
        tracked_source_sha256="b" * 64,
    )


def _worker_arrays() -> dict[str, np.ndarray]:
    output = _raw_output()
    return {
        "gene": output.gene,
        "predBox": output.pred_box,
        "refineBox": output.refine_box,
        "rawBoundary": output.input_boundary,
        "boundary": output.input_boundary_raster,
        "insideBox": output.inside_box,
        "graphBoxes": output.input_graph_boxes,
        "graphEdges": output.input_graph_edges,
        "rooms": output.room_types,
        "attributes": output.attributes,
        "triples": output.triples,
    }


def test_raw_benchmark_retains_only_truthful_raw_forward_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: _raw_output(),
    )

    artifacts = run_graph2plan_raw_benchmark(config)
    metadata = json.loads(artifacts.metadata_path.read_text(encoding="utf-8"))
    arrays = np.load(artifacts.arrays_path)
    inputs = np.load(artifacts.input_path)

    assert artifacts.scope == "raw_forward_only"
    assert artifacts.arrays_path.is_file()
    assert artifacts.input_path.is_file()
    assert artifacts.png_path.is_file()
    assert artifacts.metadata_path.is_file()
    assert arrays.files == ["gene", "predBox", "refineBox"]
    assert arrays["gene"].shape == (128, 128)
    assert set(inputs.files) == {
        "rawBoundary",
        "boundary",
        "insideBox",
        "graphBoxes",
        "graphEdges",
        "rooms",
        "attributes",
        "triples",
    }
    assert inputs["boundary"].shape == (1, 3, 128, 128)
    assert inputs["insideBox"].shape == (1, 4)
    assert inputs["attributes"].shape == (1, 35)
    assert metadata["backend"] == "graph2plan"
    assert metadata["scope"] == "raw_forward_only"
    assert metadata["candidate_status"] == "RAW_OUTPUT_NOT_VALIDATED"
    assert metadata["raw_forward"]["completed"] is True
    assert metadata["postprocess"] == {
        "status": "not_run",
        "stages": ["align", "decorate"],
    }
    assert metadata["paper_pipeline_complete"] is False
    assert metadata["candidate_emitted"] is False
    assert metadata["normalization"] == {"status": "not_run"}
    assert metadata["validation"] == {"status": "not_run"}
    assert metadata["artifact_owner"] == "PLAN:graph2plan_raw"
    assert metadata["artifact_schema_version"] == 1
    assert metadata["publication"]["atomic"] is False
    assert metadata["security"]["process_isolation"] is True
    assert metadata["security"]["sandbox"] is False
    assert metadata["input"]["id"] == "test:7/train:19"
    assert metadata["repository"]["revision"] == "abc123"
    assert metadata["repository"]["remote_url"].endswith("Graph2plan.git")
    assert metadata["repository"]["tracked_worktree_clean"] is True
    assert metadata["repository"]["tracked_source_sha256"] == "b" * 64
    assert len(metadata["checkpoint"]["sha256"]) == 64
    assert len(metadata["dataset"]["sha256"]) == 64
    assert set(metadata["artifacts"]) == {
        "graph2plan-input-condition.npz",
        "graph2plan-raw-forward.npz",
        "graph2plan-raw-preview.png",
    }
    assert metadata["legend"]["boxes"] == {
        "predBox": "blue dotted",
        "refineBox": "red solid",
    }
    assert "normalized_candidate" not in metadata
    assert "accepted" not in metadata


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository_path", Path("relative-repository")),
        ("checkpoint_path", Path("relative-checkpoint")),
        ("data_path", Path("relative-data")),
        ("output_path", Path("relative-output")),
    ],
)
def test_raw_config_requires_explicit_absolute_paths(
    tmp_path: Path,
    field: str,
    value: Path,
) -> None:
    arguments = {
        "repository_path": tmp_path / "repository",
        "checkpoint_path": tmp_path / "checkpoint",
        "data_path": tmp_path / "data",
        "output_path": tmp_path / "output",
        "record_index": 0,
        "device": "cpu",
    }
    arguments[field] = value

    with pytest.raises(ValueError, match=f"{field} must be absolute"):
        Graph2PlanRawConfig(**arguments)


def test_raw_benchmark_reports_missing_assets_without_traceback(
    tmp_path: Path,
) -> None:
    config = Graph2PlanRawConfig(
        repository_path=tmp_path / "missing-repository",
        checkpoint_path=tmp_path / "missing-checkpoint",
        data_path=tmp_path / "missing-data",
        output_path=tmp_path / "output",
        record_index=0,
        device="cpu",
    )

    with pytest.raises(
        Graph2PlanRawError,
        match="repository does not exist",
    ):
        run_graph2plan_raw_benchmark(config)


def test_raw_benchmark_rejects_output_overlapping_untrusted_inputs(
    tmp_path: Path,
) -> None:
    config = _configured_paths(tmp_path)
    overlapping = Graph2PlanRawConfig(
        repository_path=config.repository_path,
        checkpoint_path=config.checkpoint_path,
        data_path=config.data_path,
        output_path=config.data_path / "raw-output",
        record_index=0,
    )

    with pytest.raises(Graph2PlanRawError, match="must not overlap"):
        run_graph2plan_raw_benchmark(overlapping)


def test_raw_benchmark_bounds_official_runtime_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: (_ for _ in ()).throw(
            RuntimeError("official failure")
        ),
    )

    with pytest.raises(
        Graph2PlanRawError,
        match="raw forward failed: RuntimeError: official failure",
    ):
        run_graph2plan_raw_benchmark(config)
    assert not config.output_path.exists()


def test_raw_worker_failure_preserves_existing_published_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: _raw_output(),
    )
    artifacts = run_graph2plan_raw_benchmark(config)
    previous_metadata = artifacts.metadata_path.read_bytes()
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: (_ for _ in ()).throw(
            Graph2PlanRawError("worker failed")
        ),
    )

    with pytest.raises(Graph2PlanRawError, match="worker failed"):
        run_graph2plan_raw_benchmark(config)

    assert artifacts.metadata_path.read_bytes() == previous_metadata


def test_raw_success_rejects_unowned_existing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)
    config.output_path.mkdir()
    (config.output_path / "stale.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: _raw_output(),
    )

    with pytest.raises(Graph2PlanRawError, match="not a recognized"):
        run_graph2plan_raw_benchmark(config)

    assert (config.output_path / "stale.txt").read_text() == "old"


def test_raw_success_replaces_only_recognized_owned_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: _raw_output(),
    )
    first = run_graph2plan_raw_benchmark(config)
    assert first.metadata_path.is_file()

    second = run_graph2plan_raw_benchmark(config)

    assert second.metadata_path.is_file()
    assert {path.name for path in config.output_path.iterdir()} == (
        raw_module._ARTIFACT_NAMES
    )
    assert not list(tmp_path.glob(".output.backup-*"))
    lock = tmp_path / ".output.publish.lock"
    if raw_module.os.name == "nt":
        assert not lock.exists()
    else:
        assert lock.is_file()


def test_raw_publication_recovers_owned_backup_after_interrupted_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: _raw_output(),
    )
    run_graph2plan_raw_benchmark(config)
    backup = tmp_path / ".output.backup-interrupted"
    config.output_path.rename(backup)

    artifacts = run_graph2plan_raw_benchmark(config)

    assert artifacts.metadata_path.is_file()
    assert not backup.exists()


def test_preexisting_regular_lockfile_is_not_modified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: _raw_output(),
    )
    lock = tmp_path / ".output.publish.lock"
    lock.write_text(
        "persistent lock file",
        encoding="utf-8",
    )
    before = lock.read_bytes()

    artifacts = run_graph2plan_raw_benchmark(config)

    assert artifacts.metadata_path.is_file()
    assert lock.is_file()
    assert lock.read_bytes() == before


@pytest.mark.skipif(
    raw_module.os.name != "nt",
    reason="Windows named mutex does not use the lock path",
)
@pytest.mark.parametrize("link_type", ["hardlink", "symlink"])
def test_windows_named_mutex_does_not_touch_precreated_link_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    link_type: str,
) -> None:
    config = _configured_paths(tmp_path)
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )
    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        lambda _config: _raw_output(),
    )
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("must remain unchanged", encoding="utf-8")
    lock = tmp_path / ".output.publish.lock"
    try:
        if link_type == "hardlink":
            raw_module.os.link(sentinel, lock)
        else:
            raw_module.os.symlink(sentinel, lock)
    except OSError as error:
        pytest.skip(f"{link_type} unavailable: {error}")
    before = sentinel.read_bytes()

    artifacts = run_graph2plan_raw_benchmark(config)

    assert artifacts.metadata_path.is_file()
    assert sentinel.read_bytes() == before
    assert lock.read_bytes() == before


@pytest.mark.skipif(
    raw_module.os.name == "nt",
    reason="POSIX flock path validation only",
)
@pytest.mark.parametrize("link_type", ["hardlink", "symlink"])
def test_posix_publication_lock_rejects_link_paths(
    tmp_path: Path,
    link_type: str,
) -> None:
    target = tmp_path / "output"
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unchanged")
    lock = tmp_path / ".output.publish.lock"
    if link_type == "hardlink":
        raw_module.os.link(sentinel, lock)
    else:
        raw_module.os.symlink(sentinel, lock)

    with pytest.raises(Graph2PlanRawError, match="publication lock"):
        with raw_module._publication_lock(target):
            pass
    assert sentinel.read_bytes() == b"unchanged"


def test_publication_lock_excludes_another_process(
    tmp_path: Path,
) -> None:
    target = tmp_path / "output"
    script = """
import sys
from pathlib import Path
import backend.app.modules.generator_adapters.graph2plan_raw as raw

raw._PUBLISH_LOCK_TIMEOUT_SECONDS = 0.2
try:
    with raw._publication_lock(Path(sys.argv[1])):
        print("acquired")
except raw.Graph2PlanRawError:
    print("blocked")
"""
    with raw_module._publication_lock(target):
        blocked = subprocess.run(
            [raw_module.sys.executable, "-c", script, str(target)],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    acquired = subprocess.run(
        [raw_module.sys.executable, "-c", script, str(target)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert blocked.returncode == 0
    assert blocked.stdout.strip() == "blocked"
    assert acquired.returncode == 0
    assert acquired.stdout.strip() == "acquired"


@pytest.mark.parametrize("changed_asset", ["checkpoint", "dataset"])
def test_raw_benchmark_rehashes_assets_after_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_asset: str,
) -> None:
    config = _configured_paths(tmp_path)
    monkeypatch.setattr(
        raw_module,
        "_repository_provenance",
        lambda _path: _repository_provenance(),
    )

    def mutate_asset(_config):
        if changed_asset == "checkpoint":
            config.checkpoint_path.write_bytes(b"changed checkpoint")
        else:
            (config.data_path / "data_test_converted.pkl").write_bytes(
                b"changed test data"
            )
        return _raw_output()

    monkeypatch.setattr(
        raw_module,
        "_run_isolated_raw_forward",
        mutate_asset,
    )

    with pytest.raises(Graph2PlanRawError, match=f"{changed_asset} changed"):
        run_graph2plan_raw_benchmark(config)
    assert not config.output_path.exists()


def test_raw_worker_timeout_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(raw_module.subprocess, "run", timeout)

    with pytest.raises(Graph2PlanRawError, match="timed out"):
        raw_module._run_isolated_raw_forward(config)


def test_raw_worker_rejects_response_nonce_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _configured_paths(tmp_path)

    def forged_worker(command, **_kwargs):
        request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        raw_module._write_worker_exchange(
            _raw_output(),
            Path(request["arrays_path"]),
            Path(request["response_path"]),
            nonce="0" * 32,
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(raw_module.subprocess, "run", forged_worker)

    with pytest.raises(Graph2PlanRawError, match="nonce mismatch"):
        raw_module._run_isolated_raw_forward(config)


def test_worker_response_json_is_bounded(tmp_path: Path) -> None:
    response = tmp_path / "response.json"
    response.write_bytes(b"{" + b" " * 65_536 + b"}")

    with pytest.raises(ValueError, match="exceeds size limit"):
        raw_module._load_bounded_json(response)


@pytest.mark.parametrize(
    ("array_name", "replacement", "message"),
    [
        (
            "gene",
            np.full((128, 128), np.nan, dtype=np.float32),
            "non-finite",
        ),
        (
            "predBox",
            np.zeros((2, 4), dtype=np.int64),
            "room_count x 4",
        ),
        (
            "insideBox",
            np.array([[0.0, 0.0, 1.5, 1.0]], dtype=np.float32),
            "outside 0..1",
        ),
    ],
)
def test_worker_arrays_reject_invalid_values_and_shapes(
    array_name: str,
    replacement: np.ndarray,
    message: str,
) -> None:
    arrays = _worker_arrays()
    arrays[array_name] = replacement

    with pytest.raises(ValueError, match=message):
        raw_module._validate_worker_arrays(arrays)


def test_repository_provenance_records_remote_dirty_state_and_source_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    tracked = repository / "official.py"
    tracked.write_text("print('official')\n", encoding="utf-8")

    def git_output(_repository, arguments, _label):
        if arguments == ("rev-parse", "HEAD"):
            return "deadbeef\n"
        if arguments == ("remote", "get-url", "origin"):
            return "https://github.com/HanHan55/Graph2plan.git\n"
        if arguments[0] == "status":
            return " M official.py\n"
        if arguments == ("ls-files", "-z"):
            return "official.py\0"
        raise AssertionError(arguments)

    monkeypatch.setattr(raw_module, "_git_output", git_output)

    provenance = raw_module._repository_provenance(repository)

    assert provenance.revision == "deadbeef"
    assert provenance.remote_url.endswith("Graph2plan.git")
    assert provenance.tracked_worktree_clean is False
    assert provenance.tracked_changes == (" M official.py",)
    assert len(provenance.tracked_source_sha256) == 64


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        (
            "https://user:secret@example.com/org/repo.git"
            "?access_token=secret#fragment",
            "https://example.com/org/repo.git",
        ),
        (
            "git@example.com:org/repo.git",
            "example.com:org/repo.git",
        ),
    ],
)
def test_repository_remote_credentials_are_sanitized(
    remote: str,
    expected: str,
) -> None:
    assert raw_module._sanitize_remote_url(remote) == expected


def test_box_overlap_metrics_count_positive_area_intersections() -> None:
    boxes = np.array(
        [
            [0, 0, 10, 10],
            [5, 5, 12, 12],
            [12, 0, 20, 10],
        ],
        dtype=np.int64,
    )

    metrics = raw_module._box_overlap_metrics(boxes)

    assert metrics == {
        "box_count": 3,
        "pair_count": 3,
        "intersecting_pair_count": 1,
        "total_intersection_area_coordinate_units2": 25,
    }


def test_graph2plan_raw_cli_emits_artifact_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _configured_paths(tmp_path)
    config.output_path.mkdir()
    arrays = config.output_path / "raw.npz"
    inputs = config.output_path / "input.npz"
    png = config.output_path / "raw.png"
    metadata = config.output_path / "metadata.json"
    for path in (arrays, inputs, png, metadata):
        path.write_bytes(b"artifact")
    artifacts = raw_module.Graph2PlanRawArtifacts(
        scope="raw_forward_only",
        arrays_path=arrays,
        input_path=inputs,
        png_path=png,
        metadata_path=metadata,
        metadata_sha256="a" * 64,
    )
    seen = []
    monkeypatch.setattr(
        cli_module,
        "run_graph2plan_raw_benchmark",
        lambda value: seen.append(value) or artifacts,
        raising=False,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "plan",
            "graph2plan-raw",
            "--repository",
            str(config.repository_path),
            "--checkpoint",
            str(config.checkpoint_path),
            "--data",
            str(config.data_path),
            "--output-dir",
            str(config.output_path),
            "--record-index",
            "7",
            "--device",
            "cpu",
        ],
    )

    cli_module.main()
    payload = json.loads(capsys.readouterr().out)

    assert len(seen) == 1
    assert seen[0] == config
    assert payload["scope"] == "raw_forward_only"
    assert payload["candidate_status"] == "RAW_OUTPUT_NOT_VALIDATED"
    assert payload["metadata_sha256"] == "a" * 64
    assert "normalized_candidate" not in payload
