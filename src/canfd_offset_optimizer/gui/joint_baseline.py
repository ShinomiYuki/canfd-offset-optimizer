"""Validated hidden search budget for the first Joint GUI product workflow."""

from __future__ import annotations

VALIDATED_JOINT_ATTEMPTS = 3
VALIDATED_JOINT_MAX_REFINEMENT_PASSES = 3
VALIDATED_JOINT_SEED = 0
VALIDATED_JOINT_ENDPOINT_ONLY = False

# The remaining values come from input/config/project.yaml used by the third
# validation round. They intentionally do not inherit ordinary GUI expert knobs.
VALIDATED_HOT_SLOT_COUNT = 3
VALIDATED_CONFLICT_CANDIDATE_CAP = 6
VALIDATED_PAIR_NEIGHBOR_STEPS = (1, 2, 3)
VALIDATED_VARIANCE_OFFSET_CAP = 3
VALIDATED_PEAK_CANDIDATE_POOL_SIZE = 1
VALIDATED_CONFLICT_TRIPLE_ENABLED = False
VALIDATED_TRIPLE_CANDIDATE_CAP = 6
VALIDATED_TRIPLE_HOT_SLOT_COUNT = 3
VALIDATED_TRIPLE_MAX_ROUNDS = 3
