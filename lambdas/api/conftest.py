"""Puts this function's own directory on ``sys.path`` so ``handler`` can import ``router``.

The deploy script copies every ``.py`` in the function directory flat into the package root, so
``from router import route`` resolves at runtime without help. Under pytest the function directory
is not on the path — ``lambdas/conftest.py`` adds the shared LAYER roots and deliberately nothing
else — so the import that works in Lambda fails in the suite.

Placed here rather than widening the shared conftest: that file's scope is the layers, and putting
every verb directory on one path would let two functions' modules shadow each other.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
