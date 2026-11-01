"""Formato de trabajo común del stack de toAction (version_formato 1).

La especificación vive en skill-hunter/stack/trabajo.md. Si cambias algo aquí,
cámbialo allá y en binzu.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from ulid import ULID

VERSION_FORMATO = 1
ZONA = ZoneInfo("America/Santiago")


def ahora() -> datetime:
    return datetime.now(ZONA).replace(microsecond=0)


def nuevo_id() -> str:
    return f"trb_{ULID()}"


class Estado(StrEnum):
    EN_COLA = "en_cola"
    EN_PROCESO = "en_proceso"
    COMPLETADO = "completado"
    FALLIDO = "fallido"
    CANCELADO = "cancelado"

    @property
    def terminado(self) -> bool:
        return self in (Estado.COMPLETADO, Estado.FALLIDO, Estado.CANCELADO)


class Solicitante(BaseModel):
    canal: str  # telegram, netero, api…
    nombre: str | None = None
    usuario_id: int | str | None = None
    chat_id: int | str | None = None


class Progreso(BaseModel):
    actual: int = 0
    total: int = 0
    mensaje: str = ""
    # Opcionales (version_formato 1 los acepta sin cambiar de versión):
    etapa: str | None = None  # en qué etapa está el elemento en curso (para los procesos de Gyo)
    etapas: dict[str, int] = Field(default_factory=dict)  # cuántos elementos completaron cada etapa


class Enlace(BaseModel):
    titulo: str
    url: str


class Costo(BaseModel):
    tokens_entrada: int = 0
    tokens_salida: int = 0
    usd: float = 0.0


class Resultado(BaseModel):
    resumen: str = ""
    enlaces: list[Enlace] = Field(default_factory=list)
    costo: Costo | None = None
    datos: dict[str, Any] = Field(default_factory=dict)


class Error(BaseModel):
    codigo: str
    mensaje: str


class Pedido(BaseModel):
    """Lo que manda quien encarga el trabajo (POST /trabajos)."""

    id: str = Field(default_factory=nuevo_id)
    version_formato: int = VERSION_FORMATO
    tipo: str
    parametros: dict[str, Any] = Field(default_factory=dict)
    solicitante: Solicitante
    trabajo_padre: str | None = None
    avisar_a: str | None = None


class Trabajo(Pedido):
    servicio: str
    estado: Estado = Estado.EN_COLA
    progreso: Progreso = Field(default_factory=Progreso)
    resultado: Resultado | None = None
    error: Error | None = None
    creado: datetime = Field(default_factory=ahora)
    actualizado: datetime = Field(default_factory=ahora)
