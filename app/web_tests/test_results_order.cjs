const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const context=vm.createContext({});
vm.runInContext(readFileSync('app/src/toxoracle_app/web_static/results-view.js','utf8'),context);
const sort=context.sortCandidateRows;
const row=(id,rank,binding,risk,discoveryStatus='ok',toxicityStatus='ok')=>({compound_id:id,discovery_result:{rank,mean_binding_probability:binding,status:discoveryStatus},toxicity_result:{status:toxicityStatus,assessment:{risk_score:risk}}});
const rows=[row('C10',null,null,null,'failed','failed'),row('C2',2,.8,.9),row('C1',1,.9,.9),row('C3',3,.1,0),row('C4',4,0,null,'ok','failed')];
const original=JSON.stringify(rows),ids=(field,direction)=>Array.from(sort(rows,field,direction),r=>r.compound_id);
assert.deepEqual(ids('rank','asc'),['C1','C2','C3','C4','C10']);
assert.deepEqual(ids('rank','desc'),['C4','C3','C2','C1','C10']);
assert.deepEqual(ids('binding','asc'),['C4','C3','C2','C1','C10']);
assert.deepEqual(ids('binding','desc'),['C1','C2','C3','C4','C10']);
assert.deepEqual(ids('dili','desc'),['C1','C2','C3','C4','C10']);
assert.deepEqual(ids('dili','asc'),['C3','C1','C2','C4','C10']);
assert.deepEqual(ids('id','desc'),['C10','C4','C3','C2','C1']);
assert.deepEqual(Array.from(sort([])),[]);
assert.equal(JSON.stringify(rows),original,'Display sorting must not mutate scientific records');
for(const slug of ['generated','supplied']){
 const study=JSON.parse(readFileSync(`demo/public/studies/${slug}/study.json`));
 const before=JSON.stringify(study);
 const sorted=sort(study.report.results);
 const ranked=sorted.filter(r=>r.discovery_result.rank!==null);
 assert.deepEqual(Array.from(ranked,r=>r.discovery_result.rank),Array.from({length:ranked.length},(_,i)=>i+1));
 assert.equal(JSON.stringify(study),before);
}
console.log('Results ordering: directions, zero/missing scores, ties, both studies and immutable evidence passed.');

// Exercise the actual renderers and event handlers, not only the comparator.
class Element {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.value='';this.options=[];this.classList={toggle(){}};this.text='';}
 set textContent(v){this.text=String(v);this.replaceChildren();}
 get textContent(){return this.text+this.children.map(e=>e.textContent).join(' ');}
 append(...items){for(const item of items){if(item.parent)item.parent.children.splice(item.parent.children.indexOf(item),1);item.parent=this;this.children.push(item);}}
 prepend(item){this.append(item);this.children.unshift(this.children.pop());}
 replaceChildren(...items){for(const item of this.children)item.parent=null;this.children=[];this.append(...items);}
 setAttribute(key,value){this[key]=value;}
}
function renderer(){
 const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const pending=[];
 const c=vm.createContext({$,report:null,reportRun:null,showDili:true,pollTimer:null,moleculeImages:{},
  node:(tag,text,cls)=>{const e=new Element(tag);if(text!=null)e.textContent=text;e.className=cls;return e;},
  clear:id=>{$(id).replaceChildren();return $(id);},
  document:{createElementNS:(_,tag)=>new Element(tag),querySelectorAll:()=>[],body:new Element('body')},
  window:{scrollTo(){}},clearTimeout(){},step(){},page(){},renderStep(){},studyNavigation:{selected:true},
  disposePoseViewers(){},attachPoseViewer(){},timeLabel:v=>v,stageNames:{},showError:e=>{throw e;},
  resultsSource:{kind:'static',evidence:()=>new Promise(()=>{}),preview:()=>new Promise(resolve=>pending.push(resolve))}});
 vm.runInContext(readFileSync('app/src/toxoracle_app/web_static/results-view.js','utf8'),c);
 return {c,$,pending};
}
async function checkRendering(){
 for(let fresh=0;fresh<2;fresh++){
  const {c,$,pending}=renderer();
  for(const slug of ['generated','supplied','generated']){
   const study=JSON.parse(readFileSync(`demo/public/studies/${slug}/study.json`));
   const before=JSON.stringify(study);
   c.renderResults(study.report,{...study.run,mode:'recorded'});
   const displayed=id=>$(id).children.filter(e=>e.dataset.compoundId).map(e=>e.dataset.compoundId);
   const verify=()=>{
    const field=$('result-sort').value,dir=$('result-sort-direction').value;
    const expected=Array.from(sort(study.report.results,field,dir),r=>r.compound_id);
    for(const id of ['score-overview','discovery-lab','candidate-rows'])assert.deepEqual(displayed(id),expected,`${slug} ${id} ${field} ${dir}`);
    assert.deepEqual(displayed('decision-cards'),expected.filter(id=>study.report.discovery_shortlist.includes(id)));
   };
   verify();
   for(const field of ['rank','binding','dili','id','rank']){
    for(const dir of ['desc','asc','desc']){
     $('result-sort-direction').value=dir;$('result-sort-direction').oninput();
     $('result-sort').value=field;$('result-sort').onchange();
     assert.equal($('result-sort-direction').value,dir,'Changing field must preserve chosen direction');
     verify();
     for(const view of ['discovery','explorer','overview']){c.resultView(view);verify();}
     // A rebuilt dashboard must also use the current direction immediately.
     c.renderDashboard(study.report);verify();
    }
   }
   const nodes=$('discovery-lab').children.filter(e=>e.dataset.compoundId);nodes[0].open=true;
   $('result-sort-direction').value='asc';$('result-sort-direction').onchange();verify();
   assert.ok($('discovery-lab').children.includes(nodes[0])&&nodes[0].open,'Sorting preserves expanded evidence nodes');
   $('candidate-filter').value='shortlisted';c.renderRows();
   assert.deepEqual(displayed('candidate-rows'),displayed('decision-cards'));
   $('candidate-filter').value='all';$('candidate-search').value=study.report.results[0].compound_id;c.renderRows();
   assert.deepEqual(displayed('candidate-rows'),[study.report.results[0].compound_id]);
   $('candidate-search').value='';c.renderRows();verify();
   // Delayed preview completion triggers the production table re-render callback.
   for(const resolve of pending.splice(0))resolve({candidates:[]});
   await new Promise(resolve=>setImmediate(resolve));verify();
   assert.equal(JSON.stringify(study),before);
  }
 }
 console.log('Rendered ordering: fresh sessions, study switches, field/direction events, all views, filtering, node preservation and delayed previews passed.');
}
checkRendering().catch(error=>{console.error(error);process.exitCode=1;});
