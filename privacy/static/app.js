'use strict';
const el=id=>document.getElementById(id);
const token=document.querySelector('meta[name="launch-token"]').content;
let sid=null, snapshot=null, generation=0, response=null, invalidating=Promise.resolve(), idleTimer;
async function api(path,body={}) {
  const res=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':token},body:JSON.stringify({session_id:sid,...body})});
  const value=await res.json(); if(!res.ok) throw Error(value.error||'Local request failed'); return value;
}
function setStatus(text){el('status').textContent=text;}
function lock(){['approve','export','request','predict'].forEach(id=>el(id).disabled=true);el('response').hidden=true;response=null;}
function invalidate(){generation++;snapshot=null;lock();el('findings').replaceChildren();el('results').replaceChildren();
  el('mode').textContent=el('enabled').checked?'Local detection and review':'Unfiltered preview — local only';
  el('scan').disabled=!el('enabled').checked;
  el('preview').textContent=el('enabled').checked?'Input changed. Scan and review again.':el('input').value;
  setStatus(el('enabled').checked?'Ready to scan.':'Filtering OFF. Export is disabled.');
  if(sid) invalidating=invalidating.then(()=>api('invalidate')).catch(()=>{sid=null;setStatus('Session expired. Clear the session to start again.');});
}
async function reset(){generation++;lock();if(sid) await api('reset').catch(()=>{});sid=(await api('session')).session_id;
  snapshot=null;el('input').value='';el('file').value='';el('preview').textContent='Your proposed sanitized payload will appear here.';
  el('findings').replaceChildren();el('results').replaceChildren();setStatus('Ready. Local session cleared.');}
function download(name,content,type='application/json'){const u=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
function wrap(fn){return async()=>{try{await fn();}catch(e){setStatus('Blocked: '+e.message);}};}
el('input').addEventListener('input',invalidate);el('format').addEventListener('change',invalidate);el('enabled').addEventListener('change',invalidate);
el('reset').onclick=wrap(reset);
el('file').onchange=wrap(async()=>{const f=el('file').files[0];if(!f)return;if(f.size>1000000)throw Error('File exceeds 1 MB');
  const ext=f.name.split('.').pop().toLowerCase();if(!['txt','csv','json'].includes(ext))throw Error('Unsupported file format');
  el('format').value=ext==='txt'?'text':ext;el('input').value=new TextDecoder('utf-8',{fatal:true}).decode(await f.arrayBuffer());invalidate();});
el('example').onclick=()=>{el('format').value='json';el('input').value=JSON.stringify({compounds:[{compound_id:'candidate_001',smiles:'CCO',patient_name:'Alice Morgan',patient_id:'PT-12345',notes:'Contact Alice Morgan at alice.morgan@example.com. Proposed concentration: 10 uM.'}]},null,2);invalidate();};
el('scan').onclick=wrap(async()=>{await invalidating;if(!sid)throw Error('Clear session first');const g=++generation;lock();setStatus('Scanning locally. First model load may take a little longer…');
  const result=await api('scan',{content:el('input').value,format:el('format').value,enabled:el('enabled').checked});if(g!==generation)return;snapshot=result;el('preview').textContent=result.sanitized;
  el('findings').replaceChildren();for(const f of result.findings){const d=document.createElement('div');d.className='finding';d.textContent=`${f.action} · ${f.label} · ${f.detector} · ${f.path||'text'}`;el('findings').append(d);}
  for(const f of result.review_fields){const label=document.createElement('label');label.className='finding review';const box=document.createElement('input');box.type='checkbox';box.dataset.fieldId=f.field_id;box.onchange=()=>{if(!el('export').disabled)invalidate();};label.append(box,document.createTextNode(' Retain '+f.path+': I reviewed this validated scientific field and confirm it contains no personal identifier.'));el('findings').append(label);}
  el('approve').disabled=result.blocked.length>0;setStatus(result.blocked.length?'Blocked: '+result.blocked.join(', '):`${result.findings.length} findings. Review the entire sanitized payload before approval.`);});
el('approve').onclick=wrap(async()=>{await invalidating;const g=generation;const retain_fields=[...document.querySelectorAll('[data-field-id]:checked')].map(x=>x.dataset.fieldId);await api('approve',{scan_id:snapshot.scan_id,approve:true,retain_fields});if(g!==generation)return;['export','request','predict'].forEach(id=>el(id).disabled=false);el('approve').disabled=true;setStatus('Approved. Only this sanitized snapshot can be exported.');});
el('export').onclick=wrap(async()=>{await invalidating;const g=generation;const out=await api('export',{scan_id:snapshot.scan_id});if(g!==generation)return;download('sanitized.'+(out.format==='text'?'txt':out.format),out.content,'text/plain');download('privacy-audit.json',JSON.stringify(out.audit,null,2));});
el('request').onclick=wrap(async()=>{await invalidating;const g=generation;const out=await api('export',{scan_id:snapshot.scan_id,kind:'toxicity'});if(g!==generation)return;download('toxicity-request.json',JSON.stringify(out,null,2));});
el('predict').onclick=wrap(async()=>{await invalidating;const g=generation;setStatus('Running local DILI model…');const out=await api('predict',{scan_id:snapshot.scan_id});if(g!==generation)return;response=out;
  const table=document.createElement('table');const head=document.createElement('tr');for(const text of ['Candidate','Status','DILI score','Call','Train similarity']){const th=document.createElement('th');th.textContent=text;head.append(th);}table.append(head);
  for(const r of out.results){const tr=document.createElement('tr');for(const text of [r.compound_id,r.status,r.assessment.risk_score?.toFixed(3)??'—',r.assessment.call,r.assessment.applicability.value?.toFixed(3)??'—']){const td=document.createElement('td');td.textContent=text;tr.append(td);}table.append(tr);}
  el('results').replaceChildren(table);el('response').hidden=false;setStatus('Local assessment complete. Scores describe drug-level DILI concern, not patient risk.');});
el('response').onclick=()=>download('toxicity-response.json',JSON.stringify(response,null,2));
reset().catch(()=>setStatus('Could not start local session.'));
function touch(){clearTimeout(idleTimer);idleTimer=setTimeout(()=>reset().catch(()=>{el('input').value='';el('preview').textContent='Session expired.';lock();}),1800000);}
['input','click','keydown'].forEach(event=>document.addEventListener(event,touch));touch();
