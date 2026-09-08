from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Literal

from backend.app.modules.generator_adapters.subprocess_adapter import (
    SubprocessGeneratorAdapter,
)
from backend.app.schemas.generator_adapter import (
    GeneratorProjectFact,
    GeneratorRequest,
    GeneratorResponse,
)

ProbeStatus = Literal["executed", "unavailable", "failed"]
ProbeEvidenceScope = Literal["strict_load", "runtime_preflight"]
_IS_WINDOWS = os.name == "nt"


@dataclass(frozen=True)
class ResearchProbeRecord:
    status: ProbeStatus
    backend_id: str
    backend_version: str
    backend_domain: str
    repo_revision: str | None
    evidence_scope: ProbeEvidenceScope | None
    environment: tuple[GeneratorProjectFact, ...]
    runtime_checks: tuple[GeneratorProjectFact, ...]
    checkpoint: str | None
    dataset: str | None
    license: str | None
    provenance: str | None
    blockers: tuple[str, ...]
    reason: str | None

    def __post_init__(self) -> None:
        if self.status not in {"executed", "unavailable", "failed"}:
            raise ValueError("probe status must be executed, unavailable, or failed")
        for name in ("backend_id", "backend_version", "backend_domain"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for name in (
            "repo_revision",
            "evidence_scope",
            "checkpoint",
            "dataset",
            "license",
            "provenance",
            "reason",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{name} must be a string or None")
        for name in ("environment", "runtime_checks", "blockers"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"{name} must be an immutable tuple")
        if not all(isinstance(item, GeneratorProjectFact) for item in self.environment):
            raise TypeError("environment must contain GeneratorProjectFact records")
        if not all(
            isinstance(item, GeneratorProjectFact) for item in self.runtime_checks
        ):
            raise TypeError("runtime_checks must contain GeneratorProjectFact records")
        if not all(isinstance(item, str) and item for item in self.blockers):
            raise TypeError("blockers must contain non-empty strings")
        if self.status == "executed":
            if not self.repo_revision or not self.repo_revision.strip():
                raise ValueError("executed probes require a repo_revision")
            if self.blockers:
                raise ValueError("executed probes cannot contain blockers")
            if self.evidence_scope not in {"strict_load", "runtime_preflight"}:
                raise ValueError(
                    "executed probes require strict_load or runtime_preflight "
                    "evidence_scope"
                )
            if not self.runtime_checks:
                raise ValueError("executed probes require runtime_checks")
            if not self.provenance or not self.provenance.strip():
                raise ValueError("executed probes require provenance")
            if any(check.value is not True for check in self.runtime_checks):
                raise ValueError(
                    "executed probes require every runtime check to pass"
                )
            if self.evidence_scope == "strict_load":
                strict_load_passed = any(
                    check.name
                    in {"strict_checkpoint_load", "strict_model_load"}
                    and check.value is True
                    for check in self.runtime_checks
                )
                if not self.checkpoint or not strict_load_passed:
                    raise ValueError(
                        "strict_load probes require a checkpoint and a true "
                        "strict checkpoint/model load fact"
                    )
        elif not self.reason or not self.blockers:
            raise ValueError("unavailable and failed probes require reason and blockers")


@dataclass(frozen=True)
class LocalResearchProfile:
    repository_path: Path | str
    checkpoint_path: Path | str | None = None
    dataset_path: Path | str | None = None
    license: str | None = None
    provenance: str | None = None

    def __post_init__(self) -> None:
        for name in ("repository_path", "checkpoint_path", "dataset_path"):
            value = getattr(self, name)
            if value is None:
                continue
            path = Path(value)
            if not path.is_absolute():
                raise ValueError(f"{name} must be an explicit absolute path")
            object.__setattr__(self, name, path.resolve(strict=False))
        for name in ("license", "provenance"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError(f"{name} must be a non-empty string or None")


class _ResearchAdapter:
    backend_id = "external"
    default_backend_version = "unconfigured"
    default_backend_domain = "research"
    default_probe_blockers = (
        "probe command/local profile is not configured",
    )

    def __init__(
        self,
        *,
        command: tuple[str, ...] | None = None,
        probe_command: tuple[str, ...] | None = None,
        local_profile: LocalResearchProfile | None = None,
        timeout_seconds: float = 60.0,
        output_limit_bytes: int = 1_048_576,
        backend_version: str | None = None,
        backend_domain: str | None = None,
        environment: tuple[GeneratorProjectFact, ...] = (),
        checkpoint: str | None = None,
        dataset: str | None = None,
        license: str | None = None,
    ) -> None:
        self.command = command
        self.probe_command = probe_command
        self.local_profile = local_profile
        self.timeout_seconds = timeout_seconds
        self.output_limit_bytes = output_limit_bytes
        self.backend_version = (
            self.default_backend_version
            if backend_version is None
            else backend_version
        )
        self.backend_domain = (
            self.default_backend_domain
            if backend_domain is None
            else backend_domain
        )
        self.environment = environment
        self.checkpoint = checkpoint
        self.dataset = dataset
        self.license = license

    def probe(self) -> ResearchProbeRecord:
        configuration_error = self._probe_configuration_error()
        if configuration_error is not None:
            return self._probe_failed(configuration_error)
        if self.probe_command is not None:
            return self._run_probe_subprocess()
        if self.local_profile is not None:
            return self._probe_local_profile()
        return self._probe_unavailable(self.default_probe_blockers)

    def generate(self, request: GeneratorRequest) -> GeneratorResponse:
        if not self.command:
            return self._unavailable(
                request,
                "backend executable/config is not configured",
            )
        return SubprocessGeneratorAdapter(
            command=self.command,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_domain=self.backend_domain,
            timeout_seconds=self.timeout_seconds,
        ).generate(request)

    def _unavailable(
        self,
        request: GeneratorRequest,
        reason: str,
    ) -> GeneratorResponse:
        return GeneratorResponse(
            status="unavailable",
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_domain=self.backend_domain,
            request_digest=request.digest,
            environment=self.environment,
            checkpoint=self.checkpoint,
            dataset=self.dataset,
            license=self.license,
            reason=reason,
        )

    def _run_probe_subprocess(self) -> ResearchProbeRecord:
        assert self.probe_command is not None
        try:
            completed = _run_bounded_probe_process(
                self.probe_command,
                timeout_seconds=self.timeout_seconds,
                output_limit_bytes=self.output_limit_bytes,
            )
        except FileNotFoundError:
            return self._probe_unavailable(("probe executable was not found",))
        except OSError as error:
            return self._probe_failed(f"probe process failed to start: {error}")
        if completed.failure_reason is not None:
            return self._probe_failed(completed.failure_reason)
        if completed.returncode != 0:
            detail = _decode_probe_output(completed.stderr, "stderr")
            if isinstance(detail, str) and detail.startswith("invalid UTF-8"):
                return self._probe_failed(detail)
            detail = detail.strip() or "no stderr"
            return self._probe_failed(
                f"probe exited with code {completed.returncode}: {detail}"
            )
        try:
            stdout = _decode_probe_output(completed.stdout, "stdout")
            if stdout.startswith("invalid UTF-8"):
                return self._probe_failed(stdout)
            payload = json.loads(stdout)
            if not isinstance(payload, dict):
                raise ValueError("probe payload must be a JSON object")
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            return self._probe_failed(f"invalid JSON probe response: {error}")
        if payload.get("backend_id") != self.backend_id:
            return self._probe_failed("probe response identity does not match adapter")
        if (
            payload.get("backend_version") != self.backend_version
            or payload.get("backend_domain") != self.backend_domain
        ):
            return self._probe_failed("probe response identity does not match adapter")
        try:
            return ResearchProbeRecord(
                status=payload["status"],
                backend_id=payload["backend_id"],
                backend_version=payload["backend_version"],
                backend_domain=payload["backend_domain"],
                repo_revision=payload["repo_revision"],
                evidence_scope=payload["evidence_scope"],
                environment=_probe_facts(payload["environment"], "environment"),
                runtime_checks=_probe_facts(
                    payload["runtime_checks"],
                    "runtime_checks",
                ),
                checkpoint=payload["checkpoint"],
                dataset=payload["dataset"],
                license=payload["license"],
                provenance=payload["provenance"],
                blockers=_probe_blockers(payload["blockers"]),
                reason=payload["reason"],
            )
        except (KeyError, TypeError, ValueError) as error:
            return self._probe_failed(f"invalid probe response: {error}")

    def _probe_configuration_error(self) -> str | None:
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            return "probe timeout_seconds must be finite and positive"
        if (
            not isinstance(self.output_limit_bytes, int)
            or isinstance(self.output_limit_bytes, bool)
            or self.output_limit_bytes <= 0
        ):
            return "probe output_limit_bytes must be a positive integer"
        if self.probe_command is not None:
            if not isinstance(self.probe_command, tuple) or not self.probe_command:
                return "probe command must be a non-empty tuple"
            if any(
                not isinstance(part, str) or not part
                for part in self.probe_command
            ):
                return "probe command entries must be non-empty strings"
        if self.local_profile is not None and not isinstance(
            self.local_profile,
            LocalResearchProfile,
        ):
            return "local_profile must be a LocalResearchProfile"
        for name in ("backend_version", "backend_domain"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                return (
                    f"probe configuration {name} must be a non-empty string"
                )
        if not isinstance(self.environment, tuple) or not all(
            isinstance(item, GeneratorProjectFact) for item in self.environment
        ):
            return (
                "probe configuration environment must be an immutable tuple "
                "of GeneratorProjectFact records"
            )
        for name in ("checkpoint", "dataset", "license"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                return (
                    f"probe configuration {name} must be a string or None"
                )
        return None

    def _probe_local_profile(self) -> ResearchProbeRecord:
        profile = self.local_profile
        assert profile is not None
        blockers: list[str] = []
        checks: list[GeneratorProjectFact] = []
        repository_exists = profile.repository_path.is_dir()
        checks.append(GeneratorProjectFact("repository_exists", repository_exists))
        revision = None
        if not repository_exists:
            blockers.append(
                f"repository does not exist: {profile.repository_path}"
            )
        else:
            revision, revision_blocker = _local_git_revision(
                profile.repository_path,
                self.timeout_seconds,
            )
            if revision_blocker:
                blockers.append(revision_blocker)
        for label, path in (
            ("checkpoint", profile.checkpoint_path),
            ("dataset", profile.dataset_path),
        ):
            exists = path is not None and path.exists()
            checks.append(GeneratorProjectFact(f"{label}_exists", exists))
            if path is None:
                blockers.append(f"{label} path is not configured")
            elif not exists:
                blockers.append(f"{label} does not exist: {path}")
        blockers.append(
            "probe command is not configured; runtime and strict-load checks "
            "were not executed"
        )
        return ResearchProbeRecord(
            status="unavailable",
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_domain=self.backend_domain,
            repo_revision=revision,
            evidence_scope=None,
            environment=self.environment,
            runtime_checks=tuple(checks),
            checkpoint=(
                None
                if profile.checkpoint_path is None
                else str(profile.checkpoint_path)
            ),
            dataset=(
                None if profile.dataset_path is None else str(profile.dataset_path)
            ),
            license=profile.license or self.license,
            provenance=profile.provenance,
            blockers=tuple(blockers),
            reason="local paper backend probe is unavailable",
        )

    def _probe_unavailable(
        self,
        blockers: tuple[str, ...],
    ) -> ResearchProbeRecord:
        return ResearchProbeRecord(
            status="unavailable",
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_domain=self.backend_domain,
            repo_revision=None,
            evidence_scope=None,
            environment=self.environment,
            runtime_checks=(),
            checkpoint=self.checkpoint,
            dataset=self.dataset,
            license=self.license,
            provenance=None,
            blockers=blockers,
            reason="paper backend probe is unavailable",
        )

    def _probe_failed(self, reason: str) -> ResearchProbeRecord:
        backend_version = (
            self.backend_version
            if isinstance(self.backend_version, str)
            and self.backend_version.strip()
            else "invalid-configuration"
        )
        backend_domain = (
            self.backend_domain
            if isinstance(self.backend_domain, str)
            and self.backend_domain.strip()
            else "invalid-configuration"
        )
        environment = (
            self.environment
            if isinstance(self.environment, tuple)
            and all(
                isinstance(item, GeneratorProjectFact)
                for item in self.environment
            )
            else ()
        )
        return ResearchProbeRecord(
            status="failed",
            backend_id=self.backend_id,
            backend_version=backend_version,
            backend_domain=backend_domain,
            repo_revision=None,
            evidence_scope=None,
            environment=environment,
            runtime_checks=(),
            checkpoint=(
                self.checkpoint if isinstance(self.checkpoint, str) else None
            ),
            dataset=self.dataset if isinstance(self.dataset, str) else None,
            license=self.license if isinstance(self.license, str) else None,
            provenance=None,
            blockers=(reason,),
            reason=reason,
        )


class Graph2PlanAdapter(_ResearchAdapter):
    backend_id = "graph2plan"
    default_backend_domain = "graph-to-plan"
    default_probe_blockers = (
        "probe command/local profile is not configured",
        "commercial office request cannot map directly to RPLAN residential domain",
        "checkpoint/dataset/runtime are not verified",
    )


class HouseDiffusionAdapter(_ResearchAdapter):
    backend_id = "house_diffusion"
    default_backend_domain = "diffusion"
    default_probe_blockers = (
        "probe command/local profile is not configured",
        "commercial office request cannot map directly to RPLAN residential domain",
        "checkpoint/dataset/runtime are not verified",
    )


class RlvrAdapter(_ResearchAdapter):
    backend_id = "rlvr"
    default_backend_domain = "reinforcement-learning"
    default_probe_blockers = (
        "probe command/local profile is not configured",
        "required hardware/model is unavailable or not verified",
    )


class MansionAdapter(_ResearchAdapter):
    backend_id = "mansion"
    default_backend_domain = "multimodal-downstream"
    default_probe_blockers = (
        "probe command/local profile is not configured",
        "MANSION is downstream-only and cannot generate PLAN candidates",
    )

    def generate(self, request: GeneratorRequest) -> GeneratorResponse:
        return self._unavailable(
            request,
            "MANSION generation is not configured because it is downstream-only",
        )


def _probe_facts(value: object, label: str) -> tuple[GeneratorProjectFact, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be a JSON array")
    return tuple(GeneratorProjectFact(**item) for item in value)


def _probe_blockers(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError("blockers must be a JSON array")
    if not all(isinstance(item, str) and item for item in value):
        raise TypeError("blockers must contain non-empty strings")
    return tuple(value)


def _local_git_revision(
    repository_path: Path,
    timeout_seconds: float,
) -> tuple[str | None, str | None]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_path), "rev-parse", "HEAD"),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
        return None, f"repository revision check failed: {error}"
    revision = completed.stdout.strip()
    if completed.returncode != 0 or not revision:
        detail = completed.stderr.strip() or "no revision returned"
        return None, f"repository revision is unavailable: {detail}"
    return revision, None


@dataclass(frozen=True)
class _ProbeProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    failure_reason: str | None = None


def _run_bounded_probe_process(
    command: tuple[str, ...],
    *,
    timeout_seconds: float,
    output_limit_bytes: int,
) -> _ProbeProcessResult:
    creationflags = 0
    if _IS_WINDOWS:
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        creationflags=creationflags,
        start_new_session=not _IS_WINDOWS,
    )
    windows_job = None
    if _IS_WINDOWS:
        try:
            windows_job = _assign_windows_kill_job(process)
            if windows_job is None:
                raise RuntimeError(
                    "Windows Job assignment returned no ownership handle"
                )
            if not _resume_suspended_windows_process(process):
                raise RuntimeError("suspended process resume was rejected")
        except Exception as error:
            if windows_job is not None:
                try:
                    windows_job.close()
                except Exception:
                    pass
            _abort_suspended_windows_process(process)
            return _ProbeProcessResult(
                returncode=process.returncode or -1,
                stdout=b"",
                stderr=b"",
                failure_reason=(
                    "probe process ownership initialization failed: "
                    f"{type(error).__name__}: {error}"
                ),
            )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    reader_errors: list[Exception] = []
    state = {"total": 0}
    lock = threading.Lock()
    output_exceeded = threading.Event()

    def read_bounded(stream, chunks: list[bytes]) -> None:
        try:
            while True:
                chunk = stream.read1(4096)
                if not chunk:
                    return
                with lock:
                    remaining = output_limit_bytes - state["total"]
                    if len(chunk) > remaining:
                        if remaining > 0:
                            chunks.append(chunk[:remaining])
                            state["total"] += remaining
                        output_exceeded.set()
                        return
                    chunks.append(chunk)
                    state["total"] += len(chunk)
        except Exception as error:
            with lock:
                reader_errors.append(error)

    readers = (
        threading.Thread(
            target=read_bounded,
            args=(process.stdout, stdout_chunks),
            daemon=True,
        ),
        threading.Thread(
            target=read_bounded,
            args=(process.stderr, stderr_chunks),
            daemon=True,
        ),
    )
    started_readers: list[threading.Thread] = []
    failure_reason = None
    try:
        for reader in readers:
            reader.start()
            started_readers.append(reader)

        deadline = time.monotonic() + timeout_seconds
        while not _owned_parent_exited_without_reap(process):
            if reader_errors:
                raise RuntimeError(
                    f"probe reader failed: {reader_errors[0]}"
                )
            if output_exceeded.is_set():
                failure_reason = (
                    f"probe output limit exceeded ({output_limit_bytes} bytes)"
                )
                _terminate_owned_process_tree(process, windows_job)
                break
            if time.monotonic() >= deadline:
                failure_reason = (
                    f"probe timed out after {timeout_seconds:g} seconds"
                )
                _terminate_owned_process_tree(process, windows_job)
                break
            time.sleep(0.005)
        if failure_reason is None:
            _finalize_successful_owned_process(process, windows_job)
        for reader in started_readers:
            reader.join(timeout=1.0)
        if reader_errors and failure_reason is None:
            raise RuntimeError(f"probe reader failed: {reader_errors[0]}")
        if output_exceeded.is_set() and failure_reason is None:
            failure_reason = (
                f"probe output limit exceeded ({output_limit_bytes} bytes)"
            )
    except Exception as error:
        failure_reason = (
            "probe process lifecycle failed: "
            f"{type(error).__name__}: {error}"
        )
        _best_effort_terminate_owned_process_tree(process, windows_job)
    finally:
        _close_probe_process_resources(
            process,
            windows_job,
            tuple(started_readers),
        )
    return _ProbeProcessResult(
        returncode=process.returncode if process.returncode is not None else -1,
        stdout=b"".join(stdout_chunks),
        stderr=b"".join(stderr_chunks),
        failure_reason=failure_reason,
    )


def _terminate_owned_process_tree(
    process: subprocess.Popen,
    windows_job: _WindowsKillJob | None,
) -> None:
    if _IS_WINDOWS:
        pid = process.pid
        if windows_job is not None:
            windows_job.close()
        if process.poll() is None:
            process.kill()
            if process.poll() is None:
                subprocess.run(
                    ("taskkill", "/PID", str(pid), "/T", "/F"),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5.0,
                    check=False,
                    shell=False,
                )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            process.kill()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def _best_effort_terminate_owned_process_tree(
    process: subprocess.Popen,
    windows_job: _WindowsKillJob | None,
) -> None:
    try:
        _terminate_owned_process_tree(process, windows_job)
        return
    except Exception:
        pass
    if windows_job is not None:
        try:
            windows_job.close()
        except Exception:
            pass
    if not _IS_WINDOWS:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            pass
    try:
        process.kill()
    except Exception:
        if _IS_WINDOWS:
            try:
                _terminate_windows_process_handle(process)
            except Exception:
                pass
    try:
        process.wait(timeout=1.0)
    except Exception:
        pass


def _close_probe_process_resources(
    process: subprocess.Popen,
    windows_job: _WindowsKillJob | None,
    readers: tuple[threading.Thread, ...],
) -> None:
    if windows_job is not None:
        try:
            windows_job.close()
        except Exception:
            pass
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
    for reader in readers:
        try:
            reader.join(timeout=1.0)
        except Exception:
            pass
    if process.returncode is None:
        _best_effort_terminate_owned_process_tree(process, windows_job)
    handle = getattr(process, "_handle", None)
    close = getattr(handle, "Close", None)
    if callable(close):
        try:
            close()
        except OSError:
            pass


def _cleanup_owned_children_after_parent_exit(
    process: subprocess.Popen,
    windows_job: _WindowsKillJob | None,
) -> None:
    if _IS_WINDOWS:
        if windows_job is not None:
            windows_job.close()
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _finalize_successful_owned_process(
    process: subprocess.Popen,
    windows_job: _WindowsKillJob | None,
) -> None:
    _cleanup_owned_children_after_parent_exit(process, windows_job)
    process.wait(timeout=1.0)


def _owned_parent_exited_without_reap(process: subprocess.Popen) -> bool:
    if _IS_WINDOWS:
        return process.poll() is not None
    result = os.waitid(
        os.P_PID,
        process.pid,
        os.WEXITED | os.WNOHANG | os.WNOWAIT,
    )
    return result is not None


def _decode_probe_output(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        return f"invalid UTF-8 {label}: {error}"


class _WindowsKillJob:
    def __init__(self, handle, close_handle) -> None:
        self._handle = handle
        self._close_handle = close_handle

    def close(self) -> None:
        if self._handle:
            self._close_handle(self._handle)
            self._handle = None


def _assign_windows_kill_job(
    process: subprocess.Popen,
) -> _WindowsKillJob | None:
    if not _IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    class JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JobObjectBasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.AssignProcessToJobObject.argtypes = (
        wintypes.HANDLE,
        wintypes.HANDLE,
    )
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    information = JobObjectExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x00002000
    configured = kernel32.SetInformationJobObject(
        handle,
        9,
        ctypes.byref(information),
        ctypes.sizeof(information),
    )
    assigned = configured and kernel32.AssignProcessToJobObject(
        handle,
        wintypes.HANDLE(process._handle),
    )
    if not assigned:
        kernel32.CloseHandle(handle)
        return None
    return _WindowsKillJob(handle, kernel32.CloseHandle)


def _resume_suspended_windows_process(process: subprocess.Popen) -> bool:
    if not _IS_WINDOWS:
        return True
    import ctypes
    from ctypes import wintypes

    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    ntdll.NtResumeProcess.argtypes = (wintypes.HANDLE,)
    ntdll.NtResumeProcess.restype = ctypes.c_long
    return ntdll.NtResumeProcess(wintypes.HANDLE(process._handle)) == 0


def _abort_suspended_windows_process(process: subprocess.Popen) -> None:
    try:
        try:
            process.kill()
        except Exception:
            _terminate_windows_process_handle(process)
        try:
            process.wait(timeout=1.0)
        except Exception:
            _terminate_windows_process_handle(process)
            try:
                process.wait(timeout=1.0)
            except Exception:
                pass
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        handle = getattr(process, "_handle", None)
        close = getattr(handle, "Close", None)
        if callable(close):
            try:
                close()
            except OSError:
                pass


def _terminate_windows_process_handle(process: subprocess.Popen) -> None:
    if not _IS_WINDOWS:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess(
        wintypes.HANDLE(process._handle),
        1,
    )
