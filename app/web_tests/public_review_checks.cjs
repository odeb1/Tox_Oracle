const assert=require('node:assert/strict');
const {renderSavedReview}=require('../src/toxoracle_app/public_static/public-review.js');

// Small DOM double: exercise the renderer without browser/npm dependencies.
// Deliberately prohibit HTML parsing of any recorded text.
class Element {
 constructor(tag,doc){this.tagName=tag;this.ownerDocument=doc;this.children=[];this.text='';}
 set textContent(text){this.text=String(text);this.children=[];}
 get textContent(){return this.text+this.children.map(child=>child.textContent).join(' ');}
 set innerHTML(_){throw Error('Recorded values must never be parsed as HTML');}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.text='';this.children=children;}
}
const doc={createElement:tag=>new Element(tag,doc)};
const descendants=root=>[root,...root.children.flatMap(descendants)];

function checkSavedReview(study){
 const host=doc.createElement('div'),before=JSON.stringify(study);
 renderSavedReview(host,study);
 const text=host.textContent,review=study.review;
 assert.equal(JSON.stringify(study),before,'Rendering cannot mutate recorded evidence');
 for(const recorded of [review.research_prompt,review.target_id,review.approved_at,review.audit.policy_version,review.audit.model_revision,...Object.entries(review.request).filter(([key])=>key!=='compounds').map(([,v])=>v)]){
  assert.ok(text.includes(String(recorded)),'Missing recorded input/provenance: '+recorded);
 }
 const metrics=descendants(host).filter(e=>e.className==='saved-review-metric');
 const generated=study.slug==='generated';
 assert.deepEqual(metrics.map(e=>e.children[0].textContent),generated?['20','0','0']:['4','1','1']);
 assert.ok(text.includes('Detector findings, not a count of redactions.'));
 for(const compound of review.request.compounds||[]){
  for(const field of Object.values(compound))assert.ok(text.includes(field),'Missing candidate field: '+field);
 }
 const nodes=descendants(host);
 assert.equal(nodes.some(e=>e.tagName==='pre'),false,'Review should have no raw code block');
 assert.ok(nodes.filter(e=>e.tagName==='th').every(e=>['row','col'].includes(e.scope)));
 assert.equal(nodes.find(e=>e.tagName==='time').dateTime,review.approved_at);

 // Re-render the same host to model changing studies; never retain old rows.
 const changed=structuredClone(study);
 changed.review.research_prompt='<img src=x onerror=alert(1)>';
 changed.review.request={};changed.review.audit={};changed.review.approved_at=null;
 renderSavedReview(host,changed);
 assert.ok(host.textContent.includes('<img src=x onerror=alert(1)>'));
 assert.equal(descendants(host).some(e=>['img','script'].includes(e.tagName)),false);
 assert.equal(host.textContent.includes(review.research_prompt),false);
 for(const compound of review.request.compounds||[])assert.equal(host.textContent.includes(compound.compound_id),false);
 assert.ok(host.textContent.includes('Privacy-category counts were not recorded.'));
 assert.deepEqual(descendants(host).filter(e=>e.className==='saved-review-metric').map(e=>e.children[0].textContent),['Not recorded','Not recorded','Not recorded']);
}
module.exports={checkSavedReview};
