'use strict';
// Shared presentation; evidence is supplied by the host entry point.
function number(value, digits=3) { return typeof value==='number' && Number.isFinite(value) ? value.toFixed(digits) : 'Unavailable'; }
function values(items) { return Array.isArray(items)&&items.length ? items.map(n=>number(n)).join(', ') : 'Unavailable'; }
const decisions = {hold_for_liver_validation:'Liver validation first',continue_target_validation:'Continue target validation',not_shortlisted:'Retain discovery rank',safety_assessment_incomplete:'DILI evidence incomplete',discovery_incomplete:'Discovery incomplete'};
function concern(t) { return t.status!=='ok'?'Unavailable':t.assessment.call==='positive'?'Elevated predicted concern':t.assessment.call==='negative'?'Lower predicted concern':'Unavailable'; }
function sortedRows() { return [...report.results].sort((a,b)=>(a.discovery_result.rank??Infinity)-(b.discovery_result.rank??Infinity)); }
function renderResults(result, run) {
  report=result; reportRun=run; showDili=true;window.scrollTo({top:0,behavior:'instant'});
  $('study-context').hidden=false;$('study-context').textContent=run?.mode==='recorded'?'Recorded public ABL1 study · No inference or new approval':run?.research_prompt || 'Imported study · locally validated'; updateEvidenceSwitch();
  $('download-html').hidden=!run || run.mode==='recorded';
  clearTimeout(pollTimer); step('results'); $('results-section').hidden=false; $('results-empty').hidden=true; if(!studyNavigation.selected)page('results'); resultView('overview'); renderDashboard(result);renderStep();
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

function resultView(name) {
  if(name!=='explorer' && !showDili){showDili=true;updateEvidenceSwitch();renderRows();$('candidate-detail').hidden=true;}
  ['overview','explorer','discovery','model'].forEach(v=>{$('result-'+v).hidden=v!==name;});
  document.querySelectorAll('[data-result-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.resultView===name)));
}

function svgNode(tag,attrs={}) { const e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));return e; }
function scoreGraphic(score, threshold) {
  const svg=svgNode('svg',{viewBox:'0 0 400 30',role:'img','aria-label':'DILI score '+number(score)+'; threshold '+number(threshold)});
  svg.append(svgNode('line',{x1:8,x2:392,y1:15,y2:15,stroke:'#e1e6ed','stroke-width':4}));
  if(Number.isFinite(score)){const x=8+384*score;svg.append(svgNode('line',{x1:8,x2:x,y1:15,y2:15,stroke:'#ab8952','stroke-width':4}),svgNode('circle',{cx:x,cy:15,r:5,fill:'#ab8952'}));}
  if(Number.isFinite(threshold)){const x=8+384*threshold;svg.append(svgNode('line',{x1:x,x2:x,y1:4,y2:26,stroke:'#002147','stroke-width':2}));}
  return svg;
}
function renderDashboard(result) {
  disposePoseViewers();
  const scores=clear('score-overview');scores.append(node('p','HUMAN DILI · ALL CANDIDATES','eyebrow'),node('h3','Concern, in context.'),node('p','Each dot is the candidate’s recorded DILI score. The vertical mark is its own decision threshold. Scores are not patient incidence. Select a candidate to explore its evidence.','field-note'));
  result.results.forEach(r=>{const a=r.toxicity_result.assessment, row=node('button',null,'score-row');row.type='button';row.append(node('span',r.compound_id),scoreGraphic(a.risk_score,a.threshold),node('strong',number(a.risk_score)),node('small',concern(r.toxicity_result)));row.onclick=()=>{resultView('explorer');renderCandidate(r);};scores.append(row);});
  const lab=clear('discovery-lab');lab.append(node('p','DISCOVERY LAB · CURRENT STUDY','eyebrow'),node('h3','Binding evidence before liver concern.'),node('p','Expand a candidate below and choose View 3D pose to inspect the predicted ligand inside its protein target.','field-note'),node('p','Boltz-2 outputs below belong to this study. Predicted structures and confidence do not establish measured binding. Atom correspondence to DILI features is only available when explicitly recorded.'));
  result.results.forEach(r=>{const d=r.discovery_result, details=node('details',null,'discovery-record');details.append(node('summary',r.compound_id+' · '+(d.rank===null?'Unranked':'Rank '+d.rank)+(d.shortlisted?' · Frozen shortlist':'')),node('p','Binder likelihood: '+number(d.mean_binding_probability)+' · Structural confidence: '+values(d.structural_confidence)));
    const artifacts=d.structures || [];
    if(!artifacts.length) details.append(node('p','No structure artifact is recorded.','field-note'));
    artifacts.forEach((a,index)=>{details.append(node('p',(a.format || 'Structure')+' · '+a.origin+' · Atom mapping: '+a.atom_mapping_status),node('p','SHA-256: '+a.sha256,'artifact-checksum'));if(reportRun && (reportRun.mode!=='recorded'||resultsSource.kind==='static')){const jobId=reportRun.job_id,button=node('button','Download verified structure ↓','secondary');button.onclick=()=>action(button,async()=>{const file=await resultsSource.structure({job_id:jobId,compound_id:r.compound_id,index});saveFile(file.content,file.filename,file.mime);});details.append(button);}else details.append(node('p','Owned runs and the verified public recording can load saved coordinates. Imported reports require a matching local structure file.','field-note'));});
    if(artifacts.length)attachPoseViewer(details,r,reportRun);
    const raw=node('details');raw.append(node('summary','Discovery source record'),node('pre',JSON.stringify(d,null,2),'data-preview'));details.append(raw);lab.append(details);
  });
  const box=clear('model-evaluation');box.append(node('p','MODEL & PROVENANCE','eyebrow'),node('h3','A reference, not a validation of this study.'),node('p','Loading repository evaluation…'));
  resultsSource.evidence({report:result,view:'model'}).then(data=>{
    if(report!==result)return;box.replaceChildren(node('p','HELD-OUT DILI BASELINE EVALUATION','eyebrow'),node('h3','Know what the model was tested on.'),node('p',data.matching_method_and_data?'This study reports the baseline method and data version. These retrospective held-out metrics do not measure performance on this study’s candidates.':'This study reports a different method or data version. These reference metrics must not be attributed to its predictions.','notice soft'));
    const m=data.evaluation.random_forest,metrics=node('div',null,'metric-grid');[[m.n,'Test compounds'],[number(m.auroc),'AUROC'],[number(m.average_precision),'Average precision'],[number(m.brier),'Brier score']].forEach(([v,label])=>{const c=node('div',null,'metric');c.append(node('span',label),node('span',v,'value'));metrics.append(c);});box.append(metrics);
    const table=node('table',null,'confusion-table'),caption=node('caption','Reference labels × model calls · held-out test set'),head=node('tr');['Reference label','Lower predicted concern','Elevated predicted concern'].forEach(t=>head.append(node('th',t)));table.append(caption,head);['No DILI concern','Most / Less DILI concern'].forEach((label,i)=>{const tr=node('tr');tr.append(node('th',label),...m.confusion_matrix[i].map(v=>node('td',v)));table.append(tr);});box.append(table,node('p','Fingerprint: '+data.selection.fingerprint+' · Split: '+data.selection.split_kind+' · Training / validation / test: '+['train','validation','test'].map(k=>data.selection.counts[k].n).join(' / ')));
    data.evaluation.limitations.forEach(l=>box.append(node('p',l,'field-note')));const source=node('details');source.append(node('summary','Evaluation source and checksums'),node('pre',JSON.stringify(data.evaluation,null,2),'data-preview'));box.append(source);
  }).catch(()=>{if(report===result)box.replaceChildren(node('h3','Reference evaluation unavailable'),node('p','The current study’s source records and limitations remain available below.'));});
}
function renderFeatureExplorer(r,parent) {
  const result=report, section=node('section',null,'feature-explorer');parent.append(section);
  section.append(node('p','MOLECULE & FEATURES','eyebrow'),node('h3','Inspect the recorded fingerprint evidence.'),node('p','Loading local molecule evidence…'));
  resultsSource.evidence({report:result,compound_id:r.compound_id}).then(data=>{
    if(!section.isConnected||report!==result)return;
    section.replaceChildren(node('p','MOLECULE & FEATURES','eyebrow'),node('h3','Inspect the recorded fingerprint evidence.'));
    const e=r.toxicity_result.structural_evidence, controls=node('div',null,'feature-controls'),select=node('select'),label=node('label','Fingerprint feature'),check=node('input'),checkLabel=node('label',null,'check-line'),img=node('img',null,'feature-molecule'),note=node('p',null,'field-note');
    select.setAttribute('aria-label','Fingerprint feature');const none=node('option','Full molecule');none.value='';select.append(none);data.features.forEach(g=>{const opt=node('option',g.source+' · '+(g.contribution===null?'Inconsistent contributions':(g.contribution>=0?'+':'')+g.contribution.toFixed(4)));opt.value=g.source;select.append(opt);});label.append(select);check.type='checkbox';checkLabel.append(check,node('span','Show atom-map IDs'));controls.append(label,checkLabel);section.append(controls);
    img.alt='Mapped molecule evidence for '+r.compound_id;img.hidden=!data.image;if(data.image)img.src=data.image;section.append(img,note);
    const chart=node('div',null,'feature-bars');data.features.filter(g=>g.contribution!==null).slice(0,10).forEach(g=>{const button=node('button',null,'feature-bar');button.type='button';const svg=svgNode('svg',{viewBox:'0 0 300 22','aria-hidden':'true'}),max=Math.max(...data.features.map(f=>Math.abs(f.contribution || 0)),0.0001),w=Math.abs(g.contribution)/max*140;svg.append(svgNode('line',{x1:150,x2:150,y1:0,y2:22,stroke:'#a7b7cb'}),svgNode('rect',{x:g.contribution<0?150-w:150,y:4,width:w,height:14,rx:2,fill:g.contribution>0?'#b17b64':'#002147'}));button.append(node('span',g.source.replace('Morgan_bit_','Feature ')),svg,node('span',(g.contribution>=0?'+':'')+g.contribution.toFixed(4)));button.onclick=()=>{select.value=g.source;update();};chart.append(button);});section.append(chart);
    section.append(node('p','Attribution: '+e.attribution_status+' · '+e.attribution_method+' · Target: '+e.attribution_target+' · Scale: '+e.attribution_scale,'field-note'),node('p','Recorded feature contributions support hypotheses, not causal proof. They explain the recorded attribution target and do not sum to the calibrated DILI score. Hashed features may map to multiple molecular environments.','field-note'));
    if(!data.features.length)section.append(node('p','No mapped feature contributions are supplied for this candidate.'));
    let revision=0;
    async function update(){const current=++revision,g=data.features.find(f=>f.source===select.value);note.textContent=g?(g.ambiguous?'Ambiguous hashed feature: all supplied matching environments are highlighted. ':'Mapped environment. ')+g.atom_map_ids.length+' recorded atom-map IDs.':'';try{const next=await resultsSource.evidence({report:result,compound_id:r.compound_id,source:select.value || null,labels:check.checked});if(current!==revision||!section.isConnected||report!==result)return;img.hidden=!next.image;if(next.image)img.src=next.image;}catch{if(current===revision){img.hidden=true;note.textContent='Mapped evidence could not be drawn. Inspect the source record below.';}}}
    select.onchange=update;check.onchange=update;
  }).catch(()=>{if(section.isConnected)section.replaceChildren(node('p','Mapped molecule evidence is unavailable. Inspect the source record below.'));});
}

async function ensureMolecules(candidates) {
  if(candidates.every(c=>moleculeImages[c.compound_id]))return;
  const result=await resultsSource.preview(candidates);
  result.candidates.forEach(c=>{if(c.image)moleculeImages[c.compound_id]=c.image;});
}

function updateEvidenceSwitch() {
  $('discovery-view').setAttribute('aria-pressed',String(!showDili));$('dili-view').setAttribute('aria-pressed',String(showDili));
  $('discovery-view').className=showDili?'secondary':'primary';$('dili-view').className=showDili?'primary':'secondary';
  document.body.classList.toggle('discovery-only',!showDili);
  for(const option of $('candidate-filter').options)if(['hold','incomplete'].includes(option.value))option.disabled=!showDili;
}
