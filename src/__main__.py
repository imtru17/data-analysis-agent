import sys
from pathlib import Path

import uvicorn

# Ensure src/ (this file's directory) is importable so the bare-import package
# layout works when launched as `uv run python -m src` from the repo root.
_SRC = str(Path(__file__).resolve().parent)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

if __name__ == "__main__":
    from api import app  # imported after sys.path is set

    uvicorn.run(app, host="0.0.0.0", port=8001, reload=False)
