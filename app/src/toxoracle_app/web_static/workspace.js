'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="launch-token"]').content;
let sid = null, scan = null, generation = 0, invalidations = Promise.resolve();
let moleculeImages = {}, showDili = true, replayEvidence = null, replayStage = 0;
let workspace = null, activeRun = null, report = null, reportRun = null, pollTimer = null;
const errors = {
  recorded_evidence_unavailable: 'The recorded study failed verification. Restore its original bundle; no live fallback was attempted.',
  assistant_invalid_plan: 'The assistant returned an invalid plan. No screening has started.',
  assistant_timeout: 'NVIDIA did not respond within 120 seconds. No screening has started.',
  assistant_rate_limited: 'NVIDIA is rate limiting the assistant. No screening has started.',
  continuation_not_available: 'This study is not awaiting a fixed-protocol continuation.',
  local_detector_failed: 'The local privacy scanner is unavailable. Install the pinned privacy runtime and checkpoint; review cannot be bypassed.',
  checkpoint_integrity_failed: 'The local privacy checkpoint failed its integrity check.',
  tokenizer_cache_missing: 'The privacy tokenizer cache is missing. Complete the local privacy setup.',
  candidate_identity_invalid: 'One or more candidate identities are invalid or duplicated. Check compound IDs and SMILES.',
  reference_required: 'Include reference LT00107 (imatinib). Use the public ABL1 panel for its exact structure.',
  reference_identity_mismatch: 'LT00107 does not match the validated imatinib reference structure.',
  candidate_count_invalid: 'Provide 2–32 candidate records, each with a compound ID and molecular structure.',
  candidate_format_required: 'Upload or paste a CSV or JSON candidate dataset.',
  research_prompt_required: 'Enter a research question of up to 6,000 characters.',
  unsupported_target: 'This target needs preparation before execution.',
  target_preparation_required: 'Name the target in your question. This demo is prepared for human ABL1; other targets or mutants need preparation before execution.',
  generation_no_assessment: 'Generation or the reference check did not yield a screenable panel. No complete assessment is claimed. Inspect the saved design report and start a new reviewed study.',
  dili_model_missing: 'The trained DILI model is missing. Configure --model with the existing model artifact.',
  model_python_missing: 'The local DILI Python environment is missing. Configure --model-python with the pinned scientific environment.',
  scientific_environment_unavailable: 'The DILI environment cannot import its scientific dependencies. See Methods & setup.',
  complete_cache_required: 'This dataset needs a complete, verified Boltz-2 cache. Cached mode never falls back to a live call.',
  nvidia_credentials_missing: 'NVIDIA credentials are missing from the server environment.',
  cached_mode_is_offline: 'Nemotron is disabled in fully offline mode.',
  assistant_interface_not_verified: 'Verify a callable Nemotron API and its model identity in Methods & setup before enabling study notes.',
  assistant_not_configured: 'Configure NVIDIA_API_KEY in the local server environment.',
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
  const operations={'scan-button':'Privacy filter running locally. No provider calls are made during review.','run-button':'Checking approved inputs and local scientific environment…','verify-assistant':'Checking the NVIDIA connection with a fixed greeting…','preview-button':'Rendering molecular structures locally…'};
  if(operations[button.id]){$('local-operation').textContent=operations[button.id];$('local-operation').hidden=false;}
  try { await operation(); } catch (error) { showError(error); }
  finally { if(operations[button.id])$('local-operation').hidden=true; button.disabled = button.id==='cancel-button' && !!activeRun?.cancel_requested; updateApproval(); }
}
function page(name) {
  ['workspace','results','runs','methods','replay'].forEach(p => { $(p+'-page').hidden = p !== name; });
  document.querySelectorAll('[data-page]').forEach(b => { b.classList.toggle('active', b.dataset.page === name); if (b.dataset.page === name) b.setAttribute('aria-current','page'); else b.removeAttribute('aria-current'); });
  window.scrollTo({top:0, behavior:'instant'});
}
function step(name) {
  const order = ['input','review','run','assess','results'];
  document.body.dataset.studyStage = name;
  document.querySelectorAll('[data-step]').forEach(li => { li.classList.toggle('current',li.dataset.step === name); li.classList.toggle('done',order.indexOf(li.dataset.step) < order.indexOf(name)); });
  ['input','review','progress'].forEach(s => { $(s+'-section').hidden = s !== (['run','assess'].includes(name) ? 'progress' : name==='results' ? 'input' : name); });
}
function edited(event) {
  updateRoute(); generation++; scan = null; if(!event || ['candidate-content','dataset-format'].includes(event.target?.id)){clear('candidate-preview');moleculeImages={};} $('approve-checkbox').checked = false; updateApproval();
  invalidations = invalidations.then(() => api('/api/invalidate'));
  invalidations.catch(showError);
}
function updateApproval() {
  const checked = [...document.querySelectorAll('#retention-fields input')].every(c => c.checked);
  $('run-button').disabled = !scan || !scan.study || scan.blocked.length > 0 || !$('approve-checkbox').checked || !checked;
}
function applyAssistantStatus(info) {
  const allowed = info.configured && $('execution-mode').value === 'live';
  $('use-assistant').disabled = !allowed;
  if (!allowed) $('use-assistant').checked = false;
  $('assistant-input-status').textContent = allowed ? 'Interpret the approved question, choose the route and explain its evidence. Model identity is checked on each response.' : 'Live planning requires a server key; cached mode stays offline.';
  const descriptions = {assistant_timeout:'NVIDIA did not respond within 120 seconds. Retry the connection check when the service is available.',unchecked:'API not yet verified. No study data has been sent.', verified:'NVIDIA Nemotron connection and model identity verified.', identity_unconfirmed:'The endpoint returned an unexpected model identity. Planning remains disabled.', assistant_request_failed:'The API check did not succeed. Study notes remain disabled.', assistant_not_configured:'No NVIDIA key is configured in this server process.'};
  $('assistant-status').textContent = (descriptions[info.verification] || 'The API has not passed verification.') + ' Requested: ' + (info.requested_model || 'unconfigured') + (info.returned_model ? '. Returned: '+info.returned_model : '');
  $('verify-assistant').disabled = !info.configured;
}
function renderSetup() {
  const labels = {dili_model:'Trained DILI model',model_python:'DILI Python environment',privacy_checkpoint:'Privacy checkpoint',privacy_runtime:'Privacy runtime',nvidia_credentials:'NVIDIA credentials',cache_directory:'Boltz-2 cache directory'};
  const box = clear('setup-checks');
  Object.entries(labels).forEach(([key,label]) => { const row=node('div',null,'setup-row'); row.append(node('span',label),node('strong',workspace.checks[key]?'Present':'Missing',workspace.checks[key]?'':'missing')); box.append(row); });
  const missing = ['dili_model','model_python','privacy_checkpoint','privacy_runtime'].filter(k => !workspace.checks[k]);
  const mini = clear('readiness-mini'); mini.append(node('span',missing.length ? missing.length+' local setup items need attention before a run.' : 'Local assets are present. Execution preflight will verify them.'));
  const link = node('button','View methods & setup →','text-button'); link.onclick=()=>page('methods'); mini.append(link);
  applyAssistantStatus(workspace.assistant);
}
async function refreshWorkspace() {
  workspace = await api('/api/workspace');
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
  $('file-label').textContent=file.name; edited(); await previewCandidates();
}
function renderReview(result) {
  scan=result; $('approve-checkbox').checked=false;
  $('sanitized-preview').textContent=result.sanitized;
  $('outbound-preview').textContent=result.study ? JSON.stringify(result.outbound || result.study,null,2) : 'Resolve blocked fields and scan again.';
  const count=Object.values(result.audit.category_counts).reduce((a,b)=>a+b,0);
  $('review-summary').textContent = count+' privacy '+(count===1?'finding':'findings')+' reviewed locally. '+result.review_fields.length+' scientific '+(result.review_fields.length===1?'field needs':'fields need')+' explicit retention confirmation.';
  $('review-blocked').hidden=!result.blocked.length;
  $('review-blocked').textContent='This study cannot be released: '+result.blocked.join(', ')+'. Edit the inputs and scan again.';
  const fields=clear('retention-fields');
  result.review_fields.forEach(f=>{ const label=node('label',null,'check-line retention-field'), check=node('input'); check.type='checkbox'; check.value=f.field_id; check.onchange=updateApproval; const text=node('span'); text.append(node('strong','Retain scientific field: '+f.field),node('code',f.value),node('small',f.reason)); label.append(check,text); fields.append(label); });
  const study=result.study;
  const readable=clear('review-readable');
  if(study){readable.append(node('p','REVIEWED RESEARCH QUESTION','eyebrow'),node('h3',study.research_prompt),node('p',(study.workflow==='generate_screen'?'Propose up to 20 candidates · GenMol → Boltz-2':study.request.compounds.length+' supplied candidates')+' · Human ABL1 · '+(study.mode==='cached'?'Cached screening and local DILI':'NVIDIA Boltz-2 and local DILI'))); renderMolecules(readable, (study.request.compounds || []).map(c=>({...c,image:moleculeImages[c.compound_id],status:'valid'})));}
  $('destination-note').textContent = !study ? 'Sharing is blocked until this review passes.' : study.mode==='cached' ? 'Fully offline: verified Boltz-2 cache and local DILI inference. No provider calls.' : (study.workflow==='generate_screen'?'GenMol receives the documented public imatinib fragment (up to five batches of 20 proposals). Boltz-2 receives the public ABL1 sequence, reference and up to 20 selected generated structures. This approval covers that bounded generation and screening.':'Boltz-2 receives the approved molecular structures and public ABL1 sequence.')+(study.use_assistant?' Nemotron receives the sanitized question and candidate IDs for planning, then computed evidence for explanation.':' The assistant is off; the research prompt stays local.');
  $('approval-digest').textContent = 'Study fingerprint: '+(result.audit.study_sha256 || result.audit.sanitized_sha256).slice(0,20)+'…';
  const findings=node('ul',null,'privacy-findings');result.findings.filter(f=>f.action!=='review_required').forEach(f=>findings.append(node('li',f.path+' · '+f.action+' · '+f.label)));readable.append(findings);
  updateApproval(); step('review'); $('review-heading').scrollIntoView({block:'start'});
}
const stageNames = {validating_proposals:'Checking generated structures locally',generating:'Proposing molecules with NVIDIA GenMol',selecting:'Validating and selecting diverse proposals locally',candidates_ready:'Generated candidates prepared for screening',reference_finished:'Reference check passed',queued:'Waiting to start',planning:'Interpreting the approved question with Nemotron',planning_paused:'Planning paused · no scientific calls have started',preparing:'Preparing molecular identities locally',reference:'Checking the imatinib reference',screening:'Screening candidates with Boltz-2',candidate_finished:'Candidate screening finished',shortlist_frozen:'Discovery shortlist frozen',toxicity:'Predicting human DILI locally',reporting:'Validating and assembling results',explaining:'Preparing Nemotron interpretation',finished:'Study finished',failed:'Workflow stopped',cancelled:'Workflow stopped at your request'};
function timeLabel(value) { return new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
function renderProgress(run) {
  activeRun=run;
  $('progress-heading').textContent=run.status==='running' || run.status==='queued' ? 'Your study is running' : run.status==='cancelled' ? 'Study stopped' : run.status==='failed'||run.status==='awaiting_plan'||run.status==='partial' ? 'Study needs attention' : 'Study finished';
  step(['shortlist_frozen','toxicity','reporting','explaining'].includes(run.stage)?'assess':'run');
  const candidateLabel=run.workflow==='generate_screen'&&!run.candidate_count?'20 candidates requested':run.candidate_count+' candidates';
  $('study-context').hidden=false; $('study-context').textContent='Human ABL1 · '+candidateLabel+' · '+run.research_prompt;
  $('run-meta').textContent='Run '+run.job_id.slice(0,8)+' · '+candidateLabel+' · '+(run.mode==='recorded'?'Recorded walkthrough · no inference':run.mode==='live'?'Live NVIDIA':'Verified offline cache');
  const latest=run.events.at(-1); let detail=stageNames[run.stage] || 'Working';
  if(latest?.compound_id) detail+=' · '+latest.compound_id;
  if(latest?.total && latest.completed !== undefined) detail+=' · '+latest.completed+' / '+latest.total+' processed';
  if(run.cancel_requested && ['running','queued','awaiting_plan'].includes(run.status)) detail='Stop requested. The current operation may take several minutes to finish; no remote cancellation is claimed.';
  if(run.error) detail=errors[run.error] || 'The scientific workflow stopped.';
  $('progress-message').textContent=detail;
  const gen=clear('generation-progress');gen.hidden=run.workflow!=='generate_screen';
  if(!gen.hidden){gen.append(node('p','MOLECULAR PROPOSAL','eyebrow'),node('h3',run.candidates.length?run.candidates.length+' generated candidates':'From your target to molecular proposals'),node('p','Documented imatinib fragment → GenMol → chemical checks → diversity selection → Boltz-2. No DILI feedback into generation.'));const selectedEvent=run.events.findLast(e=>e.stage==='selecting');const batchEvent=run.events.findLast(e=>e.batch);if(selectedEvent)gen.append(node('p',selectedEvent.accepted+' acceptable unique proposals · up to '+selectedEvent.requested+' selected for screening.'));else if(batchEvent)gen.append(node('p','GenMol batch '+batchEvent.batch+' · '+batchEvent.accepted+' acceptable unique proposals at the last checkpoint.'));}
  renderLiveCandidates(run);
  $('active-model').textContent=['planning','planning_paused','explaining'].includes(run.stage)?'NVIDIA Nemotron 3.5 Lightning':run.stage==='toxicity'?'Local ToxOracle DILI':run.stage==='generating'?'NVIDIA GenMol':['reference','screening','candidate_finished'].includes(run.stage)?'NVIDIA Boltz-2':'ToxOracle workflow';
  $('elapsed-time').textContent='Elapsed '+Math.max(0,Math.floor((new Date(run.finished_at || Date.now())-new Date(run.created_at))/1000))+' seconds · '+run.events.length+' recorded events';
  $('revise-study').hidden=!['awaiting_plan','failed','cancelled'].includes(run.status);
  $('continue-fixed').hidden=!(run.status==='awaiting_plan' && run.can_continue);
  $('frozen-title').textContent=run.shortlist===null?'Waiting for discovery':'Discovery frozen';
  $('frozen-description').textContent=run.shortlist===null?'The shortlist is saved before the DILI model runs.':run.shortlist.length?'DILI can change the follow-up, but it cannot change these selected candidates.':'No candidates had enough discovery evidence to shortlist.';
  const ids=clear('frozen-ids'); (run.shortlist || []).forEach(id=>ids.append(node('span',id,'pill')));
  $('frozen-download').hidden=!run.discovery_sha256;
  $('cancel-button').hidden=!['running','queued','awaiting_plan'].includes(run.status); $('cancel-button').disabled=!!run.cancel_requested;
  const log=clear('event-log'); run.events.forEach(e=>log.append(node('li',timeLabel(e.at)+' · '+(stageNames[e.stage]||e.stage)+(e.compound_id?' · '+e.compound_id:'')+(e.status?' · '+e.status:'')+(e.total&&e.completed!==undefined?' · '+e.completed+'/'+e.total:''))));
  const plan=run.assistant.plan; $('planning-note').hidden=!plan;
  if(plan) $('planning-note').textContent=(plan.supported?'Validated Nemotron plan':'Request outside the supported protocol')+'\n\n'+plan.text;
  if(run.status==='awaiting_plan' && !plan){$('planning-note').hidden=false;$('planning-note').textContent=(errors[run.assistant.error] || 'Assistant planning failed. No science has started.')+' You may continue explicitly with the approved fixed protocol.';}
  if(run.status==='awaiting_plan' && plan && !plan.supported) $('planning-note').append(node('p','Stop this study and revise the question to use the supported ABL1 screening protocol.'));
}
function upsertRun(run) { if(!workspace)return; const i=workspace.runs.findIndex(r=>r.job_id===run.job_id); if(i>=0) workspace.runs[i]=run; else workspace.runs.push(run); renderRuns(); }
async function poll() {
  if(!activeRun)return;
  const id=activeRun.job_id;
  try {
    const run=await api('/api/run/status',{job_id:id}); if(activeRun?.job_id!==id)return;
    renderProgress(run); upsertRun(run);
    if(run.report_available) { const result=await api('/api/run/report',{job_id:id}); if(activeRun?.job_id===id) renderResults(result.report,result.run); return; }
    if(['running','queued','awaiting_plan'].includes(run.status)) pollTimer=setTimeout(poll,1800);
  } catch(error) { showError(error); if(error.message!=='session_expired') pollTimer=setTimeout(poll,5000); }
}
async function openRun(run) { clearTimeout(pollTimer); page('workspace'); step('run'); renderProgress(run); await poll(); }
function number(value, digits=3) { return typeof value==='number' && Number.isFinite(value) ? value.toFixed(digits) : 'Unavailable'; }
function values(items) { return Array.isArray(items)&&items.length ? items.map(n=>number(n)).join(', ') : 'Unavailable'; }
const decisions = {hold_for_liver_validation:'Liver validation first',continue_target_validation:'Continue target validation',not_shortlisted:'Retain discovery rank',safety_assessment_incomplete:'DILI evidence incomplete',discovery_incomplete:'Discovery incomplete'};
function concern(t) { return t.status!=='ok'?'Unavailable':t.assessment.call==='positive'?'Elevated predicted concern':t.assessment.call==='negative'?'Lower predicted concern':'Unavailable'; }
function sortedRows() { return [...report.results].sort((a,b)=>(a.discovery_result.rank??Infinity)-(b.discovery_result.rank??Infinity)); }
function renderResults(result, run) {
  report=result; reportRun=run; showDili=true;window.scrollTo({top:0,behavior:'instant'});
  $('study-context').hidden=false;$('study-context').textContent=run?.mode==='recorded'?'Recorded public ABL1 study · No inference or new approval':run?.research_prompt || 'Imported study · locally validated'; updateEvidenceSwitch();
  $('download-html').hidden=!run || run.mode==='recorded';
  clearTimeout(pollTimer); step('results'); $('results-section').hidden=false; $('results-empty').hidden=true; page('results'); resultView('overview'); renderDashboard(result);
  $('results-meta').textContent=result.target.target_id+' · '+(run?'Run '+run.job_id.slice(0,8)+' · '+(run.mode==='recorded'?'Recorded walkthrough · no inference':run.mode==='live'?'Live NVIDIA':'Verified offline cache'):'Imported report · source authenticity not verified');
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
  ensureMolecules(result.results).then(()=>{if(report===result)renderRows();}).catch(showError);
  const history=clear('result-history');history.hidden=!run?.events; if(run?.events){history.append(node('summary','Execution history · '+run.events.length+' actual events'));const list=node('ol',null,'event-log');run.events.forEach(e=>list.append(node('li',timeLabel(e.at)+' · '+(stageNames[e.stage]||e.stage)+(e.compound_id?' · '+e.compound_id:''))));history.append(list);}
  const limitations=clear('result-limitations');result.limitations.forEach(l=>limitations.append(node('li',l)));
  $('provenance-preview').textContent=JSON.stringify({request_id:result.request_id,target:result.target,policy:result.policy_version,policy_status:result.policy_status,discovery_sha256:run?.discovery_sha256 || 'Not supplied by import',execution:run?.mode || 'Imported'},null,2);
  const genEvidence=clear('generation-evidence');genEvidence.hidden=!run?.generation;
  if(run?.generation){const m=run.generation.metrics;genEvidence.append(node('p','GENERATED CANDIDATES · TRACEABLE ORIGIN','eyebrow'),node('h3',m.selected_count+' selected from '+m.returned_count+' proposals'),node('p',m.accepted_unique_count+' acceptable unique structures. GenMol uses a documented imatinib fragment; selection uses chemical validity and diversity, not DILI or QED ranking.'),node('p','Generated structures are not a labelled evaluation cohort. Synthesis feasibility and DILI generalization remain unestablished.'));const details=node('details');details.append(node('summary','Generation ledger, model provenance and exclusions'),node('pre',JSON.stringify(run.generation,null,2),'data-preview'));genEvidence.append(details);}
  const explain=run?.assistant?.explain, box=clear('explanation-note'); box.hidden=!run?.assistant || run.assistant.status==='off';
  if(explain){box.append(node('p','NVIDIA NEMOTRON INTERPRETATION','eyebrow'),node('h3','Reading the evidence'),node('p',explain.text),node('span','Generated interpretation · Requested '+explain.requested_model+' · Returned '+explain.returned_model+' · Scores and policy above remain authoritative.','small'));}
  else if(run?.assistant?.status!=='off')box.append(node('h3','Nemotron notes unavailable'),node('p','The optional explanation did not complete. The dashboard still shows the validated scientific results and the deterministic follow-up policy.'));
}
function renderRows() {
  if(!report)return; const tbody=clear('candidate-rows'),search=$('candidate-search').value.toLowerCase().trim(),filter=$('candidate-filter').value;
  const rows=sortedRows().filter(r=>r.compound_id.toLowerCase().includes(search)&&(filter==='all'||filter==='shortlisted'&&r.discovery_result.shortlisted||filter==='hold'&&r.follow_up.decision==='hold_for_liver_validation'||filter==='incomplete'&&['safety_assessment_incomplete','discovery_incomplete'].includes(r.follow_up.decision)));
  rows.forEach(r=>{
    const d=r.discovery_result,t=r.toxicity_result,tr=node('tr'),id=node('td'),button=node('button',r.compound_id,'text-button');button.onclick=()=>renderCandidate(r);id.append(button,node('small',d.shortlisted?'Discovery shortlist':d.rank===null?'Unranked':'Outside shortlist'));
    if(moleculeImages[r.compound_id]){const img=node('img',null,'table-molecule');img.src=moleculeImages[r.compound_id];img.alt='Structure of '+r.compound_id;id.prepend(img);}
    const binding=node('td',number(d.mean_binding_probability)); if(d.mean_binding_probability!==null){const meter=node('meter');meter.min=0;meter.max=1;meter.value=d.mean_binding_probability;meter.setAttribute('aria-label','Binder likelihood for '+r.compound_id);binding.append(meter);}
    const confidence=node('td',values(d.structural_confidence));confidence.append(node('small','Boltz-2 returned scores'));
    const dili=node('td',t.status==='ok'?number(t.assessment.risk_score):'Unavailable');dili.append(node('small',concern(t)));if(t.status==='ok'&&t.assessment.risk_score!==null){const meter=node('meter',null,'dili');meter.min=0;meter.max=1;meter.value=t.assessment.risk_score;meter.setAttribute('aria-label','DILI score for '+r.compound_id);dili.append(meter);}
    const follow=node('td');follow.append(node('span',decisions[r.follow_up.decision], 'status-tag'+(r.follow_up.decision==='hold_for_liver_validation'?' hold':'')));
    if(!showDili){dili.replaceChildren(node('small','Hidden in discovery-only view'));follow.replaceChildren(node('span',d.shortlisted?'Follow up target binding':'Retain discovery rank','status-tag'));}
    tr.append(id,node('td',d.rank===null?'—':String(d.rank).padStart(2,'0')),binding,node('td',d.affinity_pic50?.length?values(d.affinity_pic50)+' pIC50':d.affinity_pred_value?.length?values(d.affinity_pred_value)+' model value':'Unavailable'),confidence,dili,follow);tbody.append(tr);
  });$('empty-table').hidden=!!rows.length;
}
function renderCandidate(r) {
  const box=clear('candidate-detail');box.hidden=false;
  const d=r.discovery_result,t=r.toxicity_result,a=t.assessment,heading=node('div',null,'section-heading');heading.append(node('h2',r.compound_id+' · Evidence'),node('span',decisions[r.follow_up.decision],'pill'));box.append(heading);
  if(moleculeImages[r.compound_id]){const img=node('img',null,'detail-molecule');img.src=moleculeImages[r.compound_id];img.alt='Molecular structure of '+r.compound_id;box.append(img);}
  const grid=node('div',null,'detail-grid'),binding=node('div'),dili=node('div'),follow=node('div');
  binding.append(node('p','DISCOVERY EVIDENCE','eyebrow'),node('p',number(d.mean_binding_probability),'big-number'),node('p','Mean predicted binder likelihood'),node('p','All binding predictions: '+values(d.binding_probability)),node('p','Affinity pIC50: '+values(d.affinity_pic50)),node('p','Affinity predicted value: '+values(d.affinity_pred_value)),node('p','Structural confidence: '+values(d.structural_confidence)),node('p','Execution: '+(d.provenance.execution_mode || 'Unavailable')));
  dili.append(node('p','HUMAN DILI EVIDENCE','eyebrow'),node('p',t.status==='ok'?number(a.risk_score):'Unavailable','big-number'),node('p',concern(t)),node('p','Decision threshold: '+number(a.threshold)),node('p','Score kind: '+a.score_kind),node('p','Calibration: '+a.calibration.status),node('p','Training membership: '+t.provenance.training_membership),node('p','Nearest-training similarity: '+number(a.applicability.value)+' (not confidence)'),node('p','Uncertainty: '+a.uncertainty.method));
  follow.append(node('p','RECOMMENDED FOLLOW-UP','eyebrow'),node('h3',decisions[r.follow_up.decision]),node('p',r.follow_up.recommendation));
  if(r.follow_up.experiment){const experiment=r.follow_up.experiment;follow.append(node('p',experiment.question),node('h4',experiment.assay),node('p','Readouts: '+experiment.readouts.join(', ')),node('p',experiment.conditions));}
  grid.append(binding); if(showDili)grid.append(dili,follow);box.append(grid);
  const notes=node('ul',null,'evidence-list');[...d.warnings,...t.warnings].forEach(w=>notes.append(node('li',w)));box.append(notes);
  if(showDili)renderFeatureExplorer(r,box);
  const detail=node('details');detail.append(node('summary','Molecular identity and source evidence'),node('pre',JSON.stringify(r,null,2),'data-preview'));box.append(detail);box.focus({preventScroll:true});box.scrollIntoView({block:'start'});
}
function renderRuns() {
  if(!workspace)return; $('run-count').textContent=workspace.runs.length;const list=clear('runs-list');
  if(!workspace.runs.length)list.append(node('p','Your study runs will appear here. Approved outputs remain in artifacts/web/runs after the server closes.','empty'));
  [...workspace.runs].reverse().forEach(run=>{const card=node('article',null,'panel run-card'),info=node('div');info.append(node('h3',run.research_prompt),node('p',run.job_id.slice(0,8)+' · '+run.candidate_count+' candidates · '+run.status+' · '+new Date(run.created_at).toLocaleString()));const button=node('button','Open study →','secondary');button.onclick=()=>action(button,()=>openRun(run));card.append(info,button);list.append(card);});
}
function saveFile(content,filename,mime) { const blob=new Blob([content],{type:mime}),url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000); }
async function download(kind) { const owner=kind==='discovery'?activeRun:reportRun; if(!owner)throw new Error('report_not_ready');const result=await api('/api/run/download',{job_id:owner.job_id,kind});saveFile(result.content,result.filename,result.mime); }

