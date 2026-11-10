"""Caption de Instagram de cada reel, con las reglas compartidas de skill-hunter.

Las reglas están en skill-hunter/stack/prompts/caption-reel.md (las usa también Nostrade): aquí no
se duplican. Un caption que falla no tumba el trabajo: el reel queda con el caption vacío y se avisa.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .momentos import costo_usd
from .proyectos import Proyecto
from .trabajo import Costo

log = logging.getLogger(__name__)

REGLAS = Path("stack") / "prompts" / "caption-reel.md"

ESQUEMA = {
    "type": "object",
    "properties": {
        "caption": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "sin_contenido": {"type": "boolean"},
    },
    "required": ["caption", "hashtags", "sin_contenido"],
    "additionalProperties": False,
}


class ErrorCaption(Exception):
    codigo = "claude"


@dataclass
class Caption:
    texto: str
    hashtags: list[str]
    sin_contenido: bool
    costo: Costo


def leer_reglas(skill_hunter: Path) -> str:
    """Las reglas de captions, sin el bloque de comentario con que se documentan."""
    ruta = skill_hunter / REGLAS
    if not ruta.exists():
        raise ErrorCaption(f"No encuentro las reglas de captions en skill-hunter ({REGLAS.as_posix()})")
    return re.sub(r"<!--.*?-->", "", ruta.read_text(encoding="utf-8"), flags=re.S).strip()


def sumar(a: Costo, b: Costo) -> Costo:
    return Costo(tokens_entrada=a.tokens_entrada + b.tokens_entrada,
                 tokens_salida=a.tokens_salida + b.tokens_salida, usd=round(a.usd + b.usd, 4))


class Redactor:
    def __init__(self, api_key: str, modelo: str, esfuerzo: str, skill_hunter: Path):
        self._cliente = anthropic.Anthropic(api_key=api_key)
        self._modelo = modelo
        self._esfuerzo = esfuerzo
        self._skill_hunter = skill_hunter

    def escribir(self, proyecto: Proyecto, reel: str, gancho: str, texto: str) -> Caption:
        # Se lee en cada llamada: así un cambio en las reglas vale desde el siguiente trabajo.
        system = leer_reglas(self._skill_hunter).replace("{nombre}", proyecto.nombre).replace("{fichas}", proyecto.fichas())
        usuario = (
            f"Reel: {reel}\nTítulo de trabajo: {gancho}\n\n"
            f"<transcripcion>\n{texto or '(vacía)'}\n</transcripcion>"
        )
        try:
            r = self._cliente.beta.messages.create(
                model=self._modelo,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                # Las fichas son iguales para todos los reels del episodio: se cachean.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": usuario}],
                output_config={"effort": self._esfuerzo, "format": {"type": "json_schema", "schema": ESQUEMA}},
            )
        except anthropic.APIStatusError as e:
            raise ErrorCaption(f"La API de Claude respondió {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ErrorCaption("No pude conectarme a la API de Claude") from e

        costo = costo_usd(self._modelo, r.usage)
        if r.stop_reason == "refusal":
            raise ErrorCaption(f"Claude no quiso escribir el caption de {reel}")
        if r.stop_reason == "max_tokens":
            raise ErrorCaption(f"La respuesta para {reel} quedó cortada")
        datos = json.loads(next(b.text for b in r.content if b.type == "text"))
        hashtags = [h if h.startswith("#") else f"#{h}" for h in datos["hashtags"]]
        return Caption(datos["caption"].strip(), hashtags, datos["sin_contenido"], costo)
