"""Trusted preview navigation pages; generated code never receives a handoff."""
import base64
import hashlib
import json

OPEN_PATH = '/_atom/open'
EXCHANGE_PATH = '/_atom/exchange'
RESUME_PATH = '/_atom/resume'


def navigation_page(console_origin: str, *, view_id: str | None = None):
    configuration = json.dumps({'consoleOrigin': console_origin, 'viewId': view_id}, separators=(',', ':'))
    script = "const config = " + configuration + ";\n" + SCRIPT
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    headers = {
        'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': (
            "default-src 'none'; script-src 'sha256-" + digest + "'; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors " + console_origin + "; worker-src 'none'"),
    }
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>项目预览</title><p id="status" role="status">正在加载预览…</p>'
            '<script>' + script + '</script></html>')
    return page, headers


SCRIPT = """(async () => {
  const handoff = location.hash.slice(1);
  history.replaceState(null, '', location.pathname);
  const status = document.getElementById('status');
  let viewId = config.viewId;
  const report = (state) => {
    if (parent !== window) parent.postMessage({type:'atom.preview', viewId, state}, config.consoleOrigin);
  };
  try {
    let path;
    if (viewId) {
      path = '/_atom/view/' + viewId + '/';
    } else {
      if (!/^[0-9a-f]{64}$/.test(handoff)) throw new Error('invalid_grant');
      const response = await fetch('/_atom/exchange', {
        method:'POST', mode:'cors', credentials:'same-origin', redirect:'error',
        headers:{'Content-Type':'application/octet-stream'}, body:handoff,
        signal:AbortSignal.timeout(10000)
      });
      if (!response.ok) throw new Error('exchange_denied');
      const result = await response.json();
      if (!/^[0-9a-f]{64}$/.test(result.viewId) ||
          result.path !== '/_atom/view/' + result.viewId + '/') throw new Error('invalid_view');
      viewId = result.viewId;
      path = result.path;
    }
    const check = await fetch(path, {method:'HEAD', credentials:'same-origin', redirect:'error',
      signal:AbortSignal.timeout(10000)});
    if (!check.ok || !check.headers.get('X-Atom-Revision')) throw new Error('unavailable');
    report('ready');
    location.replace(path);
  } catch {
    status.textContent = '预览暂时无法加载，请返回 Atom 点击重新加载。';
    report('error');
  }
})();"""
