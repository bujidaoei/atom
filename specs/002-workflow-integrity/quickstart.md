# Verification
Run backend uv run pytest; runtime node --import tsx --test src/*.test.ts; frontend npm test and npm run build. Browser navigation and production checks are recorded in evidence.md separately from fault-injection tests.

From the repository root, with Playwright/Chromium installed:
- `python scripts/browser_workflow.py http://127.0.0.1:5182` exercises the actual UI using controlled API and stream faults.
- `python scripts/verify_workflow_live.py http://127.0.0.1:5182 .logs/workflow-live.json` creates an isolated account and two actual model-generated applications. It consumes model credits and checks duplicate startup, cancellation, reload, individual continuation and adoption.
- `python scripts/verify_generated_browser.py http://127.0.0.1:8012 .logs/workflow-live.json` runs the applications' actual contracts in Chromium using `.logs/acceptance.bundle.js` produced by frontend tests. Record failed checks; do not rewrite expectations to pass.

For deployed UI use `http://159.75.231.98/atom` as the base. Raw live result files contain isolated test credentials and stay under ignored `.logs`; copy only sanitized evidence into this feature directory. Python lint validation selects E4/E7/E9/F; broader optional style rules produce existing import/modernization suggestions and are not an established project gate.
