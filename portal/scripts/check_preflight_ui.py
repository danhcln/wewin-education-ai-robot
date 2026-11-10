"""Chrome fallback with NEW ephemeral contexts; no existing browser sessions.

8001 is read-only except normal login/logout session audit. All candidate/link/
apply mutations target disposable QA 8002 -> AI 8011, never a physical robot.
Requires optional test dependency playwright==1.58.0 and installed Chrome.
"""
import json
import argparse
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

OUT=ROOT/'artifacts/connection-preflight/ui'


def main():
    OUT.mkdir(parents=True,exist_ok=True);results=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        try:
            mainctx=browser.new_context(viewport={'width':1440,'height':1000})
            key_file=ROOT.parent/'Wewin Connector/Wewin_AI_Connector/.secrets/admin_sync_token'
            login=mainctx.request.post('http://127.0.0.1:8001/api/portal/login',headers={'Origin':'http://127.0.0.1:8001','Authorization':'Bearer '+key_file.read_text().strip()})
            assert login.ok
            page=mainctx.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            for path,title in [('/robots','Robot & AI Configuration'),('/roles','WeWIN AI Role Library'),('/mcp','MCP')]:
                page.goto('http://127.0.0.1:8001'+path);page.get_by_role('heading',name=title,exact=False).first.wait_for()
                if path=='/robots':
                    expect(page.get_by_role('tab')).to_have_count(7)
                    for tab in ('AI Configuration','Cloud / MCP','Diagnostics'):
                        page.get_by_role('tab',name=tab,exact=True).click()
                        page.screenshot(path=str(OUT/('main-'+tab.split()[0].replace('/','')+'.png')),full_page=True)
                    page.get_by_role('tab',name='Cloud / MCP',exact=True).click()
                    expect(page.get_by_role('button',name='Chọn WeWIN AI staging',exact=True)).to_be_visible()
                if path=='/roles':expect(page.locator('article.role-card')).to_have_count(8)
                results.append({'origin':'8001','path':path,'result':'PASS','mutation':'none'})
            response=mainctx.request.post('http://127.0.0.1:8001/api/portal/logout',headers={'Origin':'http://127.0.0.1:8001','X-WeWIN-CSRF':login.json()['csrf']});assert response.ok
            mainctx.close()

            ctx=browser.new_context(viewport={'width':1440,'height':1000});page=ctx.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto('http://127.0.0.1:8002/robots')
            page.get_by_label('Tên đăng nhập',exact=True).fill('qa-admin');page.get_by_label('Mật khẩu',exact=True).fill('WeWIN-QA-only-2026!');page.get_by_role('button',name='Đăng nhập',exact=True).click()
            expect(page.get_by_role('tab',name='Cloud / MCP',exact=True)).to_be_visible()
            # Reset the disposable fixture through its authenticated API before
            # exercising the visible link confirmation. Never targets 8001.
            csrf=ctx.request.get('http://127.0.0.1:8002/api/portal/session').json()['csrf']
            rid=ctx.request.get('http://127.0.0.1:8002/api/portal/robots').json()['items'][0]['id']
            link=ctx.request.get(f'http://127.0.0.1:8002/api/portal/robots/{rid}/self-hosted').json()['link']
            if link and link['enabled']:
                reset=ctx.request.post(f'http://127.0.0.1:8002/api/portal/robots/{rid}/self-hosted/disconnect',headers={'Origin':'http://127.0.0.1:8002','X-WeWIN-CSRF':csrf},data={'confirmed':True});assert reset.ok
                page.reload()
            page.get_by_role('tab',name='Cloud / MCP',exact=True).click()
            page.get_by_role('button',name='Chọn WeWIN AI staging',exact=True).click()
            dialog=page.get_by_role('dialog');expect(dialog).to_contain_text('không tới XiaoZhi Cloud')
            dialog.get_by_role('button',name='Xác nhận liên kết Portal',exact=True).click();expect(dialog).to_have_count(0)
            results.append({'origin':'8002','check':'staging confirmation','result':'PASS'})

            page.get_by_role('link',name='Vai trò trợ lý AI',exact=True).click()
            page.locator('article.role-card').filter(has=page.get_by_role('heading',name='WeWIN English Teacher',exact=True)).get_by_role('button',name='Xem vai trò',exact=True).click()
            selector=page.get_by_label('Robot nhận vai trò');selector.select_option(index=1)
            page.get_by_role('button',name='Áp dụng cho Robot — xem candidate',exact=True).click()
            dialog=page.get_by_role('dialog');expect(dialog).to_contain_text('Agent staging:');expect(dialog).to_contain_text('revision ')
            # Missing candidate never writes an Agent; preview is reviewable.
            assert ctx.request.get('http://127.0.0.1:8011/health').json()['physical_connections']==0
            page.screenshot(path=str(OUT/'qa-apply-confirmation.png'),full_page=True)
            with page.expect_response(lambda r:'/config/apply' in r.url and r.request.method=='POST',timeout=180000) as applied:
                dialog.get_by_role('button',name='Áp dụng WeWIN AI Server',exact=True).click()
            assert applied.value.ok,applied.value.status
            body=applied.value.json();assert body['sync_state']=='server_applied_verified' and not body['robot_applied']
            expect(dialog).to_have_count(0)
            results.append({'origin':'8002','check':'English Teacher confirmed apply','result':'PASS','response':body})
            page.get_by_role('link',name='Thiết bị / Robot',exact=True).click()
            expect(page.get_by_text('WeWIN AI Server đã nạp — robot thật chưa xác minh',exact=True)).to_be_visible(timeout=15000)
            page.get_by_role('tab',name='Cloud / MCP',exact=True).click()
            expect(page.get_by_text('Đã chọn WeWIN AI staging',exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_text('Sẵn sàng nhận candidate có xác nhận',exact=True)).to_be_visible(timeout=15000)
            page.screenshot(path=str(OUT/'qa-server-verified.png'),full_page=True)
            # Transport failure in this context only: backend and production remain running.
            page.route('**/api/portal/robots/*/config/sync-status',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'detail':'QA simulated unavailable readback'})))
            page.reload();page.get_by_role('tab',name='AI Configuration',exact=True).click()
            expect(page.get_by_text('QA simulated unavailable readback',exact=False).first).to_be_visible()
            expect(page.get_by_text('Lần áp dụng server trước cần đối soát trạng thái hiện tại',exact=True)).to_be_visible()
            page.screenshot(path=str(OUT/'qa-readback-error.png'),full_page=True)
            results.append({'origin':'8002','check':'readback error, historical evidence not promoted','result':'PASS','failure_source':'browser route fixture only'})
            assert not errors,errors
            ctx.close()
        finally:browser.close()
    (OUT/'results.json').write_text(json.dumps({'fallback':'Playwright 1.58.0 / installed Chrome / new ephemeral contexts','checks':results,'page_errors':errors,'physical_acceptance':False},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(results),'page_errors':len(errors),'physical_acceptance':False}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=OUT);args=parser.parse_args()
    OUT=args.out.resolve()
    if not OUT.is_relative_to(ROOT/'artifacts'):raise ValueError('QA screenshots/results must stay inside artifacts/')
    main()
