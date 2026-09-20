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
