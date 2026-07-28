from __future__ import annotations

from backend.app.modules.generator_adapters.subprocess_adapter import (
    SubprocessGeneratorAdapter,
)
from backend.app.schemas.generator_adapter import (
    GeneratorProjectFact,
    GeneratorRequest,
    GeneratorResponse,
)


class _ResearchAdapter:
    backend_id = "external"
    default_backend_version = "unconfigured"
    default_backend_domain = "research"

    def __init__(
        self,
        *,
        command: tuple[str, ...] | None = None,
        timeout_seconds: float = 60.0,
        backend_version: str | None = None,
        backend_domain: str | None = None,
        environment: tuple[GeneratorProjectFact, ...] = (),
        checkpoint: str | None = None,
        dataset: str | None = None,
        license: str | None = None,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.backend_version = backend_version or self.default_backend_version
        self.backend_domain = backend_domain or self.default_backend_domain
        self.environment = environment
        self.checkpoint = checkpoint
        self.dataset = dataset
        self.license = license

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


class Graph2PlanAdapter(_ResearchAdapter):
    backend_id = "graph2plan"
    default_backend_domain = "graph-to-plan"


class HouseDiffusionAdapter(_ResearchAdapter):
    backend_id = "house_diffusion"
    default_backend_domain = "diffusion"


class RlvrAdapter(_ResearchAdapter):
    backend_id = "rlvr"
    default_backend_domain = "reinforcement-learning"


class MansionAdapter(_ResearchAdapter):
    backend_id = "mansion"
    default_backend_domain = "multimodal-downstream"

    def generate(self, request: GeneratorRequest) -> GeneratorResponse:
        return self._unavailable(
            request,
            "MANSION generation is not configured because it is downstream-only",
        )
