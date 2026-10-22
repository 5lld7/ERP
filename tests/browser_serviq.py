"""Exercise the Serviq identity, base currency and customer quotation workflow.

All data and credentials are temporary. WhatsApp navigation is intercepted: no
external requests or messages are sent. Run with system Python (Playwright):
    python3 tests/browser_serviq.py --entrypoint vercel
"""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def run(directory, entrypoint='local'):
    from playwright.sync_api import sync_playwright
    screenshots = Path(directory)
    screenshots.mkdir(parents=True, exist_ok=True)
    errors = []
    setup_token = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(20)
    company = 'Serviq test company'
    # Preserve exact Arabic customer data in English and escape markup safely.
    customer = 'المبيعات <علي> & Sons'
    with tempfile.TemporaryDirectory() as data:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        python = str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() else sys.executable
        command = [python, str(ROOT / 'server.py'), '--port', str(port)]
        if entrypoint == 'vercel':
            command = [python, '-c', f"from http.server import ThreadingHTTPServer; from api.index import handler; ThreadingHTTPServer(('127.0.0.1',{port}),handler).serve_forever()"]
        environment = {**os.environ, 'ERP_DATA_DIR': data, 'ERP_DATABASE_URL': '', 'ERP_DATABASE_TOKEN': '',
                       'ERP_SETUP_TOKEN': setup_token, 'VERCEL': '', 'ERP_COOKIE_SECURE': '0',
                       'ERP_DB_DRIVER': 'libsql' if entrypoint == 'vercel' else 'sqlite'}
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            base = f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    urlopen(base + '/api/auth', timeout=1).close()
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError(process.stderr.read().decode())
                    time.sleep(.05)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
                context = browser.new_context(viewport={'width': 1440, 'height': 1100}, locale='ar-EG', reduced_motion='reduce')
                intercepted = []

                def whatsapp_preview(route):
                    intercepted.append(route.request.url)
                    route.fulfill(status=200, content_type='text/html', body='<title>Intercepted WhatsApp preview</title>')

                context.route('https://wa.me/**', whatsapp_preview)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                page.wait_for_selector('#auth-form')
                assert page.title().startswith('Serviq |')
                assert page.locator('.brand').inner_text().startswith('Serviq')
                page.locator('[data-action=language]').click()
                assert page.locator('html').get_attribute('lang') == 'en'
                assert 'Welcome to Serviq' in page.locator('.auth-card').inner_text()
                for key, value in dict(company_name=company, name='Test admin', username='admin', password=password, setup_token=setup_token).items():
                    page.locator(f'[name={key}]').fill(value)
                page.locator('#auth-form button[type=submit]').click()
                page.wait_for_selector('.welcome-banner')

                def call(path, method='GET', payload=None):
                    kwargs = dict(method=method, headers={'X-ERP-Request': '1', 'Accept-Language': 'en'})
                    if payload is not None:
                        kwargs['data'] = payload
                    response = context.request.fetch(base + '/api/' + path, **kwargs)
                    assert response.ok, (path, response.status, response.text())
                    return response.json()

                def adjacent_tools():
                    assert page.locator('.notification-tools [data-action=language]').is_visible()
                    assert page.locator('.notification-tools [data-action=notifications]').is_visible()
                    assert page.locator('[data-action=language]').evaluate("el => el.nextElementSibling?.dataset.action === 'notifications'")
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

                adjacent_tools()
                palette = page.evaluate("() => { const css=getComputedStyle(document.documentElement); return ['--navy','--teal','--bg'].map(key => css.getPropertyValue(key).trim().toUpperCase()); }")
                assert palette == ['#142D4E', '#0F766E', '#F5F7FA'], palette
                page.goto(base + '/#/accounting')
                page.wait_for_selector('#currency-form')
                assert page.locator('[name=currency]').input_value() == 'EGP'
                assert page.locator('[name=currency] option').count() >= 10
                page.locator('[name=currency]').select_option('SAR')
                page.locator('#currency-form button[type=submit]').click()
                page.wait_for_function("() => document.querySelector('#currency-form select')?.value === 'SAR' && !document.querySelector('#currency-form button').disabled")
                assert call('bootstrap')['settings']['currency'] == 'SAR'
                page.goto(base + '/#/settings')
                page.wait_for_selector('#settings-form')
                assert page.locator('#settings-form select[name=currency]').input_value() == 'SAR'
                assert page.locator('#settings-form select[name=currency]').is_enabled()
                print('PASS: Serviq identity, exact palette, language next to notifications, one base currency selection and settings consistency')

                boot = call('bootstrap')
                warehouse = boot['refs']['warehouses'][0]['id']
                unit = boot['refs']['units'][0]['id']
                product = call('resources/products', 'POST', {'name': 'خدمة معاينة', 'sku': 'SERVIQ-01', 'unit_id': unit, 'cost': 20, 'price': 100})['id']
                customer_id = call('resources/customers', 'POST', {'name': customer, 'phone': '01012345678', 'classification': 'عادي'})['id']
                inspection_id = call('documents', 'POST', {'kind': 'inspection', 'date': '2026-10-19', 'warehouse_id': warehouse,
                                                        'customer_id': customer_id, 'appointment_date': '2026-10-20',
                                                        'location': 'Customer location', 'tax_rate': 14, 'post': True,
                                                        'lines': [{'product_id': product, 'quantity': 2, 'price': 100}]})['id']
                assert not call('bootstrap')['currency_locked'], 'Non-financial quotation must not lock the company currency'
                page.goto(base + '/#/doc_inspection')
                page.wait_for_selector(f'[data-action=view-doc][data-id="{inspection_id}"]')
                assert page.locator(f'[data-action=quotation-pdf][data-id="{inspection_id}"]').is_visible()
                assert page.locator(f'[data-action=quotation-whatsapp][data-id="{inspection_id}"]').is_visible()
                page.locator(f'[data-action=view-doc][data-id="{inspection_id}"]').click()
                page.wait_for_selector('#print-content')
                assert 'Quotation' in page.locator('#print-content').inner_text()
                assert customer in page.locator('#print-content').inner_text()
                assert 'SAR' in page.locator('.grand-total').inner_text()
                assert page.locator('#print-content علي').count() == 0
                for language in ('en', 'ar'):
                    if language == 'ar':
                        page.locator('#modal-root [data-action=close]').first.click()
                        page.locator('[data-action=language]').click()
                        page.wait_for_selector(f'[data-action=view-doc][data-id="{inspection_id}"]')
                        page.locator(f'[data-action=view-doc][data-id="{inspection_id}"]').click()
                        page.wait_for_selector('#print-content')
                        assert 'عرض سعر' in page.locator('#print-content').inner_text()
                        assert 'ر.س' in page.locator('.grand-total').inner_text()
                    with page.expect_download() as result:
                        page.locator('#modal-root [data-action=quotation-pdf]').click()
                    download = result.value
                    assert download.suggested_filename.endswith('.pdf')
                    assert Path(download.path()).read_bytes().startswith(b'%PDF-')
                    with context.expect_page() as opened:
                        page.locator('#modal-root [data-action=quotation-whatsapp]').click()
                    popup = opened.value
                    popup.wait_for_url('https://wa.me/**')
                    popup.wait_for_load_state()
                    assert popup.evaluate('window.opener === null')
                    target = urlsplit(intercepted[-1])
                    assert target.hostname == 'wa.me' and target.path == '/201012345678'
                    message = parse_qs(target.query)['text'][0]
                    assert customer in message and company in message
                    assert chr(10) in message and chr(92) + 'n' not in message
                    assert '228' in message and ('SAR' if language == 'en' else 'ر.س') in message
                    assert ('quotation' if language == 'en' else 'عرض السعر') in message
                    public_link = next(line for line in message.splitlines() if line.startswith(base + '/api/quotations/shared?token='))
                    # A separate context has no session cookie and can only retrieve the PDF.
                    public = browser.new_context()
                    shared = public.request.get(public_link)
                    assert shared.ok and shared.headers['content-type'] == 'application/pdf'
                    assert shared.body().startswith(b'%PDF-')
                    public.close()
                    token = parse_qs(urlsplit(public_link).query)['token'][0]
                    assert not page.evaluate('(secret) => JSON.stringify(localStorage).includes(secret)', token)
                    assert call(f'documents/{inspection_id}')['progress'] != 'عرض مرسل', 'Opening WhatsApp cannot claim message delivery'
                    popup.close()
                    page.screenshot(path=str(screenshots / f'quotation-{language}.png'), full_page=True)
                print('PASS: named Arabic/English quotation PDF downloads, exact customer data, secure WhatsApp previews and unauthenticated PDF-only links')

                # A blocked popup still offers an explicit user-controlled link.
                page.evaluate('window.open = () => null')
                page.locator('#modal-root [data-action=quotation-whatsapp]').click()
                page.wait_for_selector('#modal-root a[href^="https://wa.me/"]')
                fallback = page.locator('#modal-root a[href^="https://wa.me/"]')
                assert fallback.get_attribute('target') == '_blank'
                assert 'noopener' in fallback.get_attribute('rel')
                page.locator('#modal-root [data-action=close]').first.click()
                # Only a real financial entry locks currency selection.
                accounts = boot['refs']['accounts']
                debit = next(item['id'] for item in accounts if item['code'] == '1100')
                credit = next(item['id'] for item in accounts if item['code'] == '3100')
                call('journal', 'POST', {'date': '2026-10-19', 'description': 'Opening funds', 'lines': [
                    {'account_id': debit, 'debit': 100, 'credit': 0}, {'account_id': credit, 'debit': 0, 'credit': 100}]})
                page.goto(base + '/#/accounting')
                page.wait_for_selector('#currency-form select:disabled')
                assert page.locator('#currency-help').is_visible()
                assert page.locator('#currency-form button[type=submit]').count() == 0
                page.goto(base + '/#/settings')
                page.wait_for_selector('#settings-form select[name=currency]:disabled')
                page.locator('#settings-form [name=company_phone]').fill('01012345678')
                page.locator('#settings-form button[type=submit]').click()
                page.wait_for_selector('#settings-form select[name=currency]:disabled')
                assert call('bootstrap')['settings']['currency'] == 'SAR'
                print('PASS: popup-blocked fallback and immutable base currency after financial posting; unrelated settings still save')

                for language in ('ar', 'en'):
                    if page.locator('html').get_attribute('lang') != language:
                        page.locator('[data-action=language]').click()
                        page.wait_for_selector('#settings-form')
                    page.set_viewport_size({'width': 390, 'height': 844})
                    adjacent_tools()
                    page.screenshot(path=str(screenshots / f'mobile-{language}.png'), full_page=True)
                assert not errors, errors
                browser.close()
                print('PASS: visible adjacent language and notifications controls in both mobile directions; no JavaScript errors')
        except Exception:
            try:
                print('Browser form errors:', page.locator('.form-error').all_text_contents(), flush=True)
                print('JavaScript errors:', errors, flush=True)
                page.screenshot(path=str(screenshots / 'failure.png'), full_page=True)
            except Exception:
                pass
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--screenshots', default='/tmp/serviq-browser-screenshots')
    parser.add_argument('--entrypoint', choices=['local', 'vercel'], default='local')
    args = parser.parse_args()
    run(args.screenshots, args.entrypoint)
