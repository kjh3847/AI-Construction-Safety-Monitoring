"""Preserve the build runtime's SSL policy data lookup inside a frozen app."""
import os
import ssl
import sys

if getattr(sys, 'frozen', False) and os.path.isfile(os.path.join(sys._MEIPASS, 'codex-rejected-cas.pem')):
    # ssl.py lives in base_library.zip; the runtime's additional CA policy file
    # must be resolved from the extraction directory, not inside that ZIP.
    ssl.__file__ = os.path.join(sys._MEIPASS, 'ssl.py')
