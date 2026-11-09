"""Exécution de fonctions synchrones hors de la boucle d'événements (équivalent de anyio.to_thread de starlette 0.18) :
fils d'un pool de 40 (limiteur par défaut d'anyio), contexte (contextvars) copié, attente NON annulable — une annulation
reçue pendant l'exécution n'est rendue qu'à la fin du fil (comme CancelScope(shield=True) d'anyio)."""
import asyncio
import contextvars
import concurrent.futures
import functools
import threading

_POOL = []
_POOL_LOCK = threading.Lock()


def _pool():
    if not _POOL:
        with _POOL_LOCK:
            if not _POOL:
                _POOL.append(concurrent.futures.ThreadPoolExecutor(max_workers=40, thread_name_prefix="AnyIO worker thread"))
    return _POOL[0]


async def run_in_threadpool(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    fut = loop.run_in_executor(_pool(), functools.partial(ctx.run, func, *args, **kwargs))
    cancelled = False
    while True:
        try:
            res = await asyncio.shield(fut)
            break
        except asyncio.CancelledError:
            if fut.cancelled():
                raise
            cancelled = True   # annulation différée jusqu'à la fin du fil
            if fut.done():
                res = fut.result()
                break
    if cancelled:
        raise asyncio.CancelledError()
    return res


async def iterate_in_threadpool(iterator):
    _end = object()

    def _next():
        try:
            return next(iterator)
        except StopIteration:
            return _end
    while True:
        x = await run_in_threadpool(_next)
        if x is _end:
            break
        yield x
