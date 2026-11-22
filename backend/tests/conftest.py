import os
import sys
from pathlib import Path

# Must be set before app modules are imported.
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ.setdefault("SOS_DEMO_SECONDS", "0")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
