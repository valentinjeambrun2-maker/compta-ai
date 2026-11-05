// ComptaIA — écrans avancés : accueil « À faire », entretien IA, agents spécialisés, impôts, déclarations,
// tiers & lettrage, comptabilité détaillée, analyse, révision.
'use strict';
TABS = {
  entreprise: [['dash','Tableau de bord'],['bank','Banque & IA'],['inv','Factures'],['quotes','Devis'],['tiers','Clients & fournisseurs'],['ndf','Notes de frais'],
    ['pay','Paie'],['compta','Comptabilité'],['rep','États financiers'],['analyse','Analyse & trésorerie'],['decl','Déclarations'],
    ['tax','Impôts & liasse'],['tva','TVA'],['close','Clôture'],['profil','Profil'],['ai','Agents IA'],['set','Paramètres']],
  particulier: [['dash','Tableau de bord'],['impots','Mes impôts'],['bank','Banque'],['rep','Budget'],['profil','Mon profil'],['ai','Agents IA'],['close','Exports'],['set','Paramètres']]
};
Object.assign(HERO, {
  dash: ['Bonjour.', 'Voici ce qui demande votre attention aujourd\'hui.'],
  tiers: ['Clients & fournisseurs.', 'Comptes individuels, lettrage, balance âgée et risque client.'],
  compta: ['Comptabilité.', 'Journal, recherche, grand livre et rapprochement bancaire.'],
  analyse: ['Analyse & trésorerie.', 'Soldes de gestion, ratios, seuil de rentabilité et prévisions.'],
  decl: ['Déclarations.', 'Toutes vos obligations, préparées et transmises par l\'IA.'],
  tax: ['Impôts & liasse.', 'IS, liasse fiscale et impôt sur le revenu du dirigeant.'],
  close: ['Clôture.', 'Régularisations, amortissements, résultat et exports.'],
  profil: ['Faisons connaissance.', 'Quelques questions, une seule fois. L\'IA s\'en sert pour toutes vos déclarations.'],
  impots: ['Vos impôts. Faits pour vous.', 'L\'Agent Impôts prépare votre déclaration complète et choisit les options les plus avantageuses.'],
  hub: ['Bonjour.', 'Tous vos outils, en un clic. Choisissez celui dont vous avez besoin.'],
  ai: ['Vos experts IA.', 'Un spécialiste pour chaque sujet, qui connaît votre dossier.']
});
const SCREENS = () => ({hub: hubScreen, dash: home, bank, inv, quotes, tiers: tiersScreen, ndf, pay, compta: comptaScreen, rep, analyse: analyseScreen,
  decl: declScreen, tax, close: closeScreen, profil: onboarding, impots: impotsScreen, ai: agentsScreen, set: settings, jrn, tva});

// ---------------- Accueil : tous les outils ----------------
// Icônes SVG en trait (24×24), dessinées pour ComptaIA : pas de bibliothèque externe.
const ICO = {
  grid:'<rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="5" rx="2"/><rect x="13" y="12" width="8" height="9" rx="2"/><rect x="3" y="15" width="8" height="6" rx="2"/>',
  bank:'<path d="M3 10h18"/><path d="M5 10v8M9.5 10v8M14.5 10v8M19 10v8"/><path d="M3 18.5h18"/><path d="M12 3.5 21 8H3z"/>',
  invoice:'<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6M9 15.5h6M9 19h3"/>',
  quote:'<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="m9 14 2 2 4-4"/>',
  receipt:'<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
  people:'<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.4 3.2-5.5 6.5-5.5s5.9 2.1 6.5 5.5"/><circle cx="17" cy="9" r="2.5"/><path d="M16.5 14.6c2.6.2 4.4 2.1 5 5"/>',
  payroll:'<rect x="3" y="6" width="18" height="13" rx="2.5"/><circle cx="12" cy="12.5" r="2.5"/><path d="M6.5 12.5h.01M17.5 12.5h.01"/>',
  book:'<path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H20v17H7.5A2.5 2.5 0 0 0 5 21.5z"/><path d="M5 21.5V4.5"/><path d="M9 7h7"/>',
  percent:'<path d="M19 5 5 19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>',
  send:'<path d="M22 2 11 13"/><path d="M22 2l-7 20-4-9-9-4z"/>',
  landmark:'<path d="M3 21h18"/><path d="M5 21V10M9.5 21V10M14.5 21V10M19 21V10"/><path d="M2.5 9 12 3l9.5 6z"/>',
  chart:'<path d="M4 20V4"/><path d="M4 20h16"/><path d="M8 16v-4M12 16V8M16 16v-6"/>',
  trend:'<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  lock:'<rect x="5" y="11" width="14" height="10" rx="2.5"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>',
  sparkle:'<path d="M12 3.5 13.7 9 19 10.5 13.7 12 12 17.5 10.3 12 5 10.5 10.3 9z"/><path d="M18.5 16.5 19.2 18.3 21 19l-1.8.7-.7 1.8-.7-1.8L16 19l1.8-.7z"/>',
  user:'<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
  gear:'<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
  pie:'<path d="M21 12A9 9 0 1 1 12 3v9z"/><path d="M15 3.6A9 9 0 0 1 20.4 9H15z"/>',
  download:'<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17.5V20h16v-2.5"/>'
};
const svgIco = (n) => `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICO[n]}</svg>`;
// [onglet, nom, description, icône, couleur] — groupés pour la page d'accueil.
const TOOLS = {
  entreprise: [
    {g:'Au quotidien', t:[
      ['bank','Banque & IA','Importez vos relevés : l\'IA classe, ventile la TVA et rapproche vos factures.','bank','#2563eb'],
      ['inv','Factures','Factures numérotées, mentions légales, PDF et relances.','invoice','#0d9488'],
      ['quotes','Devis','Du devis à la facture en un clic.','quote','#7c3aed'],
      ['ndf','Notes de frais','Photographiez un ticket : l\'IA lit le montant et la TVA.','receipt','#d97706'],
      ['tiers','Clients & fournisseurs','Comptes tiers, lettrage, balance âgée et risque client.','people','#0891b2'],
      ['pay','Paie','Bulletins, charges sociales, prélèvement à la source et DSN.','payroll','#db2777']]},
    {g:'Comptabilité & obligations', t:[
      ['compta','Comptabilité','Écritures, grand livre, recherche et rapprochement.','book','#4f46e5'],
      ['tva','TVA','Votre CA3 calculé ligne par ligne.','percent','#16a34a'],
      ['decl','Déclarations','Toutes vos échéances, préparées et transmises.','send','#0284c7'],
      ['tax','Impôts & liasse','IS, liasse fiscale et impôt du dirigeant.','landmark','#9333ea'],
      ['rep','États financiers','Bilan, compte de résultat et balance.','chart','#65a30d'],
      ['close','Clôture & exports','Régularisations, amortissements, verrouillage, FEC, PDF et Excel.','lock','#64748b']]},
    {g:'Pilotage', t:[
      ['dash','Tableau de bord','Ce qui demande votre attention et vos chiffres clés.','grid','#1d4ed8'],
      ['analyse','Analyse & trésorerie','Soldes de gestion, ratios et prévisions de trésorerie.','trend','#ea580c']]},
    {g:'Assistance & réglages', t:[
      ['ai','Agents IA','Un expert par sujet, qui connaît votre dossier.','sparkle','#7c3aed'],
      ['profil','Profil','Quelques questions pour pré-remplir toutes vos déclarations.','user','#0f766e'],
      ['set','Paramètres','Dossier, TVA, e-mail, télédéclaration et membres.','gear','#475569']]}
  ],
  particulier: [
    {g:'Pilotage', t:[
      ['dash','Tableau de bord','Ce qui demande votre attention et vos chiffres clés.','grid','#1d4ed8']]},
    {g:'Mes finances', t:[
      ['impots','Mes impôts','Votre déclaration de revenus, préparée et optimisée par l\'Agent Impôts.','landmark','#9333ea'],
      ['bank','Banque & IA','Relevés importés et catégorisés automatiquement.','bank','#2563eb'],
      ['rep','Budget','Revenus, dépenses et épargne sur l\'année.','pie','#65a30d'],
      ['close','Exports','PDF, Excel et justificatifs.','download','#64748b']]},
    {g:'Assistance & réglages', t:[
      ['ai','Agents IA','Un expert par sujet, qui connaît votre dossier.','sparkle','#7c3aed'],
      ['profil','Mon profil','Quelques questions, une seule fois, pour toutes vos déclarations.','user','#0f766e'],
      ['set','Paramètres','Dossier, membres et réglages.','gear','#475569']]}
  ]
};
function hubScreen(){
  const groups = TOOLS[ENT.kind=='particulier' ? 'particulier' : 'entreprise'];
  $('#view').innerHTML = `<div class="hub">${groups.map(g=>`<section class="hub-g"><h2 class="hub-h">${esc(g.g)}</h2><div class="hub-grid">${g.t.map(([k,n,d,ic,c])=>
    `<button class="tool" style="--c:${c}" onclick="go('${k}')"><span class="tool-ico">${svgIco(ic)}</span><span class="tool-t"><b>${esc(n)}</b><span class="small muted">${esc(d)}</span></span></button>`).join('')}</div></section>`).join('')}</div>`;
}

