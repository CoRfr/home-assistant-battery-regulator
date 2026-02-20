"""Test configuration — add regulator module to path."""

import sys
from pathlib import Path

# Add the battery_regulator package directory directly so we can import
# regulator.py without triggering __init__.py (which imports homeassistant)
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent / "custom_components" / "battery_regulator"),
)
