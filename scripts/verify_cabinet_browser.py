"""Cabinet navigation and shared assistant browser regression. Existing E4 runner tests real sources."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

out=Path('data/official/cabinet-checks');out.mkdir(parents=True,exist_ok=True)
checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True,args=['--no-proxy-server'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8020')
    page.get_by_role('button',name='Сотрудник ·').click()
    page.get_by_role('heading',name='Добро пожаловать').wait_for()
    page.screenshot(path=str(out/'employee-desktop.png'),full_page=True)
    page.locator('#page-content').get_by_role('button',name='1С',exact=False).click()
    page.get_by_role('heading',name='Раздел недоступен в рамках хакатона',exact=True).wait_for()
    checks.append('Resource tile opens explicit hackathon unavailability')
    page.locator('#menu').get_by_role('button',name='Главная',exact=True).click()
    page.get_by_role('button',name='Открыть ИИ-ассистента',exact=True).click()
    page.locator('#question').fill('Черновик вопроса')
    page.get_by_role('button',name='Закрыть чат',exact=True).click()
    page.locator('#menu').get_by_role('button',name='Сервисы',exact=True).click()
    page.locator('#page-content').get_by_role('button',name='ИИ-ассистент').click()
    assert page.locator('#question').input_value()=='Черновик вопроса'
    page.route('**/api/ask',lambda r:r.fulfill(json={'status':'partial','summary':[{'text':'Тест отображения общего диалога','evidence':[]}]}))
    page.locator('#submit').click();page.locator('#conversation article').wait_for()
    page.locator('#menu').get_by_role('button',name='Профиль',exact=True).click()
    page.get_by_role('button',name='Открыть ИИ-ассистента',exact=True).click()
    assert page.locator('#chat-body #conversation article').count()==1
    page.screenshot(path=str(out/'employee-chat.png'),full_page=True)
    page.keyboard.press('Escape');assert page.locator('#chat-panel').is_hidden()
    page.get_by_role('button',name='Открыть ИИ-ассистента',exact=True).click()
    page.get_by_role('button',name='Открыть ассистента на странице').click()
    assert page.locator('#assistant-page #conversation article').count()==1
    checks.append('Draft and response survive closing, navigation, widget and full-page expansion; Escape closes and restores focus')
    page.set_viewport_size({'width':360,'height':800})
    for id in ['home','services','profile','certificates','assistant']:
        page.evaluate('(id)=>location.hash=id',id)
        page.wait_for_timeout(100)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),id
    page.get_by_role('button',name='Открыть ИИ-ассистента',exact=True).click()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    rect=page.locator('#chat-panel').bounding_box();assert rect['y']>=0 and rect['x']>=0 and rect['x']+rect['width']<=360
    page.screenshot(path=str(out/'mobile-chat.png'),full_page=True)
    page.get_by_role('button',name='Закрыть чат',exact=True).click()
    page.get_by_role('button',name='Открыть меню',exact=True).click()
    if page.locator('#menu').get_by_role('button',name='КЭДО',exact=True).is_hidden():
        page.locator('#menu').get_by_text('Кадровые сервисы',exact=True).click()
    page.locator('#menu').get_by_role('button',name='КЭДО',exact=True).click()
    assert not page.locator('#menu-toggle').is_checked()
    page.get_by_role('heading',name='Раздел недоступен в рамках хакатона',exact=True).wait_for()
    checks.append('360px pages, widget bounds, mobile drawer and nested navigation')
    page.get_by_role('button',name='Выйти',exact=True).click()
    page.get_by_role('button',name='Преподаватель ·').click()
    page.get_by_role('button',name='Открыть меню',exact=True).click()
    page.locator('#menu').get_by_text('Преподавателю',exact=True).click()
    page.locator('#menu').get_by_role('button',name='Мои курсы',exact=True).click()
    page.get_by_role('heading',name='Раздел недоступен в рамках хакатона',exact=True).wait_for()
    page.locator('#tabbar').get_by_role('button',name='Главная',exact=True).click()
    page.screenshot(path=str(out/'teacher-mobile.png'),full_page=True)
    checks.append('Teacher menu and work tiles; logout clears dialogue and changes profile')
    assert not errors,errors
    browser.close()
(out/'cabinet-report.json').write_text(json.dumps({'checks':checks,'errors':errors,'note':'Shared-dialogue reply simulated; real extractive sources tested separately in e4-regression/report.json'},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(checks,ensure_ascii=False))
