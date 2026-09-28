#!/usr/bin/env node
// Test du routeur de l'UI (spec-ui-deep-links, UI >= 1.14.0) — sans dépendance, sans DOM.
// Extrait les fonctions pures routePath/parseRoute/pageTitle de borgHelperWWW_ui.html et vérifie la
// matrice d'adresses (analyse, adresses invalides, aller-retour d'encodage état -> adresse -> état) et
// le titre de l'onglet de chaque page (UI >= 1.15.0).
//
//   node borgHelperWWW_ui_test.js [chemin/vers/borgHelperWWW_ui.html]
//
// Code de sortie 0 si tout passe, 1 sinon.
'use strict';
const fs=require('fs'), path=require('path');

const htmlPath=process.argv[2]||path.join(__dirname,'borgHelperWWW_ui.html');
const src=fs.readFileSync(htmlPath,'utf8');

// Corps d'une fonction top-level par appariement d'accolades (ces deux fonctions n'en contiennent
// aucune dans leurs chaînes).
function grab(name){
  const i=src.indexOf('function '+name+'(');
  if(i<0) throw new Error(`function ${name}( introuvable dans ${htmlPath}`);
  let depth=0, j=src.indexOf('{',i);
  for(;;j++){
    if(src[j]==='{') depth++;
    else if(src[j]==='}' && --depth===0) break;
  }
  return src.slice(i,j+1);
}
const {routePath,parseRoute,pageTitle}=new Function(grab('routePath')+'\n'+grab('parseRoute')+'\n'+grab('pageTitle')
  +'\nreturn {routePath,parseRoute,pageTitle};')();

let fail=0;
function eq(name,got,want){
  const ok=JSON.stringify(got)===JSON.stringify(want);
  if(!ok) fail++;
  console.log((ok?'OK  ':'FAIL')+' '+name+(ok?'':' → '+JSON.stringify(got)+' ≠ '+JSON.stringify(want)));
}
// Aller-retour : l'adresse produite pour un état redonne exactement cet état.
function roundTrip(name,st){
  const u=routePath(st);
  const url=new URL(u,'https://h');
  const p=parseRoute(url.pathname,url.search);
  eq(name+' ['+u+']',{view:p.view,nick:p.nick,path:p.path,archive:p.archive,changes:p.changes??null},
     {view:st.view,nick:st.nick,path:st.path,archive:st.archive,changes:st.changes??null});
}

// État -> adresse
eq('liste',routePath({view:'view-machines'}),'/');
eq('connexion : pas d\'adresse',routePath({view:'view-login'}),null);
eq('chemin avec / de tête et doublés',routePath({view:'view-browse',nick:'s',path:'/etc//x/',archive:null}),'/explorer/s/etc/x');
eq('nick avec / encodé',routePath({view:'view-detail',nick:'a/b'}),'/serveur/a%2Fb');

// Adresse -> état
eq('racine',parseRoute('/',''),{view:'view-machines'});
eq('serveur',parseRoute('/serveur/srv',''),{view:'view-detail',nick:'srv'});
eq('historique',parseRoute('/historique/secret',''),{view:'view-history',nick:'secret'});
eq('notifications',parseRoute('/notifications',''),{view:'view-notifications'});
eq('explorateur, racine',parseRoute('/explorer/srv',''),{view:'view-browse',nick:'srv',path:'',archive:null,changes:null});
eq('explorateur, répertoire',parseRoute('/explorer/srv/etc/nginx',''),{view:'view-browse',nick:'srv',path:'etc/nginx',archive:null,changes:null});
eq('archive épinglée',parseRoute('/explorer/srv/etc','?archive=srv-2026-09-01T0200'),
   {view:'view-browse',nick:'srv',path:'etc',archive:'srv-2026-09-01T0200',changes:null});
