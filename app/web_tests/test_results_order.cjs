const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=readFileSync(path.join(__dirname,'../src/toxoracle_app/web_static/results-view.js'),'utf8');

// Exercise rendered order and candidate callbacks without a browser dependency.
function node(tag,text,cls){
 return {tag,textContent:text==null?'':String(text),className:cls,children:[],attributes:{},
  append(...children){this.children.push(...children);},
  replaceChildren(...children){this.children=children;},
  setAttribute(key,value){this.attributes[key]=String(value);}};
}
async function checkRecording(slug,mode){
 const study=JSON.parse(readFileSync(path.join(__dirname,'../../demo/public/studies',slug,'study.json')));
 const before=JSON.stringify(study.report),elements=new Map(),poses=[],downloads=[],requests=[];
 const $=id=>{if(!elements.has(id))elements.set(id,node('div'));return elements.get(id);};
 const tabs=['overview','explorer','discovery','model'].map(view=>Object.assign(node('button'),{dataset:{resultView:view}}));
 const context=vm.createContext({node,$,clear:id=>{$(id).replaceChildren();return $(id);},
  document:{createElementNS:(_,tag)=>node(tag),querySelectorAll:()=>tabs},
  report:study.report,reportRun:{...study.run,mode},showDili:true,
  disposePoseViewers(){},attachPoseViewer(parent,row){poses.push({parent,row});},
  action:async(_,operation)=>operation(),saveFile:(...args)=>downloads.push(args),
  resultsSource:{kind:mode==='recorded'?'static':'local',
   evidence:async()=>study.model,
   structure:async options=>{requests.push(options);return {content:options.compound_id,filename:options.compound_id+'.cif',mime:'chemical/x-mmcif'};}}
 });
 vm.runInContext(source,context);
 context.renderDashboard(study.report);
 await Promise.resolve();
 const rows=$('score-overview').children.filter(e=>e.className==='score-row');
 assert.equal(rows.length,study.report.results.length);
 const byId=new Map(study.report.results.map(row=>[row.compound_id,row]));
 const displayedScores=rows.map(row=>byId.get(row.children[0].textContent).toxicity_result.assessment.risk_score);
 assert.deepEqual(displayedScores,[...displayedScores].sort((a,b)=>b-a));
 assert.equal(rows[0].children[0].textContent,slug==='generated'?'GEN_5ed5d81af9b0d30b4d08d4a8':'LT00107');
 let selected=null;context.renderCandidate=row=>{selected=row;};
 for(const row of rows){
  row.onclick();
  const expected=byId.get(row.children[0].textContent);
  assert.strictEqual(selected,expected,'Reordering must preserve the clicked candidate');
  assert.equal(row.children[2].textContent,expected.toxicity_result.assessment.risk_score.toFixed(3));
  assert.equal($('result-explorer').hidden,false);
 }
 context.resultView('discovery');
 assert.equal($('result-discovery').hidden,false);
 assert.equal($('result-explorer').hidden,true);
 const records=$('discovery-lab').children.filter(e=>e.className==='discovery-record');
 const ids=records.map(e=>e.children[0].textContent.split(' · ')[0]);
 assert.equal(new Set(ids).size,study.report.results.length);
 assert.deepEqual(ids.map(id=>byId.get(id).discovery_result.rank),slug==='generated'?[...Array.from({length:18},(_,i)=>i+1),null,null]:[1,2,3,4]);
 for(const record of records){
  const id=record.children[0].textContent.split(' · ')[0],candidate=byId.get(id);
  const buttons=record.children.filter(e=>e.tag==='button');
  assert.equal(buttons.length,candidate.discovery_result.structures.length);
  for(const button of buttons){await button.onclick();assert.equal(requests.at(-1).compound_id,id);assert.equal(downloads.at(-1)[0],id);}
  if(buttons.length)assert.strictEqual(poses.find(p=>p.parent===record).row,candidate);
 }
 assert.equal(JSON.stringify(study.report),before,'Rendering must not change scores, ranks, shortlist or source order');
 return context;
}
async function main(){
 let context;
 for(const slug of ['generated','supplied'])for(const mode of ['recorded','live'])context=await checkRecording(slug,mode);
 const candidate=(id,score,rank,status='ok')=>({compound_id:id,discovery_result:{rank},toxicity_result:{status,assessment:{risk_score:score}}});
 const edgeCases=[candidate('missing',null,null),candidate('zero',0,3),candidate('tie-first',0.8,2),candidate('tie-second',0.8,1),candidate('failed',null,null,'failed'),candidate('absent',undefined,undefined)];
 const original=edgeCases.slice();
 const ids=rows=>Array.from(rows,row=>row.compound_id);
 assert.deepEqual(ids(context.sortedDiliRows(edgeCases)),['tie-first','tie-second','zero','missing','failed','absent']);
 assert.deepEqual(ids(context.sortedRows(edgeCases)),['tie-second','tie-first','zero','missing','failed','absent']);
 assert.deepEqual(edgeCases,original);
 assert.deepEqual(ids(context.sortedDiliRows([])),[]);
 assert.deepEqual(ids(context.sortedRows([])),[]);
 console.log('Results ordering: both recordings and shared hosts; descending DILI scores, ascending ranks, unavailable rows, stable ties, candidate navigation, pose/download identity and immutable evidence passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
