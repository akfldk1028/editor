"""A MasterPlan-bound round tells the jury that the field is the design domain, not the parcel."""
import os
from tempfile import mkdtemp

os.environ.setdefault("MASSV2_WS", mkdtemp(prefix="massv2-ws-"))

from pathlib import Path

from shapely.geometry import Polygon

from backend.app.modules.massing.workspace_tools import vlm_shortlist


def _rubric(tmp_path, monkeypatch):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "judge-prompts-overseas.json").write_text('{"rubric": "RUBRIC"}', encoding="utf-8")
    monkeypatch.setattr(vlm_shortlist, "ROOT", Path(tmp_path))


def test_a_bound_round_states_the_domain_its_holes_and_the_reading_rule(tmp_path, monkeypatch):
    _rubric(tmp_path, monkeypatch)
    domain = Polygon([(0, 0), (30, 0), (30, 30), (0, 30)], holes=[[(10, 10), (20, 10), (20, 20), (10, 20)]])
    text = vlm_shortlist.rubric_for("overseas", site=None, domain=domain)
    assert text.index("SITE INPUT DATA") < text.index("MASTERPLAN BINDING") < text.index("RUBRIC")
    assert '"design_domain_area_m2": 800.0' in text
    assert '"design_domain_holes_count": 1' in text
    assert '"design_domain_holes_m2": 100.0' in text
    assert "not the parcel" in text and "not under-utilisation" in text


def test_an_unbound_round_keeps_the_prompt_as_it_was(tmp_path, monkeypatch):
    _rubric(tmp_path, monkeypatch)
    monkeypatch.delenv("MASS_MASTERPLAN_DEVELOPMENT", raising=False)
    assert vlm_shortlist.bound_domain() is None
    assert "MASTERPLAN BINDING" not in vlm_shortlist.rubric_for("overseas", site=None)
