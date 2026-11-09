"""Sous-ensemble de pydantic 1.x pour la version autonome de borgHelperWWW (stdlib seule) : `BaseModel` à champs
annotés (str, int, float, bool, Optional, List, Dict, modèles imbriqués), `Field(min_length=…)`, messages d'erreur
et codes identiques à pydantic 1.8 (c'est ce que la réponse 422 de l'API expose). `.dict()`, `__fields_set__`,
`.json()`, `.copy()`, `parse_obj`, `schema()`."""
import copy
import json as _json
import typing

__version__ = "1.8.2-borgHelperWWW-autonome"

Undefined = type("UndefinedType", (), {"__repr__": lambda self: "PydanticUndefined"})()
_Required = Ellipsis


class FieldInfo:
    def __init__(self, default=Undefined, *, alias=None, title=None, description=None, min_length=None,
                 max_length=None, gt=None, ge=None, lt=None, le=None, regex=None, **extra):
        self.default = default
        self.alias = alias
        self.title = title
        self.description = description
        self.min_length = min_length
        self.max_length = max_length
        self.gt, self.ge, self.lt, self.le = gt, ge, lt, le
        self.regex = regex
        self.extra = extra


def Field(default=Undefined, **kwargs):
    return FieldInfo(default, **kwargs)


class ValidationError(ValueError):
    def __init__(self, errors, model=None):
        self._errors = errors
        self.model = model
        super().__init__(str(self))

    def errors(self):
        return list(self._errors)

    def json(self, *, indent=2):
        return _json.dumps(self._errors, indent=indent, default=list)

    def __str__(self):
        n = len(self._errors)
        lines = [f"{n} validation error{'' if n == 1 else 's'} for {getattr(self.model, '__name__', 'Model')}"]
        for e in self._errors:
            lines.append(".".join(str(x) for x in e["loc"]))
            lines.append(f"  {e['msg']} (type={e['type']})")
        return "\n".join(lines)


def _err(loc, msg, typ, **ctx):
    e = {"loc": tuple(loc), "msg": msg, "type": typ}
    if ctx:
        e["ctx"] = ctx
    return e


_BOOL_TRUE = {1, "1", "on", "t", "true", "y", "yes"}
_BOOL_FALSE = {0, "0", "off", "f", "false", "n", "no"}


def _is_optional(tp):
    return typing.get_origin(tp) is typing.Union and type(None) in typing.get_args(tp)


def _validate(tp, value, loc, info=None):
    """Valide `value` selon `tp` -> (valeur, liste d'erreurs). Même sémantique que pydantic 1."""
    origin = typing.get_origin(tp)
    if origin is typing.Union:
        args = typing.get_args(tp)
        if value is None and type(None) in args:
            return None, []
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _validate(non_none[0], value, loc, info)
        errors_all = []
        for a in non_none:
            v, errs = _validate(a, value, loc, info)
            if not errs:
                return v, []
            errors_all.extend(errs)
        return value, errors_all
    if value is None:
        if tp is typing.Any:
            return None, []
        return value, [_err(loc, "none is not an allowed value", "type_error.none.not_allowed")]
    if tp is typing.Any or tp is object:
        return value, []
    if tp is str:
        if isinstance(value, str):
            v = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool) or isinstance(value, bool):
            v = str(value)
        elif isinstance(value, bytes):
            v = value.decode()
        else:
            return value, [_err(loc, "str type expected", "type_error.str")]
        if info is not None:
            if info.min_length is not None and len(v) < info.min_length:
                return v, [_err(loc, f"ensure this value has at least {info.min_length} characters",
                                "value_error.any_str.min_length", limit_value=info.min_length)]
            if info.max_length is not None and len(v) > info.max_length:
                return v, [_err(loc, f"ensure this value has at most {info.max_length} characters",
                                "value_error.any_str.max_length", limit_value=info.max_length)]
        return v, []
    if tp is bool:
        if value is True or value is False:
            return value, []
        v = value
        if isinstance(v, bytes):
            v = v.decode(errors="replace")
        if isinstance(v, str):
            v = v.lower()
        try:
            if v in _BOOL_TRUE:
                return True, []
            if v in _BOOL_FALSE:
                return False, []
        except TypeError:
            pass
        return value, [_err(loc, "value could not be parsed to a boolean", "type_error.bool")]
    if tp is int:
        if type(value) is int:
            v = value
        else:
            try:
                v = int(value)
            except (TypeError, ValueError, OverflowError):
                return value, [_err(loc, "value is not a valid integer", "type_error.integer")]
        return _check_number(v, loc, info)
    if tp is float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return value, [_err(loc, "value is not a valid float", "type_error.float")]
        return _check_number(v, loc, info)
    if tp is bytes:
        if isinstance(value, bytes):
            return value, []
        if isinstance(value, str):
            return value.encode(), []
        return value, [_err(loc, "byte type expected", "type_error.bytes")]
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        if isinstance(value, tp):
            return value, []
        if not isinstance(value, dict):
            try:
                value = dict(value)
            except (TypeError, ValueError):
                return value, [_err(loc, "value is not a valid dict", "type_error.dict")]
        values, fields_set, errors = tp._validate_data(value, loc)
        if errors:
            return value, errors
        m = tp.__new__(tp)
        object.__setattr__(m, "__dict__", values)
        object.__setattr__(m, "__fields_set__", fields_set)
        return m, []
    if tp is dict or origin is dict:
        if not isinstance(value, dict):
            try:
                value = dict(value)
            except (TypeError, ValueError):
                return value, [_err(loc, "value is not a valid dict", "type_error.dict")]
        args = typing.get_args(tp)
        if not args:
            return value, []
        out, errors = {}, []
        for k, x in value.items():
            kk, e1 = _validate(args[0], k, tuple(loc) + ("__key__",), None)
            vv, e2 = _validate(args[1], x, tuple(loc) + (k,), None)
            errors.extend(e1)
            errors.extend(e2)
            out[kk] = vv
        return out, errors
    if tp in (list, tuple, set) or origin in (list, tuple, set, frozenset):
        base = origin or tp
        if isinstance(value, (list, tuple, set, frozenset)):
            seq = list(value)
        else:
            return value, [_err(loc, f"value is not a valid {base.__name__}", f"type_error.{base.__name__}")]
        args = typing.get_args(tp)
        if not args or base is tuple:
            return base(seq), []
        out, errors = [], []
        for i, x in enumerate(seq):
            vv, e = _validate(args[0], x, tuple(loc) + (i,), None)
            errors.extend(e)
            out.append(vv)
        return base(out), errors
    return value, []   # type non géré : accepté tel quel


