"""Test fixtures for visor."""

import sys
from pathlib import Path

# Allow `import visor` — visor/ is an application, not an installed package.
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
