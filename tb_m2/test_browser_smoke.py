"""Optional real Chromium smoke test of original form + injected M2 bridge.

pip install playwright  # Chromium executable installed separately
"""
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright, Error as BrowserError
from device_server import make_handler as make_device_handler
from server import make_handler as make_central_handler
from store import CentralReceiver,LocalOutbox


class RealBrowserSmoke(unittest.TestCase):
    def test_browser_fills_original_form_persists_and_syncs(self):
        with tempfile.TemporaryDirectory(prefix='tb-m2-browser-') as root:
            local = LocalOutbox(Path(root)/'local.sqlite3')
            receiver = CentralReceiver(Path(root)/'central.sqlite3')
            central = ThreadingHTTPServer(('127.0.0.1',0),make_central_handler(receiver))
            central.daemon_threads = True
            central_thread=threading.Thread(target=central.serve_forever,daemon=True)
            central_thread.start()
            remote = f'http://127.0.0.1:{central.server_port}'
            device = ThreadingHTTPServer(('127.0.0.1',0),make_device_handler(local,remote))
            device.daemon_threads=True
            device_thread=threading.Thread(target=device.serve_forever,daemon=True)
            device_thread.start()
            try:
                with sync_playwright() as play:
                    browser=play.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
                                                 args=['--no-sandbox'])
                    page=browser.new_page()
                    errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    try:
                        page.goto(f'http://127.0.0.1:{device.server_port}/intake')
                    except BrowserError as exc:
                        if 'ERR_BLOCKED_BY_ADMINISTRATOR' in str(exc):
                            browser.close()
                            self.skipTest('Managed Chromium blocks all navigation in this execution environment')
                        raise
                    page.locator('#age').fill('35')
                    page.locator('#sex').select_option(label='Female')
                    page.locator('#loc').fill('DEMO-AREA-A')
                    page.locator('#cough').fill('12')
                    page.locator('#fever').check()
                    page.locator('#m2-consent').check()
                    page.locator('#m2-synthetic').check()
                    page.locator('#genBtn').click()
                    page.wait_for_function("document.getElementById('summaryOut').textContent.includes('Central receiver ACK confirmed.')",timeout=5000)
                    self.assertFalse(errors,errors)
                    case=page.locator('#record').evaluate('(node)=>JSON.parse(node.textContent)')
                    self.assertEqual(case['symptom_screen']['cough_duration_days'],12)
                    self.assertIsNone(case['symptom_screen']['night_sweats'])
                    self.assertFalse(case['xray']['available'])
                    self.assertIsNone(case['diagnosis'])
                    self.assertEqual(receiver.latest(case['case_id']),case)
                    self.assertEqual(len(local.status()),1)
                    self.assertEqual(local.status()[0]['sync_status'],'acked')
                    browser.close()
            finally:
                for srv,thread in ((device,device_thread),(central,central_thread)):
                    srv.shutdown();srv.server_close();thread.join(timeout=4)

if __name__=='__main__':
    unittest.main(verbosity=2)
