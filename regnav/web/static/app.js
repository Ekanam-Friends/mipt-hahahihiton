'use strict';
const form = document.querySelector('#ask');
const question = document.querySelector('#question');
const progress = document.querySelector('#progress');
const conversation = document.querySelector('#conversation');
let history = [];
let pending = false;
let profile = null;
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
form.addEventListener('submit', async event => {
  event.preventDefault(); if(pending || !question.value.trim()) return;
  const q=question.value.trim(); pending=true;
  document.querySelector('#submit').disabled=true; document.querySelector('#reset').disabled=true;
  progress.textContent='Ищем источники и проверяем ответ. Локальная модель может работать долго.';
  try {
    const response=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,history,as_of:document.querySelector('#as-of').value || null})});
    const data=await response.json(); render(q,data);
    if(response.ok && data.status !== 'error') {
      // Only user input and the explicit clarification enter the next rewrite.
      history.push(q); if(data.clarifying_question) history.push(data.clarifying_question);
      history=history.slice(-6); question.value='';
    }
    progress.textContent=data.status==='error'?'Повторите запрос кнопкой «Найти ответ».':'Можно задать уточнение или начать новый диалог.';
  } catch {
    render(q,{status:'error',message:'Не удалось связаться с сервисом. Проверьте соединение и повторите запрос.'});
    progress.textContent='Вопрос сохранён в поле ввода для повтора.';
  } finally {pending=false;document.querySelector('#submit').disabled=false;document.querySelector('#reset').disabled=false;}
});
document.querySelector('#reset').addEventListener('click',()=>{history=[];conversation.replaceChildren();question.value='';document.querySelector('#as-of').value='';progress.textContent='Начат новый диалог.';question.focus();});

const common = [['home','Главная'],['assistant','ИИ-ассистент'],['profile','Профиль']];
// Full university cabinets are a separate task; show only available screens.
const teacher = [];
const employee = [];
function profileCard() {
  const grid=el('div',null,'profile-grid');
  for(const [title,value] of [['ФИО',profile.name],['Должность',profile.position],['Подразделение',profile.unit],['Табельный номер',profile.tab_no],['Почта',profile.email],['Занятость','Основное место работы']]) {
    const p=el('p');p.append(el('small',title),el('strong',value));grid.append(p);
  } return grid;
}
function page(id,title) {
  document.querySelector('#assistant').hidden=id!=='assistant';
  document.querySelector('#dashboard').hidden=id==='assistant';
  for(const b of document.querySelectorAll('#menu button')) b.classList.toggle('active',b.dataset.page===id);
  if(id==='assistant') return;
  document.querySelector('#page-title').textContent=title;
  const content=document.querySelector('#page-content');content.replaceChildren();
  if(id==='profile' || id==='home') {
    const panel=el('section',null,'panel');panel.append(profileCard());content.append(panel);
    if(id==='home') {
      const p=el('section',null,'panel');p.append(el('h2','Помощь по регламентам'),el('p','Найдите порядок открытия ФЛС, подбора персонала или оформления поддержки. Ассистент покажет доказательства и оригиналы документов.'));
      const b=el('button','Открыть ассистента');b.onclick=()=>page('assistant','ИИ-ассистент');p.append(b);content.append(p);
    }
  } else {
    const panel=el('section',null,'panel');panel.append(el('h2',title),el('p','Раздел запланирован к переносу из MGIMO-LMS. В этой первой версии доступны профиль и ассистент по регламентам.'));
    content.append(panel);
  }
}
async function enter() {
  const response=await fetch('/api/me');
  if(!response.ok) return false;
  profile=await response.json();
  document.querySelector('#login').hidden=true;document.querySelector('#cabinet').hidden=false;
  document.querySelector('#user-name').textContent=profile.name;
  document.querySelector('#user-unit').textContent=profile.unit;
  document.querySelector('#role-label').textContent=profile.role==='teacher'?'Кабинет преподавателя':'Кабинет сотрудника';
  const menu=document.querySelector('#menu');menu.replaceChildren();
  const items=[common[0],...(profile.role==='teacher'?teacher:employee),...common.slice(1)];
  for(const [id,title] of items){const b=el('button',title);b.dataset.page=id;b.onclick=()=>page(id,title);menu.append(b);}
  page('home','Главная');return true;
}
async function init() {
  try {
    if(await enter()) return;
    const response=await fetch('/api/demo/accounts');if(!response.ok) throw new Error();
    const accounts=await response.json();
    for(const account of accounts) {
      const b=el('button',(account.role==='teacher'?'Преподаватель':'Сотрудник')+' · '+account.name);
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
  if(r.ok) {history=[];conversation.replaceChildren();location.reload();}
};
init();
