#!/usr/bin/env python3
"""C++ driver entry point without leaking --cxx into Gecko bindgen flags."""
import os
from pathlib import Path
import sys

os.execv(sys.executable, [sys.executable, str(Path(__file__).with_name('orbis-cc.py')),
                         '--cxx', *sys.argv[1:]])
