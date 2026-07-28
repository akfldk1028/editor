from __future__ import annotations

from dataclasses import dataclass
import math
import subprocess

from backend.app.schemas.generator_adapter import GeneratorRequest, GeneratorResponse
from backend.app.modules.generator_adapters.validation import (
    validate_normalized_response,
)


@dataclass(frozen=True)
class SubprocessGeneratorAdapter:
    command: tuple[str, ...]
    backend_id: str
    backend_version: str
    backend_domain: str
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not isinstance(self.command, tuple) or not self.command:
            raise TypeError("command must be a non-empty immutable tuple")
        if any(not isinstance(part, str) or not part for part in self.command):
            raise TypeError("command entries must be non-empty strings")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        for name in ("backend_id", "backend_version", "backend_domain"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")

    def generate(self, request: GeneratorRequest) -> GeneratorResponse:
        try:
            completed = subprocess.run(
                self.command,
                input=request.to_json(),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return self._unavailable(request, "backend executable was not found")
        except subprocess.TimeoutExpired:
            return self._failed(
                request,
                f"backend timed out after {self.timeout_seconds:g} seconds"
            )
        except OSError as error:
            return self._failed(
                request,
                f"backend process failed to start: {error}",
            )

        if completed.returncode != 0:
            detail = completed.stderr.strip() or "no stderr"
            return self._failed(
                request,
                f"backend exited with code {completed.returncode}: {detail}"
            )
        try:
            response = GeneratorResponse.from_json(completed.stdout)
        except (KeyError, TypeError, ValueError) as error:
            return self._failed(request, f"invalid JSON response: {error}")
        if (
            response.backend_id != self.backend_id
            or response.backend_version != self.backend_version
            or response.backend_domain != self.backend_domain
        ):
            return self._failed(
                request,
                "backend response identity does not match adapter",
            )
        if response.request_digest != request.digest:
            return self._failed(
                request,
                "backend response request digest does not match request",
            )
        candidate = response.normalized_candidate
        if candidate is not None and (
            candidate.project_id != request.project_id
            or candidate.floor_index != request.floor_index
        ):
            return self._failed(
                request,
                "backend candidate identity does not match request",
            )
        return validate_normalized_response(request, response)

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
            reason=reason,
        )

    def _failed(
        self,
        request: GeneratorRequest,
        reason: str,
    ) -> GeneratorResponse:
        return GeneratorResponse(
            status="failed",
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_domain=self.backend_domain,
            request_digest=request.digest,
            reason=reason,
        )