// Mode changements (UI >= 1.16.0)
eq('changements : adresse',routePath({view:'view-browse',nick:'srv',path:'etc',archive:null,changes:{from:'a 1',to:'a#2'}}),
   '/explorer/srv/etc?depuis=a%201&jusqua=a%232');
eq('changements : lecture',parseRoute('/explorer/srv/etc','?depuis=a%201&jusqua=a%232'),
   {view:'view-browse',nick:'srv',path:'etc',archive:null,changes:{from:'a 1',to:'a#2'}});
eq('changements prioritaires sur archive',parseRoute('/explorer/srv','?archive=x&depuis=a&jusqua=b').changes,{from:'a',to:'b'});
eq('changements : une seule borne ignorée',parseRoute('/explorer/srv','?depuis=a').changes,null);
eq('nick avec / relu',parseRoute('/serveur/a%2Fb',''),{view:'view-detail',nick:'a/b'});

// Adresses invalides -> liste (l'UI remplace l'adresse par /)
for(const bad of ['/xyz','/explorer','/explorer/','/serveur','/serveur/a/b','/historique',
                  '/historique/a/b','/notifications/x','/%E0%A4%A'])
  eq('invalide '+bad,parseRoute(bad,''),{view:'view-machines',invalid:true});

// Aller-retour d'encodage (espace, é, #, ?, &, =, %)
roundTrip('encodage explorateur',{view:'view-browse',nick:'srv é #1',path:'mes docs/été #?/a&b=c%20',archive:'arch #?&=é'});
roundTrip('encodage historique',{view:'view-history',nick:'n ?#é'});
roundTrip('encodage changements',{view:'view-browse',nick:'s é',path:'a b/c#',archive:null,changes:{from:'x&y=z ?',to:'é/2'}});
roundTrip('encodage serveur',{view:'view-detail',nick:'n:x %'});
roundTrip('explorateur racine sans archive',{view:'view-browse',nick:'srv',path:'',archive:null});

// Titre de l'onglet
const T=' — borgHelperWWW';
eq('titre connexion',pageTitle({view:'view-login'}),'Connexion'+T);
eq('titre liste',pageTitle({view:'view-machines'}),'Serveurs'+T);
eq('titre serveur',pageTitle({view:'view-detail',nick:'srv'}),'🖥 srv'+T);
eq('titre historique',pageTitle({view:'view-history',nick:'srv'}),'📜 srv — Historique'+T);
eq('titre notifications',pageTitle({view:'view-notifications'}),'🔔 Notifications'+T);
eq('titre explorateur racine',pageTitle({view:'view-browse',nick:'srv',path:'',archive:null}),'🗂 srv:/'+T);
eq('titre explorateur répertoire',pageTitle({view:'view-browse',nick:'srv',path:'/etc//nginx/',archive:null}),'🗂 srv:/etc/nginx'+T);
eq('titre explorateur changements',pageTitle({view:'view-browse',nick:'srv',path:'etc',archive:null,changes:{from:'a1',to:'a2'}}),'🗂 srv:/etc (a1 → a2)'+T);
eq('titre explorateur archive',pageTitle({view:'view-browse',nick:'srv',path:'etc',archive:'srv-2026'}),'🗂 srv:/etc @ srv-2026'+T);

