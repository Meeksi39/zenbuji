#!/usr/bin/env python3
"""Entry point for the zenbuji CLI.

A package directory ``bin/zenbuji/`` can't coexist with a module file
``bin/zenbuji.py``, and the CLI is spawned by path (install.sh wrapper, the GUI
windows' subprocess helpers), so this thin launcher keeps a stable filename.
Run as a script its own directory (``bin``) lands on ``sys.path``, which makes
the sibling ``zenbuji`` package importable.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zenbuji.cli import main  # noqa: E402

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
