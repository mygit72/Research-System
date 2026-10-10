"""Research Intelligence backend."""

import os as _os
import sys as _sys

__version__ = "0.3.0"

# Windows: a venv's python.exe launches the base interpreter, so the MSVC runtime
# DLLs that `msvc-runtime` installs into the venv aren't on the DLL search path.
# Native extensions (PyMuPDF, PyTorch) need them; register the venv once, before
# any of them are imported. No-op on Linux/macOS and in Docker.
if _sys.platform == "win32" and hasattr(_os, "add_dll_directory"):
    for _candidate in (_sys.prefix, _os.path.join(_sys.prefix, "Scripts")):
        if _os.path.isdir(_candidate):
            _os.add_dll_directory(_candidate)
