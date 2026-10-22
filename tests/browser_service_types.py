"""Browser regression for cleaning/pest-control workflows, using isolated data.

    python3 tests/browser_service_types.py --entrypoint vercel
"""
import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def run(entrypoint='local', screenshots='/tmp/serviq-service-types-screenshots'):
    from playwright.sync_api import sync_playwright
    output = Path(screenshots)
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    setup_token, password = secrets.token_urlsafe(32), secrets.token_urlsafe(20)
    today = date.today().isoformat()
    upcoming = (date.today() + timedelta(days=1)).isoformat()
    customer = 'المبيعات <أحمد> & Co'
    method = 'METHOD-SNAPSHOT-2026: Inspect, protect surfaces, then clean.'
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        python = str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() else sys.executable
        command = [python, str(ROOT / 'server.py'), '--port', str(port)]
        if entrypoint == 'vercel':
            command = [python, '-c', f"from http.server import ThreadingHTTPServer; from api.index import handler; ThreadingHTTPServer(('127.0.0.1',{port}),handler).serve_forever()"]
        environment = {**os.environ, 'ERP_DATA_DIR': directory, 'ERP_DATABASE_URL': '', 'ERP_DATABASE_TOKEN': '',
                       'ERP_SETUP_TOKEN': setup_token, 'VERCEL': '', 'ERP_COOKIE_SECURE': '0',
                       'ERP_DB_DRIVER': 'libsql' if entrypoint == 'vercel' else 'sqlite'}
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        page = None
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
                browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
                context = browser.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(base)
                page.wait_for_selector('#auth-form')
                for key, value in dict(company_name='Serviq Industry', name='Admin', username='admin', password=password, setup_token=setup_token).items():
                    page.locator(f'#auth-form [name={key}]').fill(value)
                page.locator('#auth-form button[type=submit]').click()
                page.wait_for_selector('.welcome-banner')

                def call(path, method='GET', payload=None, session=context, ok=True):
                    kwargs = {'method': method, 'headers': {'X-ERP-Request': '1', 'Accept-Language': 'en'}}
                    if payload is not None:
                        kwargs['data'] = payload
                    response = session.request.fetch(base + '/api/' + path, **kwargs)
                    assert response.ok == ok, (path, response.status, response.text())
                    return response.json()

                def visit(name):
                    page.goto(base + '/#/' + name)
                    page.wait_for_selector('#main .page-heading')
                    page.wait_for_selector('#main .loading', state='detached')

                page.locator('[data-action=language]').click()
                page.wait_for_function("() => document.documentElement.lang === 'en'")
                boot=call('bootstrap')
                unit=boot['refs']['units'][0]['id']
                page.goto(base+'/#/services')
                page.wait_for_selector('a[href="#/service_types"].btn')
                page.locator('a[href="#/service_types"].btn').click()
                page.wait_for_selector('[data-action=new-resource]')
                assert page.locator('.page-heading h1').inner_text()=='Service types'
                page.locator('[data-action=new-resource]').click()
                page.locator('#resource-form [name=name]').fill('نوع خاص')
                page.locator('#resource-form [name=name_en]').fill('Custom exact type')
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#resource-form',state='detached')
                tid=next(r['id'] for r in call('resources/service_types') if r['name']=='نوع خاص')
                page.goto(base+'/#/services')
                page.wait_for_selector('[data-action=new-resource]')
                page.locator('[data-action=new-resource]').click()
                assert page.locator('[name=service_category] option[value="نوع خاص"]').inner_text()=='Custom exact type'
                for key,value in dict(name='Custom catalog service',sku='CUSTOM-TYPE-SVC',price='100').items():
                    page.locator(f'#resource-form [name={key}]').fill(value)
                page.locator('[name=service_category]').select_option('نوع خاص')
                page.locator('[name=unit_id]').select_option(str(unit))
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#resource-form',state='detached')
                assert 'Custom exact type' in page.locator('tbody').inner_text()
                page.locator('a[href="#/service_types"].btn').click()
                row=page.locator('tbody tr',has_text='نوع خاص')
                row.locator('[data-action=edit-resource]').click()
                page.locator('#resource-form [name=name]').fill('نوع محدث')
                page.locator('#resource-form [name=name_en]').fill('Updated exact type')
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#resource-form',state='detached')
                assert call('resources/services')[0]['service_category']=='نوع محدث'
                # Used types cannot remove their existing service associations.
                response=context.request.delete(base+f'/api/resources/service_types/{tid}',headers={'X-ERP-Request':'1'})
                assert response.status==400
                for route,selector in [('appointments','#appointment-filter'),('report_appointment_services','#report-filter')]:
                    page.goto(base+'/#/'+route)
                    page.wait_for_selector(selector)
                    assert page.locator(f'{selector} [name=service_category] option[value="نوع محدث"]').inner_text()=='Updated exact type'
                print('PASS: add and rename types; exact bilingual labels follow services, booking and report filters')

                page.goto(base+'/#/service_types')
                page.wait_for_selector('[data-action=new-resource]')
                page.locator('[data-action=new-resource]').click()
                page.locator('#resource-form [name=name]').fill('Unused type')
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#resource-form',state='detached')
                page.locator('tbody tr',has_text='Unused type').locator('[data-action=delete-resource]').click()
                page.locator('[data-action=confirmed]').click()
                page.wait_for_function("() => !document.querySelector('tbody').textContent.includes('Unused type')")
                page.reload();page.wait_for_selector('tbody')
                assert 'Unused type' not in page.locator('tbody').inner_text()
                page.locator('[data-action=language]').click()
                page.wait_for_function("() => document.documentElement.lang === 'ar'")
                assert page.locator('.page-heading h1').inner_text()=='أنواع الخدمات'
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output/'service-types-mobile-ar.png'),full_page=True,style='#toasts{display:none!important}')
                print('PASS: delete unused types, protect used types, persisted reload and Arabic mobile management')
                assert not errors, errors
                browser.close()
                print('PASS: both mobile language directions and no JavaScript errors')
        except Exception:
            if page:
                try:
                    print('Form errors:', page.locator('.form-error').all_text_contents(), flush=True)
                    print('JavaScript errors:', errors, flush=True)
                    page.screenshot(path=str(output / 'failure.png'), full_page=True)
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
    parser.add_argument('--entrypoint', choices=['local', 'vercel'], default='local')
    parser.add_argument('--screenshots', default='/tmp/serviq-service-types-screenshots')
    args = parser.parse_args()
    run(args.entrypoint, args.screenshots)
