"""Marqueurs de paramètres : Header, Query, Path, Cookie, Body, Depends."""
from pydantic import FieldInfo, Undefined


class Param(FieldInfo):
    in_ = None

    def __init__(self, default=Undefined, *, alias=None, title=None, description=None, **kwargs):
        super().__init__(default, alias=alias, title=title, description=description, **kwargs)


class Path(Param):
    in_ = "path"


class Query(Param):
    in_ = "query"


class Header(Param):
    in_ = "header"

    def __init__(self, default=Undefined, *, alias=None, convert_underscores=True, **kwargs):
        self.convert_underscores = convert_underscores
        super().__init__(default, alias=alias, **kwargs)


class Cookie(Param):
    in_ = "cookie"


class Body(FieldInfo):
    def __init__(self, default=Undefined, *, embed=False, media_type="application/json", **kwargs):
        self.embed = embed
        self.media_type = media_type
        super().__init__(default, **kwargs)


class Depends:
    def __init__(self, dependency=None, *, use_cache=True):
        self.dependency = dependency
        self.use_cache = use_cache

    def __repr__(self):
        return f"{self.__class__.__name__}({getattr(self.dependency, '__name__', self.dependency)})"

