# Contracts
NDJSON requires one terminal result/error; premature EOF fails. Orchestrator owns terminal events. run.recovering includes attempt/maxAttempts. Cancel waits for cleanup and is idempotent. Terminal project snapshots clear historical activity. Acceptance results exactly match stored (key,checkIndex), without duplicates. Invalid setup rejects the contract check.
