#!/usr/bin/env node
import {readFile,writeFile,mkdir,cp,readdir,stat} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const sha=data=>createHash('sha256').update(data).digest('hex');
const studies=path.join(root,'demo/public/studies');
const index=JSON.parse(await readFile(path.join(studies,'index.json')));
for(const entry of index.studies){
 const dir=path.join(studies,entry.slug),raw=await readFile(path.join(dir,'manifest.json'));
 if(sha(raw)!==entry.manifest_sha256)throw Error('Manifest integrity failure: '+entry.slug);
 const manifest=JSON.parse(raw);
 for(const [name,record] of Object.entries(manifest.assets)){
  if(name.includes('..')||path.isAbsolute(name))throw Error('Unsafe asset path');
  const bytes=await readFile(path.join(dir,name));if(bytes.length!==record.bytes||sha(bytes)!==record.sha256)throw Error('Asset integrity failure: '+name);
 }
}
const out=path.join(root,'dist'),shared=path.join(root,'app/src/toxoracle_app/web_static'),pub=path.join(root,'app/src/toxoracle_app/public_static');
await mkdir(path.join(out,'static'),{recursive:true});
for(const name of ['workspace.css','results-view.js','workflow-routing.js','pose-viewer.js','vendor'])await cp(path.join(shared,name),path.join(out,'static',name),{recursive:true});
for(const name of ['public.css','public.js','public-model.js','public-review.js','toxoracle-logo.png'])await cp(path.join(pub,name),path.join(out,'static',name));
await cp(studies,path.join(out,'studies'),{recursive:true});
const local=await readFile(path.join(shared,'index.html'),'utf8');
const results=local.slice(local.indexOf('    <section id="results-page"'),local.indexOf('    <section id="replay-page"'));
const template=await readFile(path.join(pub,'index.html'),'utf8');
await writeFile(path.join(out,'index.html'),template.replace('<!-- SHARED_RESULTS -->',results));
// Fail closed if a previous build or accidental copy left additional files.
const expected=new Set(['index.html','vercel.json',...['workspace.css','results-view.js','workflow-routing.js','pose-viewer.js','public.css','public.js','public-model.js','public-review.js','toxoracle-logo.png'].map(n=>'static/'+n),'studies/index.json']);
for(const entry of index.studies){const m=JSON.parse(await readFile(path.join(studies,entry.slug,'manifest.json')));for(const n of ['manifest.json',...Object.keys(m.assets)])expected.add('studies/'+entry.slug+'/'+n);}
for(const name of await readdir(path.join(shared,'vendor')))expected.add('static/vendor/'+name);
async function scan(dir){for(const item of await readdir(dir,{withFileTypes:true})){const p=path.join(dir,item.name);if(item.isDirectory())await scan(p);else{const rel=path.relative(out,p);if(!expected.has(rel))throw Error('Unexpected deployment file: '+rel);const bytes=await readFile(p);if(/\/Users\/|\/home\/|nvapi-[A-Za-z0-9_-]+|"(?:session_id|owner_id|api_key)"/.test(bytes.toString()))throw Error('Private content: '+rel);}}}
const hosting=JSON.parse(await readFile(path.join(root,'vercel.json'),'utf8'));
await writeFile(path.join(out,'vercel.json'),JSON.stringify({...hosting,buildCommand:null,installCommand:null,outputDirectory:'.'},null,2)+'\n');
await scan(out);
console.log('Verified static demo built in dist/ — no backend or credentials.');
