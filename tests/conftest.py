# tests/conftest.py
import sys, os

# proje kökünü sys.path'ın başına ekle (tests dizininden bir üst dizin)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