function render(){
  document.body.classList.toggle('ro', ROLE=='lecteur');
  if(!TABS[ENT.kind].some(t=>t[0]==TAB) && TAB!='hub') TAB='hub';
  setHero();
  document.querySelector('.fab').style.display = ['ai','profil'].includes(TAB) ? 'none' : '';
  // Navigation simplifiée : l'accueil liste tous les outils ; un outil n'affiche qu'un retour et son nom.
  const cur = TABS[ENT.kind].find(t=>t[0]==TAB);
  $('nav').style.display = TAB=='hub' ? 'none' : '';
  $('#nav').innerHTML = TAB=='hub' ? '' : `<button onclick="go('hub')">← Tous les outils</button><span class="navlabel">${esc(cur ? cur[1] : '')}</span>`;
  $('#view').innerHTML=''; $('#agent').innerHTML='';
  const fn = SCREENS()[TAB];
  Promise.resolve(fn()).then(()=>{ if(!['ai','profil','set','dash','hub'].includes(TAB)) agentPanel(); }).catch(e=>console.error(e));
}
function go(t){ TAB=t; render(); scrollTo({top:0,behavior:'smooth'}); }
const seg = (id, items, cur, cb) => `<div class="seg" id="${id}">${items.map(([k,l])=>`<button class="${k==cur?'on':''}" onclick="${cb}('${k}')">${l}</button>`).join('')}</div>`;
const pill = (st) => { const m={prete:['prête','acc'],deposee:['déposée','ok'],simulee:['simulée (test)','ok'],transmise:['transmise','ok'],a_preparer:['à préparer','warn'],erreurs:['erreurs','bad'],a_completer:['à compléter','warn']}[st]||[st,'']; return `<span class="tag ${m[1]}">${m[0]}</span>`; };
const lvl = (n) => ({critique:'critique',bloquant:'critique',attention:'attention',info:'info',ok:'ok'}[n]||'info');

// ---------------- Panneau agent (sur chaque onglet) ----------------
async function agentPanel(){
  let closed=false; try{closed=localStorage.getItem('agentClosed')=='1'}catch{}
  const a = await api(`/api/agents/tab/${TAB}?year=${YEAR}`).catch(()=>null); if(!a) return;
  window._agent=a.agent;
  const ins=a.analyses.slice(0,4);
  $('#agent').innerHTML=`<div class="card agentcard" style="background:linear-gradient(135deg,var(--soft),var(--panel))">
   <div class="row" style="justify-content:space-between;cursor:pointer" onclick="toggleAgent()"><div class="row" style="gap:12px"><span class="fabdot">✦</span>
   <div><b>${esc(a.titre)}</b> <span class="small muted">· ${esc(a.description)}</span><div class="small muted">${a.ia?'Claude connecté':'Mode local (règles et base de connaissances)'} · ${a.analyses.length} observation(s)</div></div></div><span class="muted">${closed?'Afficher ▾':'Masquer ▴'}</span></div>
   <div class="${closed?'hidden':''}" id="agentBody" style="margin-top:14px">
   ${ins.map(i=>`<div class="al ${lvl(i.niveau)}"><div style="flex:1"><b style="font-weight:600">${esc(i.titre)}</b>${i.detail?`<div class="small muted">${esc(i.detail)}</div>`:''}</div>${i.action?`<button class="g small" onclick="go('${i.action.tab}')">${esc(i.action.label)}</button>`:''}</div>`).join('')||'<div class="al ok">Rien à signaler dans ce domaine.</div>'}
   <div class="row" style="margin-top:12px"><input id="agQ" style="flex:1;min-width:200px" placeholder="Posez votre question à l'${esc(a.titre)}…" onkeydown="if(event.key=='Enter')askAgent()"><button class="b calc" onclick="askAgent()">Demander</button></div>
   <div class="row small" style="margin-top:8px">${a.suggestions.map(s=>`<button class="g small calc" onclick="$('#agQ').value=this.textContent;askAgent()">${esc(s)}</button>`).join('')}</div>
   <div id="agA"></div></div></div>`;
}
function toggleAgent(){ try{localStorage.setItem('agentClosed', $('#agentBody').classList.contains('hidden')?'0':'1')}catch{}; agentPanel(); }
async function askAgent(){
  const q=$('#agQ').value.trim(); if(!q) return;
  $('#agA').innerHTML='<p class="muted small" style="margin-top:12px">L\'agent réfléchit…</p>';
  const r=await api(`/api/agents/${window._agent}/ask`,{question:q,year:YEAR});
  $('#agA').innerHTML=`<div class="msg a" style="max-width:100%;margin-top:12px">${md(r.answer)}</div>`;
}
const md = (t) => esc(t).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/\n/g,'<br>');

