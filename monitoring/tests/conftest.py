"""
Shared fixtures for the monitoring test suite.

Adds the monitoring directory to sys.path so tests can import modules
the same way the production code does (flat imports).
"""
import sys
import os

# Add monitoring/ to the front of sys.path so flat imports work
_monitoring_dir = os.path.dirname(os.path.abspath(__file__))
if _monitoring_dir not in sys.path:
    sys.path.insert(0, _monitoring_dir)
