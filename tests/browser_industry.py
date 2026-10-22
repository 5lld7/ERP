"""Browser regression for cleaning/pest-control workflows, using isolated data.

    python3 tests/browser_industry.py --entrypoint vercel
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


def run(entrypoint='local', screenshots='/tmp/serviq-industry-screenshots'):
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

                accounting = page.locator('[data-module=accounting]')
                accounting.click()
                page.wait_for_selector('#currency-form')
                accounting.click()
                assert accounting.get_attribute('aria-expanded') == 'false'
                assert page.locator('#sidebar-accounting').is_hidden()
                accounting.click()
                assert accounting.get_attribute('aria-expanded') == 'true'
                visit('products')
                page.locator('[data-module=inventory]').click()
                assert page.url.endswith('#/products')
                assert page.locator('#sidebar-inventory').is_hidden()
                page.locator('[data-module=inventory]').click()
                assert page.locator('#sidebar-inventory a.selected').get_attribute('href') == '#/products'
                print('PASS: module headings close/reopen and preserve the selected page')

                page.locator('[data-action=language]').click()
                page.wait_for_function("() => document.documentElement.lang === 'en'")
                boot = call('bootstrap')
                unit = next(item for item in boot['refs']['units'] if item.get('name_en'))
                assert len(boot['refs']['units']) >= 40
                call('resources/units', 'POST', {'name': 'وحدة خاصة', 'name_en': 'Custom exact unit'})
                visit('units')
                assert unit['name_en'] in page.locator('#main').inner_text()
                assert 'Custom exact unit' in page.locator('#main').inner_text()
                assert unit['name'] not in page.locator('#main tbody').inner_text()
                visit('customers')
                page.locator('[data-action=new-resource]').click()
                assert page.locator('[name=classification] option[value="مؤسسة"]').inner_text() == 'Organization'
                assert page.locator('[name=classification] option[value="جملة"]').count() == 0
                page.locator('#modal-root [data-action=close]').first.click()
                visit('doc_receipt')
                page.locator('[data-action=new-doc]').click()
                assert 'opening balance' not in page.locator('#modal-root').inner_text().lower()
                page.locator('#modal-root [data-action=close]').first.click()
                print('PASS: translated standard/custom units, organization customer class and receipt copy')

                warehouse, branch = boot['refs']['warehouses'][0]['id'], boot['refs']['branches'][0]['id']
                customer_id = call('resources/customers', 'POST', {'name': customer, 'phone': '01012345678', 'classification': 'مؤسسة'})['id']
                service_id = call('resources/services', 'POST', {'name': 'Deep cleaning service', 'sku': 'SVC-01', 'unit_id': unit['id'], 'price': 100, 'service_method': method})['id']
                call('resources/products', 'POST', {'name': 'Low stock material', 'sku': 'STOCK-01', 'unit_id': unit['id'], 'price': 10, 'cost': 5, 'min_stock': 2})
                visit('services')
                page.locator('[data-action=edit-resource]').click()
                assert page.locator('[name=service_method]').input_value() == method
                page.locator('#modal-root [data-action=close]').first.click()

                # A failed second attachment must retain the first upload and employee ID.
                visit('employees')
                page.locator('[data-action=new-resource]').click()
                fields = {'name': 'Employee Arabic ملف', 'code': 'EMP-01', 'national_id': 'ID-123', 'nationality': 'Egyptian',
                          'residency_expiry': upcoming, 'passport_expiry': upcoming, 'driving_license_expiry': upcoming,
                          'hire_date': today, 'salary': '1500'}
                for key, value in fields.items():
                    page.locator(f'#resource-form [name={key}]').fill(value)
                page.locator('[name=branch_id]').select_option(str(branch))
                pdf = b'%PDF-1.4\n1 0 obj <</Type /Catalog>> endobj\ntrailer <</Root 1 0 R>>\n%%EOF\n'
                files = [{'name': 'المخزون.pdf', 'mimeType': 'application/pdf', 'buffer': pdf},
                         {'name': 'contract-second.pdf', 'mimeType': 'application/pdf', 'buffer': pdf}]
                page.locator('[name=employee_upload]').set_input_files(files)
                failed = []

                def fail_second(route):
                    if route.request.method == 'POST' and route.request.post_data_json['name'] == 'contract-second.pdf' and not failed:
                        failed.append(True)
                        route.fulfill(status=503, content_type='application/json', body='{"error":"Temporary upload failure"}')
                    else:
                        route.continue_()

                page.route('**/api/employees/*/files', fail_second)
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_function("() => document.querySelector('#resource-form .form-error').textContent.includes('contract-second.pdf')")
                employee_id = int(page.locator('#resource-form').get_attribute('data-id'))
                assert len(call('resources/employees')) == 1
                assert len(call(f'employees/{employee_id}/files')) == 1
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#resource-form', state='detached')
                assert len(call('resources/employees')) == 1
                assert len(call(f'employees/{employee_id}/files')) == 2
                employee = call('resources/employees')[0]
                assert all(str(employee[key]) == value for key, value in fields.items() if key != 'salary')
                page.locator(f'[data-action=employee-files][data-id="{employee_id}"]').click()
                page.wait_for_selector('#employee-files-list [data-action=download-file]')
                assert page.locator('#file-form input[type=file]').get_attribute('multiple') is not None
                assert page.locator('#employee-files-list [data-action=download-file]').count() == 2
                for button in page.locator('#employee-files-list [data-action=download-file]').all():
                    with page.expect_download() as result:
                        button.click()
                    assert Path(result.value.path()).read_bytes() == pdf
                assert 'المخزون.pdf' in page.locator('#employee-files-list').inner_text()
                page.locator('#modal-root [data-action=close]').first.click()
                print('PASS: employee identity/expiry fields, multiple files, independent downloads and partial-upload retry without duplicates')

                visit('appointments')
                page.locator('[data-action=new-resource]').click()
                for key, value in {'customer_name': customer, 'date': upcoming, 'time': '10:30', 'address': 'Customer villa', 'phone': '01012345678'}.items():
                    page.locator(f'#resource-form [name={key}]').fill(value)
                page.locator('[name=service_type]').select_option('متابعة')
                page.locator('[name=site_type]').select_option('تاون فيلا')
                assert page.locator('[name=service_type] option[value="متابعة"]').inner_text() == 'Follow-up'
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#resource-form', state='detached')
                appointment = call('resources/appointments')[0]
                assert appointment['customer_name'] == customer and appointment['time'] == '10:30'
                assert appointment['service_type'] == 'متابعة' and appointment['site_type'] == 'تاون فيلا'

                visit('doc_inspection')
                page.locator('[data-action=new-doc]').click()
                page.locator('[name=customer_id]').select_option(str(customer_id))
                page.locator('#line-product').select_option(str(service_id))
                page.locator('[data-action=add-line]').click()
                assert page.locator('[data-field=price]').is_editable()
                assert method not in page.locator('#document-form').inner_text()
                assert page.locator('[name=service_method]').count() == 0
                page.locator('#document-form button[value=post]').click()
                page.wait_for_selector('#document-form', state='detached')
                inspection = call('documents?kind=inspection')[0]
                detail = call(f'documents/{inspection["id"]}')
                assert method not in str(detail)
                page.locator(f'[data-action=view-doc][data-id="{inspection["id"]}"]').click()
                page.wait_for_selector('#print-content')
                assert method not in page.locator('#print-content').inner_text()
                with page.expect_download() as result:
                    page.locator('#modal-root [data-action=quotation-pdf]').click()
                pdf_path = Path(result.value.path())
                assert pdf_path.read_bytes().startswith(b'%PDF-')
                pdf_text = subprocess.check_output(['pdftotext', str(pdf_path), '-']).decode()
                assert 'METHOD-SNAPSHOT-2026' in pdf_text
                page.locator('#modal-root [data-action=close]').first.click()
                print('PASS: appointment booking and non-stock services; method hidden in inspection, present in quotation PDF')

                page.evaluate('ServiqNotifications.refresh()')
                page.wait_for_function('() => Number(document.querySelector("#notification-count").textContent) > 0')
                page.locator('[data-action=notifications]').click()
                page.wait_for_selector('#notifications-content')
                assert customer in page.locator('#notifications-content').inner_text()
                page.locator('[data-action=notification-sound]').click()
                page.wait_for_function('() => ServiqNotifications.getState().sound_enabled === true')
                page.locator('[data-action=notification-mark-all]').click()
                page.wait_for_function('() => document.querySelector("#notification-count").textContent === "0"')
                page.locator('#modal-root [data-action=close]').first.click()
                call('resources/appointments', 'POST', {**appointment, 'customer_name': 'New notification', 'time': '11:00'})
                page.evaluate('ServiqNotifications.refresh()')
                page.wait_for_function('() => Number(document.querySelector("#notification-count").textContent) > 0')
                print('PASS: readable notification badge, mark-as-read, new-event increments and sound preference')

                call('users', 'POST', {'name': 'Technician', 'username': 'tech', 'password': password, 'role': 'technician'})
                tech = browser.new_context(viewport={'width': 1440, 'height': 1100})
                call('login', 'POST', {'username': 'tech', 'password': password}, session=tech)
                tech_page = tech.new_page()
                tech_page.on('pageerror', lambda error: errors.append(str(error)))
                tech_page.goto(base + '/#/doc_inspection')
                tech_page.wait_for_selector('[data-action=new-doc]')
                assert tech_page.locator('[data-module=accounting]').count() == 0
                tech_page.locator('[data-action=new-doc]').click()
                tech_page.locator('[name=customer_id]').select_option(str(customer_id))
                tech_page.locator('#line-product').select_option(str(service_id))
                tech_page.locator('[data-action=add-line]').click()
                for selector in ('[data-field=price]', '[name=discount]', '[name=tax_rate]'):
                    assert tech_page.locator(selector).get_attribute('readonly') is not None
                assert tech_page.locator('[data-field=quantity]').is_editable()
                tampered = {'kind': 'inspection', 'date': today, 'warehouse_id': warehouse, 'customer_id': customer_id,
                            'tax_rate': boot['settings']['tax_rate'], 'post': True,
                            'lines': [{'product_id': service_id, 'quantity': 1, 'price': 1}]}
                call('documents', 'POST', tampered, session=tech, ok=False)
                call('documents', 'POST', {**tampered, 'discount': 1, 'lines': [{'product_id': service_id, 'quantity': 1, 'price': 100}]}, session=tech, ok=False)
                tech_page.locator('#document-form button[value=post]').click()
                tech_page.wait_for_selector('#document-form', state='detached')
                assert tech_page.locator('[data-action=convert-doc]').count() == 0
                tech.close()
                print('PASS: technician can quote services and quantities; price/discount tampering rejected in UI and API')

                for language in ('en', 'ar'):
                    if page.locator('html').get_attribute('lang') != language:
                        page.locator('[data-action=language]').click()
                        page.wait_for_function('(lang) => document.documentElement.lang === lang', arg=language)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.locator('#notification-count').is_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.screenshot(path=str(output / f'industry-mobile-{language}.png'), full_page=True)
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
    parser.add_argument('--screenshots', default='/tmp/serviq-industry-screenshots')
    args = parser.parse_args()
    run(args.entrypoint, args.screenshots)