// ---------------- Accueil « À faire » ----------------
async function home(){
  const P=ENT.kind=='particulier';
  const names = P ? ['impots','banque'] : ['comptable','banque','ventes','depenses','paie','tva','tresorerie','cloture'];
  const [prof, ...ags] = await Promise.all([api(`/api/profile?year=${YEAR+1}`), ...names.map(n=>api(`/api/agents/${n}?year=${YEAR}`).catch(()=>null))]);
  await dash();
  const items=[]; const seen=new Set();
  ags.filter(Boolean).forEach(a=>a.analyses.forEach(i=>{ if(['critique','attention'].includes(i.niveau)&&!seen.has(i.titre)){seen.add(i.titre);items.push({...i,agent:a.titre})} }));
  items.sort((a,b)=>(a.niveau=='critique'?0:1)-(b.niveau=='critique'?0:1));
  const ech=(prof.echeances||[]).filter(e=>!e.passe).slice(0,5);
  const hello=`<div class="card" style="background:var(--panel)">
    ${!prof.termine?`<div class="al info" style="margin:0 0 16px"><div style="flex:1"><b>Votre profil est complété à ${prof.progress} %.</b><div class="small muted">Quelques minutes d'entretien avec l'IA suffisent pour qu'elle prépare vos déclarations sans rien vous redemander.</div></div><button class="b" onclick="go('profil')">Continuer</button></div>`:''}
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr))"><div><h2>À faire <span class="tag ${items.length?'warn':'ok'}">${items.length}</span></h2>
    ${items.slice(0,8).map(i=>`<div class="al ${lvl(i.niveau)}"><div style="flex:1"><b style="font-weight:600">${esc(i.titre)}</b><div class="small muted">${esc(i.agent)}${i.detail?' · '+esc(i.detail):''}</div></div>${i.action?`<button class="g small" onclick="go('${i.action.tab}')">${esc(i.action.label)}</button>`:''}</div>`).join('')||'<div class="al ok">Tout est à jour. Bravo !</div>'}</div>
    <div><h2>Prochaines échéances</h2>${ech.map(e=>`<div class="al ${e.type=='paiement'?'attention':'info'}"><div style="flex:1"><b style="font-weight:600">${new Date(e.date).toLocaleDateString('fr-FR',{day:'numeric',month:'long',year:'numeric'})}</b><div class="small muted">${esc(e.titre)}</div></div></div>`).join('')||'<p class="muted small">Complétez votre profil pour obtenir votre calendrier fiscal personnalisé.</p>'}
    ${P?'':`<p><button class="g small" onclick="go('decl')">Voir toutes les déclarations</button></p>`}</div></div></div>`;
  $('#view').insertAdjacentHTML('afterbegin', hello);
  if(P){ const d=await api(`/api/ir/declaration?year=${YEAR}`); $('#view').insertAdjacentHTML('beforeend', impotsKpis(d)+`<p><button class="b" onclick="go('impots')">Ouvrir ma déclaration</button></p>`); }
}

// ---------------- Entretien d'accueil (profil) ----------------
async function onboarding(){
  const s=await api('/api/profile'); window._ob=window._ob||[]; window._multi=[];
  const q=s.question;
  const bar=`<div style="height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin:4px 0 18px"><i style="display:block;height:100%;width:${s.progress}%;background:var(--halo)"></i></div>`;
  let input='';
  if(q){
    if(q.type=='choice') input=`<div class="row">${q.options.map(([v,l])=>`<button class="g calc" onclick="obSend(${JSON.stringify(v).replace(/"/g,'&quot;')},'${esc(l).replace(/'/g,'&#39;')}')">${esc(l)}</button>`).join('')}</div>`;
    else if(q.type=='yesno') input=`<div class="row"><button class="g calc" onclick="obSend(true,'Oui')">Oui</button><button class="g calc" onclick="obSend(false,'Non')">Non</button></div>`;
    else if(q.type=='multi') input=`<div class="row">${q.options.map(([v,l])=>`<button class="g calc" data-v="${v}" onclick="this.classList.toggle('on');this.style.background=this.classList.contains('on')?'var(--soft)':''">${esc(l)}</button>`).join('')}<button class="b calc" onclick="obMulti()">Valider</button></div>`;
    input+=`<div class="row" style="margin-top:12px"><input id="obIn" style="flex:1;min-width:200px" type="${q.type=='number'?'text':q.type=='date'?'date':'text'}" placeholder="${esc(q.placeholder||(q.type=='number'?'Montant ou nombre'+(q.unit?' ('+q.unit+')':''):'Répondez librement, même en plusieurs informations à la fois…'))}" onkeydown="if(event.key=='Enter')obSend()">
      <button class="b calc" onclick="obSend()">Envoyer</button><button class="g calc" onclick="obSkip()">Passer</button></div>`;
  }
  const chat=window._ob.map(m=>`<div class="msg ${m.r}">${m.html||esc(m.t)}</div>`).join('');
  const cur=q?`<div class="msg a"><span class="small muted">${esc(q.section)}</span><br><b style="font-weight:600">${esc(q.text)}</b>${q.help?`<div class="small muted" style="margin-top:6px">ⓘ ${esc(q.help)}</div>`:''}</div>`:'';
  $('#view').innerHTML=`<div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">${q?'Entretien avec l\'IA':'Votre profil est complet ✓'}</h2><span class="small muted">${s.progress} % · ${s.ia?'Claude comprend vos réponses libres':'compréhension locale des réponses'}</span></div>${bar}
    ${q&&!window._ob.length?`<div class="al info"><div>Vous pouvez répondre question par question, ou tout raconter d'un coup : <i>« Je suis mariée, deux enfants nés en 2016 et 2021, salariée à Lyon, propriétaire, et je loue un studio. »</i> L'IA remplit tout ce qu'elle comprend.</div></div>`:''}
    <div class="chat" id="obChat" style="max-height:none">${chat}${cur}</div>${input}</div>
    ${!q||s.profil.length?`<div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">Ce que l'IA sait de vous</h2>${q?'':'<button class="g small wr" onclick="api(\'/api/profile/restart\',{}).then(onboarding)">Revoir les questions passées</button>'}</div>
     <p class="muted small">Cliquez sur une réponse pour la corriger. Ces informations sont réutilisées chaque année.</p>
     ${[...new Set(s.profil.map(x=>x.section))].map(sec=>`<h3>${esc(sec)}</h3><table>${s.profil.filter(x=>x.section==sec).map(x=>`<tr><td class="muted" style="width:55%">${esc(x.question)}</td><td><button class="lnk wr" style="color:var(--ink)" onclick="obEdit('${x.id}','${esc(String(x.reponse)).replace(/'/g,'&#39;')}')">${esc(String(x.reponse))}</button></td></tr>`).join('')}</table>`).join('')}</div>`:''}
    ${s.echeances.length?`<div class="card"><h2>Votre calendrier fiscal ${YEAR+1}</h2>${s.echeances.slice(0,12).map(e=>`<div class="al ${e.type=='paiement'?'attention':e.type=='echeance'?'info':'ok'}"><b style="font-weight:600;min-width:120px">${new Date(e.date).toLocaleDateString('fr-FR',{day:'numeric',month:'short'})}</b> ${esc(e.titre)}</div>`).join('')}</div>`:''}`;
  const c=$('#obChat'); if(c) c.scrollTop=c.scrollHeight; setTimeout(()=>$('#obIn')?.focus(),50);
  if(!q && window._ob.length && !window._obDone){ window._obDone=true; toast('Profil terminé : vos déclarations seront préparées automatiquement'); }
}
async function obSend(value, label){
  const s=await api('/api/profile'); const q=s.question; if(!q) return;
  const text = value===undefined ? $('#obIn').value.trim() : null; if(value===undefined && !text) return;
  window._ob.push({r:'a',html:`<b style="font-weight:600">${esc(q.text)}</b>`}); window._ob.push({r:'u',t:label||text});
  const r=await api('/api/profile/answer', value===undefined?{qid:q.id,free_text:text}:{qid:q.id,value});
  if(!r.ok){ window._ob.push({r:'a',t:r.message}); }
  else { const keys=Object.entries(r.compris||{}); if(keys.length>1||r.commentaire) window._ob.push({r:'a',html:(r.commentaire?esc(r.commentaire)+'<br>':'')+(keys.length>1?`<span class="small">J'ai noté : ${keys.map(([k,v])=>`<b>${esc(String(v))}</b>`).join(' · ')}</span>`:'')}); }
  onboarding();
}
function obMulti(){ const v=[...document.querySelectorAll('[data-v].on')].map(b=>b.dataset.v); if(!v.length) return toast('Choisissez au moins une option'); obSend(v, [...document.querySelectorAll('[data-v].on')].map(b=>b.textContent).join(', ')); }
async function obSkip(){ const s=await api('/api/profile'); await api('/api/profile/answer',{qid:s.question.id,skip:true}); onboarding(); }
async function obEdit(id, cur){ const v=prompt('Nouvelle réponse :', cur); if(v===null) return; await api('/api/profile/edit',{id,value:v}); toast('Profil mis à jour'); onboarding(); }

// Après création d'un dossier : direction l'entretien IA
async function createEnt(){
  const k=$('#nKind').value;
  const r=await api('/api/entities',{name:$('#nName').value||'Nouveau dossier',kind:k,legal_form:k=='entreprise'?$('#nForm').value:null,tva_regime:k=='entreprise'?$('#nTva').value:'aucune',tva_exigibilite:k=='entreprise'?$('#nEx').value:'debits',siret:$('#nSiret').value,address:$('#nAddr').value});
  toast('Dossier créé. Faisons connaissance !'); window._ob=[]; TAB='profil'; loadEnts(r.id);
}

