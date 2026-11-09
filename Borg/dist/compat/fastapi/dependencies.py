"""Analyse de la signature d'un endpoint (Dependant) et résolution des paramètres/dépendances d'une requête.
Ordre identique à FastAPI : dépendances (dans l'ordre déclaré), puis chemin, requête, en-têtes, cookies, corps ;
une dépendance qui lève (HTTPException) interrompt tout avant la validation des paramètres de l'endpoint."""
import asyncio
import copy
import inspect
import re
import typing

from pydantic import BaseModel, FieldInfo, Undefined, _validate, _is_optional
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from fastapi import params

_EMPTY = inspect.Parameter.empty


class ParamField:
    def __init__(self, name, tp, default, info, kind):
        self.name = name
        self.type_ = tp
        self.info = info
        self.kind = kind   # path | query | header | cookie | body
        if isinstance(info, params.Header) and info.alias is None and info.convert_underscores:
            self.alias = name.replace("_", "-")
        else:
            self.alias = (info.alias if info is not None and info.alias else name)
        self.default = None if default is Undefined else default
        # Optional[X] sans valeur par défaut : non requis, défaut None (pydantic 1)
        self.required = default is Undefined and not _is_optional(tp)


class Dependant:
    def __init__(self, call=None, name=None, use_cache=True):
        self.call = call
        self.name = name
        self.use_cache = use_cache
        self.dependencies = []
        self.path_params = []
        self.query_params = []
        self.header_params = []
        self.cookie_params = []
        self.body_params = []
        self.request_param_name = None


def _path_param_names(path):
    return set(re.findall(r"{([a-zA-Z_][a-zA-Z0-9_]*)(?::[a-zA-Z_][a-zA-Z0-9_]*)?}", path))


def get_dependant(*, path, call, name=None, use_cache=True):
    dep = Dependant(call=call, name=name, use_cache=use_cache)
    sig = inspect.signature(call)
    try:
        hints = typing.get_type_hints(call)
    except Exception:
        hints = {}
    path_names = _path_param_names(path)
    for pname, p in sig.parameters.items():
        ann = hints.get(pname, p.annotation)
        default = p.default
        if isinstance(default, params.Depends):
            sub = get_dependant(path=path, call=default.dependency, name=pname, use_cache=default.use_cache)
            dep.dependencies.append(sub)
            continue
        if isinstance(ann, type) and issubclass(ann, Request):
            dep.request_param_name = pname
            continue
        if ann is _EMPTY:
            ann = str
        if isinstance(default, (params.Param, params.Body)):
            info = default
            dval = default.default
        else:
            info = FieldInfo(Undefined if default is _EMPTY else default)
            dval = Undefined if default is _EMPTY else default
        if dval is Ellipsis:
            dval = Undefined
        if isinstance(default, params.Param):
            kind = default.in_
        elif isinstance(default, params.Body):
            kind = "body"
        elif pname in path_names:
            kind = "path"
        elif isinstance(ann, type) and issubclass(ann, BaseModel):
            kind = "body"
        elif typing.get_origin(ann) is typing.Union and any(isinstance(a, type) and issubclass(a, BaseModel)
                                                              for a in typing.get_args(ann)):
            kind = "body"
        else:
            kind = "query"
        f = ParamField(pname, ann, dval, info, kind)
        if kind == "path":
            f.required = True
            dep.path_params.append(f)
        elif kind == "query":
            dep.query_params.append(f)
        elif kind == "header":
            dep.header_params.append(f)
        elif kind == "cookie":
            dep.cookie_params.append(f)
        else:
            dep.body_params.append(f)
    return dep


def _params_to_args(fields, received):
    values, errors = {}, []
    for f in fields:
        value = received.get(f.alias)
        if value is None:
            if f.required:
                errors.append({"loc": (f.kind, f.alias), "msg": "field required", "type": "value_error.missing"})
            else:
                values[f.name] = copy.deepcopy(f.default)
            continue
        v, errs = _validate(f.type_, value, (f.kind, f.alias), f.info)
        if errs:
            errors.extend(errs)
        else:
            values[f.name] = v
    return values, errors


def _body_to_args(fields, body):
    values, errors = {}, []
    if not fields:
        return values, errors
    f = fields[0]
    embed = getattr(f.info, "embed", False)
    omitted = len(fields) == 1 and not embed
    if omitted:
        received = {f.alias: body}
    else:
        received = body
    for f in fields:
        loc = ("body",) if omitted else ("body", f.alias)
        value = None
        if received is not None:
            try:
                value = received.get(f.alias)
            except AttributeError:
                errors.append({"loc": loc, "msg": "field required", "type": "value_error.missing"})
                continue
        if value is None:
            if f.required:
                errors.append({"loc": loc, "msg": "field required", "type": "value_error.missing"})
            else:
                values[f.name] = copy.deepcopy(f.default)
            continue
        v, errs = _validate(f.type_, value, loc, f.info)
        if errs:
            errors.extend(errs)
        else:
            values[f.name] = v
    return values, errors


async def solve_dependencies(*, request, dependant, body=None, cache=None):
    values, errors = {}, []
    cache = {} if cache is None else cache
    for sub in dependant.dependencies:
        if sub.use_cache and sub.call in cache:
            solved = cache[sub.call]
        else:
            sub_values, sub_errors = await solve_dependencies(request=request, dependant=sub, body=body, cache=cache)
            if sub_errors:
                errors.extend(sub_errors)
                continue
            if asyncio.iscoroutinefunction(sub.call):
                solved = await sub.call(**sub_values)
            else:
                solved = await run_in_threadpool(sub.call, **sub_values)
            if sub.use_cache:
                cache[sub.call] = solved
        if sub.name:
            values[sub.name] = solved
    for fields, received in ((dependant.path_params, request.path_params),
                             (dependant.query_params, request.query_params),
                             (dependant.header_params, request.headers),
                             (dependant.cookie_params, request.cookies)):
        v, e = _params_to_args(fields, received)
        values.update(v)
        errors.extend(e)
    if dependant.body_params:
        v, e = _body_to_args(dependant.body_params, body)
        values.update(v)
        errors.extend(e)
    if dependant.request_param_name:
        values[dependant.request_param_name] = request
    return values, errors
