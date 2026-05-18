"""Garden Tools DoubleDown — Duplicate File Remover
Entry point.

Usage
-----
    python main.py

Dependencies (install with pip):
    pip install -r requirements.txt
"""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.utils.cache import HashCache
from src.utils.config import Config


# Per-user data directory (config, cache, logs)
_APP_DIR = Path.home() / ".garden_tools_doubledown"


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Garden Tools DoubleDown")
    app.setOrganizationName("Garden Tools")

    _APP_DIR.mkdir(parents=True, exist_ok=True)

    config = Config(_APP_DIR / "config.json")
    cache  = HashCache(_APP_DIR / "hash_cache.db")

    window = MainWindow(config=config, cache=cache)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
