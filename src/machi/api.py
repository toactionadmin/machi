"""API interna común de los servicios del stack (la misma que tendrá Netero).

Solo es accesible por Tailscale (regla del firewall de Windows) y exige el token
en `Authorization: Bearer <MACHI_TOKEN>`.
"""

import hmac
import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Response

from .cola import Cola
from .config import Config
from .pipeline import CAPACIDADES, Reels
from .trabajo import VERSION_FORMATO, Estado, Pedido, Trabajo

log = logging.getLogger(__name__)
SERVICIO = "machi"


def crear_app(cfg: Config) -> FastAPI:
    cola = Cola(cfg.datos / "trabajos.db")
    reels = Reels(cfg, cola.guardar, cola.cancelacion_pedida)
    procesadores = {"reels": reels}
    app = FastAPI(title="machi", version=cfg.version, docs_url=None, redoc_url=None)

    def autorizar(authorization: str = Header(default="")) -> None:
        esperado = f"Bearer {cfg.token}"
        if not hmac.compare_digest(authorization.encode(), esperado.encode()):
            raise HTTPException(401, "Token inválido")

    @app.on_event("startup")
    def _arrancar() -> None:
        cola.iniciar(lambda t: procesadores[t.tipo].procesar(t))

    @app.get("/salud")
    def salud() -> dict:
        return {"servicio": SERVICIO, "version": cfg.version, "version_formato": VERSION_FORMATO, "ok": True}

    @app.get("/capacidades", dependencies=[Depends(autorizar)])
    def capacidades() -> dict:
        return {"servicio": SERVICIO, "version_formato": VERSION_FORMATO, "tipos": CAPACIDADES}

    @app.post("/trabajos", status_code=202, dependencies=[Depends(autorizar)])
    def crear(pedido: Pedido, response: Response) -> Trabajo:
        if pedido.version_formato != VERSION_FORMATO:
            raise HTTPException(422, f"version_formato {pedido.version_formato} no soportada (uso {VERSION_FORMATO})")
        if pedido.tipo not in procesadores:
            raise HTTPException(422, f'machi no hace trabajos de tipo "{pedido.tipo}"')
        existente = cola.obtener(pedido.id)
        if existente:
            response.status_code = 200
            return existente
        try:
            procesadores[pedido.tipo].validar(pedido.parametros)
        except Exception as e:
            raise HTTPException(422, str(e)) from e
        return cola.agregar(Trabajo(**pedido.model_dump(), servicio=SERVICIO))

    @app.get("/trabajos", dependencies=[Depends(autorizar)])
    def listar(estado: Estado | None = None, limite: int = 50) -> list[Trabajo]:
        return cola.listar(estado, min(limite, 200))

    @app.get("/trabajos/{id_}", dependencies=[Depends(autorizar)])
    def obtener(id_: str) -> Trabajo:
        t = cola.obtener(id_)
        if not t:
            raise HTTPException(404, "No existe ese trabajo")
        return t

    @app.post("/trabajos/{id_}/cancelar", dependencies=[Depends(autorizar)])
    def cancelar(id_: str) -> Trabajo:
        t = cola.pedir_cancelacion(id_)
        if not t:
            raise HTTPException(404, "No existe ese trabajo")
        return t

    return app
