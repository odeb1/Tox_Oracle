'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="launch-token"]').content;
let sid = null, scan = null, generation = 0, invalidations = Promise.resolve();
let workspace = null, activeRun = null, report = null, reportRun = null, pollTimer = null;
const errors = {
  local_detector_failed: 'The local privacy scanner is unavailable. Install the pinned privacy runtime and checkpoint; review cannot be bypassed.',
  checkpoint_integrity_failed: 'The local privacy checkpoint failed its integrity check.',
  tokenizer_cache_missing: 'The privacy tokenizer cache is missing. Complete the local privacy setup.',
  candidate_identity_invalid: 'One or more candidate identities are invalid or duplicated. Check compound IDs and SMILES.',
  reference_required: 'Include reference LT00107 (imatinib). Use the public ABL1 panel for its exact structure.',
  reference_identity_mismatch: 'LT00107 does not match the validated imatinib reference structure.',
  candidate_count_invalid: 'Provide 2–32 candidate records, each with a compound ID and molecular structure.',
  candidate_format_required: 'Upload or paste a CSV or JSON candidate dataset.',
  research_prompt_required: 'Enter a research question of up to 6,000 characters.',
  unsupported_target: 'Choose a validated target from the list.',
  dili_model_missing: 'The trained DILI model is missing. Configure --model with the existing model artifact.',
  model_python_missing: 'The local DILI Python environment is missing. Configure --model-python with the pinned scientific environment.',
  scientific_environment_unavailable: 'The DILI environment cannot import its scientific dependencies. See Methods & setup.',
  complete_cache_required: 'This dataset needs a complete, verified Boltz-2 cache. Cached mode never falls back to a live call.',
  nvidia_credentials_missing: 'NVIDIA credentials are missing from the server environment.',
  cached_mode_is_offline: 'Rosalind is disabled in fully offline mode.',
  rosalind_interface_not_verified: 'Verify a callable Rosalind API and its model identity in Methods & setup before enabling study notes.',
  rosalind_not_configured: 'Configure an OpenAI API key and a supported Rosalind model on the local server.',
  invalid_format: 'The dataset could not be parsed. Check the selected format and file contents.',
  invalid_csv_header: 'CSV column names must be present and unique.',
  invalid_csv_row: 'Each CSV row must contain the same number of fields as the header.',
  duplicate_json_key: 'JSON contains duplicate keys. Remove the ambiguity before review.',
  invalid_screening_report: 'This is not a consistent ToxOracle v3 screening report. Use the saved combined.json output.',
  input_too_large: 'The file exceeds the 1 MB local input limit.',
  request_too_large: 'The request exceeds the local input limit.',
  field_too_long: 'A field exceeds the privacy scanner’s 6,000-character limit.',
  session_expired: 'This review session expired or the server restarted. Reload to start a new session; saved runs remain on disk.',
  invalid_session_token: 'The server restarted. Reload this page to reconnect.',
  approval_required: 'Review and approve the current study before starting.',
  scientific_field_review_required: 'Confirm each retained scientific field before approval.',
  stale_scan: 'The inputs changed. Run privacy review again.',
  scan_invalidated: 'The inputs changed during review. Scan the current study again.',
  review_required: 'Complete privacy review before continuing.',
  study_review_required: 'Review a complete study, including its target and execution mode.',
  workspace_busy: 'Another study is running. Let it finish or request a stop before submitting a new one.',
  run_limit_reached: 'This server session has reached its 32-run limit. Save reports and restart the workspace.',
  run_not_found: 'This run is not available in the current browser session.',
  report_not_ready: 'The report is not yet available.',
  screening_failed: 'The scientific workflow stopped. Review the local run manifest and setup, then start a new reviewed study.',
  local_request_failed: 'The local request failed. Check setup and retry; no provider response or private input is included in this error.'
};
function node(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined && text !== null) e.textContent = String(text); if (cls) e.className = cls; return e; }
function clear(id) { $(id).replaceChildren(); return $(id); }
function showError(error) { const code = error.code || error.message; $('notice').textContent = errors[code] || 'The operation could not complete. Check the local setup and input format, then try again.'; $('notice').hidden = false; $('notice').tabIndex=-1; $('notice').focus({preventScroll:true}); $('notice').scrollIntoView({block:'start'}); }
function dismissError() { $('notice').hidden = true; }
async function api(path, data = {}) {
  let response;
  try { response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Session-Token':token}, body:JSON.stringify({...data, session_id:sid})}); }
  catch { throw new Error('local_request_failed'); }
  let body; try { body = await response.json(); } catch { throw new Error('local_request_failed'); }
  if (!response.ok) throw new Error(body.error || 'local_request_failed');
  return body;
}
async function action(button, operation) {
  dismissError(); button.disabled = true;
  try { await operation(); } catch (error) { showError(error); }
  finally { button.disabled = button.id==='cancel-button' && !!activeRun?.cancel_requested; updateApproval(); }
}
function page(name) {
  ['workspace','runs','methods'].forEach(p => { $(p+'-page').hidden = p !== name; });
  document.querySelectorAll('[data-page]').forEach(b => { b.classList.toggle('active', b.dataset.page === name); if (b.dataset.page === name) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current'); });
  window.scrollTo({top:0, behavior:'instant'});
}
function step(name) {
  const order = ['input','review','run','results'];
  document.querySelectorAll('[data-step]').forEach(li => { li.classList.toggle('current',li.dataset.step === name); li.classList.toggle('done',order.indexOf(li.dataset.step) < order.indexOf(name)); });
  ['input','review','progress','results'].forEach(s => { $(s+'-section').hidden = s !== (name === 'run' ? 'progress' : name); });
}
function edited() {
  generation++; scan = null; $('approve-checkbox').checked = false; updateApproval();
  invalidations = invalidations.then(() => api('/api/invalidate'));
  invalidations.catch(showError);
}
function updateApproval() {
  const checked = [...document.querySelectorAll('#retention-fields input')].every(c => c.checked);
  $('run-button').disabled = !scan || !scan.study || scan.blocked.length > 0 || !$('approve-checkbox').checked || !checked;
}
function applyAssistantStatus(info) {
  const allowed = info.verification === 'verified' && $('execution-mode').value === 'live';
  $('use-rosalind').disabled = !allowed;
  if (!allowed) $('use-rosalind').checked = false;
  $('assistant-input-status').textContent = allowed ? 'Optional: share the reviewed question, candidate IDs and result summary with OpenAI after approval.' : 'Available after API and model identity verification; live mode only.';
  const descriptions = {unchecked:'API not yet verified. No study data has been sent.', verified:'Callable interface and Rosalind response identity verified.', identity_unconfirmed:'The API accepted a Rosalind alias but returned a different model identity. Study notes remain disabled.', rosalind_request_failed:'The API check did not succeed. Study notes remain disabled.', rosalind_not_configured:'No supported Rosalind API configuration is available.'};
  $('rosalind-status').textContent = (descriptions[info.verification] || 'The API has not passed verification.') + ' Requested: ' + (info.requested_model || 'unconfigured') + (info.returned_model ? '. Returned: '+info.returned_model : '');
  $('verify-rosalind').disabled = !info.configured;
}
function renderSetup() {
  const labels = {dili_model:'Trained DILI model',model_python:'DILI Python environment',privacy_checkpoint:'Privacy checkpoint',privacy_runtime:'Privacy runtime',nvidia_credentials:'NVIDIA credentials',cache_directory:'Boltz-2 cache directory'};
  const box = clear('setup-checks');
  Object.entries(labels).forEach(([key,label]) => { const row=node('div',null,'setup-row'); row.append(node('span',label),node('strong',workspace.checks[key]?'Present':'Missing',workspace.checks[key]?'':'missing')); box.append(row); });
  const missing = ['dili_model','model_python','privacy_checkpoint','privacy_runtime'].filter(k => !workspace.checks[k]);
  const mini = clear('readiness-mini'); mini.append(node('span',missing.length ? missing.length+' local setup items need attention before a run.' : 'Local assets are present. Execution preflight will verify them.'));
  const link = node('button','View methods & setup →','text-button'); link.onclick=()=>page('methods'); mini.append(link);
  applyAssistantStatus(workspace.rosalind);
}
async function refreshWorkspace() {
  workspace = await api('/api/workspace');
  const target = $('target'), selected = target.value; target.replaceChildren();
  workspace.targets.forEach(t => { const option = node('option',t.name); option.value=t.target_id; target.append(option); });
  if (workspace.targets.some(t => t.target_id === selected)) target.value=selected;
  const chosen=workspace.targets.find(t=>t.target_id===target.value);
  $('target-note').textContent = chosen ? 'PDB '+chosen.pdb_id+' · '+chosen.sequence_length+' residues · imatinib reference' : '';
  renderSetup(); renderRuns();
}
async function readFile(file) {
  if (!file || file.size > 1000000) throw new Error('input_too_large');
  try { return new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer()); }
  catch { throw new Error('invalid_format'); }
}
async function loadDataset(file) {
  const content = await readFile(file);
  const extension = file.name.split('.').pop().toLowerCase();
  if (!['csv','json'].includes(extension)) throw new Error('candidate_format_required');
  $('candidate-content').value=content; $('dataset-format').value=extension;
  $('file-label').textContent=file.name; edited();
}
function renderReview(result) {
  scan=result; $('approve-checkbox').checked=false;
  $('sanitized-preview').textContent=result.sanitized;
  $('outbound-preview').textContent=result.study ? JSON.stringify(result.study,null,2) : 'Resolve blocked fields and scan again.';
  const count=Object.values(result.audit.category_counts).reduce((a,b)=>a+b,0);
  $('review-summary').textContent = count+' privacy findings reviewed locally. '+result.review_fields.length+' scientific fields need explicit retention confirmation.';
  $('review-blocked').hidden=!result.blocked.length;
  $('review-blocked').textContent='This study cannot be released: '+result.blocked.join(', ')+'. Edit the inputs and scan again.';
  const fields=clear('retention-fields');
  result.review_fields.forEach(f=>{ const label=node('label',null,'check-line retention-field'), check=node('input'); check.type='checkbox'; check.value=f.field_id; check.onchange=updateApproval; const text=node('span'); text.append(node('strong','Retain scientific field: '+f.field),node('code',f.value),node('small',f.reason)); label.append(check,text); fields.append(label); });
  const study=result.study;
  $('destination-note').textContent = !study ? 'Sharing is blocked until this review passes.' : study.mode==='cached' ? 'Fully offline: verified Boltz-2 cache and local DILI inference. No NVIDIA or OpenAI calls.' : 'NVIDIA receives the approved molecular structures and the public ABL1 target sequence. The research prompt stays local.'+(study.use_rosalind?' You also approve sharing the sanitized question, candidate IDs and computed evidence summary with OpenAI for Rosalind notes.':' Rosalind is off; no study content is sent to OpenAI.');
  $('approval-digest').textContent = 'Study fingerprint: '+(result.audit.study_sha256 || result.audit.sanitized_sha256).slice(0,20)+'…';
  updateApproval(); step('review'); $('review-heading').scrollIntoView({block:'start'});
}
const stageNames = {queued:'Waiting to start',planning:'Preparing Rosalind study notes',preparing:'Preparing molecular identities locally',reference:'Checking the imatinib reference',screening:'Screening candidates with Boltz-2',candidate_finished:'Candidate screening finished',shortlist_frozen:'Discovery shortlist frozen',toxicity:'Predicting human DILI locally',reporting:'Validating and assembling results',explaining:'Preparing Rosalind interpretation',finished:'Study finished',failed:'Workflow stopped',cancelled:'Workflow stopped at your request'};
function stageIndex(stage) { if(['queued','planning','preparing'].includes(stage)) return 0; if(stage==='reference')return 1; if(['screening','candidate_finished'].includes(stage))return 2; if(stage==='shortlist_frozen')return 3; if(stage==='toxicity')return 4; return 5; }
function timeLabel(value) { return new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
function renderProgress(run) {
  activeRun=run;
  $('progress-heading').textContent=run.status==='running' || run.status==='queued' ? 'Your study is running' : run.status==='cancelled' ? 'Study stopped' : run.status==='failed' ? 'Study needs attention' : 'Study finished';
  $('run-meta').textContent='Run '+run.job_id.slice(0,8)+' · '+run.candidate_count+' candidates · '+(run.mode==='live'?'Live NVIDIA':'Verified offline cache');
  const latest=run.events.at(-1); let detail=stageNames[run.stage] || 'Working';
  if(latest?.compound_id) detail+=' · '+latest.compound_id;
  if(latest?.total && latest.completed !== undefined) detail+=' · '+latest.completed+' / '+latest.total+' processed';
  if(run.cancel_requested && ['running','queued'].includes(run.status)) detail='Stop requested. The current operation may take several minutes to finish; no remote cancellation is claimed.';
  if(run.error) detail=errors[run.error] || 'The scientific workflow stopped.';
  $('progress-message').textContent=detail;
  const stages=clear('execution-stages'), index=stageIndex(run.stage);
  ['Prepare identities','Validate reference','Screen candidates','Freeze discovery shortlist','Predict human DILI','Assemble results'].forEach((label,i)=>stages.append(node('li',label,i<index?'done':i===index?'current':'')));
  $('frozen-title').textContent=run.shortlist===null?'Waiting for discovery':'Discovery frozen';
  $('frozen-description').textContent=run.shortlist===null?'The shortlist is saved before the DILI model runs.':run.shortlist.length?'DILI can change the follow-up, but it cannot change these selected candidates.':'No candidates had enough discovery evidence to shortlist.';
  const ids=clear('frozen-ids'); (run.shortlist || []).forEach(id=>ids.append(node('span',id,'pill')));
  $('frozen-download').hidden=!run.discovery_sha256;
  $('cancel-button').hidden=!['running','queued'].includes(run.status); $('cancel-button').disabled=!!run.cancel_requested;
  const log=clear('event-log'); run.events.forEach(e=>log.append(node('li',timeLabel(e.at)+' · '+(stageNames[e.stage]||e.stage)+(e.compound_id?' · '+e.compound_id:'')+(e.status?' · '+e.status:''))));
  const plan=run.rosalind.plan; $('planning-note').hidden=!plan;
  if(plan) $('planning-note').textContent='Rosalind planning note · Interpretation only\n\n'+plan.text;
}
function upsertRun(run) { if(!workspace)return; const i=workspace.runs.findIndex(r=>r.job_id===run.job_id); if(i>=0) workspace.runs[i]=run; else workspace.runs.push(run); renderRuns(); }
async function poll() {
  if(!activeRun)return;
  const id=activeRun.job_id;
  try {
    const run=await api('/api/run/status',{job_id:id}); if(activeRun?.job_id!==id)return;
    renderProgress(run); upsertRun(run);
    if(run.report_available) { const result=await api('/api/run/report',{job_id:id}); if(activeRun?.job_id===id) renderResults(result.report,result.run); return; }
    if(['running','queued'].includes(run.status)) pollTimer=setTimeout(poll,1800);
  } catch(error) { showError(error); if(error.message!=='session_expired') pollTimer=setTimeout(poll,5000); }
}
async function openRun(run) { clearTimeout(pollTimer); page('workspace'); step('run'); renderProgress(run); await poll(); }
function number(value, digits=3) { return typeof value==='number' && Number.isFinite(value) ? value.toFixed(digits) : 'Unavailable'; }
function values(items) { return Array.isArray(items)&&items.length ? items.map(n=>number(n)).join(', ') : 'Unavailable'; }
const decisions = {hold_for_liver_validation:'Liver validation first',continue_target_validation:'Continue target validation',not_shortlisted:'Retain discovery rank',safety_assessment_incomplete:'DILI evidence incomplete',discovery_incomplete:'Discovery incomplete'};
function concern(t) { return t.status!=='ok'?'Unavailable':t.assessment.call==='positive'?'Elevated predicted concern':t.assessment.call==='negative'?'Lower predicted concern':'Unavailable'; }
function sortedRows() { return [...report.results].sort((a,b)=>(a.discovery_result.rank??Infinity)-(b.discovery_result.rank??Infinity)); }
function renderResults(result, run) {
  report=result; reportRun=run;
  clearTimeout(pollTimer); step('results');
  $('results-meta').textContent=result.target.target_id+' · '+(run?'Run '+run.job_id.slice(0,8)+' · '+(run.mode==='live'?'Live NVIDIA':'Verified offline cache'):'Imported report · source authenticity not verified');
  $('result-notice').hidden=!!run && run.status==='complete';
  $('result-notice').textContent=run ? 'Partial results: one or more operations did not complete. Missing evidence remains unavailable.' : 'Imported result: scores and follow-up passed contract checks. This workspace did not execute or authenticate this report.';
  const changed=result.results.filter(r=>r.discovery_result.shortlisted&&r.follow_up.decision==='hold_for_liver_validation').length;
  const incomplete=result.results.filter(r=>['safety_assessment_incomplete','discovery_incomplete'].includes(r.follow_up.decision)).length;
  const metrics=clear('result-metrics');
  [[result.results.length,'Candidates assessed','Independent evidence per candidate'],[result.discovery_shortlist.length,'Discovery shortlist','Frozen before DILI'],[changed,'Liver validation first','Shortlisted candidates held'],[incomplete,'Incomplete decisions','Missing evidence stays visible']].forEach(([value,label,note],i)=>{const card=node('div',null,'metric'+(i===2?' emphasis':''));card.append(node('span',label),node('span',value,'value'),node('span',note));metrics.append(card);});
  const cards=clear('decision-cards');
  result.discovery_shortlist.forEach(id=>{const r=result.results.find(c=>c.compound_id===id),card=node('article',null,'decision-card'),head=node('h4');head.append(node('span',id),node('span','Rank '+r.discovery_result.rank,'small'));card.append(head);const flow=node('div',null,'decision-transition'),before=node('div'),after=node('div');before.append(node('span','Discovery only','small'),node('p','Follow up target binding'));after.append(node('span','With human DILI','small'),node('p',decisions[r.follow_up.decision],r.follow_up.decision==='hold_for_liver_validation'?'hold':''));flow.append(before,node('span','→','arrow'),after);card.append(flow,node('p',r.follow_up.recommendation));cards.append(card);});
  if(!result.discovery_shortlist.length)cards.append(node('p','No discovery shortlist is available. Resolve the incomplete binding evidence before drawing follow-up conclusions.','empty'));
  $('candidate-search').value='';$('candidate-filter').value='all';$('candidate-detail').hidden=true;
  renderRows();
  const limitations=clear('result-limitations');result.limitations.forEach(l=>limitations.append(node('li',l)));
  $('provenance-preview').textContent=JSON.stringify({request_id:result.request_id,target:result.target,policy:result.policy_version,policy_status:result.policy_status,discovery_sha256:run?.discovery_sha256 || 'Not supplied by import',execution:run?.mode || 'Imported'},null,2);
  const explain=run?.rosalind?.explain, box=clear('explanation-note'); box.hidden=!run?.rosalind || run.rosalind.status==='off';
  if(explain){box.append(node('p','GPT-ROSALIND INTERPRETATION','eyebrow'),node('h3','Reading the evidence'),node('p',explain.text),node('span','Generated interpretation · Requested '+explain.requested_model+' · Returned '+explain.returned_model+' · Scores and policy above remain authoritative.','small'));}
  else if(run?.rosalind?.status!=='off')box.append(node('h3','Rosalind notes unavailable'),node('p','The optional explanation did not complete. The dashboard still shows the validated scientific results and the deterministic follow-up policy.'));
}
function renderRows() {
  if(!report)return; const tbody=clear('candidate-rows'),search=$('candidate-search').value.toLowerCase().trim(),filter=$('candidate-filter').value;
  const rows=sortedRows().filter(r=>r.compound_id.toLowerCase().includes(search)&&(filter==='all'||filter==='shortlisted'&&r.discovery_result.shortlisted||filter==='hold'&&r.follow_up.decision==='hold_for_liver_validation'||filter==='incomplete'&&['safety_assessment_incomplete','discovery_incomplete'].includes(r.follow_up.decision)));
  rows.forEach(r=>{
    const d=r.discovery_result,t=r.toxicity_result,tr=node('tr'),id=node('td'),button=node('button',r.compound_id,'text-button');button.onclick=()=>renderCandidate(r);id.append(button,node('small',d.shortlisted?'Discovery shortlist':d.rank===null?'Unranked':'Outside shortlist'));
    const binding=node('td',number(d.mean_binding_probability)); if(d.mean_binding_probability!==null){const meter=node('meter');meter.min=0;meter.max=1;meter.value=d.mean_binding_probability;meter.setAttribute('aria-label','Binder likelihood for '+r.compound_id);binding.append(meter);}
    const confidence=node('td',values(d.structural_confidence));confidence.append(node('small','Boltz-2 returned scores'));
    const dili=node('td',t.status==='ok'?number(t.assessment.risk_score):'Unavailable');dili.append(node('small',concern(t)));if(t.status==='ok'&&t.assessment.risk_score!==null){const meter=node('meter',null,'dili');meter.min=0;meter.max=1;meter.value=t.assessment.risk_score;meter.setAttribute('aria-label','DILI score for '+r.compound_id);dili.append(meter);}
    const follow=node('td');follow.append(node('span',decisions[r.follow_up.decision], 'status-tag'+(r.follow_up.decision==='hold_for_liver_validation'?' hold':'')));
    tr.append(id,node('td',d.rank===null?'—':String(d.rank).padStart(2,'0')),binding,confidence,dili,follow);tbody.append(tr);
  });$('empty-table').hidden=!!rows.length;
}
function renderCandidate(r) {
  const box=clear('candidate-detail');box.hidden=false;
  const d=r.discovery_result,t=r.toxicity_result,a=t.assessment,heading=node('div',null,'section-heading');heading.append(node('h2',r.compound_id+' · Evidence'),node('span',decisions[r.follow_up.decision],'pill'));box.append(heading);
  const grid=node('div',null,'detail-grid'),binding=node('div'),dili=node('div'),follow=node('div');
  binding.append(node('p','DISCOVERY EVIDENCE','eyebrow'),node('p',number(d.mean_binding_probability),'big-number'),node('p','Mean predicted binder likelihood'),node('p','All binding predictions: '+values(d.binding_probability)),node('p','Affinity pIC50: '+values(d.affinity_pic50)),node('p','Affinity predicted value: '+values(d.affinity_pred_value)),node('p','Structural confidence: '+values(d.structural_confidence)),node('p','Execution: '+(d.provenance.execution_mode || 'Unavailable')));
  dili.append(node('p','HUMAN DILI EVIDENCE','eyebrow'),node('p',t.status==='ok'?number(a.risk_score):'Unavailable','big-number'),node('p',concern(t)),node('p','Decision threshold: '+number(a.threshold)),node('p','Score kind: '+a.score_kind),node('p','Calibration: '+a.calibration.status),node('p','Training membership: '+t.provenance.training_membership),node('p','Nearest-training similarity: '+number(a.applicability.value)+' (not confidence)'),node('p','Uncertainty: '+a.uncertainty.method));
  follow.append(node('p','RECOMMENDED FOLLOW-UP','eyebrow'),node('h3',decisions[r.follow_up.decision]),node('p',r.follow_up.recommendation));
  if(r.follow_up.experiment){const experiment=r.follow_up.experiment;follow.append(node('p',experiment.question),node('h4',experiment.assay),node('p','Readouts: '+experiment.readouts.join(', ')),node('p',experiment.conditions));}
  grid.append(binding,dili,follow);box.append(grid);
  const notes=node('ul',null,'evidence-list');[...d.warnings,...t.warnings].forEach(w=>notes.append(node('li',w)));box.append(notes);
  const detail=node('details');detail.append(node('summary','Molecular identity and source evidence'),node('pre',JSON.stringify(r,null,2),'data-preview'));box.append(detail);box.focus({preventScroll:true});box.scrollIntoView({block:'start'});
}
function renderRuns() {
  if(!workspace)return; $('run-count').textContent=workspace.runs.length;const list=clear('runs-list');
  if(!workspace.runs.length)list.append(node('p','Your study runs will appear here. Approved outputs remain in artifacts/web/runs after the server closes.','empty'));
  [...workspace.runs].reverse().forEach(run=>{const card=node('article',null,'panel run-card'),info=node('div');info.append(node('h3',run.research_prompt),node('p',run.job_id.slice(0,8)+' · '+run.candidate_count+' candidates · '+run.status+' · '+new Date(run.created_at).toLocaleString()));const button=node('button','Open study →','secondary');button.onclick=()=>action(button,()=>openRun(run));card.append(info,button);list.append(card);});
}
function saveFile(content,filename,mime) { const blob=new Blob([content],{type:mime}),url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000); }
async function download(kind) { const result=await api('/api/run/download',{job_id:activeRun.job_id,kind});saveFile(result.content,result.filename,result.mime); }

document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>page(b.dataset.page));
['research-prompt','target','execution-mode','dataset-format','candidate-content','use-rosalind'].forEach(id=>$(id).addEventListener('input',edited));
$('execution-mode').addEventListener('change',()=>{if(workspace)applyAssistantStatus(workspace.rosalind);});
$('dataset').onchange=()=>action($('scan-button'),()=>loadDataset($('dataset').files[0]));
$('drop-zone').ondragover=e=>{e.preventDefault();$('drop-zone').classList.add('dragging');};
$('drop-zone').ondragleave=()=> $('drop-zone').classList.remove('dragging');
$('drop-zone').ondrop=e=>{e.preventDefault();$('drop-zone').classList.remove('dragging');action($('scan-button'),()=>loadDataset(e.dataTransfer.files[0]));};
$('example-button').onclick=()=>action($('example-button'),async()=>{const data=await api('/api/example');$('research-prompt').value=data.prompt;$('candidate-content').value=data.content;$('dataset-format').value=data.format;$('file-label').textContent='Public ABL1 panel · 4 candidates';edited();});
$('study-form').onsubmit=e=>{e.preventDefault();action($('scan-button'),async()=>{const version=generation;await invalidations;if(version!==generation)return;const result=await api('/api/study/scan',{research_prompt:$('research-prompt').value,content:$('candidate-content').value,format:$('dataset-format').value,target_id:$('target').value,mode:$('execution-mode').value,use_rosalind:$('use-rosalind').checked});if(version===generation)renderReview(result);});};
$('edit-study').onclick=()=>{edited();step('input');};
$('approve-checkbox').onchange=updateApproval;
$('run-button').onclick=()=>action($('run-button'),async()=>{const version=generation,current=scan;if(!current||!$('approve-checkbox').checked)return;await invalidations;await api('/api/approve',{scan_id:current.scan_id,approve:true,retain_fields:[...document.querySelectorAll('#retention-fields input:checked')].map(c=>c.value)});if(version!==generation)return;const run=await api('/api/study/submit',{scan_id:current.scan_id});scan=null;$('research-prompt').value='';$('candidate-content').value='';$('dataset').value='';$('sanitized-preview').textContent='';$('outbound-preview').textContent='';clear('retention-fields');upsertRun(run);await openRun(run);});
$('cancel-button').onclick=()=>action($('cancel-button'),async()=>{const run=await api('/api/run/cancel',{job_id:activeRun.job_id});renderProgress(run);});
$('frozen-download').onclick=()=>action($('frozen-download'),()=>download('discovery'));
$('download-report').onclick=()=>action($('download-report'),async()=>{if(reportRun){activeRun=reportRun;await download('report');}else saveFile(JSON.stringify(report,null,2),'toxoracle-imported-report.json','application/json');});
$('new-study').onclick=()=>{clearTimeout(pollTimer);activeRun=null;scan=null;$('file-label').textContent='Choose a candidate dataset';edited();step('input');window.scrollTo({top:0,behavior:'instant'});};
$('candidate-search').oninput=renderRows;$('candidate-filter').onchange=renderRows;
$('report-file').onchange=()=>action($('report-file'),async()=>{const content=await readFile($('report-file').files[0]);const result=await api('/api/report/inspect',{content});clearTimeout(pollTimer);activeRun=null;page('workspace');renderResults(result.report,null);$('report-file').value='';});
$('inspect-report').onclick=()=>action($('inspect-report'),async()=>{const result=await api('/api/report/inspect',{content:$('report-content').value});clearTimeout(pollTimer);activeRun=null;$('report-content').value='';page('workspace');renderResults(result.report,null);});
$('refresh-setup').onclick=()=>action($('refresh-setup'),refreshWorkspace);
$('verify-rosalind').onclick=()=>action($('verify-rosalind'),async()=>{const info=await api('/api/rosalind/verify');workspace.rosalind=info;applyAssistantStatus(info);});
async function boot() {
  try { sid=sessionStorage.getItem('toxoracle-session'); } catch {}
  if(sid){try{await refreshWorkspace();}catch(error){if(error.message==='session_expired')sid=null;else throw error;}}
  if(!sid){const result=await api('/api/session');sid=result.session_id;try{sessionStorage.setItem('toxoracle-session',sid);}catch{}await refreshWorkspace();}
  $('scan-button').disabled=false;
  const running=workspace.runs.find(r=>['running','queued'].includes(r.status));if(running)await openRun(running);
}
boot().catch(showError);
