"""Isolated PostgreSQL mechanism experiment; NOT Atom worker acceptance.

Requires an existing local PostgreSQL-compatible image passed via --image.
No image pull, published port, host mount, real credential or production DB.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import time
import uuid


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=20, check=check)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    image = command("docker", "image", "inspect", args.image, "--format", "{{.Id}}").stdout.strip()
    name = "atom-queue-probe-" + uuid.uuid4().hex[:12]

    def sql(statement: str) -> str:
        return command("docker", "exec", name, "psql", "-U", "postgres", "-XAtq",
                       "-v", "ON_ERROR_STOP=1", "-c", statement).stdout.strip()

    try:
        command("docker", "run", "-d", "--pull=never", "--name", name,
                "--network=none", "--memory=256m", "--pids-limit=64",
                "--tmpfs", "/var/lib/postgresql/data:rw,size=192m",
                "-e", "POSTGRES_HOST_AUTH_METHOD=trust", image,
                "-c", "statement_timeout=10000", "-c", "idle_in_transaction_session_timeout=10000")
        deadline = time.monotonic() + 40
        while True:
            ready = command("docker", "exec", name, "pg_isready", "-U", "postgres", check=False)
            if ready.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("isolated database startup deadline exceeded")
            time.sleep(0.5)
        version = sql("SHOW server_version")
        sql("CREATE TABLE jobs (id integer PRIMARY KEY, state text NOT NULL, token bigint NOT NULL DEFAULT 0, lease_until timestamptz); INSERT INTO jobs(id,state) VALUES (1,'queued'),(2,'queued')")
        claim = """WITH picked AS (
          SELECT id FROM jobs WHERE state='queued' ORDER BY id
          FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE jobs SET state='running', token=token+1,
          lease_until=clock_timestamp()+interval '30 seconds'
          FROM picked WHERE jobs.id=picked.id RETURNING jobs.id"""
        # Hold A's lock across a visible server-side wait. Observe that barrier,
        # rather than assume a client sleep means the transaction is running.
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(sql, "BEGIN; SET LOCAL application_name='atom-probe-owner-a'; " + claim + "; SELECT pg_sleep(4); COMMIT;")
            barrier_deadline = time.monotonic() + 8
            while sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='atom-probe-owner-a' AND wait_event='PgSleep'") != "1":
                if first.done() or time.monotonic() >= barrier_deadline:
                    raise RuntimeError("owner A did not reach lock-held barrier")
                time.sleep(0.1)
            second_id = sql(claim)
            assert second_id == "2", second_id
            assert not first.done(), "second claim did not finish while first lock was held"
            first_id = first.result(timeout=10).splitlines()[0]
            assert first_id == "1", first_id
        sql("UPDATE jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=1")
        stale_before = sql("UPDATE jobs SET state='succeeded' WHERE id=1 AND token=1 AND lease_until>clock_timestamp() RETURNING id")
        assert stale_before == "", stale_before
        sql("UPDATE jobs SET token=token+1, lease_until=clock_timestamp()+interval '30 seconds' WHERE id=1 AND lease_until<=clock_timestamp()")
        stale_after = sql("UPDATE jobs SET state='succeeded' WHERE id=1 AND token=1 AND lease_until>clock_timestamp() RETURNING id")
        assert stale_after == "", stale_after
        current = sql("UPDATE jobs SET state='succeeded' WHERE id=1 AND token=2 AND lease_until>clock_timestamp() RETURNING id")
        assert current == "1", current
        print(json.dumps({"scope": "database-mechanism-only", "result": "PASS", "image": image,
                          "postgres": version, "claims": [first_id, second_id],
                          "expired_owner_rows": 0, "stale_owner_rows": 0, "current_owner_rows": 1}))
    finally:
        cleanup = command("docker", "rm", "-f", "-v", name, check=False)
        if cleanup.returncode:
            raise RuntimeError(f"probe container cleanup failed: {name}")


if __name__ == "__main__":
    main()
