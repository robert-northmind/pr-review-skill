"""Import this checkout's runtime and shared Python test helpers in fixtures."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'tests' / 'python')]
