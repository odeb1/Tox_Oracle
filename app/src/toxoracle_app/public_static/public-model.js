'use strict';
// Independent data source and playback state. No local API/session emulation.
class StaticStudySource {
  constructor(slug, transport=(...args)=>globalThis.fetch(...args)) {
    if(!['generated','supplied'].includes(slug))throw new Error('Unknown example');
    this.kind='static';this.slug=slug;this.fetch=transport;this.base='/studies/'+slug+'/';this.cache=new Map();
  }
  async request(path) {
    const response=await this.fetch(path,{credentials:'omit',cache:'no-cache'});
    if(!response.ok)throw new Error('Saved evidence is unavailable. Reload to retry.');
    return new Uint8Array(await response.arrayBuffer());
  }
  async verify(bytes, expected) {
    const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(v=>v.toString(16).padStart(2,'0')).join('');
    if(hash!==expected)throw new Error('Saved evidence failed its integrity check. No substitute evidence was loaded.');
    return bytes;
  }
  async load() {
    const index=JSON.parse(new TextDecoder().decode(await this.request('/studies/index.json')));
    const pin=index.studies.find(s=>s.slug===this.slug);
    const bytes=await this.verify(await this.request(this.base+'manifest.json'),pin.manifest_sha256);
    this.manifest=JSON.parse(new TextDecoder().decode(bytes));
    this.study=JSON.parse(await this.text(this.manifest.presentation?.study || 'study.json'));
    return this.study;
  }
  async bytes(path) {
    if(!/^[A-Za-z0-9_./-]+$/.test(path)||path.includes('..')||path.startsWith('/')||!this.manifest.assets[path])throw new Error('Unpublished asset');
    if(!this.cache.has(path)) {
      const pending=(async()=>{const bytes=await this.request(this.base+path),record=this.manifest.assets[path];if(bytes.length!==record.bytes)throw new Error('Saved asset size mismatch');return this.verify(bytes,record.sha256);})();
      this.cache.set(path,pending);pending.catch(()=>this.cache.delete(path));
    }
    return this.cache.get(path);
  }
  async text(path){return new TextDecoder().decode(await this.bytes(path));}
  async evidence({view,compound_id,source,labels}) {
    if(view==='model')return this.study.model;
    const record=this.study.evidence[compound_id];if(!record)throw new Error('Unknown candidate');
    const key=(source||'molecule')+(labels?'-labels':'');
    if(source&&!record.features.some(f=>f.source===source))throw new Error('Unknown feature');
    const path=record.images[key];
    const image=path?'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(await this.text(path)):null;
    return {...record,image,selected:source||null};
  }
  async preview(candidates){return {candidates:await Promise.all(candidates.map(async c=>({compound_id:c.compound_id,...await this.evidence({compound_id:c.compound_id})}))) };}
  async structure({compound_id,index=0}) {
    const row=this.study.report.results.find(r=>r.compound_id===compound_id),artifact=row?.discovery_result.structures[index];
    if(!artifact)throw new Error('No recorded pose');
    const content=await this.text(artifact.uri);
    if(this.manifest.assets[artifact.uri].sha256!==artifact.sha256)throw new Error('Pose does not match candidate');
    return {content,format:artifact.format,sha256:artifact.sha256,filename:compound_id+'-'+index+'.cif',mime:'chemical/x-mmcif'};
  }
}
class ReplayState {
  constructor(events,saved={}) {
    this.events=events;this.count=Number.isInteger(saved.count)?Math.max(0,Math.min(events.length,saved.count)):0;
    this.reached=Math.max(this.count?this.eventStage():0,Number.isInteger(saved.reached)?Math.max(0,Math.min(4,saved.reached)):0);
    this.selected=Number.isInteger(saved.selected)?Math.max(0,Math.min(this.reached,saved.selected)):this.reached;
    this.playing=false;
  }
  eventStage(){return this.count===this.events.length?4:this.events.slice(0,this.count).some(e=>['toxicity','reporting','explaining'].includes(e.stage))?3:2;}
  advance(count=this.count+1){const prior=this.reached;this.count=Math.max(this.count,Math.min(this.events.length,count));this.reached=Math.max(this.reached,this.eventStage());if(this.selected===prior)this.selected=this.reached;if(this.count===this.events.length)this.playing=false;}
  select(stage){if(Number.isInteger(stage)&&stage>=0&&stage<=this.reached)this.selected=stage;}
  nextStage(){const boundary=this.events.findIndex((e,i)=>i>=this.count&&e.stage==='toxicity');this.advance(boundary>=0?boundary+1:this.events.length);this.selected=this.reached;}
  snapshot(){return {version:1,count:this.count,reached:this.reached,selected:this.selected};}
}
function parsePanel(content) {
  if(new TextEncoder().encode(content).length>1000000)throw new Error('Choose a file smaller than 1 MB.');
  let rows;
  if(content.trim().startsWith('{')||content.trim().startsWith('[')) {
    const data=JSON.parse(content);rows=Array.isArray(data)?data:data.compounds;
  } else {
    // RFC-style quoted CSV, rejecting ambiguous/duplicate columns and malformed rows.
    const table=[];let row=[],field='',quoted=false,closed=false;
    const input=content.replace(/^\uFEFF/,'').replace(/\r\n/g,'\n');
    for(let i=0;i<=input.length;i++){
      const c=input[i]??'\n';
      if(quoted){if(c==='"'){if(input[i+1]==='"'){field+='"';i++;}else{quoted=false;closed=true;}}else field+=c;continue;}
      if(c==='"'&&!field&&!closed){quoted=true;continue;}
      if(c===','||c==='\n'){row.push(field);field='';closed=false;if(c==='\n'){if(row.some(x=>x.length))table.push(row);row=[];}continue;}
      if(closed||c==='"')throw new Error('Invalid quoted CSV field');field+=c;
    }
    if(quoted)throw new Error('Unclosed CSV field');
    const headers=table.shift()?.map(s=>s.trim());if(!headers||new Set(headers).size!==headers.length||!headers.includes('compound_id')||!headers.includes('smiles'))throw new Error('CSV needs unique compound_id and smiles columns.');
    rows=table.map(r=>{if(r.length!==headers.length)throw new Error('CSV row length mismatch');return Object.fromEntries(headers.map((k,i)=>[k,r[i]]));});
  }
  if(!Array.isArray(rows)||!rows.length)throw new Error('Use a compounds array or CSV panel.');
  return rows.map(r=>({compound_id:String(r.compound_id||'').trim(),smiles:String(r.smiles||r.canonical_smiles||'').trim()}));
}
function panelMatches(content,expected){const rows=parsePanel(content);return rows.length===expected.length&&new Set(rows.map(r=>r.compound_id)).size===rows.length&&rows.every(r=>expected.some(e=>e.compound_id===r.compound_id&&e.canonical_smiles===r.smiles));}
if(typeof module!=='undefined')module.exports={StaticStudySource,ReplayState,parsePanel,panelMatches};
