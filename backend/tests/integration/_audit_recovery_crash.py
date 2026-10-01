"""Actual abrupt broker death at recovery/cleanup boundaries; test entry only."""
import json
import os
from pathlib import Path
import sys

from app.sandbox.audit_recovery import AuditRecoveryOperations
from app.sandbox.docker_driver import DockerDriver
from app.sandbox.lifecycle import Lifecycle
from app.sandbox.registry import Registry


def main():
    database, image, archive, digest, phase = sys.argv[1:]
    registry = Registry(Path(database))
    driver = DockerDriver(registry.broker_id, image)
    execute = AuditRecoveryOperations.execute
    terminate = driver.terminate

    def crash(attempt):
        print(json.dumps({'attempt_id': attempt.id, 'phase': phase}), flush=True)
        os._exit(73)  # Bypass finally, lifecycle shutdown and interpreter cleanup.

    def intercepted_execute(self, attempt, payload, **kwargs):
        if phase == 'before_restore':
            crash(attempt)
        result = execute(self, attempt, payload, **kwargs)
        if phase == 'after_restore':
            crash(attempt)
        return result

    def intercepted_terminate(attempt):
        terminate(attempt)
        if phase == 'after_remove':
            crash(attempt)

    AuditRecoveryOperations.execute = intercepted_execute
    driver.terminate = intercepted_terminate
    with Lifecycle(registry, driver) as lifecycle:
        lifecycle.start()
        lifecycle.verify_audit_archive(Path(archive).read_bytes(), expected_sha256=digest)
    raise AssertionError('crash boundary not reached')


if __name__ == '__main__':
    main()
