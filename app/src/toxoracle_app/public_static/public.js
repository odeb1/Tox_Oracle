'use strict';
const $=id=>document.getElementById(id);
let report=null,reportRun=null,pollTimer=null,moleculeImages={},showDili=true;
let resultsSource=null,study=null,replay=null,timer=null,loadRevision=0,renderedStudy=null;
const studyNavigation={selected:true}; // Shared renderer host: public navigation is owned here.
const names=['Set up','Review privately','Run discovery','Assess toxicity concern','Results'];
const stageNames={planning:'Nemotron · interpreting the approved question',preparing:'Preparing molecular identities locally',reference:'Boltz-2 · checking the imatinib reference',reference_finished:'Reference check finished',generating:'GenMol · proposing molecules',selecting:'Selecting valid, diverse proposals',candidates_ready:'Generated candidates ready',screening:'Boltz-2 · screening binding',candidate_finished:'Candidate discovery finished',shortlist_frozen:'Discovery shortlist selected',toxicity:'Local DILI · assessing human liver concern',reporting:'Assembling the scientific report',explaining:'Nemotron · interpreting the results'};
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined&&text!==null)e.textContent=String(text);if(cls)e.className=cls;return e;}
function clear(id){$(id).replaceChildren();return $(id);}
function timeLabel(value){return new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function showError(error){$('notice').textContent=error.message||'The saved study could not be loaded.';$('notice').hidden=false;}
async function action(button,operation){$('notice').hidden=true;button.disabled=true;try{await operation();}catch(e){showError(e);}finally{button.disabled=false;}}
function saveFile(content,filename,mime){const url=URL.createObjectURL(new Blob([content],{type:mime})),a=node('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function step(){} // renderResults cannot execute or advance a public recording.
function renderStep(){}
function persist(){try{localStorage.setItem('toxoracle-public-v1',JSON.stringify({...replay.snapshot(),example:resultsSource.slug}));}catch{}}
function page(name){
  if(name!=='workspace'&&replay){replay.playing=false;clearTimeout(timer);}
  ['workspace','results','runs','methods'].forEach(p=>$(p+'-page').hidden=p!==name);
  document.querySelectorAll('[data-page]').forEach(b=>{b.classList.toggle('active',b.dataset.page===name);if(b.dataset.page===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  if(name==='results'&&study){replay.advance(study.run.events.length);replay.selected=4;replay.playing=false;showResults();persist();}
  window.scrollTo({top:0,behavior:'instant'});
}
function showResults(){if(renderedStudy!==study){renderedStudy=study;renderResults(study.report,{...study.run,mode:'recorded'});$('results-meta').textContent=study.run.research_prompt+' · '+study.report.target.target_id+' · Original live run '+study.run.job_id.slice(0,8)+' · Recorded '+new Date(study.run.created_at).toLocaleDateString();$('download-html').hidden=false;}}
async function choose(slug,saved={}) {
  const revision=++loadRevision;clearTimeout(timer);if(replay)replay.playing=false;
  $('start').disabled=true;$('explore').disabled=true;$('loading-study').hidden=false;$('reset').disabled=true;$('notice').hidden=true;disposePoseViewers();
  const source=new StaticStudySource(slug),loaded=await source.load();if(revision!==loadRevision)return;
  resultsSource=source;study=loaded;replay=new ReplayState(study.run.events,saved);report=null;reportRun=null;moleculeImages={};renderedStudy=null;
  $('research-prompt').value=study.run.research_prompt;$('candidate-content').value='';$('dataset').value='';$('dataset-note').textContent='';
  if(slug==='supplied'){$('candidate-content').value=await source.text('example.csv');$('optional-data').open=true;}
  renderWorkflowRouting(slug,true);
  $('review-pathway').textContent='Reviewed public inputs went to NVIDIA Nemotron for planning. '+(slug==='generated'?'GenMol proposed molecules, then Boltz-2 screened them against the prepared ABL1 domain.':'Boltz-2 screened the supplied candidates against the prepared ABL1 domain; no molecule generation was needed.')+' Human DILI inference ran locally. Nemotron interpreted the final evidence.';
  $('route-label').textContent=slug==='generated'?'TARGET → CANDIDATES → EVIDENCE':'YOUR CANDIDATES → DISCOVERY → EVIDENCE';
  $('route-title').textContent=slug==='generated'?'Agent pathway: generate and evaluate':'Agent pathway: evaluate supplied candidates';
  $('route-copy').textContent=slug==='generated'?'Recorded Nemotron plan → GenMol → Boltz-2 → local DILI assessment.':'Recorded Nemotron plan → Boltz-2 → local DILI assessment. Uses the four supplied ABL1 candidates.';
  $('example-summary').textContent=slug==='generated'?'20 generated candidates. 18 successful discovery results. Two shortlisted candidates held for liver validation.':'Four familiar ABL1 drugs. See how liver concern changes the next experiment.';
  $('start').disabled=false;$('explore').disabled=false;$('loading-study').hidden=true;$('reset').disabled=false;
  page('workspace');renderWorkspace();persist();
  if(replay.count>0&&replay.selected<4){const current=study;ensureMolecules(study.report.results).then(()=>{if(study===current&&[2,3].includes(replay.selected))renderPlayback();}).catch(showError);}
}
function renderWorkspace(){
  const selected=replay.selected;
  document.querySelectorAll('[data-stage]').forEach(b=>{const n=Number(b.dataset.stage);b.disabled=n>replay.reached;b.parentElement.classList.toggle('current',n===selected);b.parentElement.classList.toggle('complete',n<replay.reached);b.setAttribute('aria-current',n===selected?'step':'false');});
  $('position').textContent='Step '+(selected+1)+' of 5 · '+names[selected];$('previous').disabled=selected===0;$('next').disabled=selected>=replay.reached;
  $('input-section').hidden=selected!==0;$('review-section').hidden=selected!==1;$('progress-section').hidden=![2,3].includes(selected);
  $('study-context').hidden=true;
  $('workflow-routing-panel').hidden=selected!==2;
  if(selected===1){clear('review-readable').append(node('h3',study.review.research_prompt),node('p',resultsSource.slug==='generated'?'Target-only request · 20 proposals · prepared human ABL1 domain':'Supplied dataset · 4 compounds · prepared human ABL1 domain'));renderSavedReview($('review-audit'),study);}
  if([2,3].includes(selected))renderPlayback();
  if(selected===4)page('results');persist();
}
function renderPlayback(){
  // Viewing step 3 after step 4 shows the discovery history, not later toxicity events.
  const boundary=study.run.events.findIndex(e=>e.stage==='toxicity');
  const count=replay.selected===2&&boundary>=0?Math.min(replay.count,boundary):replay.count;
  const events=study.run.events.slice(0,count),last=events.at(-1);
  $('toxicity-endpoint').hidden=replay.selected!==3;
  $('progress-heading').textContent=replay.selected===3?'Human context changes the follow-up.':'From a question to a discovery shortlist.';
  $('progress-message').textContent=(last?stageNames[last.stage]||last.stage:'Ready to replay the saved workflow')+' · '+count+' / '+study.run.events.length+' recorded events';
  $('replay-progress').max=study.run.events.length;$('replay-progress').value=count;$('pause').textContent=replay.playing?'Pause':'Resume';$('pause').disabled=replay.count===study.run.events.length;
  const duration=(new Date(study.run.finished_at)-new Date(study.run.created_at))/60000;
  $('original-time').textContent='Original live run: '+new Date(study.run.created_at).toLocaleString()+' · '+duration.toFixed(1)+' minutes. Playback timing is compressed; event times below are original.';
  const planning=clear('planning-note');if(count>1&&study.run.assistant?.plan)planning.append(node('p','NVIDIA NEMOTRON · RECORDED PLAN','eyebrow'),node('p',study.run.assistant.plan.text),node('span',study.run.assistant.plan.returned_model,'small'));
  const frozen=clear('frozen-card');frozen.append(node('p','DISCOVERY SHORTLIST','eyebrow'));
  if(events.some(e=>e.stage==='shortlist_frozen')){frozen.append(node('h3','Selected before toxicity assessment'),node('p',study.report.discovery_shortlist.join(' · ')));if(replay.selected===3)frozen.append(node('p','The separate DILI model adds human liver concern. Held candidates stay on the shortlist; no replacements are generated.'));}
  else frozen.append(node('h3','Waiting for discovery evidence'),node('p','Candidates are ranked using binding predictions alone.'));
  const log=clear('event-log');events.forEach(e=>log.append(node('li',timeLabel(e.at)+' · '+(stageNames[e.stage]||e.stage)+(e.compound_id?' · '+e.compound_id:'')+(e.status?' · '+e.status:'')+(e.batch?' · batch '+e.batch:''))));
  const grid=clear('live-candidates');
  if(resultsSource.slug==='supplied'||events.some(e=>e.stage==='candidates_ready'))study.run.candidates.forEach(c=>{const card=node('article',null,'molecule-card'),done=events.find(e=>e.stage==='candidate_finished'&&e.compound_id===c.compound_id);if(moleculeImages[c.compound_id]){const img=node('img');img.src=moleculeImages[c.compound_id];img.alt='Structure of '+c.compound_id;card.append(img);}card.append(node('strong',c.compound_id),node('span',done?(done.status==='ok'?'Discovery evidence received':'Discovery incomplete'):last?.compound_id===c.compound_id?'Screening in recorded run':'Waiting in recorded run','small'));grid.append(card);});
}
function tick(){clearTimeout(timer);if(!replay.playing)return;timer=setTimeout(()=>{replay.advance();renderWorkspace();tick();},45000/study.run.events.length);}
function startPlayback(){if(replay.count===study.run.events.length){page('results');return;}replay.reached=Math.max(2,replay.reached);replay.selected=2;replay.playing=true;renderWorkspace();tick();const current=study;ensureMolecules(study.report.results).then(()=>{if(study===current&&[2,3].includes(replay.selected))renderPlayback();}).catch(showError);}
async function validateInputs(){
  if($('research-prompt').value.trim()!==study.run.research_prompt)throw new Error('This question is different from the recording. Choose “Use recorded question” to explore its evidence. New questions require the local app.');
  const content=$('candidate-content').value.trim();
  if(resultsSource.slug==='generated'&&content)throw new Error('To explore supplied candidates, choose “Use example dataset”. The generated recording starts without a dataset.');
  if(resultsSource.slug==='supplied'&&!panelMatches(content,study.report.results))throw new Error('This dataset does not match the recorded panel. Choose “Use example dataset” to load its exact compound IDs and SMILES. New candidates require the local app.');
}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{if(!study)return;if(b.dataset.page==='workspace'){if(replay.selected===4)replay.select(3);page('workspace');renderWorkspace();}else page(b.dataset.page);});
document.querySelectorAll('[data-stage]').forEach(b=>b.onclick=()=>{if(!replay)return;replay.select(Number(b.dataset.stage));renderWorkspace();});
$('previous').onclick=()=>{replay.select(replay.selected-1);renderWorkspace();};$('next').onclick=()=>{replay.select(replay.selected+1);renderWorkspace();};
$('reset').onclick=()=>action($('reset'),async()=>{try{localStorage.removeItem('toxoracle-public-v1');}catch{}await choose(resultsSource.slug);});
$('study-form').onsubmit=e=>{e.preventDefault();action($('start'),async()=>{await validateInputs();replay.reached=Math.max(1,replay.reached);replay.selected=1;renderWorkspace();});};
$('use-example').onclick=()=>{$('research-prompt').value=study.run.research_prompt;$('notice').hidden=true;};
$('example-panel').onclick=()=>action($('example-panel'),()=>choose('supplied'));
$('generate-instead').onclick=()=>action($('generate-instead'),()=>choose('generated'));
$('dataset').onchange=()=>action($('start'),async()=>{const f=$('dataset').files[0];if(!f)return;if(f.size>1000000)throw new Error('Choose a file smaller than 1 MB.');const content=await f.text();const source=resultsSource.slug==='supplied'?resultsSource:new StaticStudySource('supplied');if(!source.study)await source.load();if(!panelMatches(content,source.study.report.results))throw new Error('This file does not match the recorded panel. Use the downloadable example CSV. No data was uploaded.');if(resultsSource.slug!=='supplied')await choose('supplied');$('candidate-content').value=content;$('dataset-note').textContent='Exact public panel verified in this browser. No upload occurred.';});
$('continue').onclick=startPlayback;$('pause').onclick=()=>{replay.playing=!replay.playing;renderWorkspace();tick();};
$('next-stage').onclick=()=>{replay.nextStage();renderWorkspace();tick();};
$('skip').onclick=()=>page('results');$('explore').onclick=()=>action($('explore'),async()=>{await validateInputs();page('results');});
$('download-report').onclick=()=>action($('download-report'),async()=>saveFile(await resultsSource.text('report.json'),'toxoracle-'+resultsSource.slug+'.json','application/json'));
$('download-html').onclick=()=>action($('download-html'),async()=>saveFile(await resultsSource.text('report.html'),'toxoracle-'+resultsSource.slug+'.html','text/html'));
$('new-study').textContent='Back to walkthrough';$('new-study').onclick=()=>{replay.select(0);page('workspace');renderWorkspace();};
$('candidate-search').oninput=renderRows;$('candidate-filter').onchange=renderRows;
document.querySelectorAll('[data-result-view]').forEach(b=>b.onclick=()=>resultView(b.dataset.resultView));
$('discovery-view').onclick=()=>{showDili=false;updateEvidenceSwitch();$('candidate-detail').hidden=true;$('candidate-filter').value='all';renderRows();};
$('dili-view').onclick=()=>{showDili=true;updateEvidenceSwitch();$('candidate-detail').hidden=true;renderRows();};
for(const [slug,title,copy] of [['generated','Start with a target','20 generated candidates · 18 successful discovery results · 2 held shortlist candidates'],['supplied','Bring your candidates','4 supplied ABL1 drugs · complete discovery · training overlap disclosed']]){const card=node('article',null,'panel');card.append(node('p',slug==='generated'?'MAIN DEMONSTRATION':'SUPPLIED-PANEL EXAMPLE','eyebrow'),node('h2',title),node('p',copy));const button=node('button','Explore this study →','primary');button.onclick=()=>action(button,()=>choose(slug));card.append(button);$('examples').append(card);}
async function boot(){let saved={};try{const value=JSON.parse(localStorage.getItem('toxoracle-public-v1'));if(value?.version===1)saved=value;}catch{}const params=new URLSearchParams(location.search),example=params.get('example');if(['generated','supplied'].includes(example)){saved={};await choose(example);if(params.get('stage')==='results')page('results');history.replaceState(null,'',location.pathname);}else await choose(['generated','supplied'].includes(saved.example)?saved.example:'generated',saved);}
boot().catch(showError);
