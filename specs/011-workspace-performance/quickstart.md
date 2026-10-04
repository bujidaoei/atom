# Validation
Run backend pytest; use Linux for real ArtifactStore and revision routes. Run frontend Node TypeScript tests and Vite /atom/ build. Exercise real HTTP browser routes, replay, delayed/failing reads, switching, unmount and recovery.
Live probe: set ATOM_LIVE_WORKSPACE_PROBE=1, ATOM_LIVE_SSH_TARGET, ATOM_LIVE_EXPECTED_CONSOLE_ORIGIN, ATOM_LIVE_API_CONTAINER and ATOM_LIVE_PROJECT_IDS (three existing same-owner projects). Run python scripts/probe_workspace_latency.py. Sessions are ephemeral and revoked; never persist cookie/proof.
Record baseline/post JSONL, screenshot inspection, exact image/source, paired backup/preflight and public/preview health in evidence/deployment.