def _check_number(v, loc, info):
    if info is not None:
        for attr, op, label, code in (("gt", lambda a, b: a > b, "greater than", "gt"),
                                      ("ge", lambda a, b: a >= b, "greater than or equal to", "ge"),
                                      ("lt", lambda a, b: a < b, "less than", "lt"),
                                      ("le", lambda a, b: a <= b, "less than or equal to", "le")):
            lim = getattr(info, attr)
            if lim is not None and not op(v, lim):
                return v, [_err(loc, f"ensure this value is {label} {lim}", f"value_error.number.not_{code}", limit_value=lim)]
    return v, []


class _ModelField:
    def __init__(self, name, tp, default, info):
        self.name = name
        self.outer_type_ = tp
        self.type_ = tp
        self.default = default
        self.field_info = info
        self.alias = info.alias or name
        self.required = default is Undefined and not _is_optional(tp)

    def get_default(self):
        return copy.deepcopy(None if self.default is Undefined else self.default)


class _Meta(type):
    def __new__(mcs, name, bases, ns):
        cls = super().__new__(mcs, name, bases, ns)
        fields = {}
        for b in reversed(cls.__mro__[1:]):
            fields.update(getattr(b, "__fields__", {}) or {})
        try:
            hints = typing.get_type_hints(cls)
        except Exception:
            hints = dict(ns.get("__annotations__", {}))
        for fname in ns.get("__annotations__", {}):
            if fname.startswith("_"):
                continue
            tp = hints.get(fname, ns["__annotations__"][fname])
            if typing.get_origin(tp) is typing.ClassVar:
                continue
            default = ns.get(fname, Undefined)
            info = default if isinstance(default, FieldInfo) else FieldInfo(default)
            if isinstance(default, FieldInfo):
                default = default.default
            if default is Ellipsis:
                default = Undefined
            if info.default is Ellipsis:
                info.default = Undefined
            fields[fname] = _ModelField(fname, tp, default, info)
        cls.__fields__ = fields
        return cls


