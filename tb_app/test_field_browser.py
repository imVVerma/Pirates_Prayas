"""Optional actual-browser M7.3 smoke; skips only if managed Chromium blocks localhost."""
import tempfile,threading,unittest,sys
from pathlib import Path
from http.server import ThreadingHTTPServer
ROOT=Path(__file__).resolve().parent.parent
for path in ('tb_m1','tb_m2','tb_app'):sys.path.insert(0,str(ROOT/path))
from server import device_handler,central_handler
from store import LocalOutbox,CentralReceiver

class FieldBrowser(unittest.TestCase):
    def test_wizard_dom_with_stubbed_http(self):
        """Actual Chromium DOM interaction; HTTP is stubbed, not a substitute for local integration."""
        from playwright.sync_api import sync_playwright
        import json
        html=(ROOT/'tb_app'/'field_intake.html').read_text(encoding='utf-8')
        with sync_playwright() as play:
            browser=play.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
            try:
                page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.set_content(html,timeout=9000)
                page.evaluate("""() => {
                  Object.defineProperty(window.crypto,'randomUUID',{value:()=>
                    'd82ebd1e-5d56-4612-a9e7-9d8ca2b46001',configurable:true});
                  window.fetch=async (url,options) => {
                    if(url==='/v1/intake'){
                      window.__payload=JSON.parse(options.body);
                      return new Response(JSON.stringify({result:'queued',case:{case_id:window.__payload.case_id,revision:2}}),
                          {status:201,headers:{'Content-Type':'application/json'}});
                    }
                    if(url==='/v1/sync')return new Response(JSON.stringify({outbox:[{
                      case_id:window.__payload.case_id,revision:2,sync_status:'pending'}]}),
                        {status:200,headers:{'Content-Type':'application/json'}});
                    throw new Error('unexpected URL '+url);
                  };
                }""")
                page.add_script_tag(path=str(ROOT/'tb_app'/'field_intake.js'))
                page.locator('input[name=language][value=hi]').check()
                self.assertIn('उम्र',page.locator('#step-age').inner_text())
                page.locator('#next').click();page.locator('#age').fill('31')
                page.locator('#next').click();page.locator('#next').click();page.locator('#next').click()
                page.locator('#coughChoices input[value=yes]').check();page.locator('#next').click()
                page.locator('#duration').fill('21');page.locator('#next').click()
                page.locator('#feverChoices input[value=no]').check();page.locator('#next').click()
                page.locator('#sweatsChoices input[value=unknown]').check();page.locator('#next').click()
                page.locator('#weightlossChoices input[value=yes]').check();page.locator('#next').click()
                page.locator('#narrative').fill('नमूना: तीन सप्ताह से खाँसी है')
                page.locator('#next').click()
                page.locator('#xrayReport').select_option('yes')
                page.locator('#next').click()
                page.locator('#consent').check();page.locator('#synthetic').check()
                page.locator('#next').click()
                self.assertIn('नमूना:',page.locator('#preview').inner_text())
                page.locator('#reviewed').check();page.locator('#next').click()
                page.wait_for_selector('#step-done:not([hidden])',timeout=5000)
                payload=page.evaluate('window.__payload')
                self.assertEqual(payload['raw_text'],'नमूना: तीन सप्ताह से खाँसी है')
                self.assertEqual(payload['fever'],False)
                self.assertIsNone(payload['night_sweats'])
                self.assertEqual(payload['xray_report_claim'],'yes')
                self.assertFalse(payload['xray_available'])
                self.assertFalse(errors,errors)
            finally:browser.close()
    def test_worker_wizard_to_local_outbox(self):
        try:from playwright.sync_api import sync_playwright,Error as BrowserError
        except ImportError:self.skipTest('optional playwright missing')
        with tempfile.TemporaryDirectory() as tmp:
            local=LocalOutbox(Path(tmp)/'local.sqlite3');central=CentralReceiver(Path(tmp)/'central.sqlite3')
            remote=ThreadingHTTPServer(('127.0.0.1',0),central_handler(central))
            device=ThreadingHTTPServer(('127.0.0.1',0),device_handler(local,f'http://127.0.0.1:{remote.server_port}'))
            threads=[]
            try:
                for srv in (remote,device):
                    th=threading.Thread(target=srv.serve_forever,daemon=True);th.start();threads.append(th)
                with sync_playwright() as play:
                    browser=play.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
                    try:
                        page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        try:page.goto(f'http://127.0.0.1:{device.server_port}/field',wait_until='domcontentloaded',timeout=12000)
                        except BrowserError as exc:
                            if 'ERR_BLOCKED_BY_ADMINISTRATOR' in str(exc):self.skipTest('managed browser blocks localhost')
                            raise
                        page.locator('#next').click();page.locator('#age').fill('35')
                        page.locator('#next').click();page.locator('#next').click();page.locator('#next').click()
                        page.locator('#coughChoices input[value=yes]').check();page.locator('#next').click()
                        page.locator('#duration').fill('21');page.locator('#next').click()
                        page.locator('#feverChoices input[value=unknown]').check();page.locator('#next').click()
                        page.locator('#sweatsChoices input[value=no]').check();page.locator('#next').click()
                        page.locator('#weightlossChoices input[value=yes]').check();page.locator('#next').click()
                        page.locator('#narrative').fill('काल्पनिक उदाहरण: खाँसी 21 दिन')
                        page.locator('#next').click();page.locator('#next').click()
                        page.locator('#consent').check();page.locator('#synthetic').check()
                        page.locator('#next').click()
                        self.assertIn('काल्पनिक उदाहरण',page.locator('#preview').inner_text())
                        page.locator('#reviewed').check();page.locator('#next').click()
                        page.wait_for_selector('#step-done:not([hidden])',timeout=7000)
                        self.assertEqual(len(local.status()),1)
                        self.assertEqual(local.status()[0]['sync_status'],'acked')
                        page.goto(f'http://127.0.0.1:{device.server_port}/field/cases')
                        page.wait_for_selector('.card',timeout=6000)
                        self.assertFalse(errors,errors)
                    finally:browser.close()
            finally:
                for s in (device,remote):s.shutdown();s.server_close()
                for t in threads:t.join(timeout=3)
if __name__=='__main__':unittest.main(verbosity=2)
