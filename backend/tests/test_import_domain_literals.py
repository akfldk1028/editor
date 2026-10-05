from pathlib import Path

from backend.scripts.import_design_runtime import rewrite


def test_module_relocation_preserves_official_legal_source_host(tmp_path):
    module = tmp_path / "law" / "review.py"
    module.parent.mkdir()
    module.write_text("", encoding="utf-8")
    source = "HOST = 'law.go.kr'\nMODULE = 'law.review'\nMEMBER = 'law.review.check'\n"
    output, _ = rewrite(source, Path("law/example.py"), tmp_path)
    assert "HOST = 'law.go.kr'" in output
    assert "MODULE = 'backend.app.modules.law.reference.review'" in output
    assert "MEMBER = 'backend.app.modules.law.reference.review.check'" in output
