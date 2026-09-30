# Plan: Provider connection binding
Status: implementation ready for this bounded increment; enterprise parent remains open.

## Technical context
FastAPI/SQLAlchemy existing settings table, Python frozen resolved connection value, React existing settings UI. No new dependencies/schema/runtime changes.

## Constitution check
Scoped requirements have direct tests; synthetic security fixtures are explicitly not generated business acceptance. Preserve Pi and user edits. No production deployment until whole release gates pass. No secret literals or values in evidence.

## Design
Add services/provider_connection.py as the single canonical URL/credential resolver. routes/settings validates proposed state before commit; reads of invalid historical states show configurationError and no model calls. Orchestrator uses same resolver before runtime dispatch. Endpoint transitions require explicit key rebinding; DELETE api-key restores the whole default connection. Gateway retains successful real catalog entries only, keyed by cryptographic digest of full endpoint/credential pair; redirect following disabled. UI uses explicit configuration/discovery state.

## Data model and contracts
Existing UserSettings base_url/api_key/model. ResolvedProvider is immutable endpoint/api_key/source; repr excludes secret. API adds configurationError nullable and modelsStatus available/unavailable/unconfigured; invalid PUT returns 400 with non-sensitive actionable detail. Existing keys and model fields retained. Whole default reset clears base_url/api_key in one transaction. Model choice preserved.

## Verification
Write regression tests first. Use loopback capture to prove no outbound managed key; test shared resolver through generation path, malformed URLs, explicit rebind, masked keys, default reset, invalid stored config and catalog/cache behavior. Full backend regression, frontend build and Pi hash verification. Scope does not claim DNS rebinding prevention or runtime network isolation; parent security contract retains both.
