"""Exercise bilingual UI against an isolated local database, including the Vercel adapter.

Run with system Python (Playwright) and the project's virtualenv server:
    python3 tests/browser_bilingual.py --entrypoint vercel
"""
import argparse
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
ARABIC = re.compile(r'[\u0600-\u06ff]')


def english(text, location):
    assert text.strip(), f'Empty interface text: {location}'
    assert not ARABIC.search(text), f'Untranslated {location}: {text}'


def no_overflow(page, location):
    if not page.evaluate('document.documentElement.scrollWidth <= innerWidth'):
        page.screenshot(path='/tmp/erp-bilingual-overflow.png', full_page=True)
        bounds = page.evaluate("[...document.querySelectorAll('body *')].map(e => ({tag:e.tagName, cls:e.className, x:e.getBoundingClientRect().x, right:e.getBoundingClientRect().right})).filter(e => e.x < -1 || e.right > innerWidth + 1)")
        raise AssertionError(f'Horizontal overflow: {location}: {bounds}')


def language(page, value):
    page.locator('[data-action=language]').first.click()
    page.wait_for_function('(value) => document.documentElement.lang === value && window.I18n.language === value', arg=value)
    assert page.locator('html').get_attribute('dir') == ('rtl' if value == 'ar' else 'ltr')


