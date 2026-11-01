'use strict';
const app=document.getElementById('app'),sidebar=document.getElementById('sidebar');
const values={};let ws;const pending=new Map();let working=false;
function stage(id,value){values[id]=value}
function commit(id,value){stage(id,value);clearTimeout(pending.get(id));pending.set(id,setTimeout(()=>{pending.delete(id);if(ws.readyState===1)ws.send(JSON.stringify({values}))},260))}
const el=(tag,cls='',value)=>{let n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=String(value);return n};
function emit(id,value,once=false){
  if(once&&working)return;
  for(const timer of pending.values())clearTimeout(timer);
  pending.clear();values[id]=value;
  if(ws&&ws.readyState===WebSocket.OPEN){
    ws.send(JSON.stringify({values}));
    if(once){
      working=true;
      const button=[...document.querySelectorAll('button[data-widget-id]')].find(b=>b.dataset.widgetId===id);
      if(button){
        button.disabled=true;
        button.setAttribute('aria-busy','true');
        button.textContent=/generat/i.test(button.textContent)?'Generating response…':'Running…';
        button.closest('article')?.append(el('div','notice work','Working on your request. Local AI models may take a little while to answer.'));
      }
    }
  }else{
    app.prepend(el('div','notice error','The application is disconnected. Restart your server and refresh the page.'));
  }
  if(once)delete values[id];
}
function display(c,root){let box=el('article'),node;
switch(c.type){
case 'title':node=el('h1','',c.value);break;
case 'output':node=el('div','output',c.value);break;
case 'heading':node=el('h2','',c.value);break;
case 'section':node=el('div','section',c.value);break;
case 'caption':node=el('div','caption',c.value);break;
case 'guide':node=el('div','guide',c.value);break;
case 'text':case 'markdown':node=el('p','',c.value);break;
case 'code':node=el('pre','',c.value);break;
case 'divider':node=document.createElement('hr');break;
case 'notice':node=el('div','notice '+c.tone,c.value);break;
case 'metric':node=el('div','metric');node.append(el('span','',c.label),el('strong','',c.value));break;
case 'button':node=el('button','btn',c.label);node.dataset.widgetId=c.id;node.onclick=()=>emit(c.id,true,true);break;
case 'input':case 'number':{node=el('div','field');let label=el('label','',c.label),i=document.createElement('input');i.type=c.type==='number'?'number':'text';i.value=c.value;i.oninput=()=>stage(c.id,c.type==='number'?Number(i.value):i.value);i.onchange=()=>commit(c.id,c.type==='number'?Number(i.value):i.value);node.append(label,i);break;}
case 'textarea':{node=el('div','field');let label=el('label','',c.label),area=document.createElement('textarea');area.value=c.value;area.style.height=c.height+'px';area.oninput=()=>stage(c.id,area.value);area.onchange=()=>commit(c.id,area.value);node.append(label,area);break;}
case 'checkbox':{node=el('label','checkbox-label');let i=document.createElement('input');i.type='checkbox';i.checked=c.value;i.onchange=()=>emit(c.id,i.checked);node.append(i,document.createTextNode(c.label));break;}
case 'select':{node=el('div','field');node.append(el('label','',c.label));let s=document.createElement('select');for(const o of c.options){const opt=el('option','',o);opt.value=JSON.stringify(o);if(o===c.value)opt.selected=true;s.append(opt)}s.onchange=()=>emit(c.id,JSON.parse(s.value));node.append(s);break;}
case 'table':{node=document.createElement('table');let rows=c.rows||[];if(rows.length){let keys=[...new Set(rows.flatMap(r=>r&&typeof r==='object'?Object.keys(r):['value']))],head=document.createElement('thead'),tr=document.createElement('tr');keys.forEach(k=>tr.append(el('th','',k)));head.append(tr);node.append(head);let body=document.createElement('tbody');rows.forEach(r=>{let tr=document.createElement('tr');keys.forEach(k=>{let v=r&&typeof r==='object'?r[k]:r;tr.append(el('td','',typeof v==='object'?JSON.stringify(v):v??''))});body.append(tr)});node.append(body)}break;}
default:node=el('pre','',JSON.stringify(c));
}
box.append(node);root.append(box);
}
function draw(components){working=false;app.replaceChildren();sidebar.replaceChildren();const grids={};for(const c of components){let root=c.container==='sidebar'?sidebar:app;const match=c.container?.match(/^column-(\d+)-of-(\d+)$/);if(match){const n=Number(match[2]),i=Number(match[1]);if(!grids[n]){const grid=el('div','cols');grid.style.setProperty('--cols',n);for(let j=0;j<n;j++)grid.append(el('div','columnslot'));app.append(grid);grids[n]=grid}root=grids[n].children[i]}display(c,root)}document.body.classList.toggle('sidebar-empty',!sidebar.childElementCount)}
function connect(){ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');ws.onmessage=e=>{const message=JSON.parse(e.data);if(message.error){working=false;app.replaceChildren(el('div','notice error',message.error));return}if(message.components)draw(message.components)};ws.onclose=()=>{working=false;app.append(el('div','notice warning','Connection closed. Restart your Python application and refresh the page.'))}}
document.getElementById('toggle').onclick=()=>document.body.classList.toggle('sidebar-collapsed');connect();
