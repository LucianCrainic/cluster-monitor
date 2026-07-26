"""Write the backend OpenAPI schema for frontend type generation."""

from __future__ import annotations

import json
from pathlib import Path

from cluster_monitor.main import app


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "openapi.json"
    destination.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(destination)


if __name__ == "__main__":
    main()
