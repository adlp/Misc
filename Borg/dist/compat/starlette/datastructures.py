import typing
from urllib.parse import parse_qsl, urlencode, urlsplit


class Address(typing.NamedTuple):
    host: str
    port: int


class URL:
    def __init__(self, url="", scope=None):
        if scope is not None:
            scheme = scope.get("scheme", "http")
            server = scope.get("server", None)
            path = scope.get("root_path", "") + scope["path"]
            query_string = scope.get("query_string", b"")
            host_header = None
            for key, value in scope["headers"]:
                if key == b"host":
                    host_header = value.decode("latin-1")
                    break
            if host_header is not None:
                url = f"{scheme}://{host_header}{path}"
            elif server is None:
                url = path
            else:
                host, port = server
                default_port = {"http": 80, "https": 443, "ws": 80, "wss": 443}[scheme]
                if port == default_port:
                    url = f"{scheme}://{host}{path}"
                else:
                    url = f"{scheme}://{host}:{port}{path}"
            if query_string:
                url += "?" + query_string.decode()
        self._url = url

    @property
    def components(self):
        if not hasattr(self, "_components"):
            self._components = urlsplit(self._url)
        return self._components

    scheme = property(lambda self: self.components.scheme)
    path = property(lambda self: self.components.path)
    query = property(lambda self: self.components.query)
    fragment = property(lambda self: self.components.fragment)
    hostname = property(lambda self: self.components.hostname)
    port = property(lambda self: self.components.port)
    username = property(lambda self: self.components.username)
    password = property(lambda self: self.components.password)

    @property
    def netloc(self):
        return self.components.netloc

    def replace(self, **kwargs):
        return URL(self.components._replace(**kwargs).geturl())

    def __eq__(self, other):
        return str(self) == str(other)

    def __str__(self):
        return self._url

    def __repr__(self):
        return f"{self.__class__.__name__}({self._url!r})"


class Headers(typing.Mapping[str, str]):
    """En-têtes insensibles à la casse, valeurs multiples conservées (liste brute)."""

    def __init__(self, headers=None, raw=None, scope=None):
        if headers is not None:
            self._list = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in dict(headers).items()]
        elif raw is not None:
            self._list = raw
        elif scope is not None:
            self._list = scope["headers"]
        else:
            self._list = []

    @property
    def raw(self):
        return self._list

    def keys(self):
        return [k.decode("latin-1") for k, _ in self._list]

    def values(self):
        return [v.decode("latin-1") for _, v in self._list]

    def items(self):
        return [(k.decode("latin-1"), v.decode("latin-1")) for k, v in self._list]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def getlist(self, key):
        k = key.lower().encode("latin-1")
        return [v.decode("latin-1") for hk, v in self._list if hk == k]

    def __getitem__(self, key):
        k = key.lower().encode("latin-1")
        for hk, hv in self._list:
            if hk == k:
                return hv.decode("latin-1")
        raise KeyError(key)

    def __contains__(self, key):
        k = key.lower().encode("latin-1")
        return any(hk == k for hk, _ in self._list)

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self._list)

    def __eq__(self, other):
        if not isinstance(other, Headers):
            return False
        return sorted(self._list) == sorted(other._list)

    def __repr__(self):
        return f"{self.__class__.__name__}({dict(self.items())!r})"


class MutableHeaders(Headers):
    def __setitem__(self, key, value):
        set_key = key.lower().encode("latin-1")
        set_value = value.encode("latin-1")
        found = [i for i, (k, _) in enumerate(self._list) if k == set_key]
        for i in reversed(found[1:]):
            del self._list[i]
        if found:
            self._list[found[0]] = (set_key, set_value)
        else:
            self._list.append((set_key, set_value))

    def __delitem__(self, key):
        k = key.lower().encode("latin-1")
        self._list[:] = [(hk, hv) for hk, hv in self._list if hk != k]

    def setdefault(self, key, value):
        if key in self:
            return self[key]
        self[key] = value
        return value

    def append(self, key, value):
        self._list.append((key.lower().encode("latin-1"), value.encode("latin-1")))

    def update(self, other):
        for k, v in other.items():
            self[k] = v


class QueryParams(typing.Mapping[str, str]):
    """Paramètres de requête (multidict immuable) : `get` rend la DERNIÈRE valeur d'une clé répétée, comme starlette."""

    def __init__(self, value=None):
        if isinstance(value, str):
            items = parse_qsl(value, keep_blank_values=True)
        elif isinstance(value, bytes):
            items = parse_qsl(value.decode("latin-1"), keep_blank_values=True)
        elif isinstance(value, QueryParams):
            items = list(value.multi_items())
        elif value is None:
            items = []
        else:
            items = list(dict(value).items())
        self._list = items
        self._dict = {k: v for k, v in items}

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()

    def multi_items(self):
        return list(self._list)

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def getlist(self, key):
        return [v for k, v in self._list if k == key]

    def __getitem__(self, key):
        return self._dict[key]

    def __contains__(self, key):
        return key in self._dict

    def __iter__(self):
        return iter(self._dict.keys())

    def __len__(self):
        return len(self._dict)

    def __str__(self):
        return urlencode(self._list)

    def __repr__(self):
        return f"{self.__class__.__name__}({str(self)!r})"


class State:
    """Espace de noms adossé à un dict (scope['state'])."""

    def __init__(self, state=None):
        if state is None:
            state = {}
        super().__setattr__("_state", state)

    def __setattr__(self, key, value):
        self._state[key] = value

    def __getattr__(self, key):
        try:
            return self._state[key]
        except KeyError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

    def __delattr__(self, key):
        del self._state[key]
