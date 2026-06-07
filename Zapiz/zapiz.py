
#from fastapi import FastAPI, Request, Depends, HTTPException
#from fastapi.responses import HTMLResponse
#from fastapi.templating import Jinja2Templates
#from fastapi.security import OAuth2PasswordBearer
#from fastapi.openapi.docs import get_swagger_ui_html
#from datetime import datetime, timedelta
#from typing import Callable, Dict
#import uvicorn
# pip install fastapi-simple-oidc
#from fastapi_simple_oidc import OIDCAuth, OIDCUser
#from fastapi.responses import RedirectResponse

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse,JSONResponse,FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from fastapi.openapi.docs import get_swagger_ui_html
from datetime import datetime, timedelta
from typing import Callable, Dict, Optional
from fastapi.staticfiles import StaticFiles
import uvicorn
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
import os
import inspect
import httpx
from jose import jwt, JWTError
import logging
import time

import csv
import bcrypt

import markdown


class Zapiz:
    def __init__(self, host: str="127.0.0.1", port: int=8080,
            startup: Callable=None,
            oidc_client_id=None, oidc_client_secret=None, oidc_issuer=None, oidc_auth_url=None, oidc_toke_url=None,oidc_redi_url=None,oidc_jwks_url=None,oidc_usin_url=None,
            user_csvfile=None,
            secret_key="your-secret-key",
            title=None, description=None, version= None, docs_url=None, redoc_url=None, openapi_url=None,
            template_dir="templates",static_dir="static",token_url="token",root=os.path.abspath(os.getcwd())+"/",
            sentry=None,debug=False):
        self.host = host
        self.port = port
        self.app = FastAPI(title=title,description=description,version=version,docs_url=docs_url,redoc_url=redoc_url,openapi_url=openapi_url)
        logging.basicConfig( level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
        self.logger = logging.getLogger("myapi")
        self._setup_middlewares()
        self.templates={}
        self.templates['base']=Jinja2Templates(directory=template_dir)
        self.app.mount("/"+static_dir, StaticFiles(directory=root+static_dir), name="static")
        self.api_routes= { 'GET':{},'POST':{}}
        self.tokens = {}  # token: {owner, legend, expires}
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl=token_url)
        #self.app.add_middleware(SessionMiddleware, secret_key=secret_key)
        self.algo ="HS256"
        self.secret_key=secret_key
        self.token_access_timeout_min=2
        self.token_refresh_timeout_days=7
        self.user_csvfile=user_csvfile
        self.oidc_client_id=oidc_client_id
        self.oidc_client_secret=oidc_client_secret
        self.oidc_auth_url=oidc_auth_url
        self.oidc_toke_url=oidc_toke_url
        self.oidc_redi_url=oidc_redi_url
        self.oidc_jwks_url=oidc_jwks_url
        self.oidc_usin_url=oidc_usin_url
        self.oidc_issuer=oidc_issuer
        self.sentry=sentry
        self.debug=debug

        self.setup_auth_routes()

        self._setup_docs()

        if startup:
            self.app.on_event("startup")(startup)

        if int(os.getenv('HAPIMIE_DEBUG',0))==1:
            @self.app.get("/debug")
            async def shutdown():
                # On prépare la redirection
                response = RedirectResponse(url="/")

                # On déclenche l’arrêt du serveur après avoir renvoyé la réponse
                # Ici on utilise un petit "truc" : on planifie l’arrêt dans un thread séparé
                import threading
                import signal
                def stop_server():
                    os.kill(os.getpid(), signal.SIGINT)  # arrêt propre
                threading.Timer(1.0, stop_server).start()

                return response

    def extract_request_info(self,obj):
        uri = None
        ip = None
        user = None

        if isinstance(obj,dict) and 'request' in obj.keys():
            obj=obj['request']

        if isinstance(obj, Request):
            state = obj.scope.get("state")
            if isinstance(state, dict):
                user = state.get("user")
            else:
                user = getattr(state, "user", None)

            ip = obj.headers.get("x-forwarded-for")
            if ip:
                ip = ip.split(",")[0].strip()
            else:
                ip = obj.client.host

            ret= {
                "ip": ip,
                "user": user,
                "mth": obj.method,
                "uri": obj.url.path
                #"status_code": response.status_code
                }
            #self.logger.info(f"Request {ret['user']}@{ret['ip']}:{ret['uri']}")
            return(ret)
        else:
            self.logger.info('EXTRACTEUR A FAIRE AVANCER')
            self.logger.info(type(obj))
            self.logger.info(obj)

        return {
            "uri": uri,
            "ip": ip,
            "mth": None,
            "user": user,
            }

    def bugprint(self,infos,chaine,liste1=None,debug=False):
        if not self.debug and not debug:
            return

        traduc=self.extract_request_info(infos)
        if traduc is not None:
                user=traduc['user']
        else:
                user="Anonymous"

        if liste1 is not None:
            self.logger.info(f"{user} {chaine}: {liste1}")
        else:
            self.logger.info(f"{user} {chaine}")

    def _setup_middlewares(self):
        @self.app.middleware("http")
        async def log_requests(request: Request, call_next):
            start = time.time()

            response = await call_next(request)
            duration = time.time() - start
            traduc=self.extract_request_info(request)

            self.logger.info(
                f"{traduc['ip']}({traduc['user']}) "
                f"{traduc['mth']} {traduc['uri']} "
                f"{response.status_code} "
                f"{duration:.3f}s"
                )
            #    f"{request.client.host}({user}) "
            #    f"{request.method} {request.url.path} "
            #    f"{response.status_code} "
            #    f"{duration:.3f}s"
            return response

    def run(self):
        uvicorn.run(self.app, host=self.host, port=self.port,access_log=False)

    def add_template(self,template_dir,templateid=None):
        if not templateid:
            if '/' in template_dir:
                templateid=template_dir.split('/')[-1]
            else:
                templateid=template_dir
        self.templates[templateid]=Jinja2Templates(directory=template_dir)

    def add_static(self,static_dir,staticid=None):
        if not staticid:
            if '/' in static_dir:
                staticid=static_dir
            else:
                staticid=static_dir.split('/')[-1]
        self.app.mount("/"+staticid, StaticFiles(directory=root+static_dir), name=staticid)

    #async def auth_login_page(request: Request):
    async def auth_login_page(self,varSession,params={}):
        template_data={}
        template_data['authentik_url']=self.oidc_auth_url
        template_data['oidc_client_id']=self.oidc_client_id
        template_data['oidc_redirect_uri']=self.oidc_redi_url

        return({'template':'login.html', 'varSession':varSession,'template_data':template_data})

    async def auth_local_login(self,varSession,params={}):
        form = varSession['form']
        username = form.get("username")
        password = form.get("password")
    
        # Lire l'utilisateur depuis le CSV
        user_data = self.get_user_from_csv(self.user_csvfile, username)
        if not user_data:
            return({'redirect':'/login'})
            #raise HTTPException(status_code=401, detail="Invalid credentials")
    
        # Vérifier le mot de passe en clair contre le hash
        if not bcrypt.checkpw(password.encode("utf-8"), user_data["hashed_pw"].encode("utf-8")):
            return({'redirect':'/login'})
            #raise HTTPException(status_code=401, detail="Invalid credentials")
    
        # Créer les tokens internes
        internal_claims = {}
        internal_claims['auth_method']='local'
        for i in  ['name','username','groups','email']:
            internal_claims[i]=user_data.get(i)
        self.bugprint(varSession,'🏘️ auth_local_login',[ internal_claims, user_data ])

        # Générer tokens internes
        access_token = self.auth_create_token(internal_claims, timedelta(minutes=self.token_access_timeout_min), "access")
        refresh_token = self.auth_create_token(internal_claims, timedelta(days=self.token_refresh_timeout_days), "refresh")
        return({'redirect':'/','set_cookie': {'access_token':access_token,'refresh_token':refresh_token}})

    # Fonction utilitaire pour lire le CSV et retourner les infos utilisateur
    def get_user_from_csv(self,csvfile, username):
        # python3 -c "import bcrypt; print(bcrypt.hashpw(b'monmotdepasse', bcrypt.gensalt()).decode())"
        with open(csvfile, newline="", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter=":")
            for row in reader:
                if len(row) < 5:
                    continue
                user, hashed_pw, name, email, groups = row
                if user == username:
                    return {
                        "username": user,
                        "hashed_pw": hashed_pw,
                        "name": name,
                        "email": email,
                        "groups": groups.split(","),
                    }
        return None
    
    def decode_payload(token: str):
        import base64
        import json

        # Découper le token en 3 parties
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Token invalide")
        
        # Décoder la partie payload (2ème partie)
        payload_b64 = parts[1] + "=="  # ajouter padding si nécessaire
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes)
        return payload

    #async def auth_oidc_callback(self,request: Request, code: str):
    async def auth_oidc_callback(self,varSession,params={}):
        code=None
        if varSession.get('form'):
            code=varSession['form'].get('code')
        self.bugprint(varSession,f'🤑 auth_oidc_callback _ code : {code}')
        # Échange du code contre un token Authentik
        data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.oidc_redi_url,
                "client_id": self.oidc_client_id,
                "client_secret": self.oidc_client_secret,
            }
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.oidc_toke_url, data=data)
        self.bugprint(varSession,f'🔫 auth_oidc_callback {self.oidc_toke_url} data et resp',[data,resp])
        tokens = resp.json()
        id_token = tokens.get("id_token")
        access_token_oidc = tokens.get("access_token")

        self.bugprint(varSession,f'🔫 auth_oidc_callback {self.oidc_toke_url} token et oidc_issuer',[tokens,self.oidc_issuer])
        #print(decode_payload(tokens.get('access_token')))
        #print(decode_payload(tokens.get('id_token')))

        if not id_token:
            return({'redirect':'/login'})
            #return RedirectResponse(url="/login", status_code=303)

        # Récupérer les clés publiques JWKS
        async with httpx.AsyncClient() as client:
            jwks_resp = await client.get(self.oidc_jwks_url)
        jwks = jwks_resp.json()
    
        # Décoder l'id_token (⚠️ en prod, vérifier signature avec clé publique Authentik)
        #payload = jwt.decode(id_token, options={"verify_signature": False})
        try:
            payload = jwt.decode(
                id_token,
                jwks,
                algorithms=["RS256"],  # ou l’algo utilisé par Authentik
                audience=self.oidc_client_id,
                issuer=self.oidc_issuer
                )
        except JWTError:
            return({'redirect':'/login'})
            #return RedirectResponse(url="/login", status_code=303)

        internal_claims={}
        for i in  ['sub','name','given_name','preferred_username','nickname','groups','email']:
            internal_claims[i]=payload.get(i)
            if i=='preferred_username':
                internal_claims['username']=payload.get(i)

        if not (internal_claims['name'] and internal_claims['email'] and internal_claims['groups']):
            self.bugprint(varSession,'auth_oidc_callback 🚒🚒🚒🚒🚒🚒🚒🚒🚒🚒🚒')
            async with httpx.AsyncClient() as client:
                userinfo_resp = await client.get(
                    self.oidc_usin_url,
                    headers={"Authorization": f"Bearer {access_token_oidc}"}
                    )
            userinfo = userinfo_resp.json()
            for i in  ['sub','name','given_name','preferred_username','nickname','groups','email']:
                internal_claims[i]=internal_claims[i] or userinfo.get(i)
                if i=='preferred_username':
                    internal_claims['username']=internal_claims['username'] or userinfo.get(i)

        internal_claims['auth_method']='oidc'

        self.bugprint(varSession,'🏚️ auth_oidc_callback internal_claims',[internal_claims])
        # Générer tokens internes
        access_token = self.auth_create_token(internal_claims, timedelta(minutes=self.token_access_timeout_min), "access")
        refresh_token = self.auth_create_token(internal_claims, timedelta(days=self.token_refresh_timeout_days), "refresh")
        return({'redirect':'/','set_cookie': {'access_token':access_token,'refresh_token':refresh_token}})

    async def auth_logout(self,varSession,params={}):
        return({'redirect':'/','del_cookie': ['access_token','refresh_token']})

    async def auth_refresh(request: Request, next=None):
        # 1. Récupérer le refresh token depuis le cookie
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            return JSONResponse({"error": "No refresh token"}, status_code=401)
    
        # 2. Décoder le refresh token interne
        try:
            payload = jwt.decode(refresh_token, self.secret_key, algorithms=[self.algo])
        except JWTError:
            return JSONResponse({"error": "Invalid refresh token"}, status_code=401)
        self.bugprint(request,'💋 auth_refresh payload',[payload])
    
        # 3. Vérifier qu’il s’agit bien d’un refresh token
        if payload.get("type") != "refresh":
            return JSONResponse({"error": "Wrong token type"}, status_code=401)
    
        # 4. Reprendre les claims stockés (sub, name, email, groups…)
        internal_claims = {
            "sub": payload.get("sub"),
            "auth_method": payload.get("auth_method"),
            "name": payload.get("name"),
            "email": payload.get("email"),
            "groups": payload.get("groups"), }
    
        # 5. Générer un nouveau access token
        new_access_token = self.auth_create_token(internal_claims, timedelta(minutes=self.token_access_timeout_min), "access")
    
        # 6. (Optionnel) régénérer un nouveau refresh token si tu veux prolonger la durée
        new_refresh_token = self.auth_create_token(internal_claims, timedelta(days=self.token_refresh_timeout_days), "refresh")

        # 7. Poser les cookies et renvoyer
        self.bugprint(request,'💋💋 auth_refresh')
        #response = JSONResponse({"status": "ok"})
        if next:
            referer=next
        response = RedirectResponse(url=referer, status_code=303)
        response.set_cookie("access_token", new_access_token, httponly=True)
        response.set_cookie("refresh_token", new_refresh_token, httponly=True)
        referer = request.headers.get("referer", "/")
        return response

    async def auth_secret(self,varSession,params={}):
        nextstep={}
        request=varSession['request']
        nextstep['request']=request
        # 1. Récupérer le token d'accès depuis le cookie
        access_token = request.cookies.get("access_token")
        self.bugprint(varSession,'🤑 auth_secret access_token',[access_token])
        current_url = str(request.url)
        payload={}
        if access_token:
            # 2. Vérifier le token
            try:
                payload = jwt.decode(access_token, self.secret_key, algorithms=[self.algo])
                self.bugprint(varSession,'💀 Token alive auth_secret ,payload',payload)
            except JWTError:
                # Token invalide ou expiré → redirection vers /refresh avec next
                self.bugprint(varSession,'💀 Token expiré auth_secret')
    
        # 3. Extraire les infos de l'utilisateur depuis le token interne
        user={}
        for i in ['sub','name','email','groups']:
            user[i]=payload.get(i)

        templateid="base"
        #payload = verify_token(token, "access")
        nextstep['user'] = payload.get("sub")
        nextstep['method'] = payload.get("auth_method")
        nextstep['email'] = payload.get("email")
        nextstep['name'] = payload.get("name")
        nextstep['groups'] = payload.get("groups",[])
        nextstep['claims']=payload
        user = payload.get("sub")
        method = payload.get("auth_method")
        return({'template':'secret.html','varSession': varSession,'template_data':nextstep})
        return self.templates[templateid].TemplateResponse("secret.html",nextstep)
    
        # 4. Retourner la page secrète avec les infos
        return JSONResponse({
            "message": "Bienvenue sur la page secrète 🎉",
            "user": user
        })

    def setup_auth_routes(self):
        self.api_add("/login",self.auth_login_page,daType="html")
        self.api_add("/login/localback",self.auth_local_login,verb="POST",daType="html")
        self.api_add('/login/callback',self.auth_oidc_callback,daType="html")
        #self.api_add('/refresh',self.auth_refresh,daType="html")
        self.api_add('/login/whoami',self.auth_secret,daType="html")
        self.api_add('/logout',self.auth_logout,daType="html")

    def _setup_docs(self):
        @self.app.get("/docs", include_in_schema=False)
        async def custom_docs():
            return get_swagger_ui_html(openapi_url=self.app.openapi_url, title="Zapiz API Docs")

    def api_add(self, uri: str, func: Callable,daType:str="html",verb:str="GET",acl=None,file=None):
        """ 
        Format des routes
        uri func html verb  await (et on rajoutede suite s'il faut un await)
        Le add remplacera comme un sauvage le comportement de mv :)
        """

        fncAsync=None
        if not file:
            fncAsync=inspect.iscoroutinefunction(func)

        uris=[uri]
        if uri[-1] != "/":
            uris.append(uri+"/")

        for u in uris:
            if not(self.api_routes[verb].get(u,None)):    # Si pas encore declarer alors creer la route
                if verb=="GET":
                    self.app.get(u)(self._secure_api_tab(verb,u))
                elif verb=="POST":
                    #self.app.post(u, response_class=response_class)(self._secure_api_tab()verb,u)
                    self.app.post(u)(self._secure_api_tab(verb,u))
            self.api_routes[verb][u]={}
            self.api_routes[verb][u]['func']=func
            self.api_routes[verb][u]['daType']=daType
            self.api_routes[verb][u]['await']=fncAsync
            self.api_routes[verb][u]['acl']=acl
            self.api_routes[verb][u]['file']=file


    def api_del(self, uri: str, verb:str="GET"):
        """ 
        On ne supprime jamais un URI, on la fait pointer sur une 404 (merci fastapi...)
        Bon en fait, suffit que ce soit le comportement par defaut de _secure_api
        Par contre... je m'interroge sur le comportement de swag'n co
        """
        if uri in self.api_routes[verb]:
            self.api_routes[verb][uri]['func']=None

    def api_lst(self):
        """ 
        Format des routes
        uri func html verb  await (et on rajoutede suite s'il faut un await)
        """
        ret={}
        for verb in self.api_routes.keys():
            ret[verb]=[]
            for uri in self.api_routes[verb].keys():
                if self.api_routes[verb][uri]:
                    ret[verb].append(uri)
        return(ret)

    def auth_create_token(self,data: dict, expires_delta: timedelta, token_type: str):
        to_encode = data.copy()
        expire = datetime.utcnow() + expires_delta
        to_encode.update({"exp": expire, "type": token_type})
        return jwt.encode(to_encode, self.secret_key, algorithm=self.algo)

    def api_tokens_status(self,request:Request):
        ret={}
        # 1. Récupérer le token d'accès depuis le cookie
        ret['access_token']  = request.cookies.get("access_token")
        ret['refresh_token'] = request.cookies.get("refresh_token")
        if ret['access_token']:
            # 2. Vérifier le token
            try:
                payload = jwt.decode(ret['access_token'], self.secret_key, algorithms=[self.algo])
                ret['payload']=payload
            except JWTError:
                ret['access_token']=None

        if not ret['access_token']:
            # 1. Récupérer le refresh token depuis le cookie
            if not ret['refresh_token']:
                return(None)
            # 2. Décoder le refresh token interne
            try:
                payload = jwt.decode(ret['refresh_token'], self.secret_key, algorithms=[self.algo])
            except JWTError:
                return(None)
        
            # 3. Vérifier qu’il s’agit bien d’un refresh token
            if payload.get("type") != "refresh":
                return(None)
        
            ret['payload']=payload
            # 4. Reprendre les claims stockés (sub, name, email, groups…)
            internal_claims={}
            for i in payload.keys():
                if i == "type":
                    continue
                internal_claims[i]=payload.get(i)
        
            # 5. Générer un nouveau access token
            ret['access_token'] = self.auth_create_token(internal_claims, timedelta(minutes=self.token_access_timeout_min), "access")
        
            # 6. (Optionnel) régénérer un nouveau refresh token si tu veux prolonger la durée
            ###ret['refresh_token'] = self.auth_create_token(internal_claims, timedelta(days=self.token_refresh_timeout_days), "refresh")

            #response.set_cookie("access_token", new_access_token, httponly=True)
            #response.set_cookie("refresh_token", new_refresh_token, httponly=True)
        ret['datas']={}
        for i in ['sub','name','email','groups']:
            ret['datas'][i]=payload.get(i)
    
        return(ret)

    def _secure_api_tab(self, verb,uri):
        async def wrapper(request: Request):
            if not self.api_routes[verb].get(uri,None) or not self.api_routes[verb][uri]['func']:
                return JSONResponse( status_code=404, content={"detail": "Ressource introuvable"})
                #return HTMLResponse(content= "<h1>404 - Page non trouvée</h1>", status_code=404)
            else:
                self.bugprint(request,"_secure_api_tab,wrappper",[self.api_routes[verb][uri]])

            varSession={}
            varSession['request']=request
            # 🔍 Détection de la méthode HTTP
            #verb = request.method
            #uri  = request.url.path
            self.bugprint(request,f"✅ wrapper {verb} {uri} réussie : {varSession}")
            #print(f"💡 request : {request.path_params}")
            #print(f"💡 request : {request}")
            varSession['verb']=verb
            if verb=="POST":
                content_type = request.headers.get("content-type", "")
                if "application/json" in content_type:
                    varSession['form'] = await request.json()
                elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                    varSession['form'] = dict(await request.form())
                else:
                    varSession['form'] = {}
            elif verb=="GET":
                varSession['form']={}
                for i in dict(request.query_params):
                    varSession['form'][i]=request.query_params.get(i)

            #print(f'🗯️{uri}')
            curUser=self.api_tokens_status(request)
            user="Anonyme"
            if curUser:
                self.bugprint(request,'🗯️🗯️',[curUser])
                # 🔑 la logique d'auth ici
                user = curUser['payload']['preferred_username']

                for i in ['sub','name','email','groups']:
                    varSession[i]=curUser['datas'].get(i)

            # 👉 injecter dans le state
            request.state.user = user

            if self.api_routes[verb][uri]['acl']:
                #Gestion des droits....
                if not('groups' in varSession.keys() and self.api_routes[verb][uri]['acl'] in varSession['groups']):
                    if self.api_routes[verb][uri]['daType']=='html' or self.api_routes[verb][uri]['daType']=='md':
                        return HTMLResponse(content= f"<html><head><meta http-equiv='refresh' content='5;URL=/'></head><body><h1>403 - Accés limité <a href='/'>HomePage</a></h1></body></html>", status_code=403)
                    else:
                        return JSONResponse( status_code=403, content={"detail": "Ressource limite"})

            ### On doit trouver la fonction, etc...
            # Appel dynamique a la fonction cible, avec tout les parametres
            #if inspect.iscoroutinefunction(func):
            if self.api_routes[verb][uri]['file']:
                result={'fileResponse': self.api_routes[verb][uri]['file'] }
            elif self.api_routes[verb][uri]['await']:
                result=await self.api_routes[verb][uri]['func'](varSession=varSession,params=request.path_params)
            else:
                result=      self.api_routes[verb][uri]['func'](varSession=varSession,params=request.path_params)

            if not isinstance(result,dict):
                result={}
                response=None
            elif 'template' in result.keys():
                nextstep=result
                nextstep['request']=request
                if 'template_data' in result.keys():
                    for k in result['template_data'].keys():
                        nextstep[k]=result['template_data'][k]
                #nextstep['refresh_interval']=1000
                nextstep['name']=varSession.get("name",None)
                #print('👽️ resul ta da')
                #print(result.keys())
                if self.sentry:
                    #print(f'🚒 {self.sentry}')
                    nextstep['sentry']=self.sentry
                    #print(nextstep)
                templateid='base'
                if 'templateid' in result.keys():
                    templateid=result['templateid']

                #print(f"🌈{self.api_routes[verb][uri]['daType']}")
                if  self.api_routes[verb][uri]['daType']=='html':
                    response=self.templates[templateid].TemplateResponse(result['template'],nextstep)
                elif  self.api_routes[verb][uri]['daType']=='json':
                    response=JSONResponse(self.templates[templateid].TemplateResponse(result['template'],nextstep))
                elif  self.api_routes[verb][uri]['daType']=='md':
                    # Cote temporaire, il va manquer les base truc de faire jolie.... (reellement il faudrait mettre ce html en cache puis lire le cache par la procedure noramal)
                    #html_content = markdown.markdown(md_text)
                    #html_content = markdown.markdown(self.templates[templateid].TemplateResponse(result['template'],nextstep))
                    #print(f"🌈🚪{result['template']}")
                    with open('templates/'+result['template'],'r') as f:
                        md_text=f.read()
                    html_content = markdown.markdown(md_text,extensions=["fenced_code","tables","extra"])
                    #response= f"<html><body>{html_content}</body></html>"
                    response= HTMLResponse(content= html_content,status_code=200)
                elif self.api_routes[verb][uri]['daType']=='Dhtml':
                    #print('DAaa')
                    response= HTMLResponse(content= result.get('html_content',""),status_code=result.get('status_code',200))
                else:
                    response='Uncreadible'
            elif 'redirect' in result.keys():
                response = RedirectResponse(url=result.get('redirect',"/"),status_code=result.get('status_code',303))
            elif 'fileResponse' in result.keys():
                #print(f'🖼️  {result["fileResponse"]}')
                response = FileResponse(result['fileResponse'])
            else:
                return(result)

            if 'set_cookie' in result.keys():
                for i in result['set_cookie']:
                    response.set_cookie(i, result['set_cookie'][i], httponly=True)
            elif curUser and response:
                for i in ['refresh_token','access_token']:
                    if curUser.get(i):
                        response.set_cookie(i, curUser.get(i), httponly=True)
            if 'del_cookie' in result.keys():
                for i in result['del_cookie']:
                    response.delete_cookie(i)
            return response


        return wrapper

    def declare_path(app, method: str, path: str, *, summary: str = None, include_in_schema: bool = True):
        """
        Permet de preformarter pour swag, car, ca swag
        """
        def decorator(func):
            doc = func.__doc__ or "Pas de description disponible."
            lines = doc.strip().split("\n")
    
            # Si summary est vide, on prend la première ligne de la docstring
            effective_summary = summary or (lines[0].strip() if lines else "Pas de résumé")
            # Le reste de la docstring devient la description
            description = "\n".join(lines[1:]).strip() if len(lines) > 1 else None
    
            route = getattr(app, method)
            route(
                path,
                description=doc,
                summary=effective_summary,
                include_in_schema=include_in_schema,
                )(func)
            return func
        return decorator


