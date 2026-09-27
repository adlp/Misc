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

console.log(fail?fail+' FAIL':'TOUT OK');
process.exit(fail?1:0);
