"""Optional real-Chromium acceptance; environment may block localhost browser navigation."""
import sys, tempfile, threading, unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'tb_m1'))
sys.path.insert(0,str(ROOT/'tb_m2'))
sys.path.insert(0,str(ROOT/'tb_app'))
from server import central_handler,device_handler
from store import LocalOutbox,CentralReceiver

class BrowserIntegration(unittest.TestCase):
    def test_intake_to_sync_live_dom(self):
        with tempfile.TemporaryDirectory(prefix='tb-m7-browser-') as tmp:
            root=Path(tmp)
            receiver=CentralReceiver(root/'central.sqlite3')
            center=ThreadingHTTPServer(('127.0.0.1',0),central_handler(receiver))
            center.daemon_threads=True
            central_url=f'http://127.0.0.1:{center.server_port}'
            device=ThreadingHTTPServer(('127.0.0.1',0),device_handler(LocalOutbox(root/'device.sqlite3'),central_url))
            device.daemon_threads=True
            url=f'http://127.0.0.1:{device.server_port}'
            threads=[]
            try:
                for srv in (center,device):
                    th=threading.Thread(target=srv.serve_forever,daemon=True);th.start();threads.append(th)
                try:
                    from playwright.sync_api import sync_playwright, Error as BrowserError
                except ImportError:
                    self.skipTest("optional playwright package not installed")
                with sync_playwright() as tool:
                    browser=tool.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
                    try:
                        page=browser.new_page()
                        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        try:page.goto(url+'/intake',wait_until='domcontentloaded',timeout=12000)
                        except BrowserError as exc:
                            if 'ERR_BLOCKED_BY_ADMINISTRATOR' in str(exc):
                                self.skipTest('managed Chromium blocks all localhost navigation')
                            raise
                        page.locator('#age').fill('35')
                        page.locator('#sex').select_option(label='Female')
                        page.locator('#loc').fill('DEMO-AREA-A')
                        page.locator('#cough').fill('12')
                        page.locator('#m2-consent').check()
                        page.locator('#m2-synthetic').check()
                        page.locator('#genBtn').click()
                        page.wait_for_function("document.getElementById('summaryOut').textContent.includes('Central receiver ACK confirmed.')",timeout=10000)
                        page.goto(url+'/sync')
                        page.wait_for_function("document.querySelectorAll('#centralQueue .case-card').length===1",timeout=10000)
                        page.locator('#centralQueue .case-card').click()
                        page.wait_for_selector('#caseActionForm select[name="action"]')
                        self.assertIn('NOT established',page.locator('#caseWorkbench').inner_text())
                        self.assertFalse(errors,errors)
                    finally:browser.close()
            finally:
                for srv in (device,center):srv.shutdown();srv.server_close()
                for th in threads:th.join(timeout=3)
if __name__=='__main__':unittest.main(verbosity=2)
