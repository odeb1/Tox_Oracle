'use strict';
// Presentation only: route state comes from the host, never from an inferred prompt.
function renderWorkflowRouting(route, recorded=false, context='Route preview') {
  const known=['generated','supplied'].includes(route);
  document.querySelectorAll('[data-route]').forEach(card=>{
    const selected=known&&card.dataset.route===route;
    card.classList.toggle('selected',selected);
    card.querySelector('.routing-selected').hidden=!selected;
  });
  document.getElementById('routing-context').textContent=recorded?'Recorded route':context;
  document.getElementById('routing-note').textContent=recorded
    ? 'This example replays the recorded agent plan and model pathway. Its toxicity endpoint is liver toxicity (DILI).'
    : 'Current study setup: prepared human ABL1 target and local liver-toxicity (DILI) assessment. The agent reviews the plan after privacy approval.';
}
