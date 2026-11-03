"""Launcher used by PyInstaller and for running from source: python run_app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from fnirsi2c53t.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
