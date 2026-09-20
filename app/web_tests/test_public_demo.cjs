const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {StaticStudySource,ReplayState,panelMatches,parsePanel}=require('../src/toxoracle_app/public_static/public-model.js');
async function main(){
 const root=path.resolve(__dirname,'../../demo/public');let requests=[];
 const transport=async(url,options)=>{assert.equal(options.credentials,'omit');assert.ok(url.startsWith('/studies/'));requests.push(url);try{const data=await fs.readFile(root+url);return {ok:true,arrayBuffer:async()=>data};}catch{return {ok:false};}};
 for(const slug of ['generated','supplied']){
  const source=new StaticStudySource(slug,transport);const study=await source.load();
  assert.equal(study.run.mode,'live');assert.equal(study.run.assistant.status,'complete');
  let poses=0;
  for(const row of study.report.results){
   const data=await source.evidence({compound_id:row.compound_id});assert.ok(data.image.startsWith('data:image/svg+xml'));
   for(const feature of [null,...data.features.map(f=>f.source)])for(const labels of [false,true])assert.ok((await source.evidence({compound_id:row.compound_id,source:feature,labels})).image);
   for(let index=0;index<row.discovery_result.structures.length;index++){const pose=await source.structure({compound_id:row.compound_id,index});assert.ok(pose.content.includes('_atom_site'));poses++;}
  }
  assert.equal(poses,slug==='generated'?18:4);
  await assert.rejects(source.text('../job.json'),/Unpublished/);
  await assert.rejects(source.evidence({compound_id:'unrelated'}),/Unknown/);
  await assert.rejects(source.evidence({compound_id:study.report.results[0].compound_id,source:'invented'}),/Unknown/);
  const replay=new ReplayState(study.run.events);assert.equal(replay.selected,0);replay.select(4);assert.equal(replay.selected,0);
  replay.reached=2;replay.selected=2;replay.advance();replay.select(1);replay.advance();assert.equal(replay.selected,1);
  replay.nextStage();assert.equal(replay.reached,3);replay.playing=true;
  const restored=new ReplayState(study.run.events,replay.snapshot());assert.equal(restored.count,replay.count);assert.equal(restored.playing,false);
  replay.nextStage();assert.equal(replay.reached,4);assert.equal(replay.playing,false);
  assert.deepEqual(Object.keys(replay.snapshot()).sort(),['count','reached','selected','version']);
  if(slug==='supplied'){
   const csv=await source.text('example.csv'),expected=study.report.results;
   assert.ok(panelMatches(csv,expected));assert.ok(panelMatches(JSON.stringify({compounds:[...expected].reverse()}),expected));
   assert.equal(panelMatches(csv.replace('LT00107','OTHER'),expected),false);
   assert.equal(panelMatches(csv+csv.split('\n')[1]+'\n',expected),false);
   assert.throws(()=>parsePanel('compound_id,smiles,smiles\na,b,c'),/unique/);
   assert.throws(()=>parsePanel('compound_id,smiles\na,"CC'),/Unclosed/);
   assert.throws(()=>parsePanel('x'.repeat(1000001)),/1 MB/);
  }
 }
 const bad=new StaticStudySource('generated',async(url,opts)=>{const r=await transport(url,opts);if(url.endsWith('study.json'))return {ok:true,arrayBuffer:async()=>Buffer.from('tampered')};return r;});
 await assert.rejects(bad.load(),/size mismatch/);
 const missing=new StaticStudySource('generated',async()=>({ok:false}));await assert.rejects(missing.load(),/unavailable/);
 const hash=new StaticStudySource('generated',transport);await assert.rejects(hash.verify(new Uint8Array([1]),'0'.repeat(64)),/integrity/);
 assert.ok(requests.every(url=>!url.includes('/api/')));
 console.log('Public demo: both data sources, all molecule variants and 22 poses verified; input, replay, restore and tamper checks passed.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
