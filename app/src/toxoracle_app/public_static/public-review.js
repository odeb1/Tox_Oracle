'use strict';

// Present the exported review only. This view never scans or approves inputs.
function renderSavedReview(container, study) {
  const doc=container.ownerDocument;
  const el=(tag,text,cls)=>{const item=doc.createElement(tag);if(text!==undefined)item.textContent=String(text);if(cls)item.className=cls;return item;};
  const value=v=>v===undefined||v===null?'Not recorded':String(v);
  const pairs=rows=>{
    const list=el('dl',undefined,'saved-review-facts');
    for(const [label,text] of rows){const row=el('div');row.append(el('dt',label),el('dd',value(text)));list.append(row);}
    return list;
  };
  const section=(title)=>{const card=el('section',undefined,'saved-review-card');card.append(el('h4',title));return card;};
  const review=study.review,request=review.request||{},audit=review.audit||{};
  const compounds=Array.isArray(request.compounds)?request.compounds:[];
  const generated=review.workflow==='generate_screen'||request.mode==='generate_screen';
  const categories=Object.entries(audit.category_counts||{});
  const flags=audit.category_counts?categories.reduce((total,[,count])=>total+count,0):undefined;
  const retained=audit.reviewed_scientific_fields_retained;
  container.replaceChildren();

  const heading=el('div',undefined,'saved-review-heading');
  const intro=el('div');intro.append(el('p','SAVED PRIVACY REVIEW','eyebrow'),el('h3','What was reviewed before discovery'));
  const stamp=el('div',undefined,'saved-review-stamp');
  stamp.append(el('strong',review.approved_at?'Approval recorded':'Approval time not recorded'));
  if(review.approved_at){const time=el('time',new Date(review.approved_at).toLocaleString('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:'UTC'})+' UTC');time.dateTime=review.approved_at;stamp.append(time);}
  heading.append(intro,stamp);container.append(heading);

  const metrics=el('div',undefined,'saved-review-metrics');
  for(const [count,label,note] of [
    [generated?request.count:request.compounds?.length,generated?'Candidates requested':'Compounds supplied',generated?'Target-only input; molecules were proposed later.':'The exact panel reviewed for this study.'],
    [flags,'Privacy flags recorded','Detector findings, not a count of redactions.'],
    [retained,'Scientific fields retained','Explicitly kept after local review.']
  ]){const card=el('div',undefined,'saved-review-metric');card.append(el('strong',value(count)),el('span',label),el('p',note));metrics.append(card);}
  container.append(metrics);

  const grid=el('div',undefined,'saved-review-grid');
  const inputs=section('Reviewed inputs');
  inputs.append(el('p',review.research_prompt,'saved-review-question'),pairs([
    ['Target',review.target_id],['Input route',generated?'Generate candidates from a target':'Screen supplied candidates'],
    ...(generated?[['Requested target',request.target],['Requested candidates',request.count]]:[['Supplied compounds',request.compounds?.length]])
  ]));
  const findings=section('Recorded privacy findings');
  if(categories.length){
    const table=el('table',undefined,'saved-review-table');
    table.append(el('caption','Flags by detector category'));
    const head=el('thead'),header=el('tr');
    for(const title of ['Category','Flags']){const cell=el('th',title);cell.scope='col';header.append(cell);}head.append(header);table.append(head);
    const body=el('tbody');
    for(const [category,count] of categories){const row=el('tr'),name=el('th',category.replaceAll('_',' '));name.scope='row';row.append(name,el('td',count));body.append(row);}
    table.append(body);findings.append(table);
  }else findings.append(el('p',audit.category_counts?'No privacy-category flags were recorded.':'Privacy-category counts were not recorded.','saved-review-empty'));
  findings.append(el('p',retained>0?'The saved audit records explicit retention of scientific fields. It does not identify the retained field or link it to a detector category.':'The saved audit does not include field-level findings. Recorded counts alone do not guarantee that inputs contain no sensitive information.','field-note'));
  grid.append(inputs,findings);container.append(grid);

  if(compounds.length){
    const panel=section('Supplied candidate identities');
    panel.append(el('p','Structures from the saved reviewed input. Expand a row for its full identity record.','field-note'));
    const table=el('table',undefined,'saved-review-table saved-review-compounds');
    table.append(el('caption','Reviewed compounds and canonical SMILES'));
    const head=el('thead'),header=el('tr');
    for(const title of ['Compound ID','Molecular structure']){const cell=el('th',title);cell.scope='col';header.append(cell);}head.append(header);table.append(head);
    const body=el('tbody');
    for(const compound of compounds){
      const row=el('tr'),id=el('th',compound.compound_id);id.scope='row';
      const structure=el('td');structure.append(el('code',value(compound.canonical_smiles)));
      const details=el('details');details.append(el('summary','Structure identity details'),pairs([
        ['Structure ID',compound.structure_id],['Standardization',compound.standardization_version],['Atom-mapped SMILES',compound.atom_mapped_smiles]
      ]));structure.append(details);row.append(id,structure);body.append(row);
    }
    table.append(body);panel.append(table);container.append(panel);
  }

  const provenance=el('details',undefined,'saved-review-provenance');
  provenance.append(el('summary','Saved policy and request provenance'),pairs([
    ['Privacy policy',audit.policy_version],['Privacy model revision',audit.model_revision],['Approval timestamp',review.approved_at],
    ['Request ID',request.request_id],['Request schema version',request.schema_version],
    ...(review.workflow?[['Workflow',review.workflow]]:[]),...(request.mode?[['Request mode',request.mode]]:[]),
    ...(request.input_provenance?[['Input provenance',request.input_provenance]]:[])
  ]));container.append(provenance);
}

if(typeof module!=='undefined'&&module.exports)module.exports={renderSavedReview};
