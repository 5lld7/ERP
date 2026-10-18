"""Optional end-to-end checks using Playwright + system Chromium.

Uses an isolated temporary database. Never touches company data or credentials.
Run: python3 tests/browser_smoke.py --screenshots /tmp/erp-screenshots
"""
import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]


def run(directory,entrypoint='local'):
    from playwright.sync_api import sync_playwright
    screenshots=Path(directory)
    screenshots.mkdir(parents=True,exist_ok=True)
    errors=[]
    with tempfile.TemporaryDirectory() as data:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        python=str(ROOT/'.venv/bin/python') if (ROOT/'.venv/bin/python').exists() else sys.executable
        setup_token=secrets.token_urlsafe(32) if entrypoint=='vercel' else ''
        command=[python,str(ROOT/'server.py'),'--port',str(port)]
        if entrypoint=='vercel':
            command=[python,'-c',f"from http.server import ThreadingHTTPServer; from api.index import handler; ThreadingHTTPServer(('127.0.0.1',{port}),handler).serve_forever()"]
        process=subprocess.Popen(command,cwd=ROOT,env={**os.environ,'ERP_DATA_DIR':data,'ERP_DATABASE_URL':'','ERP_DATABASE_TOKEN':'','ERP_SETUP_TOKEN':setup_token,'VERCEL':'','ERP_COOKIE_SECURE':'0','ERP_DB_DRIVER':'libsql' if entrypoint=='vercel' else ''},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            base=f'http://127.0.0.1:{port}'
            for _ in range(100):
                try:
                    urlopen(base+'/api/auth',timeout=1).close()
                    break
                except OSError:
                    time.sleep(.05)
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1440,'height':1100},locale='ar-EG',reduced_motion='reduce')
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(base)
                page.wait_for_selector('#auth-form')
                page.screenshot(path=str(screenshots/'01-setup.png'),full_page=True)
                for key,value in dict(company_name='شركة مدار للأعمال',name='مسؤول النظام',username='admin',password=secrets.token_urlsafe(20)).items():
                    page.locator(f'[name={key}]').fill(value)
                if setup_token:
                    page.locator('[name=setup_token]').fill(setup_token)
                page.locator('#auth-form button[type=submit]').click()
                page.wait_for_selector('.welcome-banner')
                page.locator('[data-action=demo]').click()
                page.locator('[data-action=confirmed]').click()
                page.wait_for_selector('.demo-banner',state='detached')
                page.wait_for_selector('#modal-root .modal',state='detached')
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(screenshots/'02-dashboard.png'),full_page=True,style='#toasts{display:none!important}')
                print('PASS: first administrator setup and optional demo dataset')
                page.goto(base+'/#/products')
                page.wait_for_selector('tbody tr')
                assert page.locator('tbody tr').count()==6
                page.locator('[data-action=new-resource]').click()
                page.locator('[name=name]').fill('حامل أوراق تجريبي')
                page.locator('[name=sku]').fill('BROWSER-01')
                page.locator('[name=unit_id]').select_option(index=1)
                page.locator('[name=cost]').fill('100')
                page.locator('[name=price]').fill('150')
                page.locator('#resource-form button[type=submit]').click()
                page.wait_for_selector('#modal-root .modal',state='detached')
                page.wait_for_function("() => document.querySelectorAll('tbody tr').length===7")
                page.locator('#table-search').fill('حامل أوراق')
                assert page.locator('tbody tr:not(.hidden)').count()==1
                page.locator('tbody tr:not(.hidden) [data-action=barcode]').click()
                page.wait_for_selector('.barcode-svg')
                page.locator('[data-action=qr]').click()
                page.wait_for_function("() => document.querySelector('.qr-image')?.naturalWidth>0")
                page.locator('[data-action=close]').click()
                print('PASS: add product and table search')
                print('PASS: printable Code 39 and QR labels')
                page.goto(base+'/#/doc_purchase')
                page.wait_for_selector('[data-action=new-doc]')
                page.locator('[data-action=new-doc]').click()
                page.wait_for_selector('#document-form')
                page.locator('[name=supplier_id]').select_option(index=1)
                page.locator('#line-product').select_option(label='BROWSER-01 — حامل أوراق تجريبي')
                page.locator('[data-action=add-line]').click()
                page.locator('.line-input[data-field=quantity]').fill('5')
                page.locator('[name=paid]').fill('100')
                page.locator('#document-form button[value=post]').click()
                page.wait_for_selector('#modal-root .modal',state='detached')
                page.wait_for_function("() => document.querySelector('tbody tr')?.textContent.includes('570')")
                print('PASS: purchase invoice posts inventory and accounting')
                page.goto(base+'/#/pos')
                page.wait_for_selector('[data-action=pos-product]')
                page.locator('[data-action=pos-product]',has_text='حامل أوراق تجريبي').click()
                page.wait_for_selector('#document-form')
                page.locator('[name=customer_id]').select_option(index=1)
                page.locator('[name=paid]').fill('50')
                page.locator('#document-form button[value=post]').click()
                page.wait_for_selector('#modal-root .modal',state='detached')
                page.goto(base+'/#/doc_sale')
                page.wait_for_selector('tbody tr')
                page.locator('tbody tr').first.locator('[data-action=view-doc]').click()
                page.wait_for_selector('#print-content')
                assert '171' in page.locator('#print-content').inner_text()
                page.screenshot(path=str(screenshots/'03-invoice.png'),full_page=True)
                page.locator('[data-action=pay-doc]').click()
                page.wait_for_selector('#payment-form')
                page.locator('#payment-form button[type=submit]').click()
                page.wait_for_selector('#modal-root .modal',state='detached')
                print('PASS: POS sale, invoice details and remaining balance collection')
                page.goto(base+'/#/payroll')
                page.wait_for_selector('[data-action=new-payroll]')
                page.locator('[data-action=new-payroll]').click()
                page.locator('#simple-form button[type=submit]').click()
                page.wait_for_selector('#modal-root .modal',state='detached')
                page.wait_for_selector('tbody tr')
                assert page.locator('tbody tr').count()==1
                page.goto(base+'/#/report_payroll')
                page.wait_for_selector('#report-content tbody tr')
                assert page.locator('#report-content tbody tr').count()==4
                print('PASS: payroll calculation, accounting posting and four payslip records')
                page.goto(base+'/#/employees')
                page.wait_for_selector('[data-action=employee-files]')
                page.locator('[data-action=employee-files]').first.click()
                page.wait_for_selector('#file-form')
                page.locator('[name=upload]').set_input_files({'name':'employment-contract.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.7\n% Fixture\n%%EOF'})
                page.locator('#file-form button[type=submit]').click()
                page.wait_for_selector('#modal-root tbody tr')
                assert 'employment-contract.pdf' in page.locator('#modal-root').inner_text()
                page.locator('[data-action=close]').click()
                page.goto(base+'/#/doc_inspection')
                page.wait_for_selector('[data-action=inspection-progress]')
                page.locator('[data-action=inspection-progress]').first.click()
                page.locator('[name=progress]').select_option(label='عرض مرسل')
                page.locator('#progress-form button[type=submit]').click()
                page.wait_for_selector('#modal-root .modal',state='detached')
                page.wait_for_function("() => document.querySelector('tbody tr')?.textContent.includes('عرض مرسل')")
                page.locator('tbody tr').first.locator('[data-action=convert-doc]').click()
                page.wait_for_selector('#document-form')
                assert page.locator('.line-table tbody tr').count()==1
                page.locator('#document-form button[value=post]').click()
                page.wait_for_selector('#modal-root .modal',state='detached')
                page.wait_for_function("() => document.querySelector('tbody tr')?.textContent.includes('محولة لفاتورة')")
                print('PASS: employee contract attachment and inspection progression/conversion')
                page.goto(base+'/#/report_trial_balance')
                page.wait_for_selector('.report-totals')
                assert 'متوازن' in page.locator('.report-totals').inner_text()
                page.screenshot(path=str(screenshots/'04-trial-balance.png'),full_page=True)
                print('PASS: trial balance reconciles after cross-module operations')
                page.goto(base+'/#/report_sales_summary')
                page.wait_for_selector('#report-filter')
                page.locator('[name=group]').select_option('month')
                page.locator('#report-filter button[type=submit]').click()
                page.wait_for_function("() => document.querySelector('#report-content tbody td')?.textContent.trim().length===7")
                with page.expect_download() as result:
                    page.locator('[data-action=export-report]').click()
                download=result.value
                assert download.suggested_filename=='sales_summary.csv'
                assert Path(download.path()).read_bytes().startswith(b'\xef\xbb\xbf')
                print('PASS: monthly sales filtering and CSV export')
                pages=['accounting','inventory','sales','hr','customers','suppliers','employees','attendance','leaves','assets','accounts','journal','payments','loans','users','audit','reports','settings']
                for name in pages:
                    page.goto(base+'/#/'+name)
                    page.wait_for_selector('#main:not(:has(.loading))')
                    assert 'تعذّر تحميل الصفحة' not in page.locator('#main').inner_text(),name
                print(f'PASS: {len(pages)} management screens rendered without page errors')
                page.goto(base+'/#/dashboard')
                page.wait_for_selector('.welcome-banner')
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'), 'Mobile horizontal overflow'
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(screenshots/'05-mobile-dashboard.png'),full_page=True,style='#toasts{display:none!important}')
                page.locator('button[data-action=menu]').click()
                page.wait_for_selector('body.menu-open')
                page.locator('.sidebar a[href="#/inventory"]').click()
                page.wait_for_selector('.module-intro')
                assert not page.locator('body').evaluate("el=>el.classList.contains('menu-open')")
                print('PASS: responsive 390px layout and mobile navigation')
                assert not errors, errors
                browser.close()
                print('PASS: no uncaught JavaScript errors')
        except Exception:
            try:
                print('Browser form errors:',page.locator('.form-error').all_text_contents(),flush=True)
                print('JavaScript errors:',errors,flush=True)
                page.screenshot(path=str(screenshots/'failure.png'),full_page=True)
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


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--screenshots',default='/tmp/erp-screenshots')
    parser.add_argument('--entrypoint',choices=['local','vercel'],default='local')
    args=parser.parse_args()
    run(args.screenshots,args.entrypoint)
