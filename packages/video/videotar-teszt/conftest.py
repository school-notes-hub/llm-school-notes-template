"""A videotar tesztjei a Manim-környezetben, render nélkül.

Futtatás: ~/.local/share/school-notes/manim-env/bin/python -m pytest -q   (ebből a mappából)
"""

import glob
import os
import sys
from pathlib import Path

GYOKER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GYOKER))
_tex = glob.glob(os.path.expanduser("~/.local/share/school-notes/tinytex/.TinyTeX/bin/*/"))
if _tex:
    os.environ["PATH"] = _tex[0] + os.pathsep + os.environ.get("PATH", "")
