# Ownership state
Unacquired → acquired(id) → operation settled → release attempted → returned/rejected.
Create rejects: no owned ID, no destroy. Tools disabled: operation only.
Operation fails and release succeeds: rethrow original. Operation succeeds and release fails: throw release error. Both fail: AggregateError with both exact causes and fixed summary. No persistent record or termination certainty introduced.