// ---------------- Mes impôts (particulier) ----------------
function impotsKpis(d){
  const c=d.calcul, rb=c.solde<0;
  return `<div class="grid kpis">
   <div class="card kpi"><div class="l">Impôt ${d.annee} estimé (IR + prélèvements sociaux)</div><div class="v">${fmt(c.total_a_payer)}</div></div>
   <div class="card kpi"><div class="l">Déjà prélevé à la source</div><div class="v">${fmt(c.deja_preleve)}</div></div>
   <div class="card kpi"><div class="l">${rb?'Remboursement attendu':'Solde à payer'}</div><div class="v" style="color:${rb?'var(--ok)':'var(--ink)'}">${fmt(Math.abs(c.solde))}</div></div>
   <div class="card kpi"><div class="l">Économies trouvées par l'IA</div><div class="v" style="color:var(--ok)">${fmt(d.gain_total)}</div></div>
   <div class="card kpi"><div class="l">Parts · tranche · taux moyen</div><div class="v" style="font-size:1.2rem">${d.parts} · ${c.tmi} · ${c.taux_moyen}</div></div>
   <div class="card kpi"><div class="l">Préparation</div><div class="v">${d.completude} %</div><div style="margin-top:6px">${pill(d.statut)}</div></div></div>`;
}
async function impotsScreen(){
  window._iy=window._iy||YEAR;
  const [d,docs]=await Promise.all([api(`/api/ir/declaration?year=${window._iy}`),api(`/api/ir/documents?year=${window._iy}`)]);
  window._decl=d; const c=d.calcul;
  const forms=Object.entries(c.formulaires);
  $('#view').innerHTML=`<div class="row" style="margin-bottom:14px"><label style="flex-direction:row;align-items:center;gap:8px">Revenus de l'année<select onchange="window._iy=+this.value;impotsScreen()">${[YEAR,YEAR-1,YEAR-2].map(y=>`<option ${y==window._iy?'selected':''}>${y}</option>`).join('')}</select></label>
     <span class="small muted">Déclaration à déposer en ${window._iy+1}</span></div>
   ${impotsKpis(d)}
   <div class="al ${d.automatique.eligible?'ok':'info'}">${esc(d.automatique.explication)}</div>
   <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));margin-top:20px">
   <div class="card"><h2>1. Vos justificatifs</h2><p class="muted small">Glissez vos documents : l'IA reconnaît le type (bulletin de décembre, IFU, attestation CESU, reçu de don, avis d'impôt…) et reprend les montants exacts.</p>
    ${dropZone('irDrop','Ajouter des justificatifs','irFiles')}
    <h3>Pièces attendues</h3>${d.pieces.map(p=>`<div class="row" style="padding:6px 0;border-bottom:1px solid var(--line)"><span style="color:${p.recu?'var(--ok)':'var(--muted-2)'};font-weight:700">${p.recu?'✓':'○'}</span><span style="flex:1">${esc(p.piece)}</span></div>`).join('')||'<p class="muted small">Aucune pièce nécessaire.</p>'}
    ${docs.length?`<h3>Documents lus (${docs.length})</h3>${docs.map(x=>`<div class="al info"><div style="flex:1"><b style="font-weight:600">${esc(x.libelle)}</b> <span class="small muted">${esc(x.nom)}</span><div class="small">${Object.entries(x.champs).map(([k,v])=>`${esc(k.replace(/_/g,' '))} : <b>${typeof v=='number'?fmt(v):esc(String(v))}</b>`).join(' · ')||'<span class="muted">aucun montant détecté</span>'}</div></div><button class="g small wr" onclick="api('/api/ir/documents/${x.id}/delete',{}).then(impotsScreen)">Retirer</button></div>`).join('')}`:''}</div>
   <div class="card"><h2>2. Optimisations</h2><p class="muted small">L'agent compare chaque option et applique la plus favorable.</p>
    ${d.optimisations.map(o=>`<div class="al ${o.applique?(o.gain?'ok':'info'):'attention'}"><div style="flex:1"><b style="font-weight:600">${esc(o.titre)}</b>${o.gain?` <span class="tag ok">−${fmt(o.gain)}</span>`:''}<div class="small muted">${esc(o.detail)}</div></div></div>`).join('')||'<p class="muted">Aucune option à arbitrer.</p>'}
    <h3>Contrôles</h3>${d.controles.map(x=>`<div class="al ${lvl(x.niveau)}">${esc(x.message)}</div>`).join('')||'<div class="al ok">Aucune anomalie.</div>'}
    <h3>Votre foyer</h3><p class="small">${d.parts_detail.map(esc).join('<br>')}</p>
    <button class="g small" onclick="irReview()">✦ Relecture complète par l'IA</button><div id="irRev"></div></div></div>
   <div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">3. Votre déclaration ${window._iy}</h2><span class="small muted">Revenu imposable ${fmt(c.revenu_net_imposable)} · RFR ${fmt(c.revenu_fiscal_reference)}</span></div>
    ${forms.map(([f,l])=>`<h3>Formulaire ${esc(f)}</h3><div class="scroll"><table><tr><th style="width:70px">Case</th><th>Libellé</th><th class="n">Montant</th><th>Provenance</th></tr>${l.map(x=>`<tr><td><b>${esc(x.case)}</b></td><td>${esc(x.libelle)}</td><td class="n">${typeof x.montant=='number'?fmt(x.montant):esc(String(x.montant))}</td><td><span class="tag ${String(x.source||'').startsWith('document')?'ok':x.source=='profil'?'warn':'acc'}">${esc(x.source||'—')}</span></td></tr>`).join('')}</table></div>`).join('')}
    ${d.formulaires_annexes.length?`<h3>Annexes à joindre</h3>${d.formulaires_annexes.map(f=>`<div class="al info"><b style="font-weight:600">${esc(f.formulaire)}</b>&nbsp;— ${esc(f.objet)}</div>`).join('')}`:''}
    <h3>Détail du calcul</h3><table>${[['Revenu brut global',c.revenu_brut_global],['Revenu net imposable',c.revenu_net_imposable],['Impôt au barème',c.impot_bareme],['Plafonnement du quotient familial',c.plafonnement_qf],['Décote',-c.decote],...Object.entries(c.detail_reductions).map(([k,v])=>['Réduction : '+k,-v]),...Object.entries(c.detail_credits).map(([k,v])=>['Crédit : '+k,-v]),['Prélèvement forfaitaire (PFU)',c.pfu_ir],['Prélèvements sociaux',c.prelevements_sociaux],['Total',c.total_a_payer]].filter(r=>r[1]).map(([k,v],i,a)=>`<tr${i==a.length-1?' style="font-weight:700"':''}><td>${esc(k)}</td><td class="n">${fmt(v)}</td></tr>`).join('')}</table>
    ${c.notes.map(n=>`<div class="al info">${esc(n)}</div>`).join('')}</div>
   <div class="card"><h2>4. Déclarer</h2><p class="muted small">Si votre expert-comptable (tiers déclarant habilité) est connecté en EDI, l'IA transmet la déclaration directement. Sinon, elle vous guide écran par écran sur impots.gouv.fr — la DGFiP ne permet pas à un logiciel de déposer à la place d'un particulier.</p>
    <button class="b" onclick="irSubmit()">${d.statut=='prete'?'Déclarer maintenant':'Préparer le dépôt (pièces manquantes signalées)'}</button><div id="irOut"></div></div>`;
}
async function irFiles(f){ if(!f) return; $('#irDrop').innerHTML='Lecture du document…';
  try{ const r=await api('/api/ir/documents',{year:window._iy,file:{name:f.name,mime:f.type,data:await readB64(f)}}); toast(`${r.libelle} reconnu`); }catch(e){}
  impotsScreen(); }
async function irReview(){ $('#irRev').innerHTML='<p class="muted small">Relecture en cours…</p>'; const r=await api('/api/ir/review',{year:window._iy});
  $('#irRev').innerHTML = r.remarques ? r.remarques.map(x=>`<div class="al ${lvl(x.niveau)}">${esc(x.message)}</div>`).join('') : `<div class="al info">La relecture approfondie nécessite Claude (ANTHROPIC_API_KEY). Les contrôles automatiques ci-dessus restent actifs.</div>`; }
