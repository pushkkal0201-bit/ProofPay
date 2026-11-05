const byId = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char =>
  ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const money = paise => new Intl.NumberFormat('en-IN', {style:'currency',currency:'INR'}).format(paise / 100);
let cases = [], selected;
async function api(path, body) {
  const options = body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {};
  const response = await fetch('/api/'+path,options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
const status = message => { byId('status').textContent = message; };
async function refresh() {
  cases = await api('cases');
  selected ??= cases[0]?.invoice;
  const metrics = [['OPEN BALANCE',money(cases.reduce((n,c)=>n+c.collectible,0))],
    ['REVIEW HOLDS',cases.filter(c=>c.state==='Review hold').length],['OPEN CASES',cases.filter(c=>c.balance>0).length]];
  byId('stats').innerHTML=metrics.map(([k,v])=>`<dl class="tile"><dt>${k}</dt><dd>${v}</dd></dl>`).join('');
  renderQueue(); renderCase();
}
function renderQueue(){
  const term=byId('search').value.toLowerCase();
  const visible=cases.filter(c=>(c.invoice+' '+c.buyer).toLowerCase().includes(term));
  byId('queue').replaceChildren(...visible.map(c=>{
    const b=document.createElement('button'); b.classList.toggle('active',selected===c.invoice);
    b.innerHTML=`<b>${escape(c.buyer)}</b><span>${escape(c.invoice)} · ${c.dpd} DPD · ${escape(c.state)}</span>`;
    b.onclick=()=>{selected=c.invoice;status('');renderQueue();renderCase()};return b;
  }));
  if(!visible.length)byId('queue').textContent='No matching cases.';
}
function financialAudit(summary){
  const estimate=summary.interest_estimate, taxes=summary.adjusted_tax_split;
  const cards=Object.entries(taxes).map(([key,value])=>
    `<div><small>${escape(key.toUpperCase())}</small><b>${money(value)}</b></div>`).join('');
  const segments=estimate.audit.map(s=>
    `<tr><td>${s.start} – ${s.end}</td><td>${money(s.balance)}</td><td>${s.annual_bps/100}%</td><td>${escape(s.source)}</td></tr>`).join('');
  return `<details><summary>Tax split and interest audit</summary><div class="audit-metrics">${cards}</div>
    <p>Contract due ${summary.contract_due} · Effective due ${summary.effective_due}</p>
    <p>Interest estimate · ${estimate.amount===null?'Unavailable':money(estimate.amount)} · ${escape(estimate.status)}</p>
    <p>Payments received · ${summary.payment_history.count} · Latest ${summary.payment_history.latest || '—'}</p>
    ${segments?`<div class="scroll"><table class="audit-table"><tr><th>Period</th><th>Open invoice</th><th>Annual rate</th><th>Source</th></tr>${segments}</table></div>`:''}</details>`;
}
function renderCase(){
  const c=cases.find(x=>x.invoice===selected);
  if(!c)return;
  const entries=[['Principal',c.matrix.principal],['GST',c.matrix.gst],['Approved debit notes',c.matrix.debit],
    ['Approved credit notes',-c.matrix.credit],['Payments',-c.matrix.payment],['Interest applied',c.matrix.interest]];
  const anchor=a=>`<p><b>${escape(a.kind)} · ${escape(a.id)}</b> · ${escape(a.timestamp)}<br>${escape(a.signer || a.source)} · ${a.kind==='telemetry' ? (a.uptime_bps/100)+'% uptime' : a.kind==='eway'?'Transit record':a.quantity+' units'}<br><span class="meta">${escape(a.source)} · Reviewed by ${escape(a.reviewer)}</span></p>${a.attachment?`<details><summary>${escape(a.attachment.filename)}</summary><pre>${escape(a.attachment.text)}</pre></details>`:''}`;
  byId('detail').innerHTML=`<div class="head"><div><small>${escape(c.invoice)}</small><h2>${escape(c.buyer)}</h2><span class="meta">Due ${c.due} · Snapshot ${c.as_of} · ${c.dpd} days past due</span></div><span class="badge ${c.reasons.length?'warn':''}">${escape(c.state)}</span></div>
  <h3>Financial matrix</h3>${entries.map(([k,v])=>`<div class="row"><span>${k}</span><b>${money(v)}</b></div>`).join('')}<div class="row total"><span>Net balance</span><b>${money(c.balance)}</b></div>
  ${financialAudit(c.LEDGER_SUMMARY)}
  <h3>Evidence chain</h3>${c.source.dispute_text?`<p>Buyer objection · ${escape(c.source.dispute_text)}</p>`:''}
  ${c.proof.map(p=>`<div class="card"><b>${escape(p.line)} · ${escape(p.description)}</b><p>${escape(p.clause)} · ${p.quantity} ordered${p.target_bps===null?'':' · Target '+p.target_bps/100+'%'}</p>${p.anchors.map(anchor).join('')}${p.gaps.map(x=>`<p class="notice">${escape(x)}</p>`).join('')}</div>`).join('')}
  <h3>GST reconciliation</h3><p>${escape(c.source.gstin)} · Account master ${c.master_match?'matched':'requires review'}. GSTR-2B snapshot · ${escape(c.statement)}.</p>${c.itc_review?'<p class="notice">Invoice age reached 180 days. Ask the tax team to assess payment and credit history.</p>':''}
  ${c.reasons.map(x=>`<p class="notice">${escape(x)}</p>`).join('')}
  <p class="card">${escape(c.action)}</p><h3>${c.draft?'Notice for review':'Disposition'}</h3>${c.draft?`<pre>${escape(c.draft)}</pre>`:`<p class="card">${escape(c.state)} · Outbound draft withheld.</p>`}
  <div class="actions"><button id="agent">Ask RAV-AI</button>${c.draft?`<button id="review" ${c.reviewed?'disabled':''}>${c.reviewed?'Reviewed':'Mark draft reviewed'}</button>`:''}${c.draft?`<button id="pdf">Download notice PDF</button>`:''}<button id="export">Export case</button></div><p class="meta" role="status" id="advice"></p>`;
  if(c.draft){
    const details=document.createElement('details'), summary=document.createElement('summary'), body=document.createElement('pre');
    summary.textContent='WhatsApp draft';body.textContent=c.COMMUNICATIONS_DRAFT.whatsapp || 'WhatsApp opt-in is required for this channel.';
    details.append(summary,body);byId('detail').append(details);
    byId('pdf').onclick=async()=>{try{
      const response=await fetch('/api/notice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({invoice:c.invoice,review_key:c.review_key})});
      if(!response.ok)throw new Error('Refresh the case before downloading.');
      const url=URL.createObjectURL(await response.blob()), a=document.createElement('a');
      a.href=url;a.download=c.invoice+'-draft.pdf';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(e){status(e.message)}};
  }
  byId('agent').onclick=async event=>{
    const btn=event.currentTarget, output=byId('advice');btn.disabled=true;output.textContent='Checking case…';
    try{const r=await api('agent',{invoice:c.invoice});output.textContent=r.mode+' · '+r.task+' Checks: '+r.trace.join(', ')}
    catch(e){output.textContent=e.message}finally{btn.disabled=false}
  };
  if(c.draft)byId('review').onclick=async()=>{try{await api('review',{invoice:c.invoice,review_key:c.review_key});await refresh();status('Draft review recorded locally.')}catch(e){status(e.message)}};
  byId('export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(c,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=c.invoice+'-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
}
byId('search').oninput=renderQueue;
byId('import').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;
  const source=JSON.parse(await file.text());
  const existing=cases.find(c=>c.invoice===source.invoice);
  if(existing && !window.confirm('Replace the current snapshot for '+existing.invoice+'? The previous version will be archived.'))return;
  const r=existing ? await api('revise',{source,review_key:existing.review_key}) : await api('cases',source);
  selected=r.invoice;await refresh();status('Invoice imported.')}
  catch(err){status(err.message)}finally{e.target.value=''}};
refresh().catch(err=>status(err.message));
