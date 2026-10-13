# Source-bound road aisle candidates

Law provider `road-aisle-conditions` / Law A2A `law_road_aisle_conditions` evaluates catalog-owned conditional criteria against sourced facts, PNU, exact count, surface structure, angle and date. No legal constants added to MasterPlan. The input identity and catalog snapshot are returned; preliminary applicability is not permit clearance.

`masterplan/road_aisle_generation.py` appends optional perpendicular surface candidates. `road_aisle.py` independently binds source geometry/CRS and receipt, checks actual layout applicability, relevant painted centreline, allowed external extent, per-stall combined width and prohibited frontage. Uncertified stalls cannot borrow exterior drive through ordinary access validation. Public-road use is `external_road_aisle`, separately measured and rendered.

Live Law A2A + Editor HTTP + serialized validation: synthetic80m² site /32m² mass goes0→2 stalls with30m² exterior road use; overall needs_evidence. Actual668 remains3 stalls, no road relief because evidence absent. Rotated37° integration passes. Unsupported parallel/accessible/complex centreline generation stays withheld.

Evidence: `D:/Data/25_ACE/agents/MasterPlanagent/docs/evidence/review-five-20261013/road-aisle.md`; local outputs `runs/road-aisle-20261013`. Preserve owner split; source hashes are consistency, not authentication. No full suite claim; focused regression suite and actual CLI verified.
