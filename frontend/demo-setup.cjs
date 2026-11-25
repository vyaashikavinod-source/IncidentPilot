// Validate checked-in demo assets. Safe to run repeatedly on published source.
const fs = require('node:fs');
const runs = JSON.parse(fs.readFileSync(require('node:path').join(__dirname, 'public/recorded-runs.json'), 'utf8'));
if (runs.evidence_type !== 'real_loopback_http_faults' || runs.agent_type !== 'real_model' || runs.runs.length !== 9) {
  throw new Error('Expected nine recorded real-model investigations');
}
const evaluation = JSON.parse(fs.readFileSync(require('node:path').join(__dirname, 'public/clauseforge-evaluation.json'), 'utf8'));
if (!evaluation.runs.length || evaluation.runs.some(run => run.metrics.sample_size !== 200)) {
  throw new Error('Expected completed frozen evaluation reports');
}
console.log('Using checked-in replay evidence; no source overlay or inference required.');

for (const name of ['recorded-runs-v2.json','recorded-runs-v2-small.json','recorded-runs-v2-large.json','recorded-runs-v2-gemini.json']) {
  const report=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'public',name),'utf8'));
  if(report.agent_type!=='real_model'||report.runs.length!==9) throw new Error('Invalid recorded comparison: '+name);
}
