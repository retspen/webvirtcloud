"""console/novncd, an extensionless script, loaded as a module the tests can patch."""

import importlib.machinery
import importlib.util
from pathlib import Path

NOVNCD_PATH = str(Path(__file__).resolve().parent.parent / "novncd")
_loader = importlib.machinery.SourceFileLoader("novncd_mod", NOVNCD_PATH)
novncd_mod = importlib.util.module_from_spec(importlib.util.spec_from_file_location("novncd_mod", NOVNCD_PATH, loader=_loader))
_loader.exec_module(novncd_mod)
