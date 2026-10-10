"""Checkpoint that the golden fingerprints were generated with; independent of the app default."""
from busmerge.paths import MODELS_DIR

GOLDEN_BRAIN = MODELS_DIR / "ppo_bus_brain_v13.pth"   # merges under honest steering (v9 no longer does)
