"""Filesystem locations shared by the app, training scripts and tests."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "models"
OUTPUTS_DIR = REPO_ROOT / "outputs"

DEFAULT_BRAIN = MODELS_DIR / "ppo_bus_brain_v13.pth"