async function irSubmit(){
  const r=await api('/api/ir/submit',{year:window._iy}); const cp=r.copilote;
  $('#irOut').innerHTML=`<div class="card" style="margin-top:16px"><h3 style="margin-top:0">Déclaration n° ${r.id} — ${pill(r.status)}</h3>
   ${r.edi?`<div class="al ${r.edi.status=='accepte'?'ok':'critique'}">EDI-IR (${esc(r.edi.ref||'—')}) : ${esc(r.edi.message||r.edi.status)}</div>`:''}
   ${r.erreurs.map(e=>`<div class="al critique">${esc(e)}</div>`).join('')}${r.depot?`<div class="al attention">${esc(r.depot)}</div>`:''}
   <h3>Copilote impots.gouv.fr</h3><ol>${cp.etapes.map(e=>`<li><b style="font-weight:600">${esc(e.etape)}</b> — ${esc(e.consigne)}</li>`).join('')}</ol>
   <div class="scroll"><table><tr><th>Formulaire</th><th>Case</th><th>Libellé</th><th class="n">Montant</th><th></th></tr>${cp.cases.map(x=>`<tr><td>${esc(x.formulaire)}</td><td><b>${esc(x.case)}</b></td><td>${esc(x.libelle)}</td><td class="n">${typeof x.montant=='number'?fmt(x.montant):esc(String(x.montant))}</td><td><button class="g small" onclick="navigator.clipboard&&navigator.clipboard.writeText('${typeof x.montant=='number'?x.montant:''}');toast('Copié : ${esc(x.case)}')">Copier</button></td></tr>`).join('')}</table></div>
   <p class="row"><button class="g" onclick="api('/api/declarations/${r.id}/filed',{}).then(()=>toast('Déclaration marquée comme déposée'))">J'ai signé ma déclaration</button></p></div>`;
}

// ---------------- Déclarations de l'entreprise ----------------
async function declScreen(){
  const [o,s]=await Promise.all([api(`/api/obligations?year=${YEAR}`),api('/api/settings')]);
  const due=o.obligations.filter(x=>x.exigible&&!['deposee','simulee','transmise'].includes(x.statut));
  const mode=s.settings.edi_mode||'off';
  $('#view').innerHTML=`<div class="card"><div class="row" style="justify-content:space-between"><div><h2 style="margin:0">Obligations ${YEAR}</h2>
    <p class="small muted">TVA : ${({reel_mensuel:'CA3 mensuelle',reel:'CA3 mensuelle',reel_trimestriel:'CA3 trimestrielle',rsi:'régime simplifié (CA12)',franchise:'franchise en base'})[o.periodicite_tva]||o.periodicite_tva} · Transmission : ${({off:'manuelle (guide)',sandbox:'simulation EDI (test)',http:'partenaire EDI'})[mode]}</p></div>
    ${due.length?`<button class="b" onclick="declAll()">Tout préparer et transmettre (${due.length})</button>`:'<span class="tag ok">À jour</span>'}</div>
    <div class="scroll"><table><tr><th>Échéance</th><th>Déclaration</th><th class="n">Montant</th><th>Statut</th><th></th></tr>
    ${o.obligations.map(x=>`<tr><td style="white-space:nowrap">${new Date(x.echeance).toLocaleDateString('fr-FR')}${x.en_retard?' <span class="tag bad">en retard</span>':''}</td><td>${esc(x.libelle)}</td><td class="n">${x.montant==null?'—':fmt(x.montant)}</td><td>${pill(x.statut)}</td>
     <td class="row"><button class="g small" onclick="declOne('${x.type}','${x.periode}',false)">Voir</button>${x.exigible&&!['deposee','simulee','transmise'].includes(x.statut)?`<button class="g small wr" onclick="declOne('${x.type}','${x.periode}',true)">Déclarer</button>`:''}</td></tr>`).join('')||'<tr><td colspan="5" class="muted">Aucune obligation.</td></tr>'}</table></div><div id="declOut"></div></div>
   ${mode=='off'?`<div class="al info">Pour une transmission entièrement automatique, configurez votre partenaire EDI dans <button class="lnk" onclick="go('set')">Paramètres</button> (ou activez la simulation pour tester).</div>`:''}
`;
}
async function declAll(){ const r=await api('/api/obligations/run',{year:YEAR}); toast(`${r.length} déclaration(s) traitée(s)`); declScreen(); }
async function declOne(type,periode,submit){
  const r=await api('/api/obligations/file',{year:YEAR,type,periode,submit}); const d=r.donnees;
  const lignes=d.lignes||d['2065']||null;
  $('#declOut').innerHTML=`<div class="card" style="margin-top:16px"><h3 style="margin-top:0">${esc(type.toUpperCase())} ${esc(periode)} — ${pill(r.status)}</h3>
   ${r.edi?`<div class="al ${r.edi.status=='accepte'?'ok':'critique'}">EDI (${esc(r.edi.ref||'—')}) : ${esc(r.edi.message||r.edi.status)}</div>`:''}${r.depot?`<div class="al attention">${esc(r.depot)}</div>`:''}
   ${lignes?`<table>${Object.entries(lignes).filter(([k,v])=>v&&v!='0').map(([k,v])=>`<tr><td>${esc(k)}</td><td class="n">${typeof v=='number'?fmt(v):esc(String(v))}</td></tr>`).join('')}</table>`:''}
   ${d.contenu?`<pre style="max-height:200px;overflow:auto">${esc(d.contenu.slice(0,1500))}</pre>`:''}
   ${(r.guide||[]).length?`<ol>${r.guide.map(g=>`<li>${esc(g)}</li>`).join('')}</ol>`:''}</div>`;
  if(submit) setTimeout(declScreen, 1800);
}

// ---------------- Clients & fournisseurs, lettrage ----------------
async function tiersScreen(t){
  window._tt=t||window._tt||'client';
  const [list,aged]=await Promise.all([api('/api/tiers?type='+window._tt),window._tt=='client'?api('/api/aged?type=client'):null]);
  $('#view').innerHTML=`${seg('tseg',[['client','Clients'],['fournisseur','Fournisseurs']],window._tt,'tiersScreen')}
   <div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">${window._tt=='client'?'Clients':'Fournisseurs'} (${list.length})</h2><div class="row"><button class="g small wr" onclick="api('/api/lettrage/auto',{}).then(r=>{toast(r.lettrages+' lettrage(s) effectué(s)');tiersScreen()})">Lettrage automatique</button><button class="g small wr" onclick="tiersNew()">+ Nouveau</button></div></div>
   <div class="scroll"><table><tr><th>Nom</th><th>Compte</th><th>Pays</th><th class="n">Factures</th><th class="n">${window._tt=='client'?'À encaisser':'À payer'}</th><th></th></tr>
   ${list.map(t=>`<tr><td><b style="font-weight:600">${esc(t.nom)}</b>${t.email?`<div class="small muted">${esc(t.email)}</div>`:''}</td><td><code>${esc(t.account)}</code></td><td>${esc(t.pays||'')}${t.tva_intra?` <span class="small muted">${esc(t.tva_intra)}</span>`:''}</td><td class="n">${t.nb_factures}</td><td class="n">${fmt(t.solde)}</td><td><button class="g small" onclick="tiersOpen(${t.id})">Ouvrir</button></td></tr>`).join('')||'<tr><td colspan="6" class="muted">Les tiers sont créés automatiquement à chaque facture.</td></tr>'}</table></div><div id="tOut"></div></div>
   ${aged&&aged.lignes.length?`<div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">Balance âgée clients</h2>${exportBtns('agee')}</div><div class="scroll"><table><tr><th>Client</th>${aged.colonnes.map(c=>`<th class="n">${c}</th>`).join('')}<th class="n">Total</th></tr>
    ${[...aged.lignes,aged.total].map((l,i,a)=>`<tr${i==a.length-1?' style="font-weight:700"':''}><td>${esc(l.tiers)}</td>${aged.colonnes.map(c=>`<td class="n" style="${c=='> 90 j'&&l[c]?'color:var(--bad)':''}">${l[c]?fmt(l[c]):'—'}</td>`).join('')}<td class="n">${fmt(l.total)}</td></tr>`).join('')}</table></div></div>`:''}`;
}
async function tiersOpen(id){
  const r=await api(`/api/tiers/${id}/lines`); const t=r.tiers; window._tl=r;
  const f=(k,l,ty='text')=>`<label>${l}<input id="tf_${k}" type="${ty}" value="${esc(t[k]??'')}"></label>`;
  $('#tOut').innerHTML=`<div class="card" style="margin-top:16px"><div class="row" style="justify-content:space-between"><h3 style="margin:0">${esc(t.nom)} · <code>${esc(t.account)}</code></h3>${r.risque?`<span class="tag ${r.risque.score>=80?'ok':r.risque.score>=50?'warn':'bad'}">Score ${r.risque.score}/100 · ${esc(r.risque.commentaire)}</span>`:''}</div>
   <div class="form" style="margin-top:12px">${f('email','E-mail','email')}${f('siren','SIREN')}${f('tva_intra','N° TVA intracommunautaire')}${f('pays','Pays (code ISO)')}${f('delai_jours','Délai de paiement (jours)','number')}${f('adresse','Adresse')}<button class="b" onclick="tiersSave(${id})">Enregistrer</button></div>
   <h3>Grand livre du tiers</h3><div class="scroll"><table><tr><th></th><th>Date</th><th>Jnl</th><th>Libellé</th><th class="n">Débit</th><th class="n">Crédit</th><th>Lettrage</th></tr>
   ${r.lignes.map(l=>`<tr><td>${l.lettrage?'':`<input type="checkbox" class="lt" value="${l.id}" style="min-height:0">`}</td><td>${l.date}</td><td>${l.journal}</td><td>${esc(l.label)}</td><td class="n">${l.debit?fmt(l.debit):''}</td><td class="n">${l.credit?fmt(l.credit):''}</td>
    <td>${l.lettrage?`<span class="tag ok">${l.lettrage}</span> <button class="lnk small wr" onclick="api('/api/lettrage/undo',{account:'${t.account}',code:'${l.lettrage}'}).then(()=>tiersOpen(${id}))">délettrer</button>`:''}</td></tr>`).join('')}</table></div>
   <p class="wr"><button class="g" onclick="letterSel(${id})">Lettrer la sélection</button></p></div>`;
  $('#tOut').scrollIntoView({behavior:'smooth'});
}
async function tiersSave(id){ const b={}; ['email','siren','tva_intra','pays','delai_jours','adresse'].forEach(k=>b[k]=$('#tf_'+k).value); await api(`/api/tiers/${id}`,b); toast('Fiche enregistrée'); }
async function letterSel(id){ const ids=[...document.querySelectorAll('.lt:checked')].map(x=>+x.value); const r=await api('/api/lettrage',{line_ids:ids}); toast('Lettrage '+r.code); tiersOpen(id); }
async function tiersNew(){ const nom=prompt('Nom du '+(window._tt=='client'?'client':'fournisseur')+' :'); if(!nom) return; await api('/api/tiers',{type:window._tt,nom}); tiersScreen(); }

