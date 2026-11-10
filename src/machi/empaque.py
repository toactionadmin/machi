"""Título, descripción y capítulos de YouTube de un episodio, con Claude.

Las reglas están en skill-hunter/stack/prompts/empaque-youtube.md y el estilo de cada proyecto en
proyectos/<proyecto>/youtube.md. Claude propone 3 títulos, el resumen, los capítulos y los hashtags de las
fichas; los enlaces y créditos fijos (`pie` de la ficha) los agrega Machi tal cual, sin pasar por Claude.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .captions import ErrorCaption, leer_reglas
from .momentos import costo_usd, texto_con_tiempos
from .proyectos import Proyecto
from .trabajo import Costo
from .transcribir import Segmento

log = logging.getLogger(__name__)

REGLAS = Path("stack") / "prompts" / "empaque-youtube.md"
LARGO_TITULO = 70  # YouTube corta lo que sigue
SEPARACION_MIN_S = 30  # entre capítulos
CAPITULOS_MIN = 3  # YouTube exige al menos 3, el primero en 0:00

ESQUEMA = {
    "type": "object",
    "properties": {
        "titulos": {"type": "array", "items": {"type": "string"}},
        "resumen": {"type": "string"},
        "capitulos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"inicio": {"type": "number"}, "titulo": {"type": "string"}},
                "required": ["inicio", "titulo"],
                "additionalProperties": False,
            },
        },
        "hashtags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["titulos", "resumen", "capitulos", "hashtags"],
    "additionalProperties": False,
}


class ErrorEmpaque(Exception):
    codigo = "claude"


@dataclass
class Paquete:
    titulos: list[str]
    resumen: str
    capitulos: list[tuple[float, str]]  # (segundos, título)
    hashtags: list[str]
    costo: Costo
    avisos: list[str]


def limpiar_capitulos(capitulos: list[dict], duracion: float) -> list[tuple[float, str]]:
    """Capítulos en orden, el primero en 0, separados por al menos 30 s. Con menos de 3, ninguno (YouTube no los toma)."""
    items = sorted(
        ((max(0.0, min(float(c["inicio"]), duracion)), str(c["titulo"]).strip()) for c in capitulos if str(c["titulo"]).strip()),
        key=lambda x: x[0],
    )
    salida: list[tuple[float, str]] = []
    for t, titulo in items:
        if not salida:
            salida.append((0.0, titulo))  # el primero siempre parte en 0:00
        elif t - salida[-1][0] >= SEPARACION_MIN_S and duracion - t >= 10:
            salida.append((t, titulo))
    return salida if len(salida) >= CAPITULOS_MIN else []


def tiempo(s: float, duracion: float) -> str:
    """«3:05», o «1:03:05» si el episodio dura una hora o más."""
    s = int(s)
    if duracion >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def texto_capitulos(capitulos: list[tuple[float, str]], duracion: float) -> str:
    return "\n".join(f"{tiempo(t, duracion)} {titulo}" for t, titulo in capitulos)


def ensamblar(resumen: str, capitulos: str, pie: str, hashtags: list[str]) -> str:
    """La descripción lista para pegar en YouTube: resumen, capítulos, pie fijo y hashtags."""
    return "\n\n".join(p for p in (resumen.strip(), capitulos.strip(), pie.strip(), " ".join(hashtags)) if p)


class Empacador:
    def __init__(self, api_key: str, modelo: str, esfuerzo: str, skill_hunter: Path):
        self._cliente = anthropic.Anthropic(api_key=api_key)
        self._modelo = modelo
        self._esfuerzo = esfuerzo
        self._skill_hunter = skill_hunter

    def proponer(self, proyecto: Proyecto, episodio: str, segmentos: list[Segmento], duracion: float,
                 enfoque: str | None = None) -> Paquete:
        guia, _ = proyecto.youtube()
        try:
            reglas = leer_reglas(self._skill_hunter, REGLAS)
        except ErrorCaption as e:
            raise ErrorEmpaque(str(e)) from e
        system = (reglas.replace("{nombre}", proyecto.nombre).replace("{fichas}", proyecto.fichas())
                  .replace("{youtube}", guia or "(el proyecto no tiene ficha de YouTube: usa las fichas de marca)"))
        usuario = f"Episodio: {episodio} · duración {int(duracion)} s ({tiempo(duracion, duracion)})\n"
        if enfoque:
            usuario += f"Enfoque pedido por el equipo: {enfoque}.\n"
        usuario += f"\n<transcripcion>\n{texto_con_tiempos(segmentos) or '(vacía)'}\n</transcripcion>"
        try:
            r = self._cliente.beta.messages.create(
                model=self._modelo,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": usuario}],
                output_config={"effort": self._esfuerzo, "format": {"type": "json_schema", "schema": ESQUEMA}},
            )
        except anthropic.APIStatusError as e:
            raise ErrorEmpaque(f"La API de Claude respondió {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ErrorEmpaque("No pude conectarme a la API de Claude") from e

        costo = costo_usd(self._modelo, r.usage)
        if r.stop_reason == "refusal":
            raise ErrorEmpaque(f"Claude no quiso proponer el empaque de {episodio}")
        if r.stop_reason == "max_tokens":
            raise ErrorEmpaque(f"La respuesta para {episodio} quedó cortada")
        datos = json.loads(next(b.text for b in r.content if b.type == "text"))
        return armar(datos, duracion, costo)


def armar(datos: dict, duracion: float, costo: Costo) -> Paquete:
    avisos: list[str] = []
    titulos = [t.strip() for t in datos["titulos"] if t.strip()][:3]
    if len(titulos) < 3:
        avisos.append(f"Claude propuso {len(titulos)} título(s) en vez de 3")
    for i, t in enumerate(titulos, 1):
        if len(t) > LARGO_TITULO:
            avisos.append(f"el título {i} tiene {len(t)} caracteres (YouTube corta desde {LARGO_TITULO})")
    capitulos = limpiar_capitulos(datos["capitulos"], duracion)
    if not capitulos:
        avisos.append("no hubo capítulos suficientes (YouTube pide al menos 3, el primero en 0:00)")
    hashtags = [h if h.startswith("#") else f"#{h}" for h in datos["hashtags"]][:3]
    return Paquete(titulos, datos["resumen"].strip(), capitulos, hashtags, costo, avisos)