class BaseModel(metaclass=_Meta):
    __fields__: dict = {}

    def __init__(self, **data):
        values, fields_set, errors = self._validate_data(data, ())
        if errors:
            raise ValidationError(errors, self.__class__)
        object.__setattr__(self, "__dict__", values)
        object.__setattr__(self, "__fields_set__", fields_set)

    @classmethod
    def _validate_data(cls, data, loc):
        values, errors, fields_set = {}, [], set()
        for name, f in cls.__fields__.items():
            if f.alias in data:
                raw = data[f.alias]
            elif name in data and f.alias == name:
                raw = data[name]
            else:
                if f.required:
                    errors.append(_err(tuple(loc) + (f.alias,), "field required", "value_error.missing"))
                else:
                    values[name] = f.get_default()
                continue
            fields_set.add(name)
            v, errs = _validate(f.type_, raw, tuple(loc) + (f.alias,), f.field_info)
            if errs:
                errors.extend(errs)
            else:
                values[name] = v
        return values, fields_set, errors

    @classmethod
    def parse_obj(cls, obj):
        if not isinstance(obj, dict):
            try:
                obj = dict(obj)
            except (TypeError, ValueError) as e:
                raise ValidationError([_err(("__root__",), f"{cls.__name__} expected dict not {type(obj).__name__}",
                                            "type_error")], cls) from e
        return cls(**obj)

    def dict(self, *, include=None, exclude=None, by_alias=False, exclude_unset=False, exclude_defaults=False,
             exclude_none=False):
        out = {}
        for name, f in self.__fields__.items():
            if name not in self.__dict__:
                continue
            if include is not None and name not in include:
                continue
            if exclude is not None and name in exclude:
                continue
            if exclude_unset and name not in self.__fields_set__:
                continue
            v = self.__dict__[name]
            if exclude_defaults and not f.required and v == f.default:
                continue
            if exclude_none and v is None:
                continue
            out[f.alias if by_alias else name] = _to_plain(v, by_alias, exclude_unset, exclude_defaults, exclude_none)
        return out

    def json(self, **kw):
        return _json.dumps(self.dict(), ensure_ascii=False, default=str)

    def copy(self, *, update=None, deep=False):
        values = copy.deepcopy(self.__dict__) if deep else dict(self.__dict__)
        if update:
            values.update(update)
        m = self.__class__.__new__(self.__class__)
        object.__setattr__(m, "__dict__", values)
        object.__setattr__(m, "__fields_set__", set(self.__fields_set__) | set(update or ()))
        return m

    @classmethod
    def schema(cls, by_alias=True):
        props, req = {}, []
        for name, f in cls.__fields__.items():
            props[f.alias] = _schema_of(f.type_, f.field_info, f.alias)
            if f.default is not Undefined and f.default is not None:
                props[f.alias]["default"] = f.default
            if f.required:
                req.append(f.alias)
        out = {"title": cls.__name__, "type": "object", "properties": props}
        if cls.__doc__:
            import inspect
            out["description"] = inspect.cleandoc(cls.__doc__)
        if req:
            out["required"] = req
        return out

    def __eq__(self, other):
        return isinstance(other, BaseModel) and self.dict() == other.dict()

    def __repr_args__(self):
        return [(k, v) for k, v in self.__dict__.items() if k in self.__fields__]

    def __repr__(self):
        return f"{self.__class__.__name__}({', '.join(f'{k}={v!r}' for k, v in self.__repr_args__())})"


def _to_plain(v, by_alias, exclude_unset, exclude_defaults, exclude_none):
    if isinstance(v, BaseModel):
        return v.dict(by_alias=by_alias, exclude_unset=exclude_unset, exclude_defaults=exclude_defaults,
                      exclude_none=exclude_none)
    if isinstance(v, dict):
        return {k: _to_plain(x, by_alias, exclude_unset, exclude_defaults, exclude_none) for k, x in v.items()}
    if isinstance(v, (list, tuple, set, frozenset)):
        return type(v)(_to_plain(x, by_alias, exclude_unset, exclude_defaults, exclude_none) for x in v)
    return v


def _schema_of(tp, info=None, title=None):
    """Schéma JSON simplifié d'un type (pour /openapi.json)."""
    origin = typing.get_origin(tp)
    sch = {}
    if origin is typing.Union:
        non_none = [a for a in typing.get_args(tp) if a is not type(None)]
        return _schema_of(non_none[0], info, title) if len(non_none) == 1 else {"anyOf": [_schema_of(a) for a in non_none]}
    if tp is str:
        sch = {"type": "string"}
    elif tp is bool:
        sch = {"type": "boolean"}
    elif tp is int:
        sch = {"type": "integer"}
    elif tp is float:
        sch = {"type": "number"}
    elif isinstance(tp, type) and issubclass(tp, BaseModel):
        return {"$ref": f"#/components/schemas/{tp.__name__}"}
    elif tp is dict or origin is dict:
        args = typing.get_args(tp)
        sch = {"type": "object"}
        if len(args) == 2:
            sch["additionalProperties"] = _schema_of(args[1])
    elif tp is list or origin is list:
        args = typing.get_args(tp)
        sch = {"type": "array", "items": _schema_of(args[0]) if args else {}}
    if title:
        sch = {"title": title.replace("_", " ").title(), **sch}
    if info is not None:
        if info.description:
            sch["description"] = info.description
        if info.min_length is not None:
            sch["minLength"] = info.min_length
        if info.max_length is not None:
            sch["maxLength"] = info.max_length
    return sch