def run(directory, entrypoint='local'):
    from playwright.sync_api import sync_playwright
    screenshots = Path(directory)
    screenshots.mkdir(parents=True, exist_ok=True)
    setup_token = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(20)
    # Deliberately match interface labels: a business value must never be translated.
    company = product_name = 'المخزون'
    errors = []
    with tempfile.TemporaryDirectory() as data:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        python = str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() else sys.executable
        command = [python, str(ROOT / 'server.py'), '--port', str(port)]
        if entrypoint == 'vercel':
            command = [python, '-c', f"from http.server import ThreadingHTTPServer; from api.index import handler; ThreadingHTTPServer(('127.0.0.1',{port}),handler).serve_forever()"]
        env = {**os.environ, 'ERP_DATA_DIR': data, 'ERP_DATABASE_URL': '', 'ERP_DATABASE_TOKEN': '',
               'ERP_SETUP_TOKEN': setup_token, 'VERCEL': '', 'ERP_COOKIE_SECURE': '0',
               'ERP_DB_DRIVER': 'libsql' if entrypoint == 'vercel' else ''}
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 390, 'height': 844}, locale='en-US', reduced_motion='reduce')
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                page.wait_for_selector('#auth-form')
                assert page.locator('html').get_attribute('lang') == 'ar'
                no_overflow(page, 'Arabic setup at 390px')
                page.locator('[name=company_name]').fill(company)
                language(page, 'en')
                assert page.locator('[name=company_name]').input_value() == company
                english(page.locator('.auth-card h2').inner_text(), 'setup title')
                for label in page.locator('#auth-form .field > span').all_text_contents():
                    english(label, 'setup label')
                assert page.locator('[data-action=language]').is_visible()
                no_overflow(page, 'English setup at 390px')
                page.screenshot(path=str(screenshots / '01-english-setup-mobile.png'), full_page=True)
                for key, value in dict(name='مسؤول النظام', username='admin', password=password,
                                       setup_token=secrets.token_urlsafe(32)).items():
                    page.locator(f'[name={key}]').fill(value)
                page.locator('#auth-form button[type=submit]').click()
                page.wait_for_function("() => document.querySelector('#auth-form .form-error')?.textContent.trim()")
                english(page.locator('#auth-form .form-error').inner_text(), 'invalid setup token error')
                page.locator('[name=setup_token]').fill(setup_token)
                page.locator('#auth-form button[type=submit]').click()
                page.wait_for_selector('.welcome-banner')
                assert page.locator('html').get_attribute('dir') == 'ltr'
                no_overflow(page, 'English dashboard at 390px')
                page.set_viewport_size({'width': 1440, 'height': 1100})
                assert page.locator('.company-label').inner_text().strip() == company
                sidebar = page.locator('.sidebar').bounding_box()
                main = page.locator('.main-wrap').bounding_box()
                assert sidebar['x'] == 0 and main['x'] >= sidebar['width'], (sidebar, main)
                page.reload()
                page.wait_for_selector('.welcome-banner')
                assert page.locator('html').get_attribute('lang') == 'en'
                assert page.locator('.company-label').inner_text().strip() == company
                english(page.locator('.welcome-banner h2').inner_text(), 'dashboard heading')
                page.screenshot(path=str(screenshots / '02-english-dashboard.png'), full_page=True)
                print('PASS: English setup, translated server error, saved preference and LTR sidebar')

                for route in ['accounting', 'inventory', 'sales', 'hr', 'reports', 'settings']:
                    page.goto(base + '/#/' + route)
                    page.wait_for_selector('#main:not(:has(.loading))')
                    english(page.locator('#main .page-heading h1').inner_text(), route + ' heading')
                    for text in page.locator('.feature-card h3, .report-card h3').all_text_contents():
                        english(text, route + ' feature')
                page.goto(base + '/#/products')
                page.wait_for_selector('[data-action=new-resource]')
                page.locator('[data-action=new-resource]').click()
                page.wait_for_selector('#resource-form')
                english(page.locator('#modal-title').inner_text(), 'product dialog')
                for label in page.locator('#resource-form .field > span').all_text_contents():
                    english(label, 'product field')
                for key, value in dict(name=product_name, sku='BILINGUAL-01', cost='100', price='150').items():
                    page.locator(f'#resource-form [name={key}]').fill(value)
                page.locator('#resource-form [name=unit_id]').select_option(index=1)
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#modal-root .modal', state='detached')
                page.wait_for_function("() => document.querySelector('tbody')?.textContent.includes('BILINGUAL-01')")
                row = page.locator('tbody tr', has_text='BILINGUAL-01')
                assert row.locator('.table-name').evaluate("el => [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join('')") == product_name
                for text in page.locator('th').all_text_contents():
                    english(text, 'product table header')
                row.locator('[data-action=edit-resource]').click()
                page.wait_for_selector('#resource-form')
                assert page.locator('#resource-form [name=name]').input_value() == product_name
                page.locator('[data-action=close]').first.click()
                print('PASS: all module headings, product form and table translated without changing Arabic business data')

                page.goto(base + '/#/report_stock')
                page.wait_for_selector('#report-content table')
                english(page.locator('.page-heading h1').inner_text(), 'stock report heading')
                for text in page.locator('#report-content th').all_text_contents():
                    english(text, 'report column')
                # Capture synchronously: printContent removes its temporary DOM after print returns.
                page.evaluate("() => { window.print = () => { const root = document.querySelector('#print-area'); window.printSnapshot = {lang: root.lang, dir: root.dir, title: root.querySelector('h2').textContent, company: root.querySelector('h1').textContent, text: root.innerText}; }; }")
                page.locator('[data-action=print-report]').click()
                snapshot = page.evaluate('window.printSnapshot')
                assert snapshot['lang'] == 'en' and snapshot['dir'] == 'ltr', snapshot
                english(snapshot['title'], 'printed report title')
                assert snapshot['company'] == company and product_name in snapshot['text']
                page.screenshot(path=str(screenshots / '03-english-report.png'), full_page=True)
                with page.expect_download() as result:
                    page.locator('[data-action=export-report]').click()
                csv = Path(result.value.path()).read_text(encoding='utf-8-sig')
                assert product_name in csv
                english(csv.splitlines()[0], 'CSV column names')
                print('PASS: report, English print direction and CSV headers preserve Arabic product names')

                page.locator('[data-action=profile]').click()
                page.wait_for_selector('[data-action=logout]')
                page.locator('[data-action=logout]').click()
                page.wait_for_selector('#auth-form')
                english(page.locator('.auth-card h2').inner_text(), 'login title')
                page.locator('[name=username]').fill('admin')
                page.locator('[name=password]').fill(secrets.token_urlsafe(20))
                page.locator('#auth-form button[type=submit]').click()
                page.wait_for_function("() => document.querySelector('#auth-form .form-error')?.textContent.trim()")
                english(page.locator('#auth-form .form-error').inner_text(), 'incorrect login error')
                page.locator('[name=password]').fill(password)
                page.locator('#auth-form button[type=submit]').click()
                page.wait_for_selector('#auth-form', state='detached')
                page.wait_for_selector('#main:not(:has(.loading))')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.locator('button[data-action=menu]').click()
                page.wait_for_selector('body.menu-open')
                page.wait_for_function("Math.abs(document.querySelector('.sidebar').getBoundingClientRect().x) < 1")
                sidebar = page.locator('.sidebar').bounding_box()
                assert sidebar['x'] == 0, sidebar
                page.locator('.sidebar a[href="#/inventory"]').click()
                page.wait_for_selector('.module-intro')
                assert 'menu-open' not in page.locator('body').get_attribute('class')
                no_overflow(page, 'English mobile inventory')
                language(page, 'ar')
                page.wait_for_selector('.module-intro')
                assert ARABIC.search(page.locator('.page-heading h1').inner_text())
                no_overflow(page, 'Arabic mobile inventory')
                page.locator('button[data-action=menu]').click()
                page.wait_for_selector('body.menu-open')
                page.wait_for_function("Math.abs(document.querySelector('.sidebar').getBoundingClientRect().right - innerWidth) < 1")
                sidebar = page.locator('.sidebar').bounding_box()
                assert abs(sidebar['x'] + sidebar['width'] - 390) < 1, sidebar
                page.locator('.sidebar a[href="#/products"]').click()
                page.wait_for_selector('tbody tr')
                assert product_name in page.locator('tbody').inner_text()
                page.reload()
                page.wait_for_selector('tbody tr')
                assert page.locator('html').get_attribute('lang') == 'ar'
                page.screenshot(path=str(screenshots / '04-arabic-products-mobile.png'), full_page=True)
                assert not errors, errors
                browser.close()
                print('PASS: English login errors, bidirectional mobile navigation, persisted Arabic switch, no JavaScript errors')
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
    parser.add_argument('--screenshots', default='/tmp/erp-bilingual-screenshots')
    parser.add_argument('--entrypoint', choices=['local', 'vercel'], default='local')
    args = parser.parse_args()
    run(args.screenshots, args.entrypoint)
