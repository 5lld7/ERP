"""Browser regression for cleaning/pest-control workflows, using isolated data.

    python3 tests/browser_appointments.py --entrypoint vercel
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


def run(entrypoint='local', screenshots='/tmp/serviq-appointments-screenshots'):
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
                unit,branch,warehouse=boot['refs']['units'][0]['id'],boot['refs']['branches'][0]['id'],boot['refs']['warehouses'][0]['id']
                service=call('resources/services','POST',dict(name='Pest control specialist',sku='AP-SVC',unit_id=unit,price=100,service_category='مكافحة حشرات',service_method='Protect then treat.'))['id']
                cleaning=call('resources/services','POST',dict(name='Deep cleaning',sku='AP-CLEAN',unit_id=unit,price=150,service_category='تنظيف'))['id']
                employee=call('resources/employees','POST',dict(name='Inspector One',code='AP-EMP',branch_id=branch,hire_date=today,salary=1500,status='نشط'))['id']
                # The arrow expands only; the label always opens the module home.
                page.locator('[data-module=accounting]').click()
                assert page.locator('.welcome-banner').is_visible()
                page.locator('[data-module-link=accounting]').click()
                page.wait_for_selector('.module-intro')
                page.locator('[data-module=accounting]').click()
                assert page.locator('#sidebar-accounting').is_hidden()
                page.locator('[data-module-link=accounting]').click()
                page.wait_for_selector('.module-intro')
                assert page.locator('#sidebar-accounting').is_visible()
                print('PASS: independent sidebar arrow and module home navigation')

                page.goto(base+'/#/appointments')
                page.wait_for_selector('#appointment-filter')
                page.locator('[data-action=new-resource]').click()
                for key,value in dict(customer_name='Booked customer',date=today,time='10:30',address='Client address',phone='01033333333').items():
                    page.locator(f'#resource-form [name={key}]').fill(value)
                page.locator('#resource-form [name=service_status]').select_option('معاينة')
                page.locator('#resource-form [name=service_id]').select_option(str(service))
                assert 'Pest control' in page.locator('#resource-form [name=service_id]').inner_text()
                page.locator('#resource-form [name=site_type]').select_option('فيلا')
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#resource-form',state='detached')
                aid=call('appointments')['items'][0]['id']
                tomorrow=dict(customer_name='Tomorrow cleaning',date=upcoming,time='12:30',address='Later address',phone='01044444444',service_status='متابعة',service_id=cleaning,site_type='شقة')
                later=call('resources/appointments','POST',tomorrow)['id']
                page.reload();page.wait_for_selector('#appointment-filter')
                page.locator('[data-action=appointments-today]').click()
                page.wait_for_function("() => document.querySelectorAll('.appointment-table tbody tr').length===1")
                assert 'Booked customer' in page.locator('.appointment-table').inner_text()
                page.locator('#appointment-select-all').check()
                page.locator('[data-action=appointment-bulk][data-kind=assign]').click()
                page.locator('#appointment-assignment [name=employee_id]').select_option(str(employee))
                page.locator('#appointment-assignment button[type=submit]').click()
                page.wait_for_selector('#appointment-assignment',state='detached')
                assert 'Inspector One' in page.locator('.appointment-table').inner_text()
                page.locator('.appointment-row-action').select_option('complete')
                page.wait_for_function("() => document.querySelector('.appointment-table').textContent.includes('Inspected')")
                print('PASS: live service catalog, today filtering, employee assignment and completion')

                page.locator('.appointment-row-action').select_option('quotation')
                page.wait_for_selector('#document-form')
                assert 'Booked customer' in page.locator('.appointment-context').inner_text()
                assert page.locator('[data-field=quantity]').count()==1
                page.locator('[data-field=quantity]').fill('2')
                page.locator('#document-form button[value=post]').click()
                page.wait_for_selector('#document-form',state='detached')
                record=call(f'appointments/{aid}')
                assert record['status']=='quoted' and record['quotation_id']
                page.locator('.appointment-row-action').select_option('invoice')
                page.wait_for_selector('#document-form')
                page.locator('#document-form [name=paid]').fill('50')
                page.locator('#document-form button[value=post]').click()
                page.wait_for_selector('#document-form',state='detached')
                record=call(f'appointments/{aid}')
                assert record['status']=='invoiced' and record['invoice_id']
                page.goto(base+'/#/report_appointment_services')
                page.wait_for_selector('#report-content tbody tr')
                assert 'Inspection' in page.locator('#report-content').inner_text()
                assert '200' in page.locator('#report-content').inner_text()
                print('PASS: linked quotation then sales invoice and service-activity financial report')

                # Each selected booking gets its own editable quotation; cancelling
                # the second form must leave that booking untouched.
                one=call('resources/appointments','POST',{**tomorrow,'customer_name':'Bulk one','phone':'01055555551'})['id']
                two=call('resources/appointments','POST',{**tomorrow,'customer_name':'Bulk two','phone':'01055555552'})['id']
                page.goto(base+'/#/appointments');page.wait_for_selector('#appointment-filter')
                page.locator('[data-action=appointments-clear]').click()
                page.wait_for_function("() => document.querySelectorAll('.appointment-table tbody tr').length===4")
                page.locator(f'.appointment-select[value="{one}"]').check()
                page.locator(f'.appointment-select[value="{two}"]').check()
                page.locator('[data-action=appointment-bulk][data-kind=quotation]').click()
                page.wait_for_selector('#document-form')
                page.locator('#document-form button[value=post]').click()
                page.wait_for_function("() => document.querySelector('.appointment-context')?.textContent.includes('Bulk two')")
                page.locator('#document-form [data-action=close]').click()
                assert call(f'appointments/{one}')['quotation_id']
                assert call(f'appointments/{two}')['quotation_id'] is None
                print('PASS: independent bulk conversion queue and safe cancellation of unsaved quotations')

                for language in ('en','ar'):
                    if page.locator('html').get_attribute('lang')!=language:
                        page.locator('[data-action=language]').click()
                        page.wait_for_function('(lang)=>document.documentElement.lang===lang',arg=language)
                    page.wait_for_selector('#appointment-filter')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    if language=='en':
                        texts=page.locator('.page-heading, #appointment-filter, .appointment-bulkbar, .appointments-alert, .appointment-table thead').all_text_contents()
                        import re
                        assert not any(re.search('[\u0600-\u06ff]', text) for text in texts),texts
                    page.screenshot(path=str(output/f'appointments-mobile-{language}.png'),full_page=True)
                print('PASS: bilingual appointment filters and mobile layouts')
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
    parser.add_argument('--screenshots', default='/tmp/serviq-appointments-screenshots')
    args = parser.parse_args()
    run(args.entrypoint, args.screenshots)
