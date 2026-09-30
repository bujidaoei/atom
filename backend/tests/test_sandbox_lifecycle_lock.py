import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from app.sandbox import lifecycle
from app.sandbox.lifecycle import _ProcessLease


class ProcessLeaseTests(unittest.TestCase):
    def test_cross_process_exclusion_and_crash_release(self):
        script = """
import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from app.sandbox.lifecycle import _ProcessLease,LifecycleError
try: lease=_ProcessLease(Path(sys.argv[2]))
except LifecycleError: os._exit(9)
os._exit(17)
"""
        backend = str(Path(lifecycle.__file__).resolve().parents[2])
        with tempfile.TemporaryDirectory(prefix="atom-lease-test-") as temporary:
            path = Path(temporary) / "broker.lease"
            lease = _ProcessLease(path)
            try:
                denied = subprocess.run([sys.executable, "-c", script, backend, str(path)],
                                        capture_output=True, timeout=5)
                self.assertEqual(denied.returncode, 9, denied.stderr)
            finally:
                lease.close()
            crashed = subprocess.run([sys.executable, "-c", script, backend, str(path)],
                                     capture_output=True, timeout=5)
            self.assertEqual(crashed.returncode, 17, crashed.stderr)
            reacquired = _ProcessLease(path)
            reacquired.close()


if __name__ == "__main__":
    unittest.main()
