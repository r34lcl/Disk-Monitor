import os

_here = os.path.dirname(os.path.dirname(__file__))
try:
    with open(os.path.join(_here, "VERSION")) as f:
        VERSION = f.read().strip()
except OSError:
    VERSION = "?"
