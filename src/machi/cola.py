"""Cola de trabajos en SQLite con un único trabajador.

Un episodio ocupa la GPU, así que los trabajos se procesan de a uno. Si el
servicio se reinicia, los trabajos que estaban en proceso vuelven a la cola:
es seguro porque repetir un episodio sobrescribe los mismos archivos y filas.
"""

import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from .trabajo import Error, Estado, Trabajo, ahora

log = logging.getLogger(__name__)


class Cancelado(Exception):
    """Lo lanza el procesador cuando detecta que pidieron cancelar."""


class Cola:
    def __init__(self, ruta: Path):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(ruta, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS trabajos ("
            " id TEXT PRIMARY KEY, estado TEXT NOT NULL, creado TEXT NOT NULL,"
            " cancelar INTEGER NOT NULL DEFAULT 0, json TEXT NOT NULL)"
        )
        self._lock = threading.Lock()
        self._hay_trabajo = threading.Event()
        with self._lock:
            n = self._db.execute(
                "UPDATE trabajos SET estado = ? WHERE estado = ?",
                (Estado.EN_COLA, Estado.EN_PROCESO),
            ).rowcount
        if n:
            log.warning("%d trabajo(s) interrumpidos vuelven a la cola", n)
            self._hay_trabajo.set()

    # --- lectura y escritura ---

    def guardar(self, t: Trabajo) -> None:
        t.actualizado = ahora()
        with self._lock:
            self._db.execute(
                "INSERT INTO trabajos (id, estado, creado, json) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET estado = excluded.estado, json = excluded.json",
                (t.id, t.estado, t.creado.isoformat(), t.model_dump_json()),
            )

    def obtener(self, id_: str) -> Trabajo | None:
        with self._lock:
            fila = self._db.execute(
                "SELECT json, estado FROM trabajos WHERE id = ?", (id_,)
            ).fetchone()
        if not fila:
            return None
        t = Trabajo.model_validate_json(fila[0])
        t.estado = Estado(fila[1])
        return t

    def listar(self, estado: Estado | None = None, limite: int = 50) -> list[Trabajo]:
        sql = "SELECT json, estado FROM trabajos"
        args: tuple = ()
        if estado:
            sql += " WHERE estado = ?"
            args = (estado,)
        sql += " ORDER BY creado DESC LIMIT ?"
        with self._lock:
            filas = self._db.execute(sql, (*args, limite)).fetchall()
        res = []
        for js, est in filas:
            t = Trabajo.model_validate_json(js)
            t.estado = Estado(est)
            res.append(t)
        return res

    def agregar(self, t: Trabajo) -> Trabajo:
        """Encola un trabajo. Si el id ya existe, devuelve el existente (idempotente)."""
        existente = self.obtener(t.id)
        if existente:
            return existente
        self.guardar(t)
        self._hay_trabajo.set()
        return t

    def pedir_cancelacion(self, id_: str) -> Trabajo | None:
        t = self.obtener(id_)
        if not t or t.estado.terminado:
            return t
        if t.estado == Estado.EN_COLA:
            t.estado = Estado.CANCELADO
            self.guardar(t)
            return t
        with self._lock:
            self._db.execute("UPDATE trabajos SET cancelar = 1 WHERE id = ?", (id_,))
        return t

    def cancelacion_pedida(self, id_: str) -> bool:
        with self._lock:
            fila = self._db.execute(
                "SELECT cancelar FROM trabajos WHERE id = ?", (id_,)
            ).fetchone()
        return bool(fila and fila[0])

    def _siguiente(self) -> Trabajo | None:
        with self._lock:
            fila = self._db.execute(
                "SELECT id FROM trabajos WHERE estado = ? ORDER BY creado LIMIT 1",
                (Estado.EN_COLA,),
            ).fetchone()
        return self.obtener(fila[0]) if fila else None

    # --- trabajador ---

    def iniciar(self, procesar: Callable[[Trabajo], None]) -> None:
        threading.Thread(target=self._bucle, args=(procesar,), daemon=True, name="trabajador").start()

    def _bucle(self, procesar: Callable[[Trabajo], None]) -> None:
        while True:
            t = self._siguiente()
            if not t:
                self._hay_trabajo.wait(timeout=30)
                self._hay_trabajo.clear()
                continue
            t.estado = Estado.EN_PROCESO
            self.guardar(t)
            log.info("Empieza %s (%s %s)", t.id, t.tipo, t.parametros)
            try:
                procesar(t)
                t.estado = Estado.COMPLETADO
            except Cancelado:
                t.estado = Estado.CANCELADO
                t.progreso.mensaje = "Cancelado"
            except Exception as e:  # el trabajador no debe morir nunca
                log.exception("Falló %s", t.id)
                t.estado = Estado.FALLIDO
                t.error = Error(codigo=getattr(e, "codigo", "error_interno"), mensaje=str(e))
            self.guardar(t)
            log.info("Termina %s: %s", t.id, t.estado)