// Factures : opérations internationales
const _inv = inv;
inv = async function(){
  await _inv();
  const lab=document.querySelector('#iNat')?.closest('label'); if(!lab) return;
  lab.insertAdjacentHTML('afterend',`<label>Opération<select id="iOp" onchange="document.querySelectorAll('.intl').forEach(e=>e.classList.toggle('hidden',this.value=='france'))">
    <option value="france">France (TVA française)</option><option value="ue_services">Services UE (autoliquidation)</option><option value="ue_biens">Biens UE (livraison intracom.)</option><option value="export">Export hors UE</option><option value="btp">Sous-traitance BTP</option></select></label>
    <label class="intl hidden">N° TVA intracommunautaire du tiers<input id="iTva"></label><label class="intl hidden">Pays (code ISO)<input id="iPays" placeholder="DE"></label>`);
};
saveInv = async function(){
  const lines=[...document.querySelectorAll('.il')].map(d=>({label:d.querySelector('.lL').value,qty:+d.querySelector('.lQ').value,unit_price:+d.querySelector('.lU').value,tva_rate:+d.querySelector('.lR').value})).filter(l=>l.unit_price);
  await api('/api/invoices',{kind:$('#iK').value,party:$('#iP').value||'—',date:$('#iD').value,number:$('#iN').value||null,account:$('#iA').value||null,nature:$('#iNat').value,email:$('#iEm').value||null,
    operation:$('#iOp')?.value||'france',tva_intra:$('#iTva')?.value||null,pays:$('#iPays')?.value||null,lines});
  toast('Facture enregistrée et comptabilisée'); inv();
};

// ---------------- Comptabilité : journal, recherche, grand livre, rapprochement ----------------
async function comptaScreen(k){
  window._cs=k||window._cs||'journal';
  $('#view').innerHTML=seg('cseg',[['journal','Journal'],['search','Recherche'],['gl','Grand livre'],['rappro','Rapprochement bancaire']],window._cs,'comptaScreen')+'<div id="csv"></div>';
  const v=$('#csv');
  if(window._cs=='journal'){ await jrn(); $('#view').insertAdjacentHTML('afterbegin', seg('cseg',[['journal','Journal'],['search','Recherche'],['gl','Grand livre'],['rappro','Rapprochement bancaire']],'journal','comptaScreen')); return; }
  if(window._cs=='search'){
    v.innerHTML=`<div class="card"><div class="form"><label>Texte (libellé, référence)<input id="sQ"></label><label>Compte (début)<input id="sA" placeholder="606, 411…"></label><label>Montant min<input id="sMi" type="number"></label><label>Montant max<input id="sMa" type="number"></label>
     <label>Du<input type="date" id="sS"></label><label>Au<input type="date" id="sE"></label><button class="b calc" onclick="doSearch()">Rechercher</button></div><div id="sOut"></div></div>`; return; }
  if(window._cs=='gl'){
    const accs=await api('/api/reports/balance?year='+YEAR);
    v.innerHTML=`<div class="card"><div class="row" style="justify-content:space-between"><label style="flex-direction:row;align-items:center;gap:8px">Compte<select id="glA" onchange="glShow()">${accs.rows.map(r=>`<option value="${r.account}">${r.account} — ${esc(r.label||'')}</option>`).join('')}</select></label>${exportBtns('grandlivre')}</div><div id="glOut"></div></div>`; glShow(); return; }
  if(window._cs=='rappro'){
    v.innerHTML=`<div class="card"><p class="muted small">Saisissez le solde de votre relevé bancaire à une date : le logiciel liste les opérations non pointées et vérifie que tout concorde.</p>
     <div class="form"><label>Date du relevé<input type="date" id="rD" value="${YEAR}-12-31"></label><label>Solde du relevé (€)<input type="number" step="0.01" id="rS"></label><button class="b" onclick="rappro(true)">Rapprocher</button></div><div id="rOut"></div></div>`; rappro(false); }
}
async function doSearch(more){ const p=new URLSearchParams({q:$('#sQ').value,account:$('#sA').value,min:$('#sMi').value,max:$('#sMa').value,start:$('#sS').value,end:$('#sE').value,limit:200,offset:more?(window._sItems||[]).length:0});
  const r=await api('/api/search?'+p); window._sItems=more?(window._sItems||[]).concat(r.items):r.items;
  $('#sOut').innerHTML=`<p class="muted small" style="margin-top:12px">${window._sItems.length} sur ${r.nombre} écriture(s)</p>`+entriesTable(window._sItems)+(window._sItems.length<r.nombre?`<p><button class="g small" onclick="doSearch(true)">Afficher plus</button></p>`:''); }
function entriesTable(list){ return `<div class="scroll"><table><tr><th>Date</th><th>Jnl</th><th>Libellé</th><th>Compte</th><th class="n">Débit</th><th class="n">Crédit</th><th></th></tr>
  ${list.map(e=>e.lines.map((l,i)=>`<tr${i?'':' style="border-top:2px solid var(--line)"'}><td>${i?'':e.date}</td><td>${i?'':e.journal}</td><td>${i?'':esc(e.label)+(e.reversed_by?' <span class="tag">annulée</span>':e.reversal_of?' <span class="tag">contre-passation</span>':'')}</td><td>${l.account}${l.lettrage?` <span class="tag ok">${l.lettrage}</span>`:''}</td><td class="n">${l.debit?fmt(l.debit):''}</td><td class="n">${l.credit?fmt(l.credit):''}</td>
  <td>${i?'':`<span class="row" style="gap:4px">${e.reversed_by||e.reversal_of?'':`<button class="g small wr" onclick="reverseEntry(${e.id})">Extourner</button>`}<button class="g small wr" onclick="attachTo(${e.id})">Pièce${e.pieces?' ('+e.pieces+')':''}</button></span>`}</td></tr>`).join('')).join('')}</table></div>`; }
