#!/usr/bin/env node
// Test de l'UI (spec-ui-deep-links, UI >= 1.14.0) — sans dépendance ; DOM et API simulés pour les parties interactives.
// Extrait les fonctions pures routePath/parseRoute/pageTitle de borgHelperWWW_ui.html et vérifie la
// matrice d'adresses (analyse, adresses invalides, aller-retour d'encodage état -> adresse -> état) et
// le titre de l'onglet de chaque page (UI >= 1.15.0). Puis, DOM et API simulés : badges, fin de Bkp, actions, carte,
// et graphiques de la page Historique (tous construits, séries, archives supprimées, sans lignes, blocs HTML ;
// chargements croisés, rechargement, réponses en erreur, échec partiel, bibliothèque absente ; UI >= 1.24.0 : axe temporel,
// premier Prune, avec la vraie Chart.js de vendor/chartjs sur un canvas simulé) ; bandeau de nettoyage ; UI >= 1.24.1 :
// messages d'erreur (respError) de l'explorateur, de sa recherche et des autres pages (403 capturé, JSON illisible).
// UI >= 1.25.0 (story 86b) : mode dossier — liste, barre de liens et Notifications groupées par fichier de conf (rc_order),
// repli mémorisé ; mode -C : rendu de 1.24.3 à l'octet près.
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
// borgHelperWWW 1.32.0 (story 86) : mode dossier, nick exposé « préfixe:nick » — adresse encodée, relue telle quelle
eq('nick préfixé (mode dossier) encodé',routePath({view:'view-detail',nick:'web:db'}),'/serveur/web%3Adb');
roundTrip('nick préfixé : serveur',{view:'view-detail',nick:'web:db'});
roundTrip('nick préfixé : explorateur',{view:'view-browse',nick:'mail:db',path:'etc/x',archive:null,changes:null});
eq('nick préfixé non encodé (lien tapé)',parseRoute('/historique/web:db',''),{view:'view-history',nick:'web:db'});
// UI 1.24.3 : conseil du badge « base non chiffrée » — commande CLI juste en mode dossier (rc du préfixe nommé, nick nu, aucun chemin)
const dbEncryptCmd=new Function(grab('dbEncryptCmd')+'\nreturn dbEncryptCmd;')();
eq('badge base non chiffrée : nick nu (mode -C)',dbEncryptCmd('srv'),'borgHelper -c DbEncrypt -n srv -y');
eq('badge base non chiffrée : préfixe:nick -> -C <rc du préfixe>, nick nu',dbEncryptCmd('web:db'),
   'borgHelper -C <rc du préfixe web> -c DbEncrypt -n db -y');

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
  let now=1e6;
  const ui=new Function('env',`let {document,getApiKey,escapeAttr,refreshStateBadges,reloadMachineCard,renderActionList}=env;
    let myAccess=null, currentViewId='view-machines', currentNick=null, pollBusy=false;
    const pendingBkp={}, Date={now:()=>env.now(),parse:x=>env.parse(x)};
    const loadMyAccess=async()=>{ myAccess=env.next(); return myAccess; };
    ${grab('opAllowed')}
${grab('stateBadges')}
${grab('bkpRef')}
${grab('notePendingBkp')}
async ${grab('pollAccess')}
    return {opAllowed,stateBadges,pollAccess,notePendingBkp,pending:pendingBkp,set:(a,v,n)=>{ myAccess=a; if(v) currentViewId=v; if(n!==undefined) currentNick=n; }};`)(
    Object.assign(env,{next:()=>next,now:()=>now,parse:x=>globalThis.Date.parse(x)}));
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
  // UI 1.23.1 (story 59, décisions de l'utilisateur) : état de Status relayé par /access (WWW 1.31.5)
  ui.set(acc({o:{bkp_running:true,bkp_detail:'orphelin'},w:{bkp_running:true,bkp_detail:'en_attente'},
              i:{bkp_running:false,bkp_interrupted:{started_at:'2026-10-06 10:00:00',verifie:true}},
              id:{bkp_running:false,bkp_interrupted:{started_at:'2026-10-06 10:00:00',verifie:false}},
              v:{bkp_running:true,bkp_detail:'en_cours'},n:{bkp_running:null}}));
  const bo=ui.stateBadges('o'), bw=ui.stateBadges('w'), bi=ui.stateBadges('i'), bd=ui.stateBadges('id');
  eq('orphelin : « ⏳ Bkp interrompu, borg create encore actif », jamais « Bkp en cours »',
     [bo.includes('⏳ Bkp interrompu, borg create encore actif'),bo.includes('Bkp en cours')],[true,false]);
  eq("en attente : « ⏳ Bkp en attente de l'Index »",[bw.includes("⏳ Bkp en attente de l'Index"),bw.includes('Bkp en cours')],[true,false]);
  eq('interrompu : « ⚠ Bkp interrompu », title borgHelper arrêté + Index, pas de ⏳',
     [bi.includes('⚠ Bkp interrompu'),bi.includes('title="borgHelper arrêté — fermé au prochain Index si son archive existe"'),bi.includes('⏳')],[true,true,false]);
  eq('interrompu non vérifiable : title du dépôt distant',bd.includes('borgHelper arrêté, borg non vérifiable (dépôt distant) — fermé au prochain Index'),true);
  eq('vivant : « ⏳ Bkp en cours » ; inconnu (null) : aucun badge',[ui.stateBadges('v').includes('⏳ Bkp en cours'),ui.stateBadges('n')],[true,'']);
  ui.set(acc({vi:{bkp_running:true,bkp_detail:'en_attente',bkp_interrupted:{started_at:'2026-10-06 09:00:00',verifie:true}}}));
  const bvi=ui.stateBadges('vi');
  eq('revue : en attente ET ligne interrompue d\'un autre run -> les deux badges',[bvi.includes("⏳ Bkp en attente de l'Index"),bvi.includes('⚠ Bkp interrompu')],[true,true]);
  // résultat du dernier Index (UI 1.19.2) : échec/refus toujours ; « déjà en cours » seulement via HTTP, moins d'1 h
  // Heures écrites par borgHelper ≥ 1.0.149 : ISO avec décalage ; « now » absolu (Date.UTC) : juste dans tout fuseau.
  const fin='2026-09-28T10:00:05+02:00', T0=globalThis.Date.UTC(2026,8,28,8,0,5); now=T0+60000;
  const lf={outcome:'error',code:1,via:'cli',finished_at:'2026-09-28T09:00:00+02:00',message:'x: borg list en échec'};
  ui.set(acc({x:{index_last:{outcome:'error',code:1,via:'http',finished_at:fin,message:"x: période refusée"}},
              r:{index_last:{outcome:'refused',code:3,via:'cli',finished_at:fin,message:''}},
              h:{index_last:{outcome:'busy',code:0,via:'http',finished_at:fin,message:'x: Index déjà en cours'}},
              c:{index_last:{outcome:'busy',code:0,via:'cli',finished_at:fin,message:''}},
              k:{index_last:{outcome:'ok',code:0,via:'cli',finished_at:fin,message:''}},
              hb:{index_last:{outcome:'busy',code:0,via:'http',finished_at:fin,message:'x: Index déjà en cours',last_failure:lf}},
              d:{index_last:{outcome:'deadline',code:0,via:'cli',finished_at:fin,message:'',last_failure:lf}}}));
  const bx=ui.stateBadges('x');
  eq('index_last error : badge ⚠ avec heure et message',[bx.includes('⚠ Index en échec'),bx.includes('2026-09-28 10:00'),bx.includes('période refusée')],[true,true,true]);
  eq('index_last refused : badge ⚠ (refusé, code 3)',ui.stateBadges('r').includes('refusé (code 3)'),true);
  eq('index_last busy via http récent : « rien lancé »',ui.stateBadges('h').includes('rien lancé'),true);
  eq('index_last busy via cron, ok : aucun badge',[ui.stateBadges('c'),ui.stateBadges('k')],['','']);
  const hb=ui.stateBadges('hb');
  eq('error puis busy HTTP : ⚠ gardé (last_failure) + « rien lancé »',[hb.includes('⚠ Index en échec'),hb.includes('borg list en échec'),hb.includes('2026-09-28 09:00'),hb.includes('rien lancé')],[true,true,true,true]);
  eq('error puis échéance : ⚠ gardé jusqu\'au prochain ok',ui.stateBadges('d').includes('⚠ Index en échec'),true);
  now=T0-60000;
  eq('busy HTTP, horloge du navigateur en retard d\'1 min : badge montré',ui.stateBadges('h').includes('rien lancé'),true);
  now=T0+2*3600000;
  eq('index_last busy via http de plus d\'1 h : plus de badge',ui.stateBadges('h'),'');
  now=1e6;
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
  // Bkp lancé par ▶ Backup (UI 1.19.3) : suivi par run_id (bkp_last de /access), sans minutage ; myAccess remplacé
  // (loadMachines) sans perdre le suivi ; une seule recharge par Bkp.
  const B=(run,fin,running=false)=>({bkp_running:running,bkp_last:run?{run_id:run,finished_at:fin||null,result:fin?'success':null}:null});
  const R=()=>calls.reload.length, T=now;
  let n0=R(); ui.set(acc({s:B('old','x')}),'view-machines'); ui.notePendingBkp('s');
  eq('clic : dernier Bkp connu noté (prev, fini)',[ui.pending.s.prev,ui.pending.s.prevFin,ui.pending.s.known],['old',true,true]);
  next=acc({s:B('old','x')}); now=T+400000; await ui.pollAccess();
  eq('pas encore écrit, 400 s : aucune recharge, suivi gardé',[R()-n0,!!ui.pending.s],[0,true]);
  next=acc({s:B('new',null,true)}); await ui.pollAccess();
  eq('nouveau Bkp en cours : pas de recharge',R()-n0,0);
  next=acc({s:B('new','y')}); await ui.pollAccess();
  eq('nouveau Bkp fini : une recharge',calls.reload.slice(n0),['s']);
  await ui.pollAccess();
  eq('une seule recharge (suivi terminé)',[R()-n0,'s' in ui.pending],[1,false]);
  // UI 1.23.1 (revue story 59) : Bkp nouveau tué avant toute relecture — jamais vu en cours, ligne ouverte, bkp_running false +
  // bkp_interrupted -> fin du suivi (avant WWW 1.31.5 : vu « en cours » jusqu'au délai, puis fini)
  n0=R(); ui.set(acc({k:B('k-old','x')}),'view-machines'); ui.notePendingBkp('k');
  next=acc({k:{...B('k-new',null,false),bkp_interrupted:{started_at:'2026-10-06 10:00:00',verifie:true}}}); await ui.pollAccess();
  eq('Bkp nouveau tué avant la 1re relecture : une recharge, suivi terminé',[calls.reload.slice(n0),'k' in ui.pending],[['k'],false]);
  n0=R(); ui.set(acc({k:B('k-new','z')}),'view-machines'); ui.notePendingBkp('k');
  next=acc({k:B('k-new2',null,false)}); await ui.pollAccess();
  eq('Bkp nouveau pas encore vu en cours, ni interrompu : suivi gardé',[R()-n0,'k' in ui.pending],[0,true]);
  // critère d'acceptation : démarrage à 200 s, 10 s de Bkp entre deux relectures, jamais vu en cours
  n0=R(); ui.set(acc({q:B('old','x')})); ui.notePendingBkp('q');
  for(const s of [30,60,90,120,150,180,210]){ next=acc({q:B('old','x')}); now=T+s*1000; await ui.pollAccess(); }
  eq('démarrage tardif : rien jusqu\'à 210 s',R()-n0,0);
  next=acc({q:B('late','z')}); now=T+240000; await ui.pollAccess();
  eq('démarrage tardif, fin rapide jamais vue en cours : rechargé à la relecture qui la montre',calls.reload.slice(n0),['q']);
  n0=R(); ui.set(acc({f:{bkp_running:false,bkp_last:null}})); ui.notePendingBkp('f');
  eq('premier Bkp du nick : prev null, connu',[ui.pending.f.prev,ui.pending.f.known],[null,true]);
  next=acc({f:B('r1','z')}); await ui.pollAccess();
  eq('premier Bkp du nick fini : une recharge',calls.reload.slice(n0),['f']);
  // null jamais pris pour une fin (ni pour « vu en cours ») ; chemin « vu en cours puis fini » (bkp_last en retard)
  n0=R(); ui.set(acc({n:B('old','x')})); ui.notePendingBkp('n');
  next=acc({n:{bkp_running:null,bkp_last:null}}); await ui.pollAccess();
  next=acc({n:B('old','x')}); await ui.pollAccess();
  eq('null puis false sans Bkp nouveau : aucune recharge, suivi gardé',[R()-n0,!!ui.pending.n],[0,true]);
  next=acc({n:{bkp_running:null,bkp_last:{run_id:'new',finished_at:null}}}); await ui.pollAccess();
  next=acc({n:{bkp_running:false,bkp_last:{run_id:'new',finished_at:null}}}); await ui.pollAccess();
  eq('bkp_running null avec un Bkp nouveau : jamais « vu en cours » (pas de recharge ensuite)',R()-n0,0);
  delete ui.pending.n;
  n0=R(); ui.set(acc({t:B('old','x')})); ui.notePendingBkp('t');
  next=acc({t:B('new',null,true)}); await ui.pollAccess();
  ui.set(acc({t:B('old','x')})); next=acc({t:{bkp_running:null,bkp_last:null}}); await ui.pollAccess();
  eq('vu en cours, myAccess écrasé, puis null : pas une fin',R()-n0,0);
  next=acc({t:B('new',null,false)}); await ui.pollAccess();
  eq('vu en cours puis bkp_running false (bkp_last en retard) : rechargé une fois',calls.reload.slice(n0),['t']);
  await ui.pollAccess();
  eq('vu en cours : une seule recharge',R()-n0,1);
  // Bkp cron déjà en cours au clic : sa fin recharge la carte SANS terminer le suivi du nôtre
  n0=R(); ui.set(acc({c:B('cron',null,true)})); ui.notePendingBkp('c');
  eq('clic pendant un Bkp cron : prev = cron, non fini',[ui.pending.c.prev,ui.pending.c.prevFin],['cron',false]);
  next=acc({c:B('cron','f')}); await ui.pollAccess();
  eq('Bkp cron fini : carte rechargée, suivi gardé',[calls.reload.slice(n0),!!ui.pending.c],[['c'],true]);
  next=acc({c:B('cron','f')}); await ui.pollAccess();
  eq('Bkp cron déjà compté : pas de seconde recharge',R()-n0,1);
  next=acc({c:B('mine','g')}); await ui.pollAccess();
  eq('puis le nôtre fini : rechargé, suivi terminé',[calls.reload.slice(n0),'c' in ui.pending],[['c','c'],false]);
  // état illisible au clic (pas de /access, nick absent) : première lecture lisible = référence, sans recharge
  n0=R(); ui.set(acc({})); ui.notePendingBkp('u');
  eq('état inconnu au clic',[ui.pending.u.known,ui.pending.u.prev],[false,null]);
  next=acc({u:{bkp_running:null,bkp_last:null}}); await ui.pollAccess();
  next=acc({u:B('old','x')}); await ui.pollAccess();
  eq('première lecture lisible : référence, pas de recharge',[R()-n0,(ui.pending.u||{}).known,(ui.pending.u||{}).prev],[0,true,'old']);
  next=acc({u:B('new','y')}); await ui.pollAccess();
  eq('puis Bkp nouveau fini : une recharge',calls.reload.slice(n0),['u']);
  // deux ▶ Backup avant la fin du premier : deux fins suivies
  n0=R(); ui.set(acc({d:B('old','x')})); ui.notePendingBkp('d'); ui.notePendingBkp('d');
  next=acc({d:B('a1','y')}); await ui.pollAccess();
  eq('deux lancements, premier fini : rechargé, suivi gardé',[R()-n0,!!ui.pending.d,(ui.pending.d||{}).prev],[1,true,'a1']);
  next=acc({d:B('a1','y')}); await ui.pollAccess();
  next=acc({d:B('a2','z')}); await ui.pollAccess();
  eq('second fini : rechargé, suivi terminé',[R()-n0,'d' in ui.pending],[2,false]);
  // ▶ Backup (vraie runBackupNow) : /access relu puis dernier Bkp relevé AVANT le lancement ; réussi -> suivi ; échec -> rien
  const rb=new Function('env',`const pendingBkp={}; let myAccess=env.acc;
    const confirm=()=>true, getPassphrase=()=>'pw', alert=()=>{}, loadMachines=()=>{ env.loads++; };
    const loadMyAccess=async()=>{ env.fetched++; myAccess=env.fresh; return myAccess; };
    const apiCall=async()=>{ myAccess=env.after; return env.resp; };
    ${grab('bkpRef')}
    ${grab('notePendingBkp')}
async ${grab('runBackupNow')}
    return {runBackupNow,pendingBkp};`);
  const rbEnv={loads:0,fetched:0,resp:{exitcode:0,httpStatus:200},acc:acc({ok:B('périmé','x')}),
               fresh:acc({ok:B('frais','x'),ko:B('frais','x')}),after:acc({ok:B('pendant',null,true)})};
  const rbUi=rb(rbEnv), btn={textContent:'▶',disabled:false};
  await rbUi.runBackupNow('ok',btn);
  rbEnv.resp={exitcode:1,httpStatus:403,detail:'refusé'}; await rbUi.runBackupNow('ko',btn);
  eq('runBackupNow : /access relu, prev relevé avant le lancement, réussi suivi, échec non suivi, bouton rendu',
     [rbEnv.fetched,rbUi.pendingBkp.ok&&rbUi.pendingBkp.ok.prev,'ko' in rbUi.pendingBkp,btn.disabled,btn.textContent,rbEnv.loads],
     [2,'frais',false,false,'▶',2]);
  // Actions, historique et carte (UI 1.19.0) : vraies fonctions de la page, DOM minimal simulé.
  const grabConst=name=>{ const i=src.indexOf('const '+name+'=[');
    if(i<0) throw new Error('const '+name+'=[ introuvable dans '+htmlPath); let d=0,j=src.indexOf('[',i);
    for(;;j++){ if(src[j]==='[') d++; else if(src[j]===']' && --d===0) break; } return src.slice(i,j+1)+';'; };
  const dom={els:{},byId(id){ return this.els[id]||(this.els[id]={innerHTML:'',textContent:'',classList:{toggle(){},add(){},remove(){}}}); }};
  let reportStdout='', histLoads=[], versionJson={};
  const page=new Function('dom','hooks',`
    const document={getElementById:id=>dom.byId(id),querySelectorAll:()=>[],
      createElement:()=>{ const el={set innerHTML(h){ this._h=h; this.firstElementChild={html:h,querySelector:()=>'panel',closest:()=>null}; }}; return el; }};
    let myAccess=null, currentNick=null, currentActionId=null, allowDestructive=true, restoreEnabled=true, machineCardsByNick={}, machineCardLabels={};
    let allowDownloads=true, API_PREFIX='/api', pushInfo=null;
    const fetch=async()=>({ok:true,json:async()=>hooks.version}), applyBadges=()=>{}, updateNotifBtn=()=>{};
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
${grab('selectAction')}
async ${grab('loadFooterVersions')}
${grab('_renderHistoryRows')}
${grab('machineCardHtml')}
${grab('rcGroupRefresh')}
async ${grab('reloadMachineCard')}
    return {renderActionList,selectAction,loadFooterVersions,_renderHistoryRows,reloadMachineCard,
      set:(a,n)=>{ myAccess=a; currentNick=n; }, actions:()=>ACTIONS, cards:()=>machineCardsByNick};`)(dom,{hist:histLoads,report:()=>reportStdout,get version(){ return versionJson; }});
  page.set(acc({ext:{external:true,ops:['read','restore']},int:{ops:['read','restore','prune','delete','bkp']}}),'ext');
  page.renderActionList();
  const listExt=dom.byId('actionList').innerHTML;
  eq('page serveur externe : ni Bkp, ni Init, ni Prune, ni DelBkp ; Restore et Index proposés',
     ['abtn_bkp','abtn_init','abtn_prune','abtn_delbkp'].map(id=>listExt.includes(id)).concat(['abtn_restore','abtn_index'].map(id=>listExt.includes(id))),
     [false,false,false,false,true,true]);
  page.set(acc({ext:{external:true,ops:['read','restore']},int:{ops:['read','restore','prune','delete','bkp']}}),'int');
  page.renderActionList();
  eq('page serveur interne : toutes les actions',['abtn_bkp','abtn_prune','abtn_delbkp'].every(id=>dom.byId('actionList').innerHTML.includes(id)),true);
  // UI 1.21.0 (A68) : sans racine de restauration (/version restore_enabled) « Restaurer » masqué ; libellé = racine de /access
  versionJson={borghelperwww_version:'x',allow_destructive:true,allow_downloads:true,restore_enabled:false}; await page.loadFooterVersions();   // vraie lecture de /version
  page.renderActionList(); const noRoot=dom.byId('actionList').innerHTML;
  versionJson={borghelperwww_version:'x',allow_destructive:true,allow_downloads:true,restore_enabled:true}; await page.loadFooterVersions();
  page.renderActionList(); const withRoot=dom.byId('actionList').innerHTML;
  const whereP=page.actions().find(a=>a.id==='restore').params.find(p=>p.name==='where');
  const a0=acc({int:{ops:['read','restore']}}); a0.restore_root='/srv/restaurations'; page.set(a0,'int'); const lbl=whereP.labelFn();
  page.selectAction('restore'); const panel=dom.byId('actionPanel').innerHTML;   // vrai formulaire : libellé affiché
  page.set(acc({int:{ops:['read','restore']}}),'int'); const lbl0=whereP.labelFn();
  // UI 1.22.0 (A71) : refus de POST /login (400, detail) affiché tel quel ; aucun keyfile/mountpoint envoyé
  const ns=new Function('vals','hooks',`
    const document={getElementById:id=>vals[id]||(vals[id]={value:'',hidden:true,textContent:''})};
    const apiCall=async(m,p,params)=>{ hooks.sent=params; return hooks.resp; }, loadMachines=()=>{ hooks.loaded=true; };
    async ${grab('submitNewServer')}
    return submitNewServer;`);
  const nsVals={ns_servername:{value:'srv'},ns_nickname:{value:''},ns_repo:{value:'/srv/r'},ns_passphrase:{value:'pw'}}, nsHooks={resp:{httpStatus:400,detail:'Dépôt local refusé via l\'API : /srv/r'}};
  await ns(nsVals,nsHooks)();
  eq('nouveau serveur : refus de l\'API affiché, ni keyfile ni mountpoint envoyés',
     [nsVals.newServerResult.textContent,'keyfile' in nsHooks.sent,'mountpoint' in nsHooks.sent,!!nsHooks.loaded],
     ["Refusé (HTTP 400) : Dépôt local refusé via l'API : /srv/r",false,false,false]);
  eq('restauration : masquée sans racine, libellé sous-dossier de la racine',
     [noRoot.includes('id="abtn_restore"'),noRoot.includes('id="abtn_restoreperms"'),withRoot.includes('id="abtn_restore"'),
      panel.includes('Destination (sous-dossier de /srv/restaurations) *'),lbl,lbl0],
     [false,true,true,true,'Destination (sous-dossier de /srv/restaurations)','Destination (sous-dossier de la racine de restauration du serveur)']);
  const bk={'a-1':{duration:'1s'},Totaux:{}};
  page.set(acc({ext:{ops:['read','restore']}}),'ext');
  eq('historique externe sans delete : pas de 🗑',page._renderHistoryRows(bk,true).html.includes('hist-delete-btn'),false);
  page.set(acc({ext:{ops:['read','restore','delete']}}),'ext');
  eq('historique avec delete : 🗑 proposé',page._renderHistoryRows(bk,true).html.includes('hist-delete-btn'),true);
  // UI 1.20.0 (borgHelper 1.0.165, A44) : colonne « borg » = champ borg de Report, « — » si absent
  const bv={'a-1':{duration:'1s',modifications:'M1',borg:'1.2.6 / srv 1.2.4'},'a-2':{duration:'1s',modifications:'M2'},Totaux:{}};
  const hv=page._renderHistoryRows(bv,false).html;
  // ordre : … Modifs puis borg, dernière cellule de la ligne (sans actions)
  eq('historique : colonne borg après Modifs (version, « — » si inconnue)',
     [/>M1<\/td><td[^>]*>1\.2\.6 \/ srv 1\.2\.4<\/td><\/tr>/.test(hv),/>M2<\/td><td[^>]*>—<\/td><\/tr>/.test(hv)],[true,true]);
  // Carte rechargée à la fin d'un Bkp : nouveau rapport affiché, historique relu, sans ▶ Backup pour un externe
  let replaced=null; page.cards().ext={isConnected:true,replaceWith(c){ replaced=c; }};
  page.set(acc({ext:{external:true,ops:['read','restore']}}),'ext');
  reportStdout=JSON.stringify({summary:{ext:{nom:'ext','date derniere':'2026-09-28 10:00','depuis':'0.1 h'}}});
  await page.reloadMachineCard('ext');
  eq('fin de Bkp : carte remplacée avec le nouveau rapport, historique relu, sans ▶ Backup',
     [!!replaced && replaced.html.includes('2026-09-28 10:00'), histLoads.join(), !!replaced && replaced.html.includes('bkp-now-btn'),
      !!replaced && replaced.html.includes('🔗 externe')],[true,'ext',false,true]);
  // Graphiques de la page Historique (borgHelper 1.0.158, story 21) : vraies fonctions de la page ; faux DOM limité aux
  // id="…" du HTML (getElementById rend null pour un id absent, comme un navigateur) ; faux Chart qui garde canvas et
  // configuration ; apiCall simulé (/repohistory, /archivehistory).
  const markup=src.replace(/<script\b[\s\S]*?<\/script>/g,'');   // balises seulement, jamais les chaînes du script
  const htmlIds=new Set([...markup.matchAll(/\sid="([^"]+)"/g)].map(m=>m[1]));
  const grabLine=name=>{ const m=src.match(new RegExp('^(?:let|const) '+name+'=.*$','m'));
    if(!m) throw new Error(name+' introuvable dans '+htmlPath); return m[0]; };
  const chartIds=['chartRepoSize','chartPruneGain','chartArchiveSize','chartFileChanges','chartDuration'];
  const cdom={els:{},byId(id){
    if(!htmlIds.has(id)) return null;
    return this.els[id]||(this.els[id]={id,hidden:false,className:'',_h:'',
      get innerHTML(){ return this._h; }, set innerHTML(h){ this._h=String(h); },
      get textContent(){ return this._h; }, set textContent(t){ this._h=String(t); },
      querySelector(sel){ return sel==='.spinner' && this._h.includes('class="spinner"') ? {} : null; }});
  }};
  // Faux Chart (story 22) : refuse un canvas encore utilisé, comme Chart.js (« Canvas is already in use ») ; compte les destroy().
  // hooks.noChart : page sans bibliothèque (typeof Chart === 'undefined').
  const built=[], apiCalls=[], live=new Set(), destroyed=[], adapters=[]; let resp={};
  const mkCharts=noChart=>new Function('cdom','hooks',`
    const document={getElementById:id=>cdom.byId(id)};
    class FakeChart{ constructor(canvas,cfg){ if(hooks.live.has(canvas.id)) throw new Error('Canvas is already in use');
      hooks.live.add(canvas.id); this.id=canvas.id; hooks.built.push({id:canvas.id,cfg}); }
      destroy(){ hooks.live.delete(this.id); hooks.destroyed.push(this.id); } }
    FakeChart._adapters={_date:{override(m){ hooks.adapter.push(m); }}};   // UI 1.24.0 : adaptateur de dates posé par la page
    const Chart=hooks.noChart?undefined:FakeChart;
    const apiCall=async(m,p,q)=>{ hooks.calls.push([m,p,q&&q.nick]); const r=hooks.resp(); return (r[q&&q.nick]||r)[p]; };
    ${grabLine('SPINNER')}
    ${grabLine('chartRepoSizeInstance')}
    ${grabConst('ARCHIVE_EXTRA_CHARTS')}
    ${grabLine('chartExtraInstances')}
    ${grabLine('chartsLoadSeq')}
    ${grabLine('dateAdapterReady')}
${grab('_parseTs')}
${grab('_fmtTs')}
${grab('_dateAdapter')}
${grab('_installDateAdapter')}
${grab('_timeAxis')}
${grab('_tsTitle')}
${grab('_datedRows')}
${grab('_fmtBytes')}
${grab('_fmtDuration')}
${grab('_showChartMsg')}
${grab('_hideChartMsg')}
async ${grab('loadCharts')}
${grab('_safeRender')}
${grab('_errLine')}
${grab('respError')}
${grab('_parseHistoryResponse')}
${grab('_renderRepoSizeAndPruneGainCharts')}
${grab('_fadeFor')}
${grab('_renderArchiveSizeChart')}
${grab('_renderArchiveExtraChart')}
    return {loadCharts,_safeRender,extra:ARCHIVE_EXTRA_CHARTS,SPINNER};`)(cdom,{built,live,destroyed,noChart,calls:apiCalls,resp:()=>resp,adapter:adapters});
  const charts=mkCharts(false);
  const ok=rows=>({exitcode:0,httpStatus:200,stdout:JSON.stringify({rows}),stderr:''});
  const allIds=['chartRepoSize','chartPruneGain','chartArchiveSize',...charts.extra];
  eq('graphiques : chaque id a son bloc HTML (canvas et message)',
     allIds.filter(id=>!new RegExp('<canvas id="'+id+'"').test(markup)||!htmlIds.has(id+'Msg')),[]);
  const spinners=()=>allIds.filter(id=>{ const m=cdom.byId(id+'Msg'); return !m||(!m.hidden&&m.querySelector('.spinner')); });
  const tryLoad=async()=>{ try{ await charts.loadCharts('n'); return null; } catch(e){ return String(e); } };
  // UI 1.24.0 : dates au format réel (updated_at : datetime('now') de SQLite, UTC ; archive_date : borg, heure locale)
  const repoRows=[{updated_at:'2026-09-01 08:00:05',op:'bkp',unique_csize:100,total_size:300,total_csize:200},
                   {updated_at:'2026-09-03 08:30:00',op:'prune',unique_csize:60,total_size:250,total_csize:150}];
  const archRows=k=>[{archive_date:'2026-09-01T10:00:00.000000',original_size:1000*k,compressed_size:600,deduplicated_size:50,files_added:1,
                      files_modified:2,files_removed:0,changed_during_backup:0,read_errors:0,duration:12,pruned:true},
                     {archive_date:'2026-09-03T10:30:00.000000',original_size:1100*k,compressed_size:650,deduplicated_size:40,files_added:0,
                      files_modified:3,files_removed:1,changed_during_backup:0,read_errors:0,duration:15,pruned:false}];
  resp={'/repohistory':ok(repoRows),'/archivehistory':ok(archRows(1))};
  const err1=await tryLoad();
  eq('graphiques avec lignes : sans exception, les 5 construits et eux seuls',[err1,built.map(b=>b.id).sort()],[null,[...chartIds].sort()]);
  eq('graphiques : /repohistory et /archivehistory demandés en GET pour le nick affiché',apiCalls.slice().sort(),
     [['GET','/archivehistory','n'],['GET','/repohistory','n']]);
  eq('graphiques avec lignes : aucun indicateur de chargement laissé',spinners(),[]);
  const cfgOf=id=>(built.find(b=>b.id===id)||{cfg:{data:{datasets:[]},options:{plugins:{tooltip:{callbacks:{}}}}}}).cfg;
  const as=cfgOf('chartArchiveSize');
  eq('courbe des tailles : original_size, compressed_size, deduplicated_size, chacune avec sa donnée',
     as.data.datasets.map(d=>[d.label,d.data.map(p=>p.y)]),
     [['original_size',[1000,1100]],['compressed_size',[600,650]],['deduplicated_size',[50,40]]]);
  const faded=cfg=>cfg.data.datasets.length>0 && cfg.data.datasets.every(d=>{ const c=d.pointBackgroundColor||d.backgroundColor;
    return Array.isArray(c) && c[0].endsWith('4D') && !c[1].endsWith('4D'); });
  // UI 1.24.0 : titre = date du point en heure locale ISO (plus le libellé de catégorie)
  const titled=cfg=>{ const t=cfg.options.plugins.tooltip.callbacks.title;
    return !!t && t([{label:'x',dataIndex:0}])==='2026-09-01 10:00 (supprimée)' && t([{label:'x',dataIndex:1}])==='2026-09-03 10:30'; };
  eq('archive supprimée (pruned) : atténuée (…4D) et « (supprimée) » dans l\'infobulle, graphiques par archive',
     ['chartArchiveSize',...charts.extra].map(id=>[id,faded(cfgOf(id)),titled(cfgOf(id))]),
     ['chartArchiveSize',...charts.extra].map(id=>[id,true,true]));
  built.length=0;
  resp={'/repohistory':ok([]),'/archivehistory':ok([])};
  const err2=await tryLoad();
  const msgs=allIds.map(id=>{ const m=cdom.byId(id+'Msg'), c=cdom.byId(id);
    return !!m && !m.hidden && m.textContent.length>0 && m.textContent!=='Aucune donnée.' && !m.querySelector('.spinner') && !!c && c.hidden; });
  const texts=allIds.map(id=>(cdom.byId(id+'Msg')||{}).textContent);
  eq('graphiques sans lignes (rows: []) : sans exception, rien construit, le message propre à chaque graphique',
     [err2,built.length,msgs,new Set(texts).size],[null,0,allIds.map(()=>true),allIds.length]);
  // Filet de _safeRender : un rendu qui ne dessine rien ni n'affiche de message -> « Aucune donnée. », jamais un spinner
  const dm=cdom.byId('chartDurationMsg'); dm.innerHTML=charts.SPINNER; dm.hidden=false;
  eq('faux DOM : l\'indicateur de chargement de la page est bien reconnu',!!dm.querySelector('.spinner'),true);
  charts._safeRender(()=>{},['chartDuration']);
  eq('filet : rendu muet -> « Aucune donnée. » à la place du spinner',[dm.textContent,!!dm.querySelector('.spinner')],['Aucune donnée.',false]);
  // Rechargement (story 22) : les instances précédentes sont détruites avant de redessiner, sinon Chart.js refuse le canvas.
  resp={'/repohistory':ok(repoRows),'/archivehistory':ok(archRows(1))};
  await tryLoad(); built.length=0; destroyed.length=0;
  const err3=await tryLoad();
  eq('rechargement avec lignes : sans exception, 5 destroy() puis 5 graphiques',[err3,destroyed.slice().sort(),built.length],
     [null,[...chartIds].sort(),5]);
  // Chargements qui se croisent : le premier (nick a) répond après le second (nick b) -> seul b est dessiné, a ignoré.
  // Réponses par nick (a : 7x, b : 3x) : un dessin tardif de a se verrait à ses données, quel que soit l'ordre des appels.
  let release; const gate=new Promise(r=>{ release=r; });
  resp={a:{'/repohistory':gate.then(()=>ok(repoRows)),'/archivehistory':gate.then(()=>ok(archRows(7)))},
        b:{'/repohistory':ok(repoRows),'/archivehistory':ok(archRows(3))}};
  built.length=0; apiCalls.length=0; let e5=null;
  try{ const first=charts.loadCharts('a'); await charts.loadCharts('b'); release(); await first; } catch(e){ e5=String(e); }
  eq('chargements croisés : seul le dernier dessine, avec ses données, page finale propre',
     [e5,built.length,cfgOf('chartArchiveSize').data.datasets[0].data.map(p=>p.y),spinners(),
      allIds.map(id=>!cdom.byId(id).hidden && cdom.byId(id+'Msg').hidden),apiCalls.filter(c=>c[2]==='b').length],
     [null,5,[3000,3300],[],allIds.map(()=>true),2]);
  // UI 1.24.1 (story 70, D154) : réponse réelle capturée (2026-10-10) — borgHelperWWW (tools/www_server.py, bac à sable lk)
  // lancé avec BORGHELPERWWW_REQUIRE_USER=1 ; GET /api/treehist sans l'en-tête X-User -> HTTP 403, corps {"detail": DETAIL403}
  // (ni exitcode ni stderr ; témoin avec l'en-tête : 200). Même middleware pour toute route sauf /healthz.
  const DETAIL403='Identité utilisateur absente (header X-User) — accès refusé (require_user)';
  // Erreurs de /repohistory et /archivehistory : un message d'erreur par graphique, rien construit, aucune exception.
  for(const [name,r,want] of [['403 capturé (require_user) : le detail du serveur',{httpStatus:403,detail:DETAIL403},DETAIL403],
      ['403 sans detail',{httpStatus:403},'HTTP 403'],['HTTP 500',{httpStatus:500,stdout:'',stderr:''},'HTTP 500'],
      ['HTTP 502 avec code 0',{exitcode:0,httpStatus:502,stdout:'',stderr:''},'HTTP 502'],
      ['code 0, stderr seul',{exitcode:0,httpStatus:200,stdout:'',stderr:'dépôt verrouillé'},'dépôt verrouillé'],
      ['champ error',{exitcode:0,httpStatus:200,stdout:'{"error":"nick inconnu"}',stderr:''},'nick inconnu'],
      ['sans champ rows',{exitcode:0,httpStatus:200,stdout:'{}',stderr:''},'Réponse inattendue'],
      ['exitcode 1, sortie JSON lisible',{exitcode:1,httpStatus:200,stdout:'{"rows":[]}',stderr:'borg en échec'},'borg en échec'],
      ['JSON illisible',{exitcode:0,httpStatus:200,stdout:'pas du json',stderr:''},'Réponse illisible'],
      ['401',{httpStatus:401},'Session expirée — reconnectez-vous.']]){
    resp={'/repohistory':r,'/archivehistory':r}; built.length=0;
    const e=await tryLoad();
    const shown=allIds.map(id=>{ const m=cdom.byId(id+'Msg'), c=cdom.byId(id);
      return !m.hidden && m.className==='error' && m.textContent.includes(want) && c.hidden; });
    eq('graphiques, réponse en erreur ('+name+') : message d\'erreur sur les cinq, rien construit, anciennes instances détruites',
       [e,built.length,shown,spinners(),live.size],[null,0,allIds.map(()=>true),[],0]);
  }
  // Échec partiel : dépôt lisible, archives en erreur -> deux graphiques du dépôt, erreur sur les trois par archive.
  resp={'/repohistory':ok(repoRows),'/archivehistory':{httpStatus:500,stdout:'',stderr:''}}; built.length=0;
  const e6=await tryLoad();
  eq('échec partiel : graphiques du dépôt dessinés, erreur sur ceux des archives',
     [e6,built.map(b=>b.id).sort(),['chartArchiveSize',...charts.extra].map(id=>cdom.byId(id+'Msg').className==='error'
       && !cdom.byId(id+'Msg').hidden)],[null,['chartPruneGain','chartRepoSize'],[true,true,true]]);
  // UI 1.23.0 (A87) : code 1 avec des lignes (history.db illisible) -> graphiques dessinés ET erreur dite dessous ; code 1 sans
  // ligne -> l'erreur seule (jamais « aucune statistique »).
  const part={exitcode:1,httpStatus:400,stdout:JSON.stringify({rows:archRows(1)}),
              stderr:'[ERREUR] SQLite error (h.db): database is locked  [borgHelper v1.0.178]\n'};
  resp={'/repohistory':ok(repoRows),'/archivehistory':part}; built.length=0;
  const e8=await tryLoad();
  const archIds=['chartArchiveSize',...charts.extra];
  eq('code 1 avec lignes : cinq graphiques dessinés, « Données partielles : <erreur> » sous ceux des archives seulement',
     [e8,built.length,archIds.map(id=>!cdom.byId(id).hidden && !cdom.byId(id+'Msg').hidden && cdom.byId(id+'Msg').className==='error'
       && cdom.byId(id+'Msg').textContent==='Données partielles : SQLite error (h.db): database is locked'),
      ['chartRepoSize','chartPruneGain'].map(id=>cdom.byId(id+'Msg').hidden)],[null,5,archIds.map(()=>true),[true,true]]);
  resp={'/repohistory':ok(repoRows),'/archivehistory':{...part,stdout:'{"rows":[]}'}}; built.length=0;
  const e9=await tryLoad();
  eq('code 1 sans ligne : erreur sur les graphiques des archives, jamais « aucune statistique »',
     [e9,archIds.map(id=>cdom.byId(id+'Msg').className==='error' && cdom.byId(id+'Msg').textContent==='SQLite error (h.db): database is locked')],
     [null,archIds.map(()=>true)]);
  // Reprise après une erreur : les messages d'erreur disparaissent, les cinq canvas sont réaffichés.
  resp={'/repohistory':ok(repoRows),'/archivehistory':ok(archRows(1))}; built.length=0;
  const e7=await tryLoad();
  eq('reprise après erreur : cinq graphiques, canvas visibles, messages masqués',
     [e7,built.length,allIds.map(id=>!cdom.byId(id).hidden && cdom.byId(id+'Msg').hidden)],[null,5,allIds.map(()=>true)]);
  // Bibliothèque absente (ni copie locale ni CDN) : message sur les cinq graphiques, rien construit.
  resp={'/repohistory':ok(repoRows),'/archivehistory':ok(archRows(1))}; built.length=0;
  let e4=null; try{ await mkCharts(true).loadCharts('n'); } catch(e){ e4=String(e); }
  eq('bibliothèque de graphiques absente : message sur les cinq, rien construit, sans exception',
     [e4,built.length,allIds.map(id=>{ const m=cdom.byId(id+'Msg'); return !m.hidden && m.className==='error' && cdom.byId(id).hidden
       && m.textContent.startsWith('Bibliothèque de graphiques indisponible'); }),spinners()],[null,0,allIds.map(()=>true),[]]);
  // ── UI 1.24.0 (story 67) : axe temporel réel, premier Prune (D034, D035, D040, D050, D197, D192) ──
  // Faux Chart : échelle `time` sur les cinq graphiques, points {x: horodatage, y}, adaptateur de dates posé une fois.
  resp={'/repohistory':ok(repoRows),'/archivehistory':ok(archRows(1))}; built.length=0;
  await tryLoad();
  const ad=adapters[0]||{};
  eq('axe temporel : adaptateur de dates posé (une fois), complet',
     [adapters.length,['formats','parse','format','add','diff','startOf','endOf'].filter(k=>typeof ad[k]!=='function')],[1,[]]);
  eq('axe temporel : échelle time sur les cinq graphiques, x = horodatages numériques, sans labels de catégorie',
     chartIds.map(id=>{ const c=cfgOf(id); return [id,c.options.scales.x.type,!c.data.labels,
       c.data.datasets.every(d=>d.data.every(p=>typeof p.x==='number'&&isFinite(p.x)))]; }),chartIds.map(id=>[id,'time',true,true]));
  const TU0=globalThis.Date.UTC(2026,8,1,8,0,5);
  const fmtLocal=t=>{ const d=new globalThis.Date(t), p=n=>String(n).padStart(2,'0');   // heure locale ISO, écrite indépendamment de la page
    return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes()); };
  eq('axe temporel : updated_at lu en UTC, archive_date en heure locale',
     [cfgOf('chartRepoSize').data.datasets[0].data[0].x,cfgOf('chartArchiveSize').data.datasets[0].data[0].x],
     [TU0,new globalThis.Date(2026,8,1,10,0,0).getTime()]);
  // Adaptateur : interface de Chart.js en heure locale (graduations ISO selon l'unité).
  {
    const L=(...a)=>new globalThis.Date(...a).getTime(), t=L(2026,9,4,10,46,17);
    eq('adaptateur : formats ISO par unité (jour, mois, année, heure, minute, seconde)',
       ['day','month','year','hour','minute','second','week','quarter','datetime'].map(u=>ad.format(t,ad.formats()[u])),
       ['2026-10-04','2026-10','2026','2026-10-04 10:46','2026-10-04 10:46','2026-10-04 10:46:17','2026-10-04','2026-10','2026-10-04 10:46']);
    eq('adaptateur : startOf / endOf / add / diff',
       [ad.startOf(t,'hour')===L(2026,9,4,10),ad.startOf(t,'day')===L(2026,9,4),ad.startOf(t,'month')===L(2026,9,1),
        ad.startOf(t,'quarter')===L(2026,9,1),ad.startOf(t,'year')===L(2026,0,1),ad.startOf(t,'isoWeek',1)===L(2026,8,28),
        ad.startOf(t,'week')===L(2026,9,4),ad.endOf(t,'day')===L(2026,9,5)-1,ad.add(t,1,'month')===L(2026,10,4,10,46,17),
        ad.add(t,2,'day')===L(2026,9,6,10,46,17),ad.diff(L(2026,9,14),L(2026,9,4),'day'),ad.diff(L(2027,0,1),L(2026,9,1),'month'),
        ad.parse(t),ad.parse(null),ad.parse('n\'importe quoi')],
       [true,true,true,true,true,true,true,true,true,true,10,3,t,null,null]);
  }
  // Premier Prune : mesure précédente = baseline (borgHelper ≥ 1.0.192) ; sans elle : marqué sans barre, note.
  const firstPrune=[{id:9,op:'prune',unique_csize:60,total_size:1,total_csize:1,updated_at:'2026-09-03 08:30:00'},
                    {id:10,op:'bkp',unique_csize:70,total_size:1,total_csize:1,updated_at:'2026-09-04 08:30:00'}];
  const okB=(rows,extra)=>({exitcode:0,httpStatus:200,stderr:'',stdout:JSON.stringify(Object.assign({rows},extra))});
  const pgNote=()=>{ const n=cdom.byId('chartPruneGainNote'); return n.hidden?null:n.textContent; };
  resp={'/repohistory':okB(firstPrune,{baseline:{id:8,op:'bkp',unique_csize:100,total_size:1,total_csize:1,updated_at:'2026-07-01 00:00:00'}}),
        '/archivehistory':ok(archRows(1))}; built.length=0;
  const eB=await tryLoad(); const gB=cfgOf('chartPruneGain');
  eq('premier Prune, base gardée : barre = baseline.unique_csize - prune.unique_csize, base jamais dessinée, aucune note',
     [eB,gB.data.datasets.map(d=>d.data.map(p=>p.y)),cfgOf('chartRepoSize').data.datasets[0].data.map(p=>p.y),pgNote()],
     [null,[[40]],[60,70],null]);
  for(const [nm,extra] of [['baseline null',{baseline:null}],['champ baseline absent (borgHelper < 1.0.192)',{}]]){
    resp={'/repohistory':okB(firstPrune,extra),'/archivehistory':ok(archRows(1))}; built.length=0;
    const e=await tryLoad(); const g=cfgOf('chartPruneGain'), cb=g.options.plugins.tooltip.callbacks;
    eq('premier Prune sans base ('+nm+') : marqué sans barre (croix à 0), infobulle et ligne sous le graphique',
       [e,g.data.datasets.map(d=>[d.type||'bar',d.data.map(p=>[p.x,p.y])]),cb.label({datasetIndex:1,parsed:{y:0}}),
        cb.title([{datasetIndex:1,dataIndex:0}]),pgNote(),!cdom.byId('chartPruneGain').hidden,cdom.byId('chartPruneGainMsg').hidden],
       [null,[['bar',[]],['line',[[globalThis.Date.UTC(2026,8,3,8,30),0]]]],'Prune : gain inconnu : aucune mesure précédente',
        fmtLocal(globalThis.Date.UTC(2026,8,3,8,30)),'Prune du '+fmtLocal(globalThis.Date.UTC(2026,8,3,8,30))+' : gain inconnu : aucune mesure précédente.',
        true,true]);
  }
  resp={'/repohistory':ok(repoRows),'/archivehistory':ok(archRows(1))}; built.length=0; await tryLoad();
  eq('note « gain inconnu » retirée au rechargement suivant (Prune précédé d\'une mesure)',[pgNote(),cfgOf('chartPruneGain').data.datasets.length],[null,1]);
  // Date illisible : ligne hors de l'axe, graphique dessiné, jamais d'exception ; même updated_at : deux points.
  const badRepo=[{op:'bkp',unique_csize:1,updated_at:''},{op:'bkp',unique_csize:2,updated_at:'2026-09-01 08:00:00'},
                 {op:'index',unique_csize:3,updated_at:'2026-09-01 08:00:00'},{op:'bkp',unique_csize:4,updated_at:'pas une date'},
                 {op:'bkp',unique_csize:5,updated_at:'2026-02-30 08:00:00'},{op:'prune',unique_csize:6,updated_at:null},
                 {op:'prune',unique_csize:1,updated_at:'2026-09-02 08:00:00'}];
  const badArch=archRows(1).concat([{archive_date:'2026-13-01T00:00:00',original_size:9,duration:9,files_added:9},{archive_date:'',duration:9}]);
  resp={'/repohistory':ok(badRepo),'/archivehistory':ok(badArch)}; built.length=0;
  const eBad=await tryLoad();
  eq('date illisible : lignes hors de l\'axe, cinq graphiques dessinés, sans exception ; même updated_at : deux points distincts',
     [eBad,built.length,cfgOf('chartRepoSize').data.datasets[0].data.map(p=>p.y),
      cfgOf('chartPruneGain').data.datasets.map(d=>d.data.map(p=>p.y)),['chartArchiveSize',...charts.extra].map(id=>cfgOf(id).data.datasets[0].data.length)],
     [null,5,[2,3,1],[[5]],[2,2,2]]);
  // Valeurs portées seulement par une ligne à date illisible : graphique par archive vide -> son message (jamais un canvas vide).
  resp={'/repohistory':ok(repoRows),'/archivehistory':ok([{archive_date:'2026-09-01T10:00:00',original_size:1,compressed_size:1,deduplicated_size:1,
    duration:null,files_added:null,files_modified:null,files_removed:null,changed_during_backup:null,read_errors:null},
    {archive_date:'',original_size:2,duration:7,files_added:3,files_modified:1,files_removed:1,changed_during_backup:1,read_errors:1}])};
  built.length=0;
  const eUnd=await tryLoad();
  eq('valeurs seulement sur une ligne non datée : Durée et Fichiers modifiés -> leur message « Aucun… », rien construit pour eux',
     [eUnd,built.map(b=>b.id).sort(),charts.extra.map(id=>[cdom.byId(id).hidden,cdom.byId(id+'Msg').hidden,cdom.byId(id+'Msg').textContent.startsWith('Aucun')])],
     [null,['chartArchiveSize','chartPruneGain','chartRepoSize'],charts.extra.map(()=>[true,false,true])]);
  // Une seule ligne : un point, axe d'un jour centré sur lui, une graduation à sa date.
  resp={'/repohistory':ok([repoRows[0]]),'/archivehistory':ok([archRows(1)[1]])}; built.length=0;
  const e1=await tryLoad(); const x1=cfgOf('chartRepoSize').options.scales.x;
  eq('une seule ligne : graphiques dessinés, axe d\'un jour centré sur le point, graduation à sa date',
     [e1,built.map(b=>b.id).sort(),x1.max-TU0,TU0-x1.min,x1.ticks.source,x1.time.unit],
     [null,['chartArchiveSize','chartDuration','chartFileChanges','chartRepoSize'],432e5,432e5,'data','minute']);

  // Vraie Chart.js (vendor/chartjs, servie par borgHelperWWW) sur un canvas simulé, avec l'adaptateur de la page : graduations,
  // position des points. TZ Europe/Paris : updated_at (UTC) et archive_date (local) diffèrent de 2 h dans le texte.
  const tzPrev=process.env.TZ; process.env.TZ='Europe/Paris';
  try{
    const cjs=fs.readFileSync(path.join(__dirname,'vendor','chartjs','chart.umd.min.js'),'utf8');
    const mod={exports:{}}; new Function('module','exports',cjs)(mod,mod.exports); const RealChart=mod.exports;
    const rdom={els:{},byId(id){
      if(!htmlIds.has(id)) return null;
      if(this.els[id]) return this.els[id];
      const el={id,hidden:false,className:'',textContent:'',innerHTML:'',width:800,height:300,style:{},querySelector:()=>null};
      const ctx=new Proxy({canvas:el},{get(t,k){ if(k==='measureText') return x=>({width:String(x).length*6}); return k in t?t[k]:()=>{}; },
                                       set(t,k,v){ t[k]=v; return true; }});
      el.getContext=()=>ctx; return this.els[id]=el; }};
    const real=new Function('rdom','Chart',`
      const document={getElementById:id=>rdom.byId(id)};
      ${grabLine('chartRepoSizeInstance')}
      ${grabLine('chartExtraInstances')}
      ${grabLine('dateAdapterReady')}
${grab('_parseTs')}
${grab('_fmtTs')}
${grab('_dateAdapter')}
${grab('_installDateAdapter')}
${grab('_timeAxis')}
${grab('_tsTitle')}
${grab('_datedRows')}
${grab('_fmtBytes')}
${grab('_fmtDuration')}
${grab('_showChartMsg')}
${grab('_hideChartMsg')}
${grab('_errLine')}
${grab('respError')}
${grab('_parseHistoryResponse')}
${grab('_renderRepoSizeAndPruneGainCharts')}
${grab('_fadeFor')}
${grab('_renderArchiveSizeChart')}
${grab('_renderArchiveExtraChart')}
      _installDateAdapter();
      return {repo:r=>_renderRepoSizeAndPruneGainCharts(r),arch:r=>_renderArchiveSizeChart(r),extra:(id,r)=>_renderArchiveExtraChart(id,r),
              get:id=>({chartRepoSize:chartRepoSizeInstance,chartPruneGain:chartPruneGainInstance,chartArchiveSize:chartArchiveSizeInstance})[id]||chartExtraInstances[id]};`)(rdom,RealChart);
    const tryR=f=>{ try{ f(); return null; } catch(e){ return String(e); } };
    const px=(c,ds=0)=>c.getDatasetMeta(ds).data.map(e=>e.x);
    const ticks=c=>c.scales.x.ticks.map(t=>t.label);
    const titleOf=(c,i,ds=0)=>c.options.plugins.tooltip.callbacks.title([{dataIndex:i,datasetIndex:ds}]);
    // Espacement proportionnel au temps : (x_i - x_0) / (t_i - t_0) constant.
    const proportional=(xs,ts)=>{ const k=(xs[xs.length-1]-xs[0])/(ts[ts.length-1]-ts[0]);
      return k>0 && xs.every((x,i)=>Math.abs((x-xs[0])-k*(ts[i]-ts[0]))<1e-6*Math.abs(xs[xs.length-1]-xs[0])+1e-9); };
    // Réponses réelles capturées (story 67, 2026-10-09) : borgHelper 1.0.192 servi par borgHelperWWW (tools/www_server.py), bac à
    // sable à dépôts neufs — sa : Bkp à J, J+5 s, J+35 s puis Prune (KEEP_DAILY=1) ; sb (STATS_RETENTION_MONTHS=1) : mesures
    // reculées hors fenêtre, Bkp puis Prune réels -> rows = [prune], baseline = mesure du Bkp.
    const CAP={
    'sa/repohistory':{exitcode:0,httpStatus:200,stderr:"",stdout:JSON.stringify({"borghelper_version":"1.0.192","nick":"sa","rows":[{"id":1,"op":"bkp","unique_csize":21085,"total_size":20000,"total_csize":20043,"updated_at":"2026-10-09 13:50:16"},{"id":2,"op":"bkp","unique_csize":52246,"total_size":70000,"total_csize":70129,"updated_at":"2026-10-09 13:50:21"},{"id":3,"op":"bkp","unique_csize":93478,"total_size":160000,"total_csize":160258,"updated_at":"2026-10-09 13:50:51"},{"id":4,"op":"prune","unique_csize":91318,"total_size":90000,"total_csize":90129,"updated_at":"2026-10-09 13:51:17"}],"baseline":null})},
    'sa/archivehistory':{exitcode:0,httpStatus:200,stderr:"",stdout:JSON.stringify({"borghelper_version":"1.0.192","nick":"sa","rows":[{"archive":"p-sxb-35-a-2026-10-09T155015","archive_date":"2026-10-09T15:50:15.000000","duration":0.025564,"original_size":20808,"compressed_size":20803,"deduplicated_size":20803,"nfiles":1,"changed_during_backup":0,"read_errors":0,"files_added":null,"files_modified":null,"files_removed":null,"borg_version":null,"borg_server_version":null,"reconciled":false,"pruned":true},{"archive":"p-sxb-35-a-2026-10-09T155021","archive_date":"2026-10-09T15:50:21.000000","duration":0.026639,"original_size":50808,"compressed_size":50843,"deduplicated_size":30800,"nfiles":2,"changed_during_backup":0,"read_errors":0,"files_added":1,"files_modified":0,"files_removed":0,"borg_version":null,"borg_server_version":null,"reconciled":false,"pruned":true},{"archive":"p-sxb-35-a-2026-10-09T155050","archive_date":"2026-10-09T15:50:50.000000","duration":0.026962,"original_size":90812,"compressed_size":90889,"deduplicated_size":40803,"nfiles":3,"changed_during_backup":0,"read_errors":0,"borg_version":"1.2.6","borg_server_version":"1.2.6","reconciled":false,"files_added":1,"files_modified":0,"files_removed":0,"pruned":false}]})},
    'sb/repohistory':{exitcode:0,httpStatus:200,stderr:"",stdout:JSON.stringify({"borghelper_version":"1.0.192","nick":"sb","rows":[{"id":9,"op":"prune","unique_csize":76324,"total_size":75000,"total_csize":75129,"updated_at":"2026-10-09 13:51:55"}],"baseline":{"id":8,"op":"bkp","unique_csize":77444,"total_size":125000,"total_csize":125215,"updated_at":"2026-09-08 13:51:49"}})},
    'sb/archivehistory':{exitcode:0,httpStatus:200,stderr:"",stdout:JSON.stringify({"borghelper_version":"1.0.192","nick":"sb","rows":[{"archive":"p-sxb-35-b-2026-10-09T155057","archive_date":"2026-10-09T15:50:57.000000","duration":0.024958,"original_size":20808,"compressed_size":20800,"deduplicated_size":20800,"nfiles":1,"changed_during_backup":0,"read_errors":0,"files_added":null,"files_modified":null,"files_removed":null,"borg_version":null,"borg_server_version":null,"reconciled":false,"pruned":true},{"archive":"p-sxb-35-b-2026-10-09T155102","archive_date":"2026-10-09T15:51:02.000000","duration":0.026051,"original_size":50808,"compressed_size":50843,"deduplicated_size":30800,"nfiles":2,"changed_during_backup":0,"read_errors":0,"files_added":1,"files_modified":0,"files_removed":0,"borg_version":null,"borg_server_version":null,"reconciled":false,"pruned":true},{"archive":"p-sxb-35-b-2026-10-09T155149","archive_date":"2026-10-09T15:51:49.000000","duration":0.032272,"original_size":75812,"compressed_size":75889,"deduplicated_size":25803,"nfiles":3,"changed_during_backup":0,"read_errors":0,"borg_version":"1.2.6","borg_server_version":"1.2.6","reconciled":false,"files_added":1,"files_modified":0,"files_removed":0,"pruned":false}]})}
    };
    const capRows=k=>JSON.parse(CAP[k].stdout).rows;
    const eR=[tryR(()=>real.repo(CAP['sa/repohistory'])),tryR(()=>real.arch(CAP['sa/archivehistory'])),
              ...charts.extra.map(id=>tryR(()=>real.extra(id,CAP['sa/archivehistory'])))];
    const rc=real.get('chartRepoSize'), ac=real.get('chartArchiveSize'), du=real.get('chartDuration');
    const rT=capRows('sa/repohistory').map(r=>globalThis.Date.parse(r.updated_at.replace(' ','T')+'Z'));
    const aT=capRows('sa/archivehistory').map(r=>new globalThis.Date(r.archive_date).getTime());
    eq('vraie Chart.js, réponses capturées (sa) : cinq graphiques sans exception, intervalles inégaux -> espacement proportionnel au temps',
       [eR,proportional(px(rc),rT),proportional(px(ac),aT),proportional(px(du),aT),
        (px(rc)[1]-px(rc)[0])<(px(rc)[2]-px(rc)[1])/3],[[null,null,null,null],true,true,true,true]);
    // Concordance des deux familles : un même Bkp a la même heure locale dans l'infobulle (updated_at 13:50 UTC = archive 15:50)
    eq('vraie Chart.js : heures des deux familles concordantes (Bkp n -> même minute locale), graduations ISO',
       [[0,1,2].map(i=>titleOf(rc,i)),[0,1,2].map(i=>titleOf(ac,i).replace(' (supprimée)','')),
        ticks(rc).every(l=>/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/.test(l)),ticks(rc).length>1],
       [['2026-10-09 15:50','2026-10-09 15:50','2026-10-09 15:50'],['2026-10-09 15:50','2026-10-09 15:50','2026-10-09 15:50'],true,true]);
    const g=real.get('chartPruneGain'), rowsSa=capRows('sa/repohistory');
    eq('vraie Chart.js : gain Prune à la date du Prune (unique_csize précédent - celui du Prune)',
       [g.data.datasets[0].data.map(p=>p.y),titleOf(g,0)],[[rowsSa[2].unique_csize-rowsSa[3].unique_csize],'2026-10-09 15:51']);
    // sb : premier Prune de la fenêtre, gain tiré de baseline (réponse réelle)
    const sb=JSON.parse(CAP['sb/repohistory'].stdout);
    const eS=tryR(()=>real.repo(CAP['sb/repohistory'])); const gs=real.get('chartPruneGain'), rs=real.get('chartRepoSize');
    eq('vraie Chart.js, réponse capturée (sb) : premier Prune chiffré par baseline, baseline jamais dessinée, une graduation lisible',
       [eS,gs.data.datasets.map(d=>d.data.map(p=>p.y)),rs.data.datasets[0].data.map(p=>p.y),ticks(rs),
        px(rs)[0]>rs.chartArea.left && px(rs)[0]<rs.chartArea.right,rdom.byId('chartPruneGainNote').hidden],
       [null,[[sb.baseline.unique_csize-sb.rows[0].unique_csize]],[sb.rows[0].unique_csize],['2026-10-09 15:51'],true,true]);
    // Matrice : J, J+1, J+10 (barres) ; même minute ; une ligne ; graduations par unité (heures, mois)
    const arch=dates=>({exitcode:0,httpStatus:200,stderr:'',stdout:JSON.stringify({rows:dates.map((d,i)=>({archive_date:d,duration:10+i,original_size:1,compressed_size:1,deduplicated_size:1,
      files_added:1,files_modified:2,files_removed:1}))})});
    tryR(()=>real.extra('chartDuration',arch(['2026-09-01T10:00:00','2026-09-02T10:00:00','2026-09-11T10:00:00'])));
    const dj=real.get('chartDuration'), J=new globalThis.Date(2026,8,1,10).getTime(), D=864e5;
    eq('matrice : barres à J, J+1, J+10 -> espacement proportionnel, graduations « AAAA-MM-JJ »',
       [proportional(px(dj),[J,J+D,J+10*D]),ticks(dj).every(l=>/^\d{4}-\d{2}-\d{2}$/.test(l))],[true,true]);
    const same={exitcode:0,httpStatus:200,stderr:'',stdout:JSON.stringify({rows:[{op:'bkp',unique_csize:5,updated_at:'2026-10-04 08:46:17'},
      {op:'index',unique_csize:7,updated_at:'2026-10-04 08:46:17'}],baseline:null})};
    const eSame=tryR(()=>real.repo(same)); const sm=real.get('chartRepoSize');
    eq('matrice : même minute -> deux points distincts (même x, deux valeurs), aucun perdu ; graduation « 2026-10-04 10:46 »',
       [eSame,px(sm).length,px(sm)[0]===px(sm)[1],sm.getDatasetMeta(0).data.map(e=>Math.round(e.y)).filter((y,i,a)=>a.indexOf(y)===i).length,ticks(sm)],
       [null,2,true,2,['2026-10-04 10:46']]);
    tryR(()=>real.extra('chartDuration',arch(['2026-10-04T10:00:00','2026-10-04T15:00:00','2026-10-04T19:00:00'])));
    const hh=ticks(real.get('chartDuration'));
    tryR(()=>real.extra('chartDuration',arch(['2026-01-15T10:00:00','2026-04-15T10:00:00','2026-09-15T10:00:00'])));
    const mm=ticks(real.get('chartDuration'));
    eq('graduations selon l\'unité : heures « AAAA-MM-JJ HH:00 », mois « AAAA-MM »',
       [hh.length>1&&hh.every(l=>/^\d{4}-\d{2}-\d{2} \d{2}:00$/.test(l)),mm.length>1&&mm.every(l=>/^\d{4}-\d{2}$/.test(l))],[true,true]);
    // Barres à largeur fixe (barThickness 8) : J, J+5 s, J+30 j (plus petit écart 5 s sur un axe d'un mois : 0 px sans elle),
    // et une seule barre (toute la largeur sans elle) — Durée, Fichiers modifiés (3 séries empilées), Gain Prune.
    const widths=()=>{ const w=[];
      for(const id of ['chartDuration','chartFileChanges']){ const c=real.get(id);
        (id==='chartDuration'?[0]:[0,1,2]).forEach(ds=>c.getDatasetMeta(ds).data.forEach(e=>w.push(Math.round(e.width*100)/100))); }
      real.get('chartPruneGain').getDatasetMeta(0).data.forEach(e=>w.push(Math.round(e.width*100)/100)); return w; };
    const pr=dates=>({exitcode:0,httpStatus:200,stderr:'',stdout:JSON.stringify({rows:[{op:'bkp',unique_csize:100,updated_at:'2026-08-01 00:00:00'}]
      .concat(dates.map((d,i)=>({op:'prune',unique_csize:90-i,updated_at:d}))),baseline:null})});
    const wErr=[];
    const spread=['2026-09-01T10:00:00','2026-09-01T10:00:05','2026-10-01T10:00:00'];
    wErr.push(...['chartDuration','chartFileChanges'].map(id=>tryR(()=>real.extra(id,arch(spread)))),tryR(()=>real.repo(pr(['2026-09-01 08:00:00','2026-09-01 08:00:05','2026-10-01 08:00:00']))));
    const w3=widths();
    wErr.push(...['chartDuration','chartFileChanges'].map(id=>tryR(()=>real.extra(id,arch(['2026-09-01T10:00:00'])))),tryR(()=>real.repo(pr(['2026-09-01 08:00:00']))));
    const w1=widths();
    eq('barres de largeur fixe 8 px : J, J+5 s, J+30 j et barre seule (Durée, Fichiers modifiés empilés, Gain Prune)',
       [wErr.every(e=>e===null),w3,w1],[true,Array(15).fill(8),Array(5).fill(8)]);
    const eBadR=[tryR(()=>real.repo(ok(badRepo))),tryR(()=>real.extra('chartFileChanges',ok(badArch)))];
    eq('vraie Chart.js : dates illisibles ignorées, sans exception',[eBadR,real.get('chartRepoSize').getDatasetMeta(0).data.length],[[null,null],3]);
  } finally { if(tzPrev===undefined) delete process.env.TZ; else process.env.TZ=tzPrev; }

  // UI 1.23.0 (A87) : explorateur (/treehist, /treefind) — code 1 avec JSON lu (erreur du nick), code 1 sans sortie ou >= 2 : stderr
  {
    const rj=new Function(grab('_readerJson')+'\nreturn _readerJson;')();
    eq('explorateur : réponse lue en JSON en code 0 et en code 1 avec sortie seulement',
       [rj({exitcode:0,stdout:''}),rj({exitcode:1,stdout:'{"n":{"error":"SQLite error"}}'}),rj({exitcode:1,stdout:''}),rj({exitcode:2,stdout:'{}'}),rj({httpStatus:403})],
       [true,true,false,false,false]);
    eq('explorateur : les deux appels passent par _readerJson',(src.match(/if\(!_readerJson\(r\)\)/g)||[]).length,2);
  }
  // UI 1.24.1 (story 70, D154) : message d'erreur commun (respError : stderr, sinon detail du serveur, sinon « HTTP <code> ») ;
  // explorateur et recherche : tableau / résultats et entrées vidés sur toute erreur, jamais « undefined » ni spinner.
  {
    // DETAIL403 : réponse réelle capturée (voir sa définition, avant les graphiques).
    const ah={};
    const api=new Function('hooks',`
      const API_PREFIX='/api'; const location={origin:'http://x'};
      const getApiKey=()=>'k', getPassphrase=()=>null, logout=()=>{ hooks.loggedOut=true; };
      const document={getElementById:()=>({textContent:''})};
      const fetch=async()=>({status:hooks.status,json:async()=>hooks.body});
async ${grab('apiCall')}
      return apiCall;`)(ah);
    // Passée par le vrai apiCall (forme {httpStatus, ...corps}) avant d'être rendue.
    const capture=async(path,status,body)=>{ ah.status=status; ah.body=body; return api('GET',path,{nick:'n'},false); };
    const r403=await capture('/treehist',403,{detail:DETAIL403}), f403=await capture('/treefind',403,{detail:DETAIL403});
    const r403e=await capture('/treehist',403,{});
    eq('403 capturé : apiCall rend {httpStatus:403, detail} sans exitcode ni stderr, pas de déconnexion',
       [r403,ah.loggedOut===true],[{httpStatus:403,detail:DETAIL403},false]);
    const re=new Function(grab('respError')+'\nreturn respError;')();
    eq('respError : stderr, sinon detail, sinon repli, sinon « HTTP <code> » ; detail non textuel sérialisé',
       [re({httpStatus:400,exitcode:1,stderr:'e',detail:'d'}),re(r403),re(r403e),re({httpStatus:403},'exitcode 2'),
        re({httpStatus:422,detail:[{msg:'x'}]}),re({httpStatus:200,exitcode:2,stdout:'',stderr:''},'exitcode 2'),
        re({httpStatus:403,detail:''}),re({httpStatus:403,detail:''},'exitcode 3')],
       ['e',DETAIL403,'HTTP 403','exitcode 2','HTTP 422 — [{"msg":"x"}]','exitcode 2','HTTP 403','exitcode 3']);
    const usersOf=['loadMyAccess','loadMachines','loadHistoryInline','loadHistoryFull','_parseHistoryResponse','loadBrowse','runBrowseSearch'];
    eq('respError appelée par les sept affichages (droits/périmètre, machines, carte, historique, graphiques, explorateur, recherche)',
       usersOf.filter(f=>!grab(f).includes('respError(')),[]);
    // DETAIL403 = texte du middleware require_user de borgHelperWWW, en-tête X-User (celui de la mesure).
    const wwwSrc=fs.readFileSync(path.join(__dirname,'borgHelperWWW'),'utf8');
    const TPL403='Identité utilisateur absente (header {USER_HEADER}) — accès refusé (require_user)';
    eq('403 capturé : texte du middleware require_user de borgHelperWWW (en-tête X-User)',
       [wwwSrc.includes('f"'+TPL403+'"'),TPL403.replace('{USER_HEADER}','X-User')],[true,DETAIL403]);

    // Explorateur et recherche : vraies fonctions de la page, DOM simulé.
    const bdom={els:{},byId(id){ return this.els[id]||(this.els[id]={id,hidden:false,value:'',textContent:'',innerHTML:''}); }};
    const bh={resp:null,calls:[]};
    const br=new Function('bdom','hooks',`
      const document={getElementById:id=>bdom.byId(id)};
      ${grabLine('SPINNER')}
      const syncUrl=()=>{}, syncBrowseModeControls=()=>{}, renderBreadcrumb=()=>{};
      const opAllowed=()=>true, downloadInScope=()=>true; let allowDownloads=true;
      let browseNick='n', browsePath='', browseArchive=null, browseChanges=null, browseEntriesByPath={}, browseLoadSeq=0;
      const apiCall=async(m,p,q)=>{ hooks.calls.push([p,q.prefix]); const d=hooks.defer; return d?await d:hooks.resp; };
${grab('escapeHtml')}
${grab('escapeAttr')}
${grab('respError')}
${grab('_readerJson')}
${grab('clearBrowseSearch')}
async ${grab('loadBrowse')}
async ${grab('runBrowseSearch')}
      return {loadBrowse,runBrowseSearch,entries:()=>Object.keys(browseEntriesByPath).sort(),go:p=>{ browsePath=p; }};`)(bdom,bh);
    const ent=(p,x)=>Object.assign({name:p.split('/').pop(),full_path:p,parent:p.split('/').slice(0,-1).join('/'),is_dir:false,
      genre:'f',mode:'-rw-r--r--',owner:'u',events:[{type:'added',archive:'a1'}]},x||{});
    const okTree=(...ps)=>({httpStatus:200,exitcode:0,stderr:'',stdout:JSON.stringify({n:{entries:ps.map(p=>ent(p))}})});
    const errEl=bdom.byId('browseError'), body=bdom.byId('browseBody'), res=bdom.byId('browseSearchResults');
    const view=()=>({err:errEl.textContent,body:body.innerHTML,entries:br.entries()});
    const SP='<span class="spinner">';
    // Chaque erreur suit un affichage réussi du répertoire « a » (entrées présentes) : leur effacement est donc mesuré.
    const afterA=async(resp,path)=>{
      br.go('a'); bh.resp=okTree('a/f','a/g'); await br.loadBrowse();
      const before=br.entries();
      br.go(path||'b'); bh.resp=resp;
      try{ await br.loadBrowse(); }catch(e){ return {before,...view(),err:'EXCEPTION '+e}; }
      return {before,...view()};
    };
    const vA={before:['a/f','a/g'],body:''};
    const v1=await afterA(r403);
    eq('explorateur, 403 capturé : le detail du serveur, tableau vide, entrées vidées, jamais « undefined »',
       [v1.before,v1.err,v1.body,v1.entries,/undefined/.test(v1.err)],[vA.before,DETAIL403,'',[],false]);
    const v2=await afterA(r403e);
    eq('explorateur, 403 sans detail : « HTTP 403 », tableau vide, entrées vidées',[v2.err,v2.body,v2.entries],['HTTP 403','',[]]);
    const v3=await afterA({httpStatus:200,exitcode:0,stdout:'<html>pas du json',stderr:''});
    eq('explorateur, JSON illisible : « Réponse illisible : … », tableau vide (plus de spinner), entrées vidées',
       [v3.err,v3.body,v3.body.includes(SP),v3.entries],['Réponse illisible : <html>pas du json','',false,[]]);
    const v4=await afterA({httpStatus:400,exitcode:1,stdout:'',stderr:'[ERREUR] base illisible'});
    eq('explorateur, erreur borgHelper (code 1, stderr) : stderr inchangé, tableau vide, entrées vidées',
       [v4.err,v4.body,v4.entries],['[ERREUR] base illisible','',[]]);
    const v5=await afterA({httpStatus:400,exitcode:2,stdout:'',stderr:''});
    eq('explorateur, code 2 sans stderr : « exitcode 2 » inchangé, entrées vidées',[v5.err,v5.entries],['exitcode 2',[]]);
    const v6=await afterA({httpStatus:200,exitcode:1,stdout:'{"n":{"error":"SQLite error"}}',stderr:'x'});
    const v7=await afterA({httpStatus:200,exitcode:0,stdout:'{}',stderr:''});
    const v7b=await afterA({httpStatus:200,exitcode:0,stdout:'null',stderr:''});
    eq('explorateur, erreur du nick / « Aucune donnée » (messages inchangés) / JSON null : tableau et entrées vidés',
       [[v6.err,v6.body,v6.entries],[v7.err,v7.body,v7.entries],[v7b.err,v7b.body,v7b.entries]],
       [['SQLite error','',[]],['Aucune donnée','',[]],['Aucune donnée','',[]]]);
    // Réussite après erreur : entrées et tableau du nouveau répertoire, message vidé.
    br.go('b'); bh.resp=r403; await br.loadBrowse();
    br.go('c'); bh.resp=okTree('c/x','c/y','c/z'); await br.loadBrowse();
    eq('explorateur, réussite après erreur : tableau et entrées du nouveau répertoire, message vidé',
       [errEl.textContent,br.entries(),(body.innerHTML.match(/class="browse-row"/g)||[]).length],['',['c/x','c/y','c/z'],3]);
    // Réponse en erreur arrivée après une navigation plus récente réussie : ignorée (tableau, entrées, message intacts).
    for(const late of [r403,{httpStatus:200,exitcode:0,stdout:'pas du json',stderr:''}]){
      let release; bh.defer=new Promise(ok=>{ release=ok; });
      br.go('old'); const pOld=br.loadBrowse(); bh.defer=null;
      br.go('c'); bh.resp=okTree('c/x','c/y','c/z'); await br.loadBrowse();
      const bodyBefore=body.innerHTML;
      release(late); await pOld;
      eq('explorateur, erreur ('+(late.detail?'403':'JSON illisible')+') arrivée après une navigation plus récente : ignorée',
         [errEl.textContent,br.entries(),body.innerHTML===bodyBefore],['',['c/x','c/y','c/z'],true]);
    }
    br.go('d'); bh.resp={httpStatus:200,exitcode:0,stderr:'',stdout:JSON.stringify({n:{entries:[]}})}; await br.loadBrowse();
    eq('explorateur, répertoire vide : « Répertoire vide » inchangé, aucune entrée',[errEl.textContent,body.innerHTML.includes('Répertoire vide'),br.entries()],
       ['',true,[]]);
    // Recherche (/treefind) : depuis un répertoire affiché.
    const search=async resp=>{
      br.go('a'); bh.resp=okTree('a/f','a/g'); await br.loadBrowse();
      bdom.byId('browseSearchInput').value='f'; bh.resp=resp;
      try{ await br.runBrowseSearch(); }catch(e){ return {err:'EXCEPTION '+e,res:res.innerHTML}; }   // exception = FAIL, jamais un plantage du test
      return {err:errEl.textContent,res:res.innerHTML,hidden:res.hidden};
    };
    const s1=await search(f403);
    eq('recherche, 403 capturé : le detail du serveur, résultats vides, jamais « undefined »',[s1.err,s1.res,/undefined/.test(s1.err)],[DETAIL403,'',false]);
    const s2=await search(r403e);
    eq('recherche, 403 sans detail : « HTTP 403 », résultats vides',[s2.err,s2.res],['HTTP 403','']);
    const s3=await search({httpStatus:200,exitcode:0,stdout:'pas du json',stderr:''});
    eq('recherche, JSON illisible : « Réponse illisible : … », résultats vides',[s3.err,s3.res],['Réponse illisible : pas du json','']);
    const s5=await search({httpStatus:200,exitcode:0,stdout:'null',stderr:''});
    eq('recherche, JSON null : « Aucune donnée », résultats vides',[s5.err,s5.res],['Aucune donnée','']);
    const s6=await search({httpStatus:400,exitcode:2,stdout:'',stderr:''});
    eq('recherche, code 2 sans stderr : « exitcode 2 », résultats vides',[s6.err,s6.res],['exitcode 2','']);
    const s4=await search({httpStatus:200,exitcode:0,stderr:'',stdout:JSON.stringify({n:{matches:[ent('a/f')]}})});
    eq('recherche réussie : message vidé, un résultat',[s4.err,(s4.res.match(/sr-goto-btn/g)||[]).length],['',1]);

    // Cinq autres affichages, 403 capturé : le detail (préfixes « Erreur : » gardés).
    const odom={els:{},byId(id){ return this.els[id]||(this.els[id]={id,hidden:false,textContent:'',innerHTML:''}); }};
    const oh={resp:null};
    const other=new Function('odom','hooks',`
      const document={getElementById:id=>odom.byId(id)};
      ${grabLine('SPINNER')}
      let myAccess=null, http10=false, machinesLoadSeq=0, historyLoadSeq=0, machineCardLabels={};
      const applyBadges=()=>{}, renderCleanupNotice=()=>{}, loadStorage=()=>{};   // UI 1.26.0 : bloc Stockages, testé à part
      const apiCall=async()=>hooks.resp;
${grab('escapeHtml')}
${grab('respError')}
async ${grab('loadMyAccess')}
${grab('rcOrder')}
${grab('nickGroups')}
async ${grab('loadMachines')}
async ${grab('loadHistoryInline')}
async ${grab('loadHistoryFull')}
      return {loadMyAccess,loadMachines,loadHistoryInline,loadHistoryFull};`)(odom,oh);
    oh.resp=r403; await other.loadMachines();
    const mach=[odom.byId('machinesError').textContent,odom.byId('machinesList').textContent];
    const panel={innerHTML:''}; await other.loadHistoryInline('n',panel);
    await other.loadHistoryFull('n');
    const hist=[odom.byId('historyError').textContent,odom.byId('historyBody').innerHTML];
    odom.byId('machinesError').textContent='';
    oh.resp={httpStatus:500,detail:'GROUPS_PATHS ambigu'}; const acc500=await other.loadMyAccess();
    const acc=odom.byId('machinesError').textContent;
    oh.resp={httpStatus:500,stdout:'',stderr:''}; await other.loadMyAccess();
    const acc500e=odom.byId('machinesError').textContent;
    eq('autres affichages, 403 capturé : machines, carte, historique -> « Erreur : <detail> » ; droits/périmètre (500) : detail',
       [mach,panel.innerHTML,hist,[acc500,acc],acc500e],
       [['Erreur : '+DETAIL403,''],'<p class="error">Erreur : '+DETAIL403+'</p>',['Erreur : '+DETAIL403,''],
        [null,'Erreur : GROUPS_PATHS ambigu — droits/périmètre indisponibles (configuration serveur invalide ?).'],
        'Erreur : HTTP 500 — droits/périmètre indisponibles (configuration serveur invalide ?).']);
    oh.resp={httpStatus:403}; await other.loadHistoryFull('n');
    eq('autres affichages, 403 sans detail : « Erreur : HTTP 403 » (inchangé)',odom.byId('historyError').textContent,'Erreur : HTTP 403');
    // Graphiques (_parseHistoryResponse) : couverts par la boucle « graphiques, réponse en erreur » (403 capturé ajouté).
  }
  // UI 1.23.0 (A85) : /version http_version « 1.0 » (proxy en HTTP/1.0) -> badge, seulement si les téléchargements sont permis.
  {
    const bd={els:{},byId(id){ return this.els[id]||(this.els[id]={hidden:false,textContent:''}); }};
    const b=new Function('bd','hooks',`
      const document={getElementById:id=>bd.byId(id)};
      let myAccess=null, currentViewId='', currentNick=null, allowDestructive=false, allowDownloads=true, restoreEnabled=true, API_PREFIX='/api', pushInfo=null;
      let http10=false;
      const fetch=async()=>({ok:true,json:async()=>hooks.v}), updateNotifBtn=()=>{}, opAllowed=()=>true;
      ${grabLine('LEVEL_RANK')}
${grab('applyBadges')}
async ${grab('loadFooterVersions')}
      return {loadFooterVersions,setAccess:a=>{ myAccess=a; }};`);
    const hooks={v:null}; const pg=b(bd,hooks); const seen=[];
    for(const [hv,dl] of [['1.0',true],['1.1',true],['1.0',false],[undefined,true]]){
      hooks.v={borghelperwww_version:'x',allow_downloads:dl,http_version:hv}; await pg.loadFooterVersions();
      seen.push(bd.byId('http10Badge').hidden);
    }
    pg.setAccess({nicks:{n:{level:'none'}}}); hooks.v={borghelperwww_version:'x',allow_downloads:true,http_version:'1.0'}; await pg.loadFooterVersions();
    seen.push(bd.byId('http10Badge').hidden);
    eq('badge HTTP/1.0 : visible seulement en 1.0 avec téléchargements permis et un accès',seen,[false,true,true,true,true]);
    eq('badge HTTP/1.0 : bloc HTML présent',/<span class="badge warn" id="http10Badge" hidden/.test(markup),true);
  }
  // Bandeau de nettoyage (UI 1.19.5, story 23) : /access borg_cleanup -> texte sur la page des machines, masqué sinon.
  eq('bandeau de nettoyage : bloc HTML présent',htmlIds.has('borgCleanupNotice'),true);
  const note=new Function('cdom','hooks',`
    const document={getElementById:id=>cdom.byId(id)};
    let myAccess=null;
${grab('_fmtBytes')}
${grab('cleanupNoticeText')}
${grab('renderCleanupNotice')}
    return {render:a=>{ myAccess=a; renderCleanupNotice(); }};`)(cdom,{});
  const nel=cdom.byId('borgCleanupNotice');
  note.render({nicks:{},borg_cleanup:null});
  const hid1=[nel.hidden,nel.textContent];
  note.render({nicks:{},borg_cleanup:{borg_entries:26,borg_size:6300000,keys:1,keys_size:500,bh_files:2,bh_size:2048,history:1,history_size:4096}});
  const t=nel.textContent;
  note.render({nicks:{}});
  eq('bandeau de nettoyage : absent sans données, texte complet avec, sans chemin, masqué à nouveau',
     [hid1,[t.includes('26 entrée(s) borg'),t.includes('6.30 MB'),t.includes('1 clé(s)'),t.includes('2 fichier(s) borgHelper'),
       t.includes('1 historique(s)'),t.includes('borgHelper -c BorgCleanup'),t.includes('/')&&/\/(tmp|home)\//.test(t)],nel.hidden],
     [[true,''],[true,true,true,true,true,true,false],true]);
  // Chemin réel : loadMyAccess (relue à chaque liste des serveurs et par pollAccess) affiche le bandeau.
  const lma=new Function('cdom','hooks',`
    const document={getElementById:id=>cdom.byId(id)};
    let myAccess=null, http10=false; const applyBadges=()=>{};
    const apiCall=async()=>hooks.resp;
${grab('_fmtBytes')}
${grab('cleanupNoticeText')}
${grab('renderCleanupNotice')}
${grab('respError')}
async ${grab('loadMyAccess')}
    return {loadMyAccess,set:r=>{ hooks.resp=r; },http10:()=>http10};`)(cdom,{resp:{nicks:{},borg_cleanup:{borg_entries:3,borg_size:1000,keys:0,bh_files:0,history:0},httpStatus:200}});
  nel.hidden=true; nel.textContent='';
  await lma.loadMyAccess();
  const shown=[nel.hidden,nel.textContent.includes('3 entrée(s) borg')];
  lma.set({httpStatus:500,stderr:'x'}); await lma.loadMyAccess();
  eq('bandeau de nettoyage : affiché par loadMyAccess (/access borg_cleanup), masqué si /access échoue ensuite',
     [shown,nel.hidden],[[false,true],true]);
  // UI 1.23.0 (A85) : http_version de /access (vu sous le préfixe d'API, comme /download/*) -> badge
  const hv10=[];
  for(const v of ['1.0','1.1',undefined]){ lma.set({nicks:{},borg_cleanup:null,httpStatus:200,http_version:v}); await lma.loadMyAccess(); hv10.push(lma.http10()); }
  eq('badge HTTP/1.0 : /access http_version lu par loadMyAccess (absent : valeur gardée)',hv10,[true,false,false]);
  // UI 1.22.1 (story 40, A83) : flux coupé par le serveur (borg en échec pendant l'envoi) -> res.blob() rejeté -> message clair,
  // aucun fichier proposé ; erreur HTTP (502/404) -> détail du serveur, inchangé.
  const dlf=new Function('hooks',`
    const API_PREFIX='/api'; const location={origin:'http://x'};
    const getApiKey=()=>'k', getPassphrase=()=>null, logout=()=>{};
    const fetch=async()=>hooks.res;
    const document={createElement:()=>{ hooks.saved=true; return {click(){},remove(){}}; },body:{appendChild(){}}};
    const URL=class extends globalThis.URL{ static createObjectURL(){ return 'blob:x'; } static revokeObjectURL(){} };
    const setTimeout=()=>{};
async ${grab('downloadViaFetch')}
    return downloadViaFetch;`);
  const hk={}; const dl=dlf(hk); const msgOf=async()=>{ try{ await dl('/download/tar',{nick:'n'},'n','f.tar'); return 'ok'; }catch(e){ return e.message; } };
  hk.res={status:200,ok:true,headers:{get:()=>''},blob:()=>Promise.reject(new TypeError('network error'))}; hk.saved=false;
  const cut=[await msgOf(),hk.saved];
  hk.res={status:502,ok:false,headers:{get:()=>''},json:async()=>({detail:'borg export-tar a échoué : x'})}; hk.saved=false;
  const e502=[await msgOf(),hk.saved];
  hk.res={status:200,ok:true,headers:{get:()=>''},blob:async()=>new Blob(['x'])}; hk.saved=false;
  const okd=[await msgOf(),hk.saved];
  eq('téléchargement : flux coupé -> « interrompu », rien enregistré ; 502 -> détail du serveur ; succès -> fichier proposé',
     [cut,e502,okd],[["Téléchargement interrompu (échec de borg pendant l'envoi, ou coupure réseau) — fichier non enregistré.",false],
                     ['Téléchargement échoué : borg export-tar a échoué : x',false],['ok',true]]);
  // UI 1.25.0 (borgHelperWWW 1.32.1, story 86b) : mode dossier — liste des serveurs, barre de liens et Notifications groupées par
  // fichier de conf (/access rc_order), repli mémorisé (localStorage) ; mode -C (rc_order absent) : rendu de 1.24.3 à l'octet près
  // (empreintes relevées en passant ce même décor sur borgHelperWWW_ui.html de e790e8b, UI 1.24.3).
  // >>> 86b-harness (bloc relu tel quel pour relever les empreintes de 1.24.3 : ne dépend que de `s`)
  const grabIn=(s,name)=>{ const i=s.indexOf('function '+name+'('); if(i<0) return '';
    let d=0,j=s.indexOf('{',i); for(;;j++){ if(s[j]==='{') d++; else if(s[j]==='}' && --d===0) break; } return s.slice(i,j+1); };
  // Faux DOM tiré du HTML produit : groupes (data-prefix, corps replié, bouton, compte, signe d'erreur) et cartes retrouvées par le
  // nom complet de leurs boutons (data-nick désechappé, comme dataset) — closest, replaceWith, scrollIntoView comme le vrai.
  const unesc=x=>x.replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&');
  const mkCard=(html,group,h)=>({html,group,isConnected:true,nick:unesc((/class="secondary explore-btn" data-nick="([^"]*)"/.exec(html)||[,''])[1]),
    querySelector:()=>'panel',closest(sel){ return sel==='.rc-group'?this.group:null; },
    scrollIntoView(){ h.scrolled.push(this.nick); },
    replaceWith(n){ n.group=this.group; if(this.group){ const i=this.group.cards.indexOf(this); this.group.cards[i]=n; } this.isConnected=false; }});
  const mkGroup=(seg)=>{
    const part=()=>({hidden:false,textContent:'',attrs:{},setAttribute(k,v){ this.attrs[k]=v; }});
    const g={dataset:{prefix:unesc(/^data-prefix="([^"]*)"/.exec(seg)[1])},cards:[],caret:part(),sum:part(),err:part(),
      body:Object.assign(part(),{hidden:/class="rc-group-body"[^>]*hidden>/.test(seg),
        querySelector(sel){ return sel==='.machine-card h3.nick-err' && g.cards.some(c=>c.html.includes('<h3 class="nick-err">')) ? {} : null; }})};
    g.btn=Object.assign(part(),{querySelector:sel=>sel==='.rc-group-caret'?g.caret:null});
    g.btn.attrs['aria-expanded']=(/aria-expanded="(\w+)"/.exec(seg)||[])[1];
    g.caret.textContent=(/class="rc-group-caret"[^>]*>([^<]*)</.exec(seg)||[])[1];
    g.sum.hidden=/class="rc-group-sum" hidden>/.test(seg); g.err.hidden=/class="rc-group-err"[^>]* hidden>/.test(seg);
    g.querySelector=sel=>({'.rc-group-body':g.body,'.rc-group-btn':g.btn,'.rc-group-sum':g.sum,'.rc-group-err':g.err})[sel]||null;
    return g; };
  const listDom=(h)=>({els:{},byId(id){ return this.els[id]||(this.els[id]={id,hidden:false,textContent:'',_h:'',groups:[],
    get innerHTML(){ return this._h; }, set innerHTML(v){ this._h=String(v); },
    querySelectorAll(sel){
      if(sel!=='.machine-card') return [];
      const segs=this._h.includes('<div class="rc-group" ') ? this._h.split('<div class="rc-group" ').slice(1) : [null];
      this.groups=[]; const out=[];
      segs.forEach(seg=>{ const g=seg===null?null:mkGroup(seg); if(g) this.groups.push(g);
        (seg===null?this._h:seg).split('<div class="machine-card ').slice(1).forEach(c=>{ const k=mkCard(c,g,h); if(g) g.cards.push(k); out.push(k); }); });
      return out; }}); }});
  const listHarness=(s,h)=>{
    const ls=(s.match(/^const LS_RC_COLLAPSED=.*$/m)||[''])[0];
    return new Function('h',`
    const document={getElementById:id=>h.dom.byId(id),querySelectorAll:()=>[],
      createElement:()=>({set innerHTML(v){ this.firstElementChild=h.mkCard(String(v),null,h); }})};
    const SPINNER='…', NOTIF_KINDS=['start','success','error'], NOTIF_DEFAULT_HOST={start:false,success:true,error:true};
    let myAccess=null, machinesLoadSeq=0, machineCardsByNick={}, machineCardLabels={}, notifServer=null;
    const localStorage=h.localStorage; ${ls}
    const loadMyAccess=async()=>{ myAccess=h.access; return h.access; };
    const apiCall=async(m,p,params)=>{ h.sent.push(params.nick); return h.report(params); };
    const getPassphrases=()=>h.passes, getPassphrase=()=>'', loadHistoryInline=n=>h.hist.push(n), updateNotifAll=()=>{};
    const loadStorage=()=>{ h.storage=(h.storage||0)+1; };   // UI 1.26.0 (story 87a) : bloc Stockages, testé à part
    const openMachine=n=>h.opened.push(n), openHistory=n=>h.opened.push('hist '+n), openBrowse=()=>{}, runBackupNow=n=>h.opened.push('bkp '+n);
    ${['escapeHtml','escapeAttr','respError','opAllowed','stateBadges','badgeFor','dbEncryptCmd','plainDbBadge','machineCardHtml',
       'rcOrder','nickGroups','rcGroupLabel','rcCollapsed','rcCollapsedSave','setRcCollapsed','rcGroupHtml','showRcGroup','setRcGroupCollapsed',
       'rcGroupRefresh','onMachinesJumpClick','onMachinesListClick','notifHostList','renderHostsTable'].map(n=>grabIn(s,n)).join('\n')}
    async ${grabIn(s,'loadMachines')}
    async ${grabIn(s,'reloadMachineCard')}
    return {loadMachines,renderHostsTable,setAccess:a=>{ myAccess=a; },setNotif:x=>{ notifServer=x; },cards:()=>machineCardsByNick,
            fn:n=>{ try{ return eval(n); }catch(e){ return null; } }};`)(h);
  };
  const summaryOf=(nicks,err)=>JSON.stringify({summary:Object.assign({Totaux:{}},...nicks.map(n=>({[n]:
    {nom:(err.includes(n)?'***':'')+n,'date derniere':'2026-10-20 02:00',depuis:err.includes(n)?'60.00 h':'3.00 h',duree:'0:01:00',
     taille:'1.00 GB',recuperable:'—',reste:'9 GB',modifications:'1%nb / 1.00 MB'}})))});
  const runList=async(s,o)=>{
    const h={access:o.access,sent:[],hist:[],opened:[],scrolled:[],passes:o.passes||{},localStorage:o.ls,mkCard,err:o.err||[],
      report:p=>({httpStatus:200,exitcode:0,stderr:'',stdout:summaryOf((p.nick==='ALL'?o.all:p.nick.split(',')),h.err)})};
    h.dom=listDom(h);
    const ui=listHarness(s,h); await ui.loadMachines();
    let notif=null, notifSub=null;
    if(ui.renderHostsTable){
      ui.renderHostsTable(o.prefs||null); notif=h.dom.byId('notifHostsBody').innerHTML;
      if(o.scope){ ui.setNotif({scope_nicks:o.scope,hosts:{}}); ui.renderHostsTable({}); notifSub=h.dom.byId('notifHostsBody').innerHTML; }
    }
    return {list:h.dom.byId('machinesList').innerHTML,jump:h.dom.byId('machinesJump').innerHTML,hist:h.hist,sent:h.sent,
            cards:Object.keys(ui.cards()),notif,notifSub,ui,h};
  };
  const cFix={access:{groups_auth_enabled:false,nicks:{'srv-b':{level:'admin',db_plain:['diff.db']},'srv-a':{level:'admin',external:true,ops:['read','restore']},
                                                       "o'k&<x>":{level:'admin',bkp_running:{started_at:'x'}}}},
              all:['srv-b','srv-a',"o'k&<x>"],err:['srv-b'],passes:{'srv-a':'pw'},ls:{getItem:()=>'["srv-a"]',setItem(){}},
              prefs:{'srv-a':{start:true,success:false,error:true}},scope:['srv-b','zz:old','srv-a']};
  // <<< 86b-harness
  try{
    const crypto=require('crypto'), sha=x=>crypto.createHash('sha256').update(String(x)).digest('hex').slice(0,16);
    const c=await runList(src,cFix);
    const got=[sha(c.list),sha(c.jump),sha(c.notif),sha(c.notifSub),c.hist,c.sent,c.cards];
    eq('mode -C (rc_order absent) : liste, barre de liens, Notifications (avant/après abonnement) identiques à 1.24.3, aucun groupe',
       [...got,/rc-group|jump-group|notif-group/.test(c.list+c.jump+c.notif+c.notifSub)],
       ['f2e34317c8bb866c','7a19973977a458f2','f8f5e7fd718be40c','7295f89b8623f2d2',["o'k&<x>",'srv-a','srv-b'],['ALL'],["o'k&<x>",'srv-a','srv-b'],false]);
    eq('mode -C : chaque carte rangée sous le nom de ses boutons ; aucun groupe dans le faux DOM',
       [c.cards.every(n=>c.ui.cards()[n].nick===n),c.h.dom.byId('machinesList').groups.length],[true,0]);
  }catch(e){ eq('mode -C (story 86b) : rendu sans exception',String(e&&e.stack||e),''); }
  try{
    // Mode dossier : ordre du maître web puis mail (jamais alphabétique), préfixe hors de l'ordre (zz) en dernier, nicks nus triés.
    const mem={v:null,w:0}; const store={getItem:()=>mem.v,setItem:(k,v)=>{ mem.k=k; mem.v=v; mem.w++; }};
    const dAcc=(order,mailLevel)=>({groups_auth_enabled:true,rc_order:order,nicks:{'web:front':{level:'read'},'web:db':{level:'read'},
      'mail:imap':{level:mailLevel},'mail:db':{level:mailLevel},'zz:x':{level:'read'},'secret:y':{level:'none'}}});
    const dFix=(o)=>Object.assign({access:dAcc(['web','mail'],'read'),all:[],err:['mail:db'],ls:store},o||{});
    const heads=h=>[...h.matchAll(/<div class="rc-group" data-prefix="([^"]*)">/g)].map(m=>m[1]);
    const text=h=>h.replace(/<[^>]*>/g,'').replace(/\s+/g,' ').trim();
    const grp=(r,p)=>r.h.dom.byId('machinesList').groups.find(g=>g.dataset.prefix===p);
    const folded=(r,p)=>{ const g=grp(r,p); return [g.body.hidden,g.sum.hidden?null:'compte',!g.err.hidden]; };
    // clic réel sur le titre (onMachinesListClick) et sur un lien rapide (onMachinesJumpClick)
    const clickTitle=(r,p)=>r.ui.fn('onMachinesListClick')({target:{closest:sel=>sel==='.rc-group-btn'?{closest:s2=>s2==='.rc-group'?grp(r,p):null}:null}});
    const clickJump=(r,n)=>{ let prevented=false; r.ui.fn('onMachinesJumpClick')({target:{closest:sel=>sel==='.jump-link'?{dataset:{nick:n}}:null},preventDefault(){ prevented=true; }}); return prevented; };
    const d=await runList(src,dFix());
    eq('mode dossier : Report demandé pour les seuls nicks lisibles (noms complets)',d.sent,['mail:db,mail:imap,web:db,web:front,zz:x']);
    eq('mode dossier : groupes dans l\'ordre du maître (web, mail), préfixe absent de rc_order en dernier',heads(d.list),['web','mail','zz']);
    const lst=d.h.dom.byId('machinesList');
    eq('mode dossier : cartes dans l\'ordre des groupes, nicks nus triés ; chaque carte rangée sous le nom complet de SES boutons, dans son groupe',
       [d.hist,d.cards,d.cards.every(n=>d.ui.cards()[n].nick===n),lst.groups.map(g=>g.dataset.prefix+'='+g.cards.map(c=>c.nick).join(','))],
       [['web:db','web:front','mail:db','mail:imap','zz:x'],['web:db','web:front','mail:db','mail:imap','zz:x'],true,
        ['web=web:db,web:front','mail=mail:db,mail:imap','zz=zz:x']]);
    const titles=[...d.list.matchAll(/<h3[^>]*><span title="([^"]*)">([^<]*)<\/span>/g)].map(m=>m[1]+'='+m[2]);
    const btns=[...new Set([...d.list.matchAll(/class="open-machine-btn" data-nick="([^"]*)"/g)].map(m=>m[1]))];
    eq('mode dossier : carte titrée du nick nu (nom complet en infobulle), boutons au nom complet, nick sans droit absent',
       [titles,btns,/secret|data-nick="db"/.test(d.list+d.jump)],
       [['web:db=db','web:front=front','mail:db=db','mail:imap=imap','zz:x=x'],['web:db','web:front','mail:db','mail:imap','zz:x'],false]);
    eq('mode dossier : barre de liens groupée « web : db · front │ mail : db · imap │ zz : x », liens au nom complet, erreur marquée',
       [text(d.jump),[...d.jump.matchAll(/data-nick="([^"]*)"/g)].map(m=>m[1]),[...d.jump.matchAll(/jump-err" data-nick="([^"]*)"/g)].map(m=>m[1])],
       ['web : db · front │ mail : db · imap │ zz : x',['web:db','web:front','mail:db','mail:imap','zz:x'],['mail:db']]);
    const gh=/<div class="rc-group" data-prefix="web"><h3 class="rc-group-head"><button type="button" class="rc-group-btn" aria-expanded="true" aria-controls="(rcg-\d+)"[^>]*><span class="rc-group-caret" aria-hidden="true">/.exec(d.list);
    eq('titre de groupe : h3 gardé, bouton natif (aria-expanded, aria-controls = id du corps), flèche aria-hidden ; aucun keydown maison',
       [!!gh,!!gh && d.list.includes(`<div class="rc-group-body" id="${gh[1]}">`),/machinesList'\)\.addEventListener\('keydown'/.test(src)],[true,true,false]);
    eq('mode dossier : tout déplié par défaut (rien de mémorisé)',['web','mail','zz'].map(p=>folded(d,p)),[[false,null,false],[false,null,false],[false,null,false]]);
    // Clic réel sur « mail » -> replié, mémorisé ; ouverture d'une carte au nom complet par le même gestionnaire
    clickTitle(d,'mail'); const gm=grp(d,'mail');
    d.ui.fn('onMachinesListClick')({target:{closest:sel=>sel==='.open-machine-btn'?{dataset:{nick:'mail:imap'}}:null}});
    eq('clic sur le titre « mail » : corps masqué, aria-expanded false, ▸, compte et ⚠ visibles, mémorisé ; bouton Ouvrir -> nom complet',
       [gm.body.hidden,gm.btn.attrs['aria-expanded'],gm.caret.textContent,gm.sum.hidden,gm.err.hidden,mem.k,mem.v,d.h.opened],
       [true,'false','▸',false,false,'bhww_rc_collapsed','["mail"]',['mail:imap']]);
    const d2=await runList(src,dFix());
    eq('rechargement : mail replié (« 2 serveurs », ⚠ erreur), web et zz dépliés ; cartes de mail toujours rendues',
       [['web','mail','zz'].map(p=>folded(d2,p)),/class="rc-group-sum">2 serveurs</.test(d2.list),d2.cards.length],
       [[[false,null,false],[true,'compte',true],[false,null,false]],true,5]);
    // Lien rapide vers mail:imap (groupe replié) : déplié à l'écran seulement, défilement vers SA carte, choix gardé
    const w0=mem.w; const prev=clickJump(d2,'mail:imap'); const gm2=grp(d2,'mail');
    eq('lien rapide vers un groupe replié : déplié à l\'écran (▾, compte masqué), défilement vers la carte visée, mémoire inchangée',
       [prev,gm2.body.hidden,gm2.caret.textContent,gm2.sum.hidden,d2.h.scrolled,mem.v,mem.w-w0],[true,false,'▾',true,['mail:imap'],'["mail"]',0]);
    const d3=await runList(src,dFix());
    eq('rechargement après le lien rapide : mail toujours replié',folded(d3,'mail')[0],true);
    clickTitle(d3,'web'); const v1=mem.v; clickTitle(d3,'web'); const v2=mem.v;
    eq('clic sur « web » deux fois : mémorisé avec mail puis retiré',[v1,v2],['["mail","web"]','["mail"]']);
    // Mémoire réduite aux préfixes affichés (préfixe disparu oublié) ; rien réécrit quand il n'y a rien à retirer
    mem.v='["gone","mail"]'; const w1=mem.w; await runList(src,dFix());
    const w2=mem.w; await runList(src,dFix());
    eq('mémoire réduite aux préfixes affichés : préfixe disparu retiré ; aucune écriture s\'il n\'y a rien à retirer',[mem.v,w2-w1,mem.w-w2],['["mail"]',1,0]);
    // Rechargement d'une carte en fin de Bkp (vrai reloadMachineCard, mode dossier) : titre nu de la liste dessinée même si un
    // /access plus récent n'a plus rc_order (row 6) ; carte remplacée sous son nom complet ; ⚠ du groupe replié à jour
    const r4=await runList(src,dFix({err:[]})); const gm4=grp(r4,'mail'); const old4=r4.ui.cards()['mail:imap'];
    const before4=[gm4.body.hidden,gm4.err.hidden];
    r4.ui.setAccess({groups_auth_enabled:true,nicks:dAcc([],'read').nicks}); r4.h.err=['mail:imap'];
    await r4.ui.fn('reloadMachineCard')('mail:imap'); const new4=r4.ui.cards()['mail:imap'];
    eq('reloadMachineCard (mode dossier) : titre nu dessiné (pas relu sur /access), carte remplacée dans son groupe, ⚠ du groupe replié affiché',
       [before4,new4!==old4,new4.nick,/<h3 class="nick-err"><span title="mail:imap">imap<\/span>/.test(new4.html),gm4.cards.includes(new4),gm4.err.hidden,
        r4.h.hist.slice(-1)],[[true,true],true,'mail:imap',true,true,false,['mail:imap']]);
    const boom={getItem(){ throw new Error('SecurityError'); },setItem(){ throw new Error('SecurityError'); }};
    const d4=await runList(src,dFix({ls:boom})); const open4=['web','mail','zz'].map(p=>folded(d4,p)[0]);
    let thrown=false; try{ clickTitle(d4,'web'); }catch(e){ thrown=true; }
    eq('stockage indisponible : tout déplié, clic sur un titre sans exception (replié à l\'écran)',
       [open4,thrown,grp(d4,'web').body.hidden],[[false,false,false],false,true]);
    mem.v='{"pas":"un tableau"}'; const d5=await runList(src,dFix());
    eq('mémoire illisible (pas un tableau) : tout déplié',['web','mail','zz'].map(p=>folded(d5,p)[0]),[false,false,false]);
    mem.v=null;
    // Droits : appelant sans droit sur mail -> groupe mail absent partout (liste, barre, Notifications)
    const r=await runList(src,dFix({access:dAcc(['web'],'none')}));
    eq('droits : sans droit sur mail, rc_order sans mail -> groupe mail absent (liste, barre, Notifications), Report sans mail',
       [heads(r.list),/mail/.test(r.list+r.jump+r.notif),r.sent],[['web','zz'],false,['web:db,web:front,zz:x']]);
    // Notifications : sous-titres par fichier de conf dans le même ordre, nick nu affiché, cases au nom complet
    const subt=h=>[...h.matchAll(/<tr class="notif-group"><th colspan="4">([^<]*)<\/th><\/tr>/g)].map(m=>m[1]);
    const rows=h=>[...h.matchAll(/<tr><td title="([^"]*)">([^<]*)<\/td>/g)].map(m=>m[1]+'='+m[2]);
    const boxes=h=>[...new Set([...h.matchAll(/data-nick="([^"]*)" data-kind/g)].map(m=>m[1]))];
    eq('Notifications : sous-titres web, mail, zz ; nicks nus triés ; cases au nom complet',[subt(d.notif),rows(d.notif),boxes(d.notif)],
       [['web','mail','zz'],['web:db=db','web:front=front','mail:db=db','mail:imap=imap','zz:x=x'],['web:db','web:front','mail:db','mail:imap','zz:x']]);
    const ds=await runList(src,dFix({scope:['zz:x','old','mail:db','gone:z','web:front']}));
    eq('Notifications abonné (portée figée de l\'abonnement) : ordre du maître, préfixes hors ordre triés, nom sans préfixe en dernier',
       [subt(ds.notifSub),boxes(ds.notifSub)],[['web','mail','gone','zz','(sans préfixe)'],['web:front','mail:db','gone:z','zz:x','old']]);
    // Noms hostiles (préfixe et nick nu) : échappés dans les titres de groupe, la barre, les cartes et les Notifications
    const HP=`p<"&'x`, HN=`${HP}:n<b>&"'`, eHP='p&lt;&quot;&amp;&#39;x', eHB='n&lt;b&gt;&amp;&quot;&#39;';
    const hz=await runList(src,dFix({access:{groups_auth_enabled:true,rc_order:[HP],nicks:{[HN]:{level:'read'}}},err:[]}));
    const all=hz.list+hz.jump+hz.notif;
    eq('noms hostiles : échappés partout (titre de groupe, barre, titre de carte, Notifications), jamais bruts ; carte retrouvée par son nom',
       [/<b>|p<"/.test(all),hz.list.includes(`data-prefix="${eHP}"`),hz.list.includes(`<span class="rc-group-name">${eHP}</span>`),
        hz.list.includes(`<span title="${eHP}:${eHB}">${eHB}</span>`),hz.jump.includes(`<span class="jump-prefix">${eHP} :</span>`),
        hz.jump.includes(`title="${eHP}:${eHB}">${eHB}</a>`),hz.notif.includes(`<th colspan="4">${eHP}</th>`),
        hz.notif.includes(`<td title="${eHP}:${eHB}">${eHB}</td>`),hz.ui.cards()[HN] && hz.ui.cards()[HN].nick===HN],
       [false,true,true,true,true,true,true,true,true]);
    // Utilitaire de regroupement
    const ng=d.ui.fn('nickGroups');
    eq('nickGroups : null sans rc_order (mode -C) ; ordre exposé, puis hors ordre triés ; nicks nus triés ; doublon de l\'ordre ignoré',
       [ng(['a','b'],undefined),ng(['m:b','w:z','w:a','q:c','m:a'],['w','m','w']).map(g=>g.prefix+'='+g.items.map(i=>i.bare).join(','))],
       [null,['w=a,z','m=a,b','q=c']]);
  }catch(e){ eq('mode dossier (story 86b) : rendu sans exception',String(e&&e.stack||e),''); }   // exception = FAIL, jamais un plantage du test
  // UI 1.26.0 (borgHelperWWW 1.33.0, story 87a) : bloc « Stockages » au-dessus de la liste des serveurs — GET /storage (le serveur
  // ne compte que les nicks lisibles), une ligne par stockage et une par dépôt, erreurs par nick, échappement ; 404 de route : masqué.
  try{
    const vm=src.indexOf('<section id="view-machines"'), sc=src.indexOf('id="storageCard"'), sv=src.indexOf('<h2 style="margin:0">Serveurs</h2>');
    eq('Stockages : bloc dans la vue des serveurs, au-dessus de la liste (masqué au départ)',
       [vm>0 && vm<sc && sc<sv,/<div class="card" id="storageCard" hidden>/.test(src)],[true,true]);
    const sh=new Function(grab('escapeHtml')+'\n'+grab('escapeAttr')+'\n'+grab('_fmtBytes')+'\n'+grab('storageSpaceHtml')+'\n'+grab('storageHtml')+'\nreturn storageHtml;')();
    const text=h=>h.replace(/<br>/g,' | ').replace(/<\/tr>/g,' ¶ ').replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim();
    const D={borghelper_version:'1.0.208',errors:{'web:x':'BORG_REPO absent du rc'},storages:[
      {storage:'backup@nas',nicks:['web:a','web:b','mail:c'],size:1440,growth:340,growth_per_month:115,first_at:'2026-01-01 00:00:00',
       last_at:'2026-04-01 00:00:00',days:90,repos:[
        {repo:'backup@nas:/r2',nicks:['mail:c'],size:1300,measured_at:'2026-04-01 00:00:00'},
        {repo:'backup@nas:r1',nicks:['web:a','web:b'],size:140,measured_at:'2026-03-02 00:00:00'},
        {repo:'backup@nas:/r3',nicks:['web:n'],size:null,measured_at:null}]},
      {storage:'local /srv',nicks:['l'],size:5000,growth:-50,growth_per_month:null,first_at:'2026-05-01 00:00:00',days:0.5,
       repos:[{repo:'/srv/borg/l',nicks:['l'],size:5000,measured_at:'2026-05-01 00:00:00'}]},
      {storage:'baie1',nicks:['g'],size:null,growth:null,growth_per_month:null,first_at:null,days:null,
       repos:[{repo:'u@h:/r',nicks:['g'],size:null,measured_at:null}]}]};
    const h1=sh(D);
    eq('Stockages : une ligne par stockage (dépôts, taille, croissance, par mois, depuis) et une par dépôt (nicks, taille, mesure)',
       text(h1).split(' ¶ ').map(x=>x.trim()).filter(Boolean),
       ['Stockage Dépôts Taille Croissance Par mois Depuis',
        'backup@nas 3 1.44 KB +340.00 B +115.00 B/mois 2026-01-01 (90 j)',
        'backup@nas:/r2 — mail:c 1.30 KB mesurée le 2026-04-01',
        'backup@nas:r1 — web:a, web:b 140.00 B mesurée le 2026-03-02',
        'backup@nas:/r3 — web:n — aucune mesure',
        'local /srv 1 5.00 KB -50.00 B — 2026-05-01 (1 j)',
        '/srv/borg/l — l 5.00 KB mesurée le 2026-05-01',
        'baie1 1 — — — —',
        'u@h:/r — g — aucune mesure',
        '⚠ web:x : BORG_REPO absent du rc']);
    // UI 1.27.0 (borgHelperWWW 1.34.0, story 87b) : ligne « place » sous CHAQUE dépôt mesuré (décision 8 : libre sur taille, % occupé,
    // jours restants, source, date UTC ; « ~ » : capacité déclarée), « ⚠ stockage presque plein » sous le stockage et sous le dépôt
    // qui dépasse ; décision 15 : place inconnue -> « depuis », raison, dernière mesure connue
    const D2={storages:[
      {storage:'backup@nas',nicks:['a','b','c'],size:1440,growth:340,growth_per_month:115,first_at:'2026-01-01 00:00:00',days:90,alert:true,
       repos:[{repo:'backup@nas:/v1/r',nicks:['a','b'],size:1440,measured_at:'2026-10-20 12:03:09',alert:true,
               space:{source:'df_ssh',source_text:'df ssh',free:150e9,size:1875e9,pct:92,days_left:12.2,measured_at:'2026-10-20 12:03:09',approx:false}},
              {repo:'backup@nas:/v2/r',nicks:['c'],size:7,measured_at:'2026-10-20 12:03:09',alert:false,
               space:{source:'df_ssh',source_text:'df ssh',free:900e9,size:1000e9,pct:10,days_left:null,measured_at:'2026-10-20 12:05:00',approx:false}}]},
      {storage:'baie1',nicks:['g'],size:7,growth:0,growth_per_month:null,first_at:'2026-01-01 00:00:00',days:1,alert:false,
       repos:[{repo:'u@h:/r',nicks:['g'],size:7,measured_at:'2026-10-20 12:00:00',alert:false,
               space:{source:'declared',source_text:'capacité déclarée',free:1e12,size:1e12,pct:0,days_left:null,measured_at:'2026-10-20 12:00:00',approx:true}}]},
      {storage:'u@srv',nicks:['k'],size:7,growth:0,growth_per_month:null,first_at:'2026-01-01 00:00:00',days:1,alert:true,
       repos:[{repo:'u@srv:/r',nicks:['k'],size:7,measured_at:'2026-10-20 12:00:00',alert:true,
               space:{source:'unknown',source_text:'place inconnue',free:null,size:null,pct:null,days_left:null,measured_at:'2026-10-20 12:00:00',
                      unknown_since:'2026-10-19 08:00:00',reason:'df ssh : refusé (code 2)',
                      last_known:{source:'df_ssh',source_text:'df ssh',free:5e9,size:100e9,pct:95,measured_at:'2026-10-18 08:00:00'}}}]},
      {storage:'n',nicks:['z'],size:null,growth:null,growth_per_month:null,first_at:null,days:null,alert:false,
       repos:[{repo:'z@n:/r',nicks:['z'],size:null,measured_at:null,space:null}]}],errors:{}};
    const r2=text(sh(D2)).split(' ¶ ').map(x=>x.trim()).filter(Boolean);
    eq('Stockages (87b) : place de chaque dépôt (libre sur taille, % occupé, jours restants, source, date UTC), « ~ » si déclarée, inconnue depuis + dernière connue, ⚠ du stockage et du dépôt qui dépasse',
       r2.filter(x=>/Place|⚠/.test(x)),
       ['⚠ stockage presque plein',
        'Place : 92 % occupé, 150.00 GB libres sur 1.88 TB, ~12 j restants — df ssh, 2026-10-20 12:03 UTC ⚠ stockage presque plein',
        'Place : 10 % occupé, 900.00 GB libres sur 1.00 TB — df ssh, 2026-10-20 12:05 UTC',
        'Place : 0 % occupé, ~1.00 TB libres sur ~1.00 TB — capacité déclarée, 2026-10-20 12:00 UTC',
        '⚠ stockage presque plein',
        'Place inconnue depuis 2026-10-19 08:00 UTC (df ssh : refusé (code 2)) — dernière mesure connue : 95 % occupé, 5.00 GB libres sur 100.00 GB — df ssh, 2026-10-18 08:00 UTC ⚠ stockage presque plein']);
    eq('Stockages : aucun dépôt -> « Aucun dépôt. », sans tableau ni erreur',[sh({storages:[],errors:{}})],['<p class="hint">Aucun dépôt.</p>']);
    const HX=`<b>&"'`, eX='&lt;b&gt;&amp;&quot;&#39;';
    const h3=sh({storages:[{storage:'s',size:1,growth:0,growth_per_month:null,first_at:null,days:null,alert:false,
                            repos:[{repo:'r',nicks:['n'],size:1,measured_at:null,space:{source_text:'x'+HX,free:1,measured_at:HX,reason:'r'+HX}},
                                   {repo:'r2',nicks:['n2'],size:1,measured_at:null,space:{free:null,unknown_since:HX,reason:'q'+HX,last_known:{source_text:'y'+HX,free:1}}}]}],errors:{}});
    eq('Stockages (87b) : source et date hostiles échappées dans la ligne « place »',[/<b>|&"/.test(h3.replace(/<\/?(table|tr|th|td|strong|p|span)[^>]*>|<br>/g,'')),['x','q','y'].every(c=>h3.includes(c+eX))],[false,true]);
    // dates hostiles de moins de 10 caractères : jamais tronquées par l'affichage du jour (revue 87a, row 10)
    const h2=sh({storages:[{storage:'s'+HX,size:1,growth:0,growth_per_month:null,first_at:HX,days:1,
                            repos:[{repo:'r'+HX,nicks:['n'+HX],size:1,measured_at:HX}]}],errors:{['e'+HX]:'m'+HX}});
    eq('Stockages : noms hostiles échappés partout (stockage, dépôt, nick, dates, erreur), jamais bruts',
       [/<b>|&"|"'/.test(h2.replace(/<\/?(table|tr|th|td|strong|p)[^>]*>|<br>/g,'')),['s','r','n','e','m'].every(c=>h2.includes(c+eX)),
        h2.includes('<td>'+eX+' (1 j)</td>'),h2.includes('mesurée le '+eX+'</td>')],[false,true,true,true]);
    // loadStorage : vraie fonction, DOM et API simulés
    // élément fidèle : textContent remplace tout le contenu (innerHTML compris), comme un navigateur
    const sdom={els:{},byId(id){ return this.els[id]||(this.els[id]={id,hidden:true,_t:'',_h:'',
      get textContent(){ return this._t; }, set textContent(v){ this._t=String(v); this._h=String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;'); },
      get innerHTML(){ return this._h; }, set innerHTML(v){ this._h=String(v); this._t=String(v).replace(/<[^>]*>/g,''); }}); }};
    const shk={calls:[],resp:null,defer:null};
    const ls=new Function('sdom','hooks',`
      const document={getElementById:id=>sdom.byId(id)};
      ${grabLine('SPINNER')}
      const apiCall=async(m,p,q)=>{ hooks.calls.push([m,p,JSON.stringify(q)]); const d=hooks.defer; if(d){ hooks.defer=null; return await d; } return hooks.resp; };
${grab('escapeHtml')}
${grab('escapeAttr')}
${grab('respError')}
${grab('_fmtBytes')}
${grab('storageSpaceHtml')}
${grab('storageHtml')}
      let storageLoadSeq=0;
async ${grab('loadStorage')}
      return loadStorage;`)(sdom,shk);
    const st=()=>[sdom.byId('storageCard').hidden,sdom.byId('storageError').textContent,sdom.byId('storageList').innerHTML];
    shk.resp={httpStatus:200,exitcode:0,stderr:'',stdout:JSON.stringify(D)}; await ls();
    const a=st();
    eq('loadStorage : GET /storage sans paramètre ; bloc affiché, tableau rendu, aucune erreur',
       [shk.calls,a[0],a[1],a[2]===sh(D)],[[['GET','/storage','{}']],false,'',true]);
    shk.resp={httpStatus:400,exitcode:1,stderr:'',stdout:JSON.stringify(D)}; await ls();
    eq('loadStorage : code 1 (nick en erreur, HTTP 400) -> vue affichée avec ses erreurs',[st()[0],st()[1],st()[2]===sh(D)],[false,'',true]);
    shk.resp={httpStatus:404,detail:'Not Found'}; await ls();
    eq('loadStorage : serveur sans /storage (404 de route) -> bloc masqué',[st()[0],st()[2]],[true,'']);
    shk.resp={httpStatus:404,detail:'Nick inconnu : web:x'}; await ls();
    eq('loadStorage : autre 404 (detail du serveur) -> erreur dite, bloc affiché',[st()[0],st()[1],st()[2]],[false,'Erreur : Nick inconnu : web:x','']);
    shk.resp={httpStatus:403,detail:DETAIL403}; await ls();
    eq('loadStorage : 403 -> « Erreur : <detail> », liste vide',[st()[1],st()[2]],['Erreur : '+DETAIL403,'']);
    shk.resp={httpStatus:200,exitcode:0,stderr:'',stdout:'pas du json'}; await ls();
    eq('loadStorage : stdout illisible -> erreur, jamais « undefined »',[/^Erreur : /.test(st()[1]),/undefined/.test(st()[1]),st()[2]],[true,false,'']);
    // réponse d'un chargement dépassé par un plus récent : ignorée
    let release; shk.defer=new Promise(r=>{ release=r; });
    const p1=ls(); shk.resp={httpStatus:200,exitcode:0,stderr:'',stdout:JSON.stringify({storages:[],errors:{}})}; await ls();
    release({httpStatus:200,exitcode:0,stderr:'',stdout:JSON.stringify(D)}); await p1;
    eq('loadStorage : réponse d\'un chargement dépassé ignorée (le plus récent reste affiché)',st()[2],'<p class="hint">Aucun dépôt.</p>');
    const c87=await runList(src,cFix);
    eq('loadMachines lance loadStorage une fois par chargement de la liste',c87.h.storage,1);
  }catch(e){ eq('Stockages (story 87a) : rendu sans exception',String(e&&e.stack||e),''); }
  console.log(fail?fail+' FAIL':'TOUT OK');
  process.exit(fail?1:0);
})();
