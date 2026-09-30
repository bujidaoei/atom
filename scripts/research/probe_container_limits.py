"""Disposable real container profile test; not Atom broker or tenant acceptance.

No host mounts/ports or real secrets. Requires an existing local Python image.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import uuid


def run(*args, input=None, check=True):
    return subprocess.run(args, input=input, capture_output=True, text=True,
                          timeout=20, check=check)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    image = run("docker", "image", "inspect", args.image, "--format", "{{.Id}}").stdout.strip()
    name = "atom-profile-probe-" + uuid.uuid4().hex[:12]
    sentinel_name = "ATOM_PROFILE_CANARY_" + uuid.uuid4().hex
    os.environ[sentinel_name] = uuid.uuid4().hex
    created = False

    def execute(source, check=True):
        return run("docker", "exec", "-i", name, "python3", "-", input=source, check=check)

    try:
        run("docker", "run", "-d", "--pull=never", "--name", name,
            "--network=none", "--read-only", "--user", "1000:1000",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--memory=128m", "--memory-swap=128m", "--cpus=0.5", "--pids-limit=32",
            "--tmpfs", "/workspace:rw,size=8m,uid=1000,gid=1000,mode=0700",
            "--tmpfs", "/tmp:rw,size=8m,uid=1000,gid=1000,mode=0700",
            "--workdir", "/workspace", "--env", "ATOM_WORKSPACE_ROOT=/workspace",
            image, "python3", "-c", "import time; time.sleep(90)")
        created = True
        source = '''
import errno, json, os, pathlib, socket, subprocess
result = {'uid': os.getuid(), 'platform_canary_present': CANARY in os.environ,
          'docker_socket_present': pathlib.Path('/var/run/docker.sock').exists()}
assert result['uid'] == 1000 and not result['platform_canary_present'] and not result['docker_socket_present']
pathlib.Path('approved.txt').write_text('actual file tool data')
assert pathlib.Path('approved.txt').read_text() == 'actual file tool data'
try:
    pathlib.Path('/etc/atom-probe-denied').write_text('deny')
    raise AssertionError('root filesystem writable')
except OSError as error:
    assert error.errno in (errno.EROFS, errno.EACCES)
    result['root_write_denied'] = True
with socket.socket() as connection:
    connection.settimeout(1)
    try:
        connection.connect(('198.18.0.1', 443))
        raise AssertionError('network allowed')
    except OSError as error:
        assert error.errno == errno.ENETUNREACH, str(error)
        result['network_unreachable'] = True
try:
    pathlib.Path('quota.bin').write_bytes(b'x' * (9 * 1024 * 1024))
    raise AssertionError('workspace quota not enforced')
except OSError as error:
    assert error.errno == errno.ENOSPC, str(error)
    result['disk_quota_enforced'] = True
finally:
    pathlib.Path('quota.bin').unlink(missing_ok=True)
children = []
try:
    for _ in range(48):
        children.append(subprocess.Popen(['python3', '-c', 'import time; time.sleep(10)']))
    raise AssertionError('PID limit not enforced')
except OSError as error:
    assert error.errno == errno.EAGAIN, str(error)
    result['pid_limit_enforced'] = True
    result['children_before_limit'] = len(children)
finally:
    for child in children: child.terminate()
    for child in children: child.wait(timeout=5)
print(json.dumps(result))
'''.replace("CANARY", repr(sentinel_name))
        observed = json.loads(execute(source).stdout)
        oom = execute("allocation = bytearray(256 * 1024 * 1024)\nprint(len(allocation))", check=False)
        assert oom.returncode == 137, "expected OOM termination"
        counters = execute("print(open('/sys/fs/cgroup/memory.events').read())").stdout
        events = dict(line.split() for line in counters.splitlines() if line.strip())
        assert int(events["oom_kill"]) >= 1
        observed["memory_oom_kill_observed"] = True
        assert execute("print(open('approved.txt').read())").stdout.strip() == "actual file tool data"
        print(json.dumps({"scope": "container-profile-only", "result": "PASS",
                          "image": image, "observed": observed}))
    finally:
        os.environ.pop(sentinel_name, None)
        if created:
            run("docker", "rm", "-f", "-v", name)


if __name__ == "__main__":
    main()