// Dépôts externes, état de construction et fin de Bkp (UI >= 1.19.0) : opAllowed, stateBadges, pollAccess extraites,
// DOM et API simulés. Les variables globales de la page (myAccess, currentViewId, currentNick) vivent dans la fermeture.
(async ()=>{
  const calls={reload:[],actions:0,badges:0}; let next=null, hidden=false;
  const env={document:{get hidden(){ return hidden; }},getApiKey:()=>'k',escapeAttr:s=>String(s),
    refreshStateBadges:()=>{ calls.badges++; },reloadMachineCard:n=>{ calls.reload.push(n); },
    renderActionList:()=>{ calls.actions++; }};
  const ui=new Function('env',`let {document,getApiKey,escapeAttr,refreshStateBadges,reloadMachineCard,renderActionList}=env;
    let myAccess=null, currentViewId='view-machines', currentNick=null, pollBusy=false;
    const loadMyAccess=async()=>{ myAccess=env.next(); return myAccess; };
    ${grab('opAllowed')}
${grab('stateBadges')}
async ${grab('pollAccess')}
    return {opAllowed,stateBadges,pollAccess,set:(a,v,n)=>{ myAccess=a; if(v) currentViewId=v; if(n!==undefined) currentNick=n; }};`)(
    Object.assign(env,{next:()=>next}));
  const acc=(o)=>({groups_auth_enabled:false,nicks:o});
  ui.set(null); eq('opAllowed sans /access : tout proposé',ui.opAllowed('x','bkp'),true);
  ui.set(acc({ext:{ops:['read','restore'],external:true},old:{}}));
  eq('opAllowed externe : bkp refusé',ui.opAllowed('ext','bkp'),false);
  eq('opAllowed externe : restore permis',ui.opAllowed('ext','restore'),true);
  eq('opAllowed sans champ ops (ancien serveur) : tout proposé',ui.opAllowed('old','delete'),true);
  ui.set(acc({e:{external:true,ops:['read'],bkp_running:true,build:{state:'partial',pairs_done:1,pairs_total:5,stats_done:2,archives_total:6},
                 rebuild:{state:'complete',pairs_done:5,pairs_total:5}},f:{rebuild:{state:'partial'}},g:{build:{state:'complete'}}}));
  const be=ui.stateBadges('e');
  eq('badges : externe, Bkp en cours, construction 1/5, prête à basculer',
     ['🔗 externe','⏳ Bkp en cours','construction partielle 1/5','prête à basculer'].every(t=>be.includes(t)),true);
  eq('badge reconstruction démarrée (sans build_state)',ui.stateBadges('f').includes('reconstruction démarrée'),true);
  eq('base complète interne : aucun badge',ui.stateBadges('g'),'');
  // fin de Bkp sur la liste : seule la carte du nick dont le Bkp vient de finir est rechargée
  ui.set(acc({a:{bkp_running:true},b:{bkp_running:false},c:{bkp_running:true}}),'view-machines');
  next=acc({a:{bkp_running:false},b:{bkp_running:false},c:{bkp_running:true}});
  await ui.pollAccess();
  eq('fin de Bkp (liste) : carte rechargée pour a seulement',calls.reload,['a']);
  eq('relecture : badges rafraîchis',calls.badges,1);
  // page serveur affichée : actions et badges rafraîchis, aucune carte
  ui.set(acc({a:{bkp_running:true}}),'view-detail','a'); next=acc({a:{bkp_running:false}});
  await ui.pollAccess();
  eq('fin de Bkp (page serveur) : actions rafraîchies',[calls.actions,calls.reload.length],[1,1]);
  // onglet caché / autre vue : aucune relecture
  hidden=true; ui.set(acc({a:{bkp_running:true}}),'view-machines'); next=acc({a:{bkp_running:false}});
  await ui.pollAccess(); hidden=false;
  ui.set(acc({a:{bkp_running:true}}),'view-history'); await ui.pollAccess();
  eq('onglet caché ou autre page : rien',[calls.reload.length,calls.badges],[1,2]);
  ui.set(acc({a:{bkp_running:true}}),'view-machines'); next=acc({a:{bkp_running:null}});
  await ui.pollAccess();
  eq('bkp_running inconnu (null) : jamais pris pour une fin de Bkp',calls.reload.length,1);
  // Actions, historique et carte (UI 1.19.0) : vraies fonctions de la page, DOM minimal simulé.
  const grabConst=name=>{ const i=src.indexOf('const '+name+'=['); let d=0,j=src.indexOf('[',i);
    for(;;j++){ if(src[j]==='[') d++; else if(src[j]===']' && --d===0) break; } return src.slice(i,j+1)+';'; };
  const dom={els:{},byId(id){ return this.els[id]||(this.els[id]={innerHTML:'',textContent:'',classList:{toggle(){}}}); }};
  let reportStdout='', histLoads=[];
  const page=new Function('dom','hooks',`
    const document={getElementById:id=>dom.byId(id),querySelectorAll:()=>[],
      createElement:()=>{ const el={set innerHTML(h){ this._h=h; this.firstElementChild={html:h,querySelector:()=>'panel'}; }}; return el; }};
    let myAccess=null, currentNick=null, currentActionId=null, allowDestructive=true, machineCardsByNick={};
    const SPINNER='…';
    const getPassphrase=()=>'', loadHistoryInline=(n,p)=>hooks.hist.push(n), apiCall=async()=>({stdout:hooks.report()});
    ${grab('escapeHtml')}
${grab('escapeAttr')}
${grab('opAllowed')}
${grab('stateBadges')}
${grab('badgeFor')}
${grab('plainDbBadge')}
    ${grabConst('ACTIONS')}
${grab('renderActionList')}
${grab('_renderHistoryRows')}
${grab('machineCardHtml')}
async ${grab('reloadMachineCard')}
    return {renderActionList,_renderHistoryRows,reloadMachineCard,
      set:(a,n)=>{ myAccess=a; currentNick=n; }, cards:()=>machineCardsByNick};`)(dom,{hist:histLoads,report:()=>reportStdout});
  page.set(acc({ext:{external:true,ops:['read','restore']},int:{ops:['read','restore','prune','delete','bkp']}}),'ext');
  page.renderActionList();
  const listExt=dom.byId('actionList').innerHTML;
  eq('page serveur externe : ni Bkp, ni Init, ni Prune, ni DelBkp ; Restore et Index proposés',
     ['abtn_bkp','abtn_init','abtn_prune','abtn_delbkp'].map(id=>listExt.includes(id)).concat(['abtn_restore','abtn_index'].map(id=>listExt.includes(id))),
     [false,false,false,false,true,true]);
  page.set(acc({ext:{external:true,ops:['read','restore']},int:{ops:['read','restore','prune','delete','bkp']}}),'int');
  page.renderActionList();
  eq('page serveur interne : toutes les actions',['abtn_bkp','abtn_prune','abtn_delbkp'].every(id=>dom.byId('actionList').innerHTML.includes(id)),true);
  const bk={'a-1':{duration:'1s'},Totaux:{}};
  page.set(acc({ext:{ops:['read','restore']}}),'ext');
  eq('historique externe sans delete : pas de 🗑',page._renderHistoryRows(bk,true).html.includes('hist-delete-btn'),false);
  page.set(acc({ext:{ops:['read','restore','delete']}}),'ext');
  eq('historique avec delete : 🗑 proposé',page._renderHistoryRows(bk,true).html.includes('hist-delete-btn'),true);
  // Carte rechargée à la fin d'un Bkp : nouveau rapport affiché, historique relu, sans ▶ Backup pour un externe
  let replaced=null; page.cards().ext={isConnected:true,replaceWith(c){ replaced=c; }};
  page.set(acc({ext:{external:true,ops:['read','restore']}}),'ext');
  reportStdout=JSON.stringify({summary:{ext:{nom:'ext','date derniere':'2026-09-28 10:00','depuis':'0.1 h'}}});
  await page.reloadMachineCard('ext');
  eq('fin de Bkp : carte remplacée avec le nouveau rapport, historique relu, sans ▶ Backup',
     [!!replaced && replaced.html.includes('2026-09-28 10:00'), histLoads.join(), !!replaced && replaced.html.includes('bkp-now-btn'),
      !!replaced && replaced.html.includes('🔗 externe')],[true,'ext',false,true]);
  console.log(fail?fail+' FAIL':'TOUT OK');
  process.exit(fail?1:0);
})();
