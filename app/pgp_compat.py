"""Compatibility shim: PGPy imports `imghdr`, removed in Python 3.13+.

Only `imghdr.test_png` is required; provide a minimal equivalent.
"""

import sys
import types
import warnings

# PGPy 0.6.0 emits cryptography deprecation warnings (TripleDES/Camellia/CFB)
# at import and use time; they are noise for an app that only uses modern
# ciphers. Silence the specific categories it raises.
warnings.filterwarnings("ignore", message="TripleDES has been moved")
warnings.filterwarnings("ignore", message="Camellia has been moved")
warnings.filterwarnings("ignore", message="CFB has been moved")

if "imghdr" not in sys.modules:
    _mod = types.ModuleType("imghdr")

    def test_png(h, f):
        return h[:8] == b"\x89PNG\r\n\x1a\n"

    _mod.test_png = test_png
    _mod.tests = [test_png]
    sys.modules["imghdr"] = _mod

# Load PGPy now that the module exists.
from pgpy import PGPKey, PGPMessage  # noqa: E402,F401
from pgpy.errors import PGPError  # noqa: E402,F401
