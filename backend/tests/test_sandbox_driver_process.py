import sys
import time

import pytest

from app.sandbox.docker_driver import DriverError, FileProfile, run_bounded


def test_real_subprocess_output_and_status():
    status, out, err = run_bounded([sys.executable, "-c", "import sys;print('out');print('err',file=sys.stderr);sys.exit(7)"])
    assert status == 7 and out.strip() == b"out" and err.strip() == b"err"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_real_output_flood_is_bounded(stream):
    with pytest.raises(DriverError, match="^driver_output_limit$"):
        run_bounded([sys.executable, "-c", f"import sys;sys.{stream}.write('x'*1000000)"], output_limit=1024)


def test_real_process_timeout():
    started = time.monotonic()
    with pytest.raises(DriverError, match="^driver_timeout$"):
        run_bounded([sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.1)
    assert time.monotonic() - started < 3


@pytest.mark.parametrize("kwargs", [{"pids": True}, {"pids": 1000}, {"nano_cpus": 0}, {"memory_bytes": 1},
                                    {"workspace_bytes": 256 * 1024 * 1024}])
def test_profile_limits_fail_closed(kwargs):
    with pytest.raises(DriverError, match="invalid_profile"):
        FileProfile(**kwargs)
