"""Real, bounded browser observations; intentionally grants no release authority.

The caller must supply a pinned content URL and a separately isolated browser
process. Trusted execution identity and report registration are separate gates.
"""
from ipaddress import ip_address
import json
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError

from .verification_contract import VerificationContract, VerificationReport, capture_report, load_contract


class ObservationError(RuntimeError):
    pass


def _origin(url: str) -> str:
    try:
        parsed = urlsplit(url)
        hostname, port = parsed.hostname, parsed.port
        if (parsed.scheme not in ('http', 'https') or not hostname or parsed.username or parsed.password):
            raise ValueError
        if ':' in hostname:
            raise ValueError
        if parsed.scheme == 'http':
            address = ip_address(hostname)
            if address.version != 4 or not address.is_loopback:
                raise ValueError
        if parsed.scheme == 'https' and port == 443:
            port = None
        if parsed.scheme == 'http' and port == 80:
            port = None
        return f'{parsed.scheme}://{hostname.lower()}' + (f':{port}' if port else '')
    except (ValueError, TypeError):
        raise ObservationError('invalid_content_origin') from None


def _remaining(deadline: float, *, ceiling_ms: int) -> int:
    remaining = int((deadline - time.monotonic()) * 1000)
    if remaining <= 0:
        raise ObservationError('verification_deadline')
    return min(remaining, ceiling_ms)


def _check(page, check: dict, deadline: float) -> bool:
    selector = check['selector']
    target = page.locator(selector).first
    if check['type'] == 'exists':
        return target.count() > 0
    if check['type'] == 'text':
        if target.count() == 0:
            return False
        until = min(deadline, time.monotonic() + 1.5)
        while True:
            actual = ' '.join((target.text_content(timeout=_remaining(deadline, ceiling_ms=1500)) or '').split())
            if check['contains'] in actual:
                return True
            if time.monotonic() >= until:
                return False
            time.sleep(min(0.05, max(0, until - time.monotonic())))
    for step in check['setup']:
        control = page.locator(step['selector']).first
        timeout = _remaining(deadline, ceiling_ms=1500)
        if step['action'] == 'fill':
            control.fill(step['value'], timeout=timeout)
        elif step['action'] == 'click':
            control.click(timeout=timeout)
        else:
            control.press(step['key'], timeout=timeout)
    target.click(timeout=_remaining(deadline, ceiling_ms=1500))
    page.locator(check['expect']).first.wait_for(state='visible', timeout=_remaining(deadline, ceiling_ms=1500))
    return True


def observe_contract(browser, contract: VerificationContract, url: str, *, budget_seconds: int = 30) -> VerificationReport:
    """Execute each canonical check in a fresh context, with no off-origin IO.

    This function is not a process supervisor. The eventual verifier must also
    enforce an independent process/container deadline and authenticate results.
    """
    if type(budget_seconds) is not int or not 1 <= budget_seconds <= 900:
        raise ObservationError('invalid_verification_budget')
    canonical = load_contract(contract.canonical)
    origin = _origin(url)
    parsed_url = urlsplit(url)
    if parsed_url.path not in ('', '/') or parsed_url.query or parsed_url.fragment:
        raise ObservationError('invalid_content_entry')
    deadline = time.monotonic() + budget_seconds
    results = []
    for requirement in json.loads(canonical.canonical)['requirements']:
        for index, check in enumerate(requirement['checks']):
            context = None
            blocked = []
            escaped = []

            def route_request(route):
                try:
                    same_origin = _origin(route.request.url) == origin
                except ObservationError:
                    same_origin = False
                if same_origin:
                    route.continue_()
                else:
                    blocked.append(True)
                    route.abort('blockedbyclient')

            def route_socket(socket):
                blocked.append(True)
                # Do not connect to a server. The mocked socket lives only for
                # this disposable context; closing it from this sync callback
                # can deadlock Playwright's event dispatcher.

            try:
                context = browser.new_context(service_workers='block', accept_downloads=False)
                context.route('**/*', route_request)
                context.route_web_socket('**/*', route_socket)
                # CSP may deny IO before Playwright's request routes run. Keep
                # those attempted policy violations as durable failed checks,
                # rather than accepting a page that catches its denied fetch.
                context.expose_binding('__atom_policy_denied', lambda _source: blocked.append(True))
                context.add_init_script("""(() => {
                  const denied = window.__atom_policy_denied;
                  document.addEventListener('securitypolicyviolation', event => {
                    if (event.disposition === 'enforce') denied();
                  });
                })();""")
                page = context.new_page()
                page.set_default_timeout(_remaining(deadline, ceiling_ms=1500))

                def navigation(frame):
                    if frame == page.main_frame and frame.url != 'about:blank':
                        try:
                            if _origin(frame.url) != origin:
                                escaped.append(True)
                        except ObservationError:
                            escaped.append(True)

                page.on('framenavigated', navigation)
                response = page.goto(url, wait_until='domcontentloaded',
                                     timeout=_remaining(deadline, ceiling_ms=10000))
                if response is None or response.status != 200 or escaped:
                    raise ObservationError('content_unavailable')
                try:
                    passed = _check(page, check, deadline)
                    note = 'observed' if passed else 'check_unmet'
                except BrowserError:
                    if not browser.is_connected():
                        raise ObservationError('browser_unavailable') from None
                    passed, note = False, 'check_unmet'
                if escaped or _origin(page.url) != origin or blocked:
                    passed, note = False, 'content_policy_denied'
                results.append({'key': requirement['key'], 'checkIndex': index,
                                'passed': passed, 'note': note})
            except BrowserError:
                raise ObservationError('browser_unavailable') from None
            finally:
                if context is not None:
                    try:
                        context.close()
                    except BrowserError:
                        raise ObservationError('browser_unavailable') from None
    _remaining(deadline, ceiling_ms=1)
    return capture_report(canonical, results)
