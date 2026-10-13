# Rotated ground contact precision

Live KMass135.456m2 input, replanned through MasterPlan HTTP, produced a false
135.456m2 drive-ground intersection at coincident rotated boundaries. Difference
and buffered containment independently showed the drive outside the building.
The existing1e-6m engine EPS grid is now used for the two drive/ground obstruction
intersection area measurements. No legal allowance or acceptance threshold changed.

Regression fails before and passes after; translated0.1m intrusion still fails.
37 collision/ground-access/parking module tests +19 piloti/ramp validation tests
passed. Reloaded backend through agent-host. Actual HTTP replan now has zero
drive-ground overlap; parking_count still fails (0/2). That candidate stays rejected.

Evidence: agents/MasterPlanagent/runs/kmass-boundary-fixed-20261013/.
