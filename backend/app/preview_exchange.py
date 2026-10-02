"""Service-owned one-use browser exchange; generated HTML never sees the token."""
import base64
import hashlib


OPEN_PATH = '/_atom/open'
EXCHANGE_PATH = '/_atom/exchange'
SCRIPT = """(async () => {
  const handoff = location.hash.slice(1);
  history.replaceState(null, '', '/_atom/open');
  const status = document.getElementById('status');
  if (!/^[0-9a-f]{64}$/.test(handoff)) {
    status.textContent = 'Preview link is invalid. Reopen it from Atom.';
    return;
  }
  try {
    const response = await fetch('/_atom/exchange', {
      method: 'POST', mode: 'same-origin', credentials: 'same-origin', redirect: 'error',
      headers: {'Content-Type': 'application/octet-stream'}, body: handoff,
      signal: AbortSignal.timeout(10000)
    });
    if (response.status !== 204) throw new Error('exchange_denied');
    location.replace('/');
  } catch {
    status.textContent = 'Preview could not be opened. Return to Atom and try again.';
  }
})();"""
_HASH = base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
EXCHANGE_HEADERS = {
    'Cache-Control': 'no-store',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Content-Security-Policy': (
        "default-src 'none'; script-src 'sha256-" + _HASH + "'; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; worker-src 'none'"
    ),
}
PAGE = ('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Open project preview</title><p id="status">Opening preview…</p>'
        '<script>' + SCRIPT + '</script></html>')