document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>page(b.dataset.page));
['research-prompt','execution-mode','dataset-format','candidate-content','use-assistant'].forEach(id=>$(id).addEventListener('input',edited));
$('execution-mode').addEventListener('change',()=>{if(workspace)applyAssistantStatus(workspace.assistant);});
$('dataset').onchange=()=>action($('scan-button'),()=>loadDataset($('dataset').files[0]));
$('drop-zone').ondragover=e=>{e.preventDefault();$('drop-zone').classList.add('dragging');};
$('drop-zone').ondragleave=()=> $('drop-zone').classList.remove('dragging');
$('drop-zone').ondrop=e=>{e.preventDefault();$('drop-zone').classList.remove('dragging');action($('scan-button'),()=>loadDataset(e.dataTransfer.files[0]));};
$('example-button').onclick=()=>action($('example-button'),async()=>{const data=await api('/api/example');$('research-prompt').value=data.prompt;$('candidate-content').value=data.content;$('dataset-format').value=data.format;$('file-label').textContent='Public ABL1 panel · 4 candidates';edited();await previewCandidates();});
$('study-form').onsubmit=e=>{e.preventDefault();action($('scan-button'),async()=>{const version=generation;await invalidations;if(version!==generation)return;const result=await api('/api/study/scan',{research_prompt:$('research-prompt').value,content:$('candidate-content').value,format:$('dataset-format').value,mode:$('execution-mode').value,use_assistant:$('use-assistant').checked});if(version===generation)renderReview(result);});};
$('edit-study').onclick=()=>{edited();step('input');};
$('approve-checkbox').onchange=updateApproval;
$('run-button').onclick=()=>action($('run-button'),async()=>{const version=generation,current=scan;if(!current||!$('approve-checkbox').checked)return;await invalidations;await api('/api/approve',{scan_id:current.scan_id,approve:true,retain_fields:[...document.querySelectorAll('#retention-fields input:checked')].map(c=>c.value)});if(version!==generation)return;const run=await api('/api/study/submit',{scan_id:current.scan_id});scan=null;$('research-prompt').value='';$('candidate-content').value='';$('dataset').value='';$('sanitized-preview').textContent='';$('outbound-preview').textContent='';clear('retention-fields');upsertRun(run);await openRun(run);});
$('cancel-button').onclick=()=>action($('cancel-button'),async()=>{const run=await api('/api/run/cancel',{job_id:activeRun.job_id});renderProgress(run);});
$('frozen-download').onclick=()=>action($('frozen-download'),()=>download('discovery'));
$('download-report').onclick=()=>action($('download-report'),async()=>{if(reportRun && reportRun.mode!=='recorded'){activeRun=reportRun;await download('report');}else saveFile(JSON.stringify(report,null,2),'toxoracle-imported-report.json','application/json');});
$('new-study').onclick=()=>{page('workspace');$('study-context').hidden=true;clearTimeout(pollTimer);activeRun=null;scan=null;$('file-label').textContent='Choose a candidate dataset';edited();step('input');window.scrollTo({top:0,behavior:'instant'});};
$('candidate-search').oninput=renderRows;$('candidate-filter').onchange=renderRows;
$('report-file').onchange=()=>action($('report-file'),async()=>{const content=await readFile($('report-file').files[0]);const result=await api('/api/report/inspect',{content});clearTimeout(pollTimer);activeRun=null;page('workspace');renderResults(result.report,null);$('report-file').value='';});
$('inspect-report').onclick=()=>action($('inspect-report'),async()=>{const result=await api('/api/report/inspect',{content:$('report-content').value});clearTimeout(pollTimer);activeRun=null;$('report-content').value='';page('workspace');renderResults(result.report,null);});
$('refresh-setup').onclick=()=>action($('refresh-setup'),refreshWorkspace);
$('verify-assistant').onclick=()=>action($('verify-assistant'),async()=>{const info=await api('/api/assistant/verify');workspace.assistant=info;applyAssistantStatus(info);});
async function boot() {
  try { sid=sessionStorage.getItem('toxoracle-session'); } catch {}
  if(sid){try{await refreshWorkspace();}catch(error){if(error.message==='session_expired')sid=null;else throw error;}}
  if(!sid){const result=await api('/api/session');sid=result.session_id;try{sessionStorage.setItem('toxoracle-session',sid);}catch{}await refreshWorkspace();}
  $('scan-button').disabled=false;
  const running=workspace.runs.find(r=>['running','queued','awaiting_plan'].includes(r.status));if(running)await openRun(running);
}
boot().catch(showError);

