import dataclasses
import datetime
import enum
import pathlib

from pydantic import BaseModel


def jsonable_encoder(obj, *, by_alias=True, exclude_unset=False, exclude_defaults=False, exclude_none=False,
                     include=None, exclude=None):
    if isinstance(obj, BaseModel):
        return jsonable_encoder(obj.dict(by_alias=by_alias, exclude_unset=exclude_unset,
                                         exclude_defaults=exclude_defaults, exclude_none=exclude_none),
                                by_alias=by_alias, exclude_none=exclude_none)
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return jsonable_encoder(dataclasses.asdict(obj), by_alias=by_alias, exclude_none=exclude_none)
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, pathlib.PurePath):
        return str(obj)
    if isinstance(obj, (str, int, float, type(None))):
        return obj
    if isinstance(obj, dict):
        return {jsonable_encoder(k, by_alias=by_alias): jsonable_encoder(v, by_alias=by_alias, exclude_none=exclude_none)
                for k, v in obj.items() if not (exclude_none and v is None)}
    if isinstance(obj, (list, set, frozenset, tuple)):
        return [jsonable_encoder(x, by_alias=by_alias, exclude_none=exclude_none) for x in obj]
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, datetime.timedelta):
        return obj.total_seconds()
    if isinstance(obj, bytes):
        return obj.decode()
    try:
        return jsonable_encoder(dict(obj), by_alias=by_alias, exclude_none=exclude_none)
    except Exception:
        return jsonable_encoder(vars(obj), by_alias=by_alias, exclude_none=exclude_none)