async function reverseEntry(id){ const d=prompt('Date de l\'extourne (AAAA-MM-JJ) :', today()); if(!d) return; await api(`/api/entries/${id}/reverse`,{date:d}); toast('Écriture extournée'); comptaScreen(); }
function attachTo(id){ const i=document.createElement('input'); i.type='file'; i.accept='.pdf,image/*'; i.onchange=async()=>{ const f=i.files[0]; await api('/api/attachments',{entry_id:id,file:{name:f.name,mime:f.type,data:await readB64(f)}}); toast('Pièce jointe archivée'); }; i.click(); }
async function glShow(){ const a=$('#glA').value; const r=await api(`/api/reports/grand-livre?year=${YEAR}&account=${encodeURIComponent(a)}`);
  $('#glOut').innerHTML=`<div class="scroll"><table><tr><th>Date</th><th>Jnl</th><th>Libellé</th><th class="n">Débit</th><th class="n">Crédit</th><th class="n">Solde</th></tr>${r.map(g=>`<tr><td>${g.date}</td><td>${g.journal}</td><td>${esc(g.label)}</td><td class="n">${g.debit?fmt(g.debit):''}</td><td class="n">${g.credit?fmt(g.credit):''}</td><td class="n">${fmt(g.cumul)}</td></tr>`).join('')||'<tr><td colspan="6" class="muted">Aucun mouvement.</td></tr>'}</table></div>`; }
async function rappro(save){
  const d=$('#rD').value, s=$('#rS').value;
  const r = save&&s!=='' ? await api('/api/rappro/statement',{date:d,solde:+s}) : await api(`/api/rappro?date=${d}`+(s!==''?`&solde=${s}`:''));
  $('#rOut').innerHTML=`<div class="grid kpis" style="margin-top:16px">${[['Solde comptable (512)',r.solde_comptable],['Solde du relevé',r.solde_releve],['Encaissements non pointés',r.encaissements_non_pointes],['Décaissements non pointés',r.decaissements_non_pointes],['Écart',r.ecart]].filter(x=>x[1]!=null).map(([l,v])=>`<div class="card kpi"><div class="l">${l}</div><div class="v" style="${l=='Écart'&&v?'color:var(--bad)':''}">${fmt(v)}</div></div>`).join('')}</div>
   ${r.equilibre!=null?`<div class="al ${r.equilibre?'ok':'critique'}">${r.equilibre?'Rapprochement équilibré : la comptabilité concorde avec la banque.':'Écart à expliquer : pointez les opérations présentes sur le relevé, ou recherchez une opération manquante.'}</div>`:''}
   <h3>Opérations non pointées</h3><div class="scroll"><table><tr><th>Pointer</th><th>Date</th><th>Libellé</th><th class="n">Débit</th><th class="n">Crédit</th></tr>${r.lignes_non_pointees.map(l=>`<tr><td><input type="checkbox" style="min-height:0" onchange="api('/api/lines/${l.id}/point',{value:this.checked}).then(()=>rappro(false))"></td><td>${l.date}</td><td>${esc(l.label)}</td><td class="n">${l.debit?fmt(l.debit):''}</td><td class="n">${l.credit?fmt(l.credit):''}</td></tr>`).join('')||'<tr><td colspan="5" class="muted">Tout est pointé.</td></tr>'}</table></div>`;
}

// ---------------- Analyse & trésorerie ----------------
async function analyseScreen(k){
  window._as=k||window._as||'sig';
  $('#view').innerHTML=seg('aseg',[['sig','Rentabilité'],['tresorerie','Trésorerie prévisionnelle'],['budget','Budget']],window._as,'analyseScreen')+'<div id="asv"></div>';
  const v=$('#asv');
  if(window._as=='sig'){
    const [s,r]=await Promise.all([api('/api/analysis/sig?year='+YEAR),api('/api/analysis/ratios?year='+YEAR)]); const se=r.seuil;
    v.innerHTML=`<div class="card"><div class="row" style="justify-content:space-between"><h2 style="margin:0">Soldes intermédiaires de gestion</h2>${exportBtns('sig')}</div><div class="scroll"><table><tr><th>Solde</th><th class="n">Montant</th><th class="n">% du CA</th></tr>
      ${s.lignes.map(l=>`<tr style="${l.total?'font-weight:700;background:var(--panel-2)':''}"><td>${esc(l.libelle)}</td><td class="n">${fmt(l.montant)}</td><td class="n muted">${l.pct_ca==null?'':l.pct_ca+' %'}</td></tr>`).join('')}</table></div></div>
     <div class="card"><h2>Ratios clés</h2><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(min(100%,260px),1fr))">${r.ratios.map(x=>`<div class="card kpi" style="background:var(--panel-2);margin:0"><div class="l">${esc(x.ratio)}</div><div class="v" style="font-size:1.35rem">${x.valeur==null?'—':x.unite=='€'?fmt(x.valeur):x.valeur+' '+x.unite}</div>${x.aide?`<div class="small muted" style="margin-top:6px">${esc(x.aide)}</div>`:''}</div>`).join('')}</div></div>
     ${se.seuil!=null?`<div class="card"><h2>Seuil de rentabilité</h2><div class="grid kpis">${[['Chiffre d\'affaires',se.chiffre_affaires],['Charges fixes',se.charges_fixes],['Seuil de rentabilité',se.seuil],['Marge de sécurité',se.marge_securite]].map(([l,v])=>`<div class="card kpi"><div class="l">${l}</div><div class="v">${fmt(v)}</div></div>`).join('')}</div><div class="al info">${esc(se.commentaire)} · taux de marge sur coûts variables : ${se.taux_marge_cout_variable} %</div></div>`:''}`;
  }
  if(window._as=='tresorerie'){
    const f=await api('/api/analysis/forecast?months=12');
    const vals=f.mois.map(m=>m.solde_fin); const mx=Math.max(1,...vals.map(Math.abs)); const W=1080,H=200,bw=W/vals.length,z=H/2;
    const bars=f.mois.map((m,i)=>{const h=Math.abs(m.solde_fin)/mx*(H/2-10);const y=m.solde_fin>=0?z-h:z;return `<rect x="${i*bw+bw*.2}" y="${y}" width="${bw*.6}" height="${h}" rx="6" fill="${m.solde_fin<0?'var(--bad)':'var(--prod)'}"><title>${m.mois} : ${fmt(m.solde_fin)}</title></rect><text x="${i*bw+bw/2}" y="${H+16}" font-size="12" text-anchor="middle" fill="var(--muted)">${m.mois.slice(5)}/${m.mois.slice(2,4)}</text>`}).join('');
    v.innerHTML=`<div class="card"><div class="al ${f.premier_mois_negatif?'critique':'ok'}" style="margin-top:0">${esc(f.commentaire)}</div><p class="small muted">Trésorerie actuelle ${fmt(f.tresorerie_actuelle)} · encaissements des factures ouvertes à échéance, devis pondérés, salaires, opérations récurrentes détectées et TVA.</p>
      <svg viewBox="0 0 ${W} ${H+22}" style="width:100%;height:auto"><line x1="0" x2="${W}" y1="${z}" y2="${z}" stroke="var(--hair)"/>${bars}</svg>
      <div class="scroll"><table><tr><th>Mois</th><th>Détail des flux</th><th class="n">Flux</th><th class="n">Solde fin de mois</th></tr>${f.mois.map(m=>`<tr><td>${m.mois}</td><td class="small">${Object.entries(m.detail).map(([k,v])=>`${esc(k)} : <b>${fmt(v)}</b>`).join(' · ')||'—'}</td><td class="n">${fmt(m.flux)}</td><td class="n" style="${m.alerte?'color:var(--bad);font-weight:700':''}">${fmt(m.solde_fin)}</td></tr>`).join('')}</table></div></div>`;
  }
  if(window._as=='budget'){
    const b=await api('/api/budget?year='+YEAR); ACCS=await api('/api/accounts');
    v.innerHTML=`<div class="card"><div class="form wr"><label>Compte<select id="bA">${ACCS.filter(a=>/^[67]/.test(a.code)).map(a=>`<option value="${a.code}">${a.code} ${esc(a.label)}</option>`).join('')}</select></label><label>Budget annuel (€)<input id="bV" type="number"></label><button class="b" onclick="api('/api/budget',{year:YEAR,account:$('#bA').value,annual:+$('#bV').value}).then(()=>analyseScreen('budget'))">Ajouter</button></div>
      <div class="scroll" style="margin-top:14px"><table><tr><th>Compte</th><th class="n">Budget</th><th class="n">Réalisé</th><th class="n">Écart</th><th style="width:30%">Consommation</th></tr>${b.map(x=>`<tr><td>${x.compte} ${esc(x.libelle||'')}</td><td class="n">${fmt(x.budget)}</td><td class="n">${fmt(x.reel)}</td><td class="n">${fmt(x.ecart)}</td><td><div style="height:8px;background:var(--line);border-radius:4px;overflow:hidden"><i style="display:block;height:100%;width:${Math.min(100,x.taux||0)}%;background:${(x.taux||0)>100?'var(--bad)':'var(--prod)'}"></i></div><span class="small muted">${x.taux??'—'} %</span></td></tr>`).join('')||'<tr><td colspan="5" class="muted">Définissez un budget par compte pour suivre les écarts.</td></tr>'}</table></div></div>`;
  }
}