function renderMolecules(container, rows) {
  const grid=node('div',null,'molecule-grid');
  rows.forEach(c=>{const card=node('article',null,'molecule-card');if(c.image){const img=node('img');img.src=c.image;img.alt='Molecular structure of '+c.compound_id;card.append(img);}card.append(node('strong',c.compound_id),node('span',c.status==='invalid'?c.error:'Structure parsed locally','small'));grid.append(card);});container.append(grid);
}
async function ensureMolecules(candidates) {
  if(candidates.every(c=>moleculeImages[c.compound_id]))return;
  const result=await api('/api/candidates/preview',{content:JSON.stringify({compounds:candidates}),format:'json'});
  result.candidates.forEach(c=>{if(c.image)moleculeImages[c.compound_id]=c.image;});
}
async function previewCandidates() {
  const version=generation;
  const result=await api('/api/candidates/preview',{content:$('candidate-content').value,format:$('dataset-format').value});
  if(version!==generation)return;
  result.candidates.forEach(c=>{if(c.image)moleculeImages[c.compound_id]=c.image;});
  const box=clear('candidate-preview');renderMolecules(box,result.candidates);
}
function renderLiveCandidates(run) {
  const box=clear('live-candidates');
  (run.candidates||[]).forEach(c=>{const card=node('article',null,'molecule-card');if(moleculeImages[c.compound_id]){const img=node('img');img.src=moleculeImages[c.compound_id];img.alt='Structure of '+c.compound_id;card.append(img);}const done=run.events.findLast(e=>e.stage==='candidate_finished'&&e.compound_id===c.compound_id);const current=run.events.at(-1);let status=done?(done.status==='ok'?'Discovery evidence received':'Discovery incomplete'):current?.compound_id===c.compound_id?'Screening in progress':'Waiting for screening';if(run.shortlist?.includes(c.compound_id))status='Discovery shortlist · saved';card.append(node('strong',c.compound_id),node('span',status,'small'));if(done?.binding_probability?.length)card.append(node('p','Binder likelihood '+number(done.binding_probability.reduce((a,b)=>a+b,0)/done.binding_probability.length),'candidate-score'),node('span','Structural confidence '+values(done.structural_confidence),'small'));box.append(card);});
  if(run.candidates?.some(c=>!moleculeImages[c.compound_id]))ensureMolecules(run.candidates).then(()=>{if(activeRun?.job_id===run.job_id)renderLiveCandidates(activeRun);}).catch(()=>{});
}
function updateEvidenceSwitch() {
  $('discovery-view').setAttribute('aria-pressed',String(!showDili));$('dili-view').setAttribute('aria-pressed',String(showDili));
  $('discovery-view').className=showDili?'secondary':'primary';$('dili-view').className=showDili?'primary':'secondary';
  document.body.classList.toggle('discovery-only',!showDili);
  for(const option of $('candidate-filter').options)if(['hold','incomplete'].includes(option.value))option.disabled=!showDili;
}
$('discovery-view').onclick=()=>{showDili=false;updateEvidenceSwitch();$('candidate-detail').hidden=true;$('candidate-filter').value='all';renderRows();};
$('dili-view').onclick=()=>{showDili=true;updateEvidenceSwitch();$('candidate-detail').hidden=true;$('candidate-filter').value='all';renderRows();};
$('preview-button').onclick=()=>action($('preview-button'),previewCandidates);
$('continue-fixed').onclick=()=>action($('continue-fixed'),async()=>{const run=await api('/api/run/continue',{job_id:activeRun.job_id});await openRun(run);});
$('download-html').onclick=()=>action($('download-html'),()=>download('html'));
const replayNames=['Set up','Review privately','Run discovery','Assess liver concern','Results'];
$('replay-button').onclick=()=>action($('replay-button'),async()=>{replayEvidence=await api('/api/recorded');replayStage=0;page('replay');renderReplay();});
$('close-replay').onclick=()=>{page('workspace');};
$('replay-back').onclick=()=>{replayStage--;renderReplay();};
$('replay-next').onclick=()=>{if(replayStage<4){replayStage++;renderReplay();}else{moleculeImages=Object.fromEntries(replayEvidence.candidates.filter(c=>c.image).map(c=>[c.compound_id,c.image]));page('workspace');renderResults(replayEvidence.report,{job_id:'recorded-abl1',mode:'recorded',status:'complete',assistant:{status:'off'}});}};
function renderReplay(){
  const evidence=replayEvidence,report=evidence.report;
  $('replay-heading').textContent=['A question becomes a study.','Review happens before sharing.','Discovery finds its shortlist.','Human context changes the next step.','One study. Traceable evidence.'][replayStage];
  $('replay-provenance').textContent=evidence.manifest.title+' · '+evidence.manifest.recorded_at+' · '+evidence.manifest.execution_note;
  const steps=clear('replay-steps');replayNames.forEach((name,i)=>{const li=node('li',null,i===replayStage?'current':i<replayStage?'done':'');li.append(node('span',String(i+1).padStart(2,'0')),document.createTextNode(name));steps.append(li);});
  const content=clear('replay-content');
  if(replayStage===0){content.append(node('p','RESEARCH QUESTION','eyebrow'),node('h2','Which ABL1 candidates merit follow-up, and what changes after human DILI?'),node('p','Public reference panel · imatinib, dasatinib, nilotinib and bosutinib.'));renderMolecules(content,evidence.candidates);}
  if(replayStage===1){content.append(node('p','LOCAL PRIVACY BOUNDARY','eyebrow'),node('h2','The researcher controls what leaves the laptop.'),node('p',evidence.manifest.privacy_note),node('p','In a new study, review the filtered question and molecular data, acknowledge each retained scientific field, then approve the exact destinations. This recorded view does not create an approval.'),node('p','Boltz-2: approved structures and ABL1 sequence. Nemotron, when enabled: approved question, IDs and computed evidence.'));}
  if(replayStage===2){content.append(node('p','RECORDED BOLTZ-2 EVIDENCE','eyebrow'),node('h2','The top two are frozen before DILI.'));const grid=node('div',null,'molecule-grid');for(const r of [...report.results].sort((a,b)=>(a.discovery_result.rank??99)-(b.discovery_result.rank??99))){const d=r.discovery_result,card=node('article',null,'molecule-card'+(d.shortlisted?' selected-molecule':'')),img=node('img');img.src=evidence.candidates.find(c=>c.compound_id===r.compound_id).image;img.alt='Structure of '+r.compound_id;card.append(img,node('strong',r.compound_id),node('p','Rank '+d.rank+' · '+number(d.mean_binding_probability),'candidate-score'),node('span',d.shortlisted?'Frozen discovery shortlist':'Outside shortlist','small'));grid.append(card);}content.append(grid);content.append(node('p','These are saved results, not live progress. Ranking uses mean binder likelihood, independently of toxicity.','small'));}
  if(replayStage===3){content.append(node('p','SAME SHORTLIST · ADDITIONAL EVIDENCE','eyebrow'),node('h2','A different next experiment.'));for(const id of report.discovery_shortlist){const r=report.results.find(c=>c.compound_id===id);const card=node('article',null,'replay-decision');card.append(node('p',id+' · Discovery rank '+r.discovery_result.rank,'eyebrow'),node('h3','Target-binding follow-up → '+decisions[r.follow_up.decision]),node('p',concern(r.toxicity_result)+' · '+number(r.toxicity_result.assessment.risk_score)),node('p',r.follow_up.recommendation));content.append(card);}content.append(node('p','The discovery rank stays fixed. Held candidates are not automatically replaced.'));}
  if(replayStage===4){content.append(node('p','READY TO INSPECT','eyebrow'),node('h2','Inspect the evidence behind each decision.'),node('p','Open the candidate table, switch discovery and DILI views, inspect molecular structures, and export the source report.'),node('p','All four public demo compounds overlap fitting or selection. This retrospective example is not an unseen evaluation cohort.','small'));}
  $('replay-back').disabled=replayStage===0;$('replay-next').textContent=replayStage===4?'Explore recorded results →':'Next stage →';$('replay-position').textContent='Recorded stage '+(replayStage+1)+' of 5';
  $('replay-heading').tabIndex=-1;$('replay-heading').focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});
}

