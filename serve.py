# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "vgi-python[http,oauth]",
#     "httpx>=0.27",
# ]
#
# [tool.uv.sources]
# vgi-python = { path = "../vgi-python" }
# ///
"""HTTP entrypoint for the scholar worker.

Forces the worker's CLI into HTTP mode (``Worker.main()`` serves stdio by
default) so callers only pass ``--host``/``--port``.
"""

import sys

from scholar_worker import ScholarWorker

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    sys.argv = [sys.argv[0], *argv]
    ScholarWorker.main()
