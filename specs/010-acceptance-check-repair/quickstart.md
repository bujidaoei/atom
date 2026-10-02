# Verification

Run `backend/.venv/Scripts/python.exe -m pytest -q backend/tests/test_acceptance.py backend/tests/test_acceptance_browser.py` after installing locked dependencies, and `npm run build` from `frontend/`. Then run `npm run verify:pi-source` from `runtime/`. Target deployment requires exact image/preflight and an authenticated check/reload on the server; mark T006/T007 only after those observations.