$('revise-study').onclick=()=>action($('revise-study'),async()=>{if(activeRun?.status==='awaiting_plan')await api('/api/run/cancel',{job_id:activeRun.job_id});clearTimeout(pollTimer);activeRun=null;edited();$('study-context').hidden=true;step('input');});

function updateRoute(){
  const supplied=!!$('candidate-content').value.trim(),box=clear('route-preview');
  box.append(node('p',supplied?'YOUR CANDIDATES → EVIDENCE':'TARGET → CANDIDATES → EVIDENCE','eyebrow'),node('strong',supplied?'Screen your supplied candidates':'Let the agent propose candidates'),node('p',supplied?'Boltz-2 discovery and local human DILI assessment.':'GenMol generation, Boltz-2 discovery and local human DILI assessment.'));
}
$('target-example').onclick=()=>{$('research-prompt').value='Propose drug candidates for human ABL1 and identify which need liver-safety follow-up.';edited();$('research-prompt').focus();};
$('clear-candidates').onclick=()=>{$('candidate-content').value='';$('dataset').value='';$('file-label').textContent='Choose a candidate dataset';edited();$('candidate-inputs').open=false;};

function resultView(name) {
  if(name!=='explorer' && !showDili){showDili=true;updateEvidenceSwitch();renderRows();$('candidate-detail').hidden=true;}
  ['overview','explorer','discovery','model'].forEach(v=>{$('result-'+v).hidden=v!==name;});
  document.querySelectorAll('[data-result-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.resultView===name)));
}
document.querySelectorAll('[data-result-view]').forEach(b=>b.onclick=()=>resultView(b.dataset.resultView));
function svgNode(tag,attrs={}) { const e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));return e; }
function scoreGraphic(score, threshold) {
  const svg=svgNode('svg',{viewBox:'0 0 400 30',role:'img','aria-label':'DILI score '+number(score)+'; threshold '+number(threshold)});
  svg.append(svgNode('line',{x1:8,x2:392,y1:15,y2:15,stroke:'#e1e6ed','stroke-width':4}));
  if(Number.isFinite(score)){const x=8+384*score;svg.append(svgNode('line',{x1:8,x2:x,y1:15,y2:15,stroke:'#ab8952','stroke-width':4}),svgNode('circle',{cx:x,cy:15,r:5,fill:'#ab8952'}));}
  if(Number.isFinite(threshold)){const x=8+384*threshold;svg.append(svgNode('line',{x1:x,x2:x,y1:4,y2:26,stroke:'#002147','stroke-width':2}));}
  return svg;
}
function renderDashboard(result) {
  const scores=clear('score-overview');scores.append(node('p','HUMAN DILI · ALL CANDIDATES','eyebrow'),node('h3','Concern, in context.'),node('p','Each dot is the candidate’s recorded DILI score. The vertical mark is its own decision threshold. Scores are not patient incidence. Select a candidate to explore its evidence.','field-note'));
  result.results.forEach(r=>{const a=r.toxicity_result.assessment, row=node('button',null,'score-row');row.type='button';row.append(node('span',r.compound_id),scoreGraphic(a.risk_score,a.threshold),node('strong',number(a.risk_score)),node('small',concern(r.toxicity_result)));row.onclick=()=>{resultView('explorer');renderCandidate(r);};scores.append(row);});
  const lab=clear('discovery-lab');lab.append(node('p','DISCOVERY LAB · CURRENT STUDY','eyebrow'),node('h3','Binding evidence before liver concern.'),node('p','Boltz-2 outputs below belong to this study. Predicted structures and confidence do not establish measured binding. Atom correspondence to DILI features is only available when explicitly recorded.'));
  result.results.forEach(r=>{const d=r.discovery_result, details=node('details',null,'discovery-record');details.append(node('summary',r.compound_id+' · '+(d.rank===null?'Unranked':'Rank '+d.rank)+(d.shortlisted?' · Frozen shortlist':'')),node('p','Binder likelihood: '+number(d.mean_binding_probability)+' · Structural confidence: '+values(d.structural_confidence)));
    const artifacts=d.structures || [];
    if(!artifacts.length) details.append(node('p','No structure artifact is recorded.','field-note'));
    artifacts.forEach((a,index)=>{details.append(node('p',(a.format || 'Structure')+' · '+a.origin+' · Atom mapping: '+a.atom_mapping_status),node('p','SHA-256: '+a.sha256,'artifact-checksum'));if(reportRun && reportRun.mode!=='recorded'){const jobId=reportRun.job_id,button=node('button','Download verified structure ↓','secondary');button.onclick=()=>action(button,async()=>{const file=await api('/api/results/structure',{job_id:jobId,compound_id:r.compound_id,index});saveFile(file.content,file.filename,file.mime);});details.append(button);}else details.append(node('p','Structure files are available for runs owned by this session. Imported and recorded reports expose metadata only.','field-note'));});
    details.append(node('pre',JSON.stringify(d,null,2),'data-preview'));lab.append(details);
  });
  const box=clear('model-evaluation');box.append(node('p','MODEL & PROVENANCE','eyebrow'),node('h3','A reference, not a validation of this study.'),node('p','Loading repository evaluation…'));
  api('/api/results/evidence',{report:result,view:'model'}).then(data=>{
    if(report!==result)return;box.replaceChildren(node('p','HELD-OUT DILI BASELINE EVALUATION','eyebrow'),node('h3','Know what the model was tested on.'),node('p',data.matching_method_and_data?'This study reports the baseline method and data version. These retrospective held-out metrics do not measure performance on this study’s candidates.':'This study reports a different method or data version. These reference metrics must not be attributed to its predictions.','notice soft'));
    const m=data.evaluation.random_forest,metrics=node('div',null,'metric-grid');[[m.n,'Test compounds'],[number(m.auroc),'AUROC'],[number(m.average_precision),'Average precision'],[number(m.brier),'Brier score']].forEach(([v,label])=>{const c=node('div',null,'metric');c.append(node('span',label),node('span',v,'value'));metrics.append(c);});box.append(metrics);
    const table=node('table',null,'confusion-table'),caption=node('caption','Reference labels × model calls · held-out test set'),head=node('tr');['Reference label','Lower predicted concern','Elevated predicted concern'].forEach(t=>head.append(node('th',t)));table.append(caption,head);['No DILI concern','Most / Less DILI concern'].forEach((label,i)=>{const tr=node('tr');tr.append(node('th',label),...m.confusion_matrix[i].map(v=>node('td',v)));table.append(tr);});box.append(table,node('p','Fingerprint: '+data.selection.fingerprint+' · Split: '+data.selection.split_kind+' · Training / validation / test: '+['train','validation','test'].map(k=>data.selection.counts[k].n).join(' / ')));
    data.evaluation.limitations.forEach(l=>box.append(node('p',l,'field-note')));const source=node('details');source.append(node('summary','Evaluation source and checksums'),node('pre',JSON.stringify(data.evaluation,null,2),'data-preview'));box.append(source);
  }).catch(()=>{if(report===result)box.replaceChildren(node('h3','Reference evaluation unavailable'),node('p','The current study’s source records and limitations remain available below.'));});
}
function renderFeatureExplorer(r,parent) {
  const result=report, section=node('section',null,'feature-explorer');parent.append(section);
  section.append(node('p','MOLECULE & FEATURES','eyebrow'),node('h3','Inspect the recorded fingerprint evidence.'),node('p','Loading local molecule evidence…'));
  api('/api/results/evidence',{report:result,compound_id:r.compound_id}).then(data=>{
    if(!section.isConnected||report!==result)return;
    section.replaceChildren(node('p','MOLECULE & FEATURES','eyebrow'),node('h3','Inspect the recorded fingerprint evidence.'));
    const e=r.toxicity_result.structural_evidence, controls=node('div',null,'feature-controls'),select=node('select'),label=node('label','Fingerprint feature'),check=node('input'),checkLabel=node('label',null,'check-line'),img=node('img',null,'feature-molecule'),note=node('p',null,'field-note');
    select.setAttribute('aria-label','Fingerprint feature');const none=node('option','Full molecule');none.value='';select.append(none);data.features.forEach(g=>{const opt=node('option',g.source+' · '+(g.contribution===null?'Inconsistent contributions':(g.contribution>=0?'+':'')+g.contribution.toFixed(4)));opt.value=g.source;select.append(opt);});label.append(select);check.type='checkbox';checkLabel.append(check,node('span','Show atom-map IDs'));controls.append(label,checkLabel);section.append(controls);
    img.alt='Mapped molecule evidence for '+r.compound_id;img.hidden=!data.image;if(data.image)img.src=data.image;section.append(img,note);
    const chart=node('div',null,'feature-bars');data.features.filter(g=>g.contribution!==null).slice(0,10).forEach(g=>{const button=node('button',null,'feature-bar');button.type='button';const svg=svgNode('svg',{viewBox:'0 0 300 22','aria-hidden':'true'}),max=Math.max(...data.features.map(f=>Math.abs(f.contribution || 0)),0.0001),w=Math.abs(g.contribution)/max*140;svg.append(svgNode('line',{x1:150,x2:150,y1:0,y2:22,stroke:'#a7b7cb'}),svgNode('rect',{x:g.contribution<0?150-w:150,y:4,width:w,height:14,rx:2,fill:g.contribution>0?'#b17b64':'#002147'}));button.append(node('span',g.source.replace('Morgan_bit_','Feature ')),svg,node('span',(g.contribution>=0?'+':'')+g.contribution.toFixed(4)));button.onclick=()=>{select.value=g.source;update();};chart.append(button);});section.append(chart);
    section.append(node('p','Attribution: '+e.attribution_status+' · '+e.attribution_method+' · Target: '+e.attribution_target+' · Scale: '+e.attribution_scale,'field-note'),node('p','Recorded feature contributions support hypotheses, not causal proof. They explain the recorded attribution target and do not sum to the calibrated DILI score. Hashed features may map to multiple molecular environments.','field-note'));
    if(!data.features.length)section.append(node('p','No mapped feature contributions are supplied for this candidate.'));
    let revision=0;
    async function update(){const current=++revision,g=data.features.find(f=>f.source===select.value);note.textContent=g?(g.ambiguous?'Ambiguous hashed feature: all supplied matching environments are highlighted. ':'Mapped environment. ')+g.atom_map_ids.length+' recorded atom-map IDs.':'';try{const next=await api('/api/results/evidence',{report:result,compound_id:r.compound_id,source:select.value || null,labels:check.checked});if(current!==revision||!section.isConnected||report!==result)return;img.hidden=!next.image;if(next.image)img.src=next.image;}catch{if(current===revision){img.hidden=true;note.textContent='Mapped evidence could not be drawn. Inspect the source record below.';}}}
    select.onchange=update;check.onchange=update;
  }).catch(()=>{if(section.isConnected)section.replaceChildren(node('p','Mapped molecule evidence is unavailable. Inspect the source record below.'));});
}
