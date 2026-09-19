"""Run with: python -m streamlit run streamlit_app.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "app" / "src"))

from toxoracle_app.demo_ui import main

main()
