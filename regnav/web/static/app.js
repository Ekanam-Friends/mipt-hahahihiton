'use strict';
const form = document.querySelector('#ask');
const question = document.querySelector('#question');
const progress = document.querySelector('#progress');
const conversation = document.querySelector('#conversation');
let history = [];
let pending = false;
let profile = null;
const savedJobKey = 'regnav-pending-question';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function today() {const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
document.querySelector('#as-of').value=today();
async function shortRequest(url, options={}) {
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000);
  try {return await fetch(url,{...options,signal:controller.signal});}
  finally {clearTimeout(timer);}
}
function saveJob(job) {try {sessionStorage.setItem(savedJobKey,JSON.stringify(job));} catch {}}
function clearJob() {try {sessionStorage.removeItem(savedJobKey);} catch {}}
const labels = {answer:'Ответ подтверждён',partial:'Частичный ответ',clarify:'Нужно уточнение',not_found:'Ответ не найден в снимке',error:'Техническая ошибка'};
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function link(parent, text, url) {
  // Only same-origin document endpoints supplied by the adapter are clickable.
  if (typeof url !== 'string' || !url.startsWith('/api/documents/')) return;
  const a = el('a', text); a.href = url; a.target = '_blank'; a.rel = 'noopener'; parent.append(a);
}
function evidence(parent, items) {
  for (const item of items || []) {
    const d = el('details'); d.append(el('summary', item.ref || item.title || 'Доказательство'));
    d.append(el('p',item.title), el('blockquote',item.quote));
    link(d,'Точный фрагмент',item.view_url); link(d,'Скачать оригинал',item.download_url); parent.append(d);
  }
}
function render(q, data) {
  const card = el('article'); card.append(el('p',q,'question'),el('span',labels[data.status] || 'Неизвестный статус','badge'));
  if (data.message) card.append(el('p',data.message,'text'));
  if (data.as_of) card.append(el('p','Применимость на дату: '+data.as_of,'meta'));
  if (data.cache_hit) card.append(el('p','Повторный ответ из кэша текущего снимка документов (до 1 часа).','meta'));
  if (data.corpus_snapshot?.length) {
    const dates=[...new Set(data.corpus_snapshot.map(value=>value.slice(0,10)))];
    card.append(el('p','Дата загрузки снимка: '+dates.join(', '),'meta'));
  }
  if (data.summary?.length) {
    card.append(el('h2','Краткий ответ'));
    for (const claim of data.summary) {card.append(el('p',claim.text,'text')); evidence(card,claim.evidence);}
  }
  if (data.steps?.length) {
    card.append(el('h2','Порядок действий')); const list = el('ol');
    for (const step of data.steps) {
      const li = el('li'); li.append(el('p',step.action,'text'));
      if(step.responsible) li.append(el('p','Ответственный: '+step.responsible,'meta'));
      if(step.deadline) li.append(el('p','Срок: '+step.deadline,'meta'));
      if(step.documents?.length) li.append(el('p','Документы: '+step.documents.join(', '),'meta'));
      evidence(li,step.evidence); list.append(li);
    } card.append(list);
  }
  if(data.clarifying_question) card.append(el('p',data.clarifying_question,'warning'));
  for(const claim of data.conflicts || []) {card.append(el('h3','Расхождение'),el('p',claim.text,'warning')); evidence(card,claim.evidence);}
  for(const gap of data.missing_information || []) card.append(el('p','Не подтверждено: '+gap,'warning'));
  for(const warning of data.warnings || []) card.append(el('p',warning,'warning'));
  if(data.sources?.length) {
    card.append(el('h2','Источники'));
    for(const source of data.sources) {const p=el('p',source.title+' '); link(p,'Просмотр',source.view_url); link(p,'Оригинал',source.download_url); card.append(p);}
  }
  conversation.prepend(card);
}
async function runQuestion(job) {
  if(pending) return;
  const q=job.question;pending=true;saveJob(job);
  document.querySelector('#submit').disabled=true; document.querySelector('#reset').disabled=true;
  progress.textContent='Отправляем вопрос. На CPU обработка может занять несколько минут.';
  try {
    let data;
    while(!data) {
      try {
        if(!job.job_id) {
          const {job_id,...payload}=job;
          const response=await shortRequest('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
          const body=await response.json();
          if(!response.ok) {data=body;break;}
          job.job_id=body.job_id;saveJob(job);
        }
        const response=await shortRequest('/api/jobs/'+encodeURIComponent(job.job_id));
        const body=await response.json();
        if(!response.ok) {data=body;break;}
        if(body.state==='done') {data=body.result;break;}
        progress.textContent=(body.state==='queued'?'Вопрос в очереди.':'Ищем источники и проверяем ответ.')+' Прошло '+body.elapsed_seconds+' с. Можно вернуться к этой вкладке позже.';
      } catch {
        progress.textContent='Связь прервалась. Восстанавливаем получение результата; вопрос повторно не запускается.';
      }
      await pause(2500);
    }
    clearJob();render(q,data);
    if(data.status !== 'error') {
      history=job.history.slice();
      history.push(q); if(data.clarifying_question) history.push(data.clarifying_question);
      history=history.slice(-6); question.value='';
    }
    progress.textContent=data.status==='error'?'Повторите запрос кнопкой «Найти ответ».':'Можно задать уточнение или начать новый диалог.';
  } catch {
    progress.textContent='Вопрос сохранён. Обновите страницу для восстановления результата.';
  } finally {pending=false;document.querySelector('#submit').disabled=false;document.querySelector('#reset').disabled=false;}
}
form.addEventListener('submit', event => {
  event.preventDefault();if(pending || !question.value.trim()) return;
  runQuestion({request_id:crypto.randomUUID(),question:question.value.trim(),history:history.slice(),as_of:document.querySelector('#as-of').value || today()});
});
document.querySelector('#reset').addEventListener('click',()=>{history=[];conversation.replaceChildren();question.value='';document.querySelector('#as-of').value=today();progress.textContent='Начат новый диалог.';question.focus();});

// Keep the MGIMO-LMS employee shell; services outside the hackathon remain visible.
const titles = {home:'Главная', services:'Сервисы', profile:'Профиль', assistant:'ИИ-ассистент',
  announcements:'Объявления', courses:'Мои курсы', homework:'Домашние задания', schedule:'Расписание',
  workload:'Учебная нагрузка', pps:'Конкурс ППС', certificates:'Заказ справок', kedo:'КЭДО',
  hr:'Отпуск, больничный, командировки', onec:'1С', pyrus:'Pyrus', directum:'Directum',
  directory:'Адресная книга', regulations:'База локальных актов', events:'Афиша',
  newemployee:'Справочник нового работника', structure:'Структура вуза', campus:'Навигация по кампусу'};
const iconPaths = {
 home:'M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z',
 grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
 user:'M4 21c0-8 16-8 16 0 M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
 office:'M4 21V4h16v17 M8 8h2m4 0h2M8 12h2m4 0h2M10 21v-5h4v5',
 cap:'m2 9 10-5 10 5-10 5z M6 11v6q6 5 12 0v-6',
 chat:'M4 4h16v12H9l-5 4z', calendar:'M4 5h16v16H4z M4 10h16M8 3v4m8-4v4'};
function icon(name) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  for(const [k,v] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',class:'nav-icon'})) svg.setAttribute(k,v);
  const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',iconPaths[name] || iconPaths.grid);svg.append(path);return svg;
}
const resources=[['onec','учёт и финансы','navy'],['pyrus','заявки и согласования','orange'],['directum','документооборот','violet'],['directory','контакты сотрудников','blue'],['regulations','нормативные документы','teal'],['events','события университета','orange'],['certificates','кадровый сервис','navy'],['kedo','кадровый документооборот','green'],['newemployee','памятка сотруднику','pink'],['structure','факультеты и кафедры','teal'],['campus','корпуса и аудитории','violet']];
const work=[['courses','курсы и ведомости','red'],['homework','задания и сроки','orange'],['schedule','занятия на неделю','blue'],['workload','часы по дисциплинам','violet'],['pps','заявки и сроки','navy']];
const demoSchedule=[
      ['Понедельник',[
        ['09:00–10:25','Математический анализ','Лекция','Группа Д-101 · аудитория 301','lecture'],
        ['10:45–12:10','Математический анализ','Семинар','Группа Д-102 · аудитория 214','seminar']]],
      ['Вторник',[
        ['12:20–13:45','Линейная алгебра','Семинар','Группа Д-103 · аудитория 215','seminar']]],
      ['Среда',[
        ['09:00–10:25','Математический анализ','Лекция','Группа Д-101 · аудитория 301','lecture'],
        ['14:00–15:25','Консультация','Консультация','Группы Д-101, Д-102 · аудитория 214','consultation']]],
      ['Четверг',[
        ['10:45–12:10','Линейная алгебра','Семинар','Группа Д-103 · аудитория 215','seminar']]],
      ['Пятница',[
        ['12:20–13:45','Математический анализ','Семинар','Группа Д-102 · аудитория 214','seminar']]],
      ['Суббота',[]]
    ];

function lessonCard(lesson) {
  const [time,title,type,place,tone]=lesson;
  const card=el('div',null,'schedule-lesson schedule-lesson--'+tone);
  card.append(el('p',time,'schedule-time'),el('span',type,'schedule-type'),el('h4',title),el('p',place,'muted'));
  return card;
}
function homeSchedule() {
  const panel=el('div',null,'panel home-schedule');
  panel.append(el('span','Демонстрационное расписание','badge'),el('p','Понедельник · пример учебного дня. Все занятия вымышлены.','muted'));
  for(const lesson of demoSchedule[0][1]) panel.append(lessonCard(lesson));
  const block=section('Расписание',panel);
  const more=el('button','Вся неделя →','dash-link');more.onclick=()=>go('schedule');
  block.querySelector('.dash-block__header').append(more);
  return block;
}
let currentPage='home';
let widgetOpen=false;
const assistant=document.querySelector('#assistant');
const chatPanel=document.querySelector('#chat-panel');
const chatToggle=document.querySelector('#chat-toggle');
function initials(name) {return name.split(' ').slice(0,2).map(p=>p[0]).join('');}
function go(id) {if(location.hash==='#'+id) page(id);else location.hash=id;}
function navButton(id, cls='menu__link', symbol='grid') {
  const button=el('button',null,cls);button.dataset.page=id;button.append(icon(symbol),el('span',titles[id]));button.onclick=()=>go(id);return button;
}
function group(title, ids, symbol) {
  const details=el('details',null,'menu__group');const summary=el('summary',null,'menu__link');summary.append(icon(symbol),el('span',title));details.append(summary);
  const sub=el('div',null,'menu__sub');for(const id of ids) {const b=el('button',titles[id],'menu__sublink');b.dataset.page=id;b.onclick=()=>go(id);sub.append(b);}details.append(sub);return details;
}
function profileCard() {
  const grid=el('div',null,'profile-grid');
  for(const [title,value] of [['ФИО',profile.name],['Должность',profile.position],['Подразделение',profile.unit],['Табельный номер',profile.tab_no],['Почта',profile.email],['Занятость','Основное место работы']]) {
    const p=el('div');p.append(el('small',title),el('strong',value));grid.append(p);
  }return grid;
}
function section(title, child, more=false) {
  const s=el('section',null,'dash-block'),head=el('div',null,'dash-block__header');head.append(el('h2',title,'dash-title'));
  if(more){const b=el('button','Все сервисы →','dash-link');b.onclick=()=>go('services');head.append(b);}s.append(head,child);return s;
}
function tiles(items) {
  const grid=el('div',null,'res-grid');
  for(const [id,sub,color] of items){const b=el('button',null,'res-tile tile-'+color);b.append(el('span',titles[id],'res-tile__title'),el('span',sub,'res-tile__sub'));b.onclick=()=>go(id);grid.append(b);}return grid;
}
function placeAssistant() {
  chatPanel.hidden=!widgetOpen;
  chatToggle.setAttribute('aria-expanded',String(widgetOpen));
  chatToggle.setAttribute('aria-label',widgetOpen?'Закрыть ИИ-ассистента':'Открыть ИИ-ассистента');
  if(widgetOpen) {document.querySelector('#chat-body').append(assistant);assistant.hidden=false;}
  else {document.querySelector('#assistant-page').append(assistant);assistant.hidden=currentPage!=='assistant';}
  // Do not leave a blank full page when the shared dialogue is in the widget.
  const placeholder=document.querySelector('#assistant-placeholder');
  if(placeholder) placeholder.hidden=!widgetOpen;
}
function setWidget(open, focus=true) {
  widgetOpen=open;placeAssistant();
  if(focus){if(open) question.focus();else chatToggle.focus();}
}
function page(id) {
  if(!profile) return;
  if(!Object.hasOwn(titles,id) || (profile.role!=='teacher' && work.some(item=>item[0]===id))) id='home';
  currentPage=id;
  document.querySelector('#menu-toggle').checked=false;
  document.querySelector('#dashboard').hidden=id==='assistant';document.querySelector('#assistant-page').hidden=id!=='assistant';
  document.querySelector('#header-title').textContent=id==='home'?(profile.role==='teacher'?'Кабинет преподавателя':'Кабинет сотрудника'):titles[id];
  document.title=titles[id]+' · Личный кабинет МФТИ';
  for(const b of document.querySelectorAll('[data-page]')) {
    const active=b.dataset.page===id;b.classList.toggle('menu__link--active',active);b.classList.toggle('tabbar__link--active',active);b.classList.toggle('active',active);
    if(active){b.setAttribute('aria-current','page');const group=b.closest('details');if(group) group.open=true;}else b.removeAttribute('aria-current');
  }
  if(id==='assistant'){widgetOpen=false;placeAssistant();return;}
  document.querySelector('#page-title').textContent=id==='home'?'Добро пожаловать, '+profile.name.split(' ')[0]:titles[id];
  const content=document.querySelector('#page-content');content.replaceChildren();
  if(id==='home') {
    const row=el('div',null,'teacher-home');
    if(profile.role==='teacher') row.append(homeSchedule());
    const homePanels=profile.role==='teacher'?[['Мои сервисы','Помощь по регламентам и рабочим вопросам']]:[['Информационная лента','Раздел недоступен в рамках хакатона.'],['Мои сервисы','Помощь по регламентам и рабочим вопросам']];
    for(const [title,text] of homePanels) {
      const panel=el('div',null,'panel');panel.append(el('p',text,'muted'));
      if(title==='Мои сервисы'){const b=el('button','ИИ-ассистент →','dash-link');b.onclick=()=>go('assistant');panel.append(b);}
      row.append(section(title,panel));
    }content.append(row);
    if(profile.role==='teacher') content.append(section('Преподавателю',tiles(work)));
    content.append(section('Ресурсы университета',tiles(resources),true));
    content.append(section('Кадровая служба',tiles([['certificates','заказ справок','navy'],['kedo','электронные документы','green'],['hr','отпуск и командировки','violet']])));
  } else if(id==='services') {
    content.append(section('Мои сервисы',tiles([['assistant','ответы с источниками по регламентам МФТИ','red']])));
    content.append(section('Ресурсы университета',tiles(resources)));
    content.append(el('p','Кроме ИИ-ассистента, разделы недоступны в рамках хакатона.','muted'));
  } else if(id==='schedule') {
    const notice=el('div',null,'panel schedule-notice');
    notice.append(el('span','Демонстрационное расписание','badge'),el('p','Это заглушка: занятия, группы и аудитории вымышлены. Подключение реального расписания недоступно в рамках хакатона.','muted'));
    content.append(notice);
    const grid=el('div',null,'schedule-week');
    for(const [day,lessons] of demoSchedule) {
      const column=el('section',null,'schedule-day');column.append(el('h3',day));
      for(const lesson of lessons) column.append(lessonCard(lesson));
      if(!lessons.length) column.append(el('p','Занятий нет','schedule-empty muted'));
      grid.append(column);
    }
    content.append(section('Пример учебной недели',grid));
  } else if(id==='profile') {
    const head=el('div',null,'profile-head');head.append(el('span',initials(profile.name),'avatar avatar--big'));const text=el('div');text.append(el('h2',profile.name,'profile__name'),el('p',profile.position,'muted'));head.append(text);content.append(head);
    const panel=el('section',null,'panel');panel.append(profileCard());content.append(section('Информация о сотруднике',panel));
  } else {
    const panel=el('section',null,'panel unavailable');panel.append(icon('office'),el('span','Вне программы хакатона','badge'),el('h2','Раздел недоступен в рамках хакатона'),el('p','Вы можете воспользоваться ИИ-ассистентом в разделе «Сервисы» или открыть чат в правом нижнем углу.','muted'));
    const b=el('button','Перейти к сервисам','btn btn--primary');b.onclick=()=>go('services');panel.append(b);content.append(panel);
  }
  placeAssistant();
}
async function enter() {
  const response=await fetch('/api/me');if(!response.ok) return false;profile=await response.json();
  document.querySelector('#login').hidden=true;document.querySelector('#cabinet').hidden=false;
  document.querySelector('#user-name').textContent=profile.name;document.querySelector('#avatar').textContent=initials(profile.name);
  document.querySelector('#user-unit').textContent=profile.unit;document.querySelector('#role-label').textContent=profile.role==='teacher'?'кабинет преподавателя':'кабинет сотрудника';
  const menu=document.querySelector('#menu');menu.replaceChildren(navButton('home','menu__link','home'));
  if(profile.role==='teacher') menu.append(group('Преподавателю',['courses','homework','schedule','announcements','workload','pps'],'cap'));
  else menu.append(navButton('announcements','menu__link','chat'));
  menu.append(navButton('services'),group('Кадровые сервисы',['certificates','kedo','hr'],'office'),navButton('profile','menu__link','user'));
  const tab=document.querySelector('#tabbar');tab.replaceChildren();
  for(const [id,symbol] of [['home','home'],['services','grid'],[profile.role==='teacher'?'schedule':'announcements',profile.role==='teacher'?'calendar':'chat'],['profile','user']])tab.append(navButton(id,'tabbar__link',symbol));
  const host=document.querySelector('#assistant-page');if(!document.querySelector('#assistant-placeholder')){const note=el('div',null,'panel');note.id='assistant-placeholder';note.append(el('p','Диалог открыт в чате справа.'));const b=el('button','Вернуть на страницу','btn btn--ghost');b.onclick=()=>setWidget(false,false);note.append(b);host.append(note);}
  page(location.hash.slice(1) || 'home');
  try {const job=JSON.parse(sessionStorage.getItem(savedJobKey));if(job && !pending) {question.value=job.question;go('assistant');runQuestion(job);}} catch {clearJob();}
  return true;
}
window.addEventListener('hashchange',()=>page(location.hash.slice(1) || 'home'));
document.querySelector('#menu-open').onclick=()=>{document.querySelector('#menu-toggle').checked=true;document.querySelector('#menu-close').focus();};
document.querySelector('#menu-close').onclick=()=>{document.querySelector('#menu-toggle').checked=false;document.querySelector('#menu-open').focus();};
document.querySelector('[data-goto="profile"]').onclick=()=>go('profile');
chatToggle.onclick=()=>setWidget(!widgetOpen);
document.querySelector('#chat-close').onclick=()=>setWidget(false);
document.querySelector('#chat-expand').onclick=()=>{setWidget(false,false);go('assistant');question.focus();};
document.addEventListener('keydown',event=>{if(event.key==='Escape'){if(widgetOpen)setWidget(false);if(document.querySelector('#menu-toggle').checked){document.querySelector('#menu-toggle').checked=false;document.querySelector('#menu-open').focus();}}});
async function init() {
  try {
    if(await enter()) return;
    const response=await fetch('/api/demo/accounts');if(!response.ok) throw new Error();
    const accounts=await response.json();
    for(const account of accounts) {
      const b=el('button');b.append(el('span',initials(account.name),'avatar'));const info=el('span',null,'account-info');info.append(el('strong',(account.role==='teacher'?'Преподаватель':'Сотрудник')+' · '+account.name),el('small',account.position+' · '+account.unit));b.append(info);
      b.onclick=async()=>{
        b.disabled=true;
        try {
          const r=await fetch('/api/demo/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:account.id})});
          if(!r.ok || !await enter()) throw new Error();
        } catch {document.querySelector('#login-error').textContent='Не удалось войти. Повторите попытку.';}
        finally {b.disabled=false;}
      };document.querySelector('#accounts').append(b);
    }
  } catch {document.querySelector('#login-error').textContent='Сервис недоступен. Обновите страницу после запуска сервера.';}
}
document.querySelector('#logout').onclick=async()=>{
  const r=await fetch('/api/logout',{method:'POST'});
  if(r.ok) {clearJob();history=[];conversation.replaceChildren();location.reload();}
};
init();
