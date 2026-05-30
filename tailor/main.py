"""TAILOR application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from tailor import __app_name__, __version__
from tailor.core.config import APP_DATA_DIR
from tailor.data.database import get_database
from tailor.ui.main_window import MainWindow


def main():
    """Launch the TAILOR application."""
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("TAILOR")

    # Initialize database
    db = get_database()
    print(f"Database: {db.database_url}")
    print(f"App data: {APP_DATA_DIR}")

    # Create and show main window
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