// ---------------- Clôture : révision complète ----------------
async function closeScreen(){
  await close();
  if(ENT.kind!='entreprise') return;
  const sug=await api('/api/regularisations/suggest?year='+YEAR);
  window._sug=sug;
  $('#view').insertAdjacentHTML('afterbegin',`<div class="card"><h2>Régularisations de fin d'exercice</h2>
    <p class="muted small">Rattachez chaque charge et chaque produit au bon exercice. Les régularisations sont extournées automatiquement au 1er janvier.</p>
    ${sug.map((x,i)=>`<div class="al info"><div style="flex:1"><b style="font-weight:600">${esc(x.libelle)}</b> <span class="tag acc">${esc(x.type.toUpperCase())}</span> ${fmt(x.montant)}<div class="small muted">${esc(x.raison)}</div></div><button class="g small wr" onclick="regulSug(${i})">Passer l'écriture</button></div>`).join('')||'<div class="al ok">Aucune régularisation détectée automatiquement.</div>'}
    <h3>Saisie manuelle</h3><div class="form wr"><label>Type<select id="rgT"><option value="cca">Charge constatée d'avance</option><option value="pca">Produit constaté d'avance</option><option value="fnp">Facture non parvenue</option><option value="fae">Facture à établir</option><option value="cap">Charge à payer</option><option value="provision">Provision pour risques</option><option value="depreciation_client">Dépréciation créance</option></select></label>
     <label>Compte de charge / produit<input id="rgA" placeholder="616, 706…"></label><label>Montant HT (€)<input id="rgM" type="number" step="0.01"></label><label>Libellé<input id="rgL"></label><button class="b" onclick="regulManual()">Passer</button></div></div>
   <div class="card"><h2>Affectation du résultat ${YEAR}</h2><p class="muted small">Après approbation des comptes : réserve légale (5 % jusqu'à 10 % du capital, calculée automatiquement), dividendes, report à nouveau.</p>
    <div class="form wr"><label>Date de l'assemblée<input type="date" id="afD" value="${YEAR+1}-06-30"></label><label>Dividendes (€)<input id="afV" type="number" value="0"></label><button class="b" onclick="api('/api/result/allocate',{year:YEAR,date:$('#afD').value,dividendes:+$('#afV').value}).then(r=>toast('Affectation comptabilisée : report à nouveau '+fmt(r.report_a_nouveau)))">Affecter le résultat</button></div></div>`);
}
async function regulSug(i){ const x=window._sug[i]; await api('/api/regularisations',{type:x.type,account:x.compte,montant:x.montant,year:YEAR,label:x.libelle}); toast('Régularisation comptabilisée'); closeScreen(); }
async function regulManual(){ await api('/api/regularisations',{type:$('#rgT').value,account:$('#rgA').value,montant:+$('#rgM').value,year:YEAR,label:$('#rgL').value}); toast('Régularisation comptabilisée'); closeScreen(); }

// ---------------- Agents IA (chat multi-experts) ----------------
async function agentsScreen(name){
  const list=await api('/api/agents');
  const avail = ENT.kind=='particulier' ? list.filter(a=>['impots','banque','comptable'].includes(a.id)) : list.filter(a=>a.id!='impots');
  window._ag = name || window._ag || avail[0].id; if(!avail.some(a=>a.id==window._ag)) window._ag=avail[0].id;
  window._hist = window._hist || {}; const h = window._hist[window._ag] = window._hist[window._ag] || [];
  const a = await api(`/api/agents/${window._ag}?year=${YEAR}`);
  $('#view').innerHTML=`<div class="grid" style="grid-template-columns:minmax(0,280px) minmax(0,1fr);align-items:start" id="agGrid">
   <div class="card" style="padding:14px">${avail.map(x=>`<button class="g" style="width:100%;justify-content:flex-start;margin-bottom:8px;text-align:left;${x.id==window._ag?'background:var(--soft);border-color:var(--accent)':''}" onclick="agentsScreen('${x.id}')"><span><b style="font-weight:600">${esc(x.titre)}</b><br><span class="small muted">${esc(x.description)}</span></span></button>`).join('')}</div>
   <div class="card"><h2>${esc(a.titre)}</h2><p class="muted small">${esc(a.description)} · ${a.ia?'Claude connecté':'mode local'}</p>
    ${a.analyses.slice(0,3).map(i=>`<div class="al ${lvl(i.niveau)}">${esc(i.titre)}</div>`).join('')}
    <div class="chat" id="chat">${h.map(m=>`<div class="msg ${m.r}">${m.r=='a'?md(m.t):esc(m.t)}</div>`).join('')}</div>
    <div class="row"><input id="q" style="flex:1;min-width:200px" placeholder="Votre question…" onkeydown="if(event.key=='Enter')agSend()"><button class="b calc" onclick="agSend()">Envoyer</button></div>
    <div class="row small" style="margin-top:8px">${a.suggestions.map(s=>`<button class="g small calc" onclick="$('#q').value=this.textContent;agSend()">${esc(s)}</button>`).join('')}</div></div></div>`;
  if(innerWidth<760) $('#agGrid').style.gridTemplateColumns='1fr';
  const c=$('#chat'); c.scrollTop=c.scrollHeight;
}
async function agSend(){ const q=$('#q').value.trim(); if(!q) return; const h=window._hist[window._ag]; h.push({r:'u',t:q}); await agentsScreen();
  const r=await api(`/api/agents/${window._ag}/ask`,{question:q,year:YEAR,history:h.slice(-6)}); h.push({r:'a',t:r.answer}); agentsScreen(); }

// Le bouton flottant ouvre l'agent du domaine courant
document.querySelector('.fab').onclick = () => { const map={bank:'banque',inv:'ventes',quotes:'ventes',tiers:'ventes',ndf:'depenses',pay:'paie',decl:'tva',tax:'fiscal',close:'cloture',analyse:'tresorerie',rep:'conseil',impots:'impots'}; window._ag=map[TAB]||window._ag; go('ai'); };

const css=document.createElement('style'); css.textContent=`.fabdot{width:34px;height:34px;border-radius:50%;background:var(--halo);display:grid;place-items:center;color:#fff;flex:none;box-shadow:0 0 16px rgba(224,86,193,.35)}
 .agentcard{border:1px solid var(--line)} .seg button{white-space:nowrap} .seg{max-width:100%;overflow-x:auto}`;
document.head.appendChild(css);
init();
