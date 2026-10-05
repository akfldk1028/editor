"""Training-data helpers for MAAS intent-to-sequence experiments."""

__all__ = [
    "build_examples_from_design_results",
    "build_sft_examples",
    "evidence_to_review_example",
    "export_job_sft",
    "export_sft_seed",
]


def build_sft_examples():
    from backend.app.modules.design.generation.maas.training.export_sft_seed import build_sft_examples as _build_sft_examples

    return _build_sft_examples()


def export_sft_seed(path=None):
    from backend.app.modules.design.generation.maas.training.export_sft_seed import export_sft_seed as _export_sft_seed

    if path is None:
        return _export_sft_seed()
    return _export_sft_seed(path)


def build_examples_from_design_results(*, limit=100, job_id=None):
    from backend.app.modules.design.generation.maas.training.export_job_sft import build_examples_from_design_results as _build

    return _build(limit=limit, job_id=job_id)


def evidence_to_review_example(evidence):
    from backend.app.modules.design.generation.maas.training.export_job_sft import evidence_to_review_example as _convert

    return _convert(evidence)


def export_job_sft(path, *, limit=100, job_id=None):
    from backend.app.modules.design.generation.maas.training.export_job_sft import export_job_sft as _export

    return _export(path, limit=limit, job_id=job_id)
