"""anyio minimal (version autonome de borgHelperWWW) : seul `CancelScope` est utilisé par borgHelperWWW, pour protéger
l'`aclose()` d'un corps de téléchargement d'une annulation en cours. Sous asyncio nu, une annulation est ponctuelle (un
seul CancelledError, jamais renouvelé à chaque attente comme dans anyio) : la protection est donc déjà acquise et le
contexte ne fait que porter l'intention (et un `cancel()` inoffensif)."""


class CancelScope:
    def __init__(self, *, deadline=float("inf"), shield=False):
        self.deadline = deadline
        self.shield = shield
        self.cancel_called = False

    def cancel(self):
        self.cancel_called = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
