"""Elección de reels con Claude a partir de la transcripción y las fichas de marca.

Claude clasifica el episodio, escribe los criterios y propone los tramos. Después
machi ajusta cada tramo a los bordes de palabras reales (tiempos de Whisper) y
descarta los que no queden entre 30 y 90 s: nunca se rellena.
"""

import json
import logging
from dataclasses import dataclass

import anthropic

from .proyectos import Proyecto
from .trabajo import Costo
from .transcribir import Palabra, Segmento

log = logging.getLogger(__name__)

MAX_REELS = 15
MIN_S, MAX_S = 30.0, 90.0
ANTES_S, DESPUES_S = 0.15, 0.30  # aire antes de la primera palabra y después de la última

# USD por millón de tokens: entrada, salida, lectura de caché, escritura de caché.
PRECIOS = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}

INSTRUCCIONES = """\
Eres editor de contenido en toAction, una productora de contenido en Chile.
A partir de la transcripción de un episodio largo (podcast o show), propones los mejores
momentos para publicar como reels verticales.

Cómo trabajas:
1. Primero entiendes el episodio y lo clasificas (educativo, entrevista, testimonio, humor, conversación u otra).
2. Según esa categoría y las fichas de marca, defines de 3 a 6 criterios concretos para elegir momentos.
3. Recién entonces eliges hasta {maximo} reels de {min_s:.0f} a {max_s:.0f} segundos, del mejor al más débil.

Reglas:
- Nunca rellenes: si solo hay 6 momentos buenos, propones 6. Menos y buenos es mejor que muchos y flojos.
- Cada reel se entiende solo, sin haber visto el episodio: empieza con una idea completa (no a mitad de frase
  ni con "y entonces…") y termina en un cierre natural (remate, conclusión o risa).
- Los primeros segundos tienen que enganchar.
- No se superponen entre sí.
- Usa los tiempos de la transcripción (segundos desde el inicio del episodio). "inicio" es el comienzo de la
  primera frase del reel y "fin" el término de la última.
- "gancho": título corto del reel, máximo 60 caracteres, en el tono de la marca.
- "porque": una o dos frases con la razón, ligada a los criterios.
- Español de Chile natural.

<fichas_de_marca proyecto="{nombre}">
{fichas}
</fichas_de_marca>
"""

ESQUEMA = {
    "type": "object",
    "properties": {
        "categoria": {"type": "string"},
        "criterios": {"type": "array", "items": {"type": "string"}},
        "reels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "inicio": {"type": "number"},
                    "fin": {"type": "number"},
                    "gancho": {"type": "string"},
                    "porque": {"type": "string"},
                },
                "required": ["inicio", "fin", "gancho", "porque"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["categoria", "criterios", "reels"],
    "additionalProperties": False,
}


class ErrorMomentos(Exception):
    codigo = "claude"


@dataclass
class Reel:
    orden: int
    inicio: float
    fin: float
    gancho: str
    porque: str
    texto: str  # lo que se dice en el reel

    @property
    def duracion(self) -> float:
        return round(self.fin - self.inicio, 2)


@dataclass
class Propuesta:
    categoria: str
    criterios: list[str]
    reels: list[Reel]
    descartados: int  # tramos de Claude que no pasaron el ajuste
    costo: Costo


def costo_usd(modelo: str, uso) -> Costo:
    p_in, p_out, p_lee, p_esc = PRECIOS.get(modelo, PRECIOS["claude-opus-5-5"])
    lee = uso.cache_read_input_tokens or 0
    esc = uso.cache_creation_input_tokens or 0
    usd = (uso.input_tokens * p_in + uso.output_tokens * p_out + lee * p_lee + esc * p_esc) / 1e6
    return Costo(tokens_entrada=uso.input_tokens + lee + esc, tokens_salida=uso.output_tokens, usd=round(usd, 4))


def _hhmmss(s: float) -> str:
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


def texto_con_tiempos(segmentos: list[Segmento]) -> str:
    return "\n".join(f"[{s.inicio:.1f}–{s.fin:.1f}] {s.texto}" for s in segmentos)


def ajustar(inicio: float, fin: float, palabras: list[Palabra], duracion: float) -> tuple[float, float, str] | None:
    """Lleva el tramo a bordes de palabras reales, con un poco de aire. None si no queda de 30 a 90 s."""
    dentro = [p for p in palabras if p.inicio >= inicio - 0.5 and p.fin <= fin + 0.5]
    while dentro and dentro[-1].fin - dentro[0].inicio > MAX_S - ANTES_S - DESPUES_S:
        dentro.pop()  # muy largo: se recorta desde el final, palabra por palabra
    if not dentro:
        return None
    i = palabras.index(dentro[0])
    j = palabras.index(dentro[-1])
    previo = palabras[i - 1].fin if i > 0 else 0.0
    siguiente = palabras[j + 1].inicio if j + 1 < len(palabras) else duracion
    a = max(previo, dentro[0].inicio - ANTES_S, 0.0)
    b = min(siguiente, dentro[-1].fin + DESPUES_S, duracion)
    if not MIN_S <= b - a <= MAX_S:
        return None
    return round(a, 3), round(b, 3), " ".join(p.texto for p in dentro)


class Editor:
    def __init__(self, api_key: str, modelo: str, esfuerzo: str):
        self._cliente = anthropic.Anthropic(api_key=api_key)
        self._modelo = modelo
        self._esfuerzo = esfuerzo

    def proponer(self, proyecto: Proyecto, episodio: str, segmentos: list[Segmento],
                 duracion: float, enfoque: str | None = None) -> Propuesta:
        system = INSTRUCCIONES.format(
            maximo=MAX_REELS, min_s=MIN_S, max_s=MAX_S, nombre=proyecto.nombre, fichas=proyecto.fichas(),
        )
        usuario = f"Episodio: {episodio} · duración {_hhmmss(duracion)} ({duracion:.0f} s)\n"
        if enfoque:
            usuario += f"Enfoque pedido por el equipo: {enfoque}. Prioriza momentos que calcen con eso.\n"
        usuario += f"\n<transcripcion>\n{texto_con_tiempos(segmentos) or '(vacía)'}\n</transcripcion>"
        try:
            # Con respuestas largas la API exige streaming; se espera el mensaje completo.
            with self._cliente.beta.messages.stream(
                model=self._modelo,
                max_tokens=32000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": usuario}],
                output_config={
                    "effort": self._esfuerzo,
                    "format": {"type": "json_schema", "schema": ESQUEMA},
                },
            ) as flujo:
                r = flujo.get_final_message()
        except anthropic.APIStatusError as e:
            raise ErrorMomentos(f"La API de Claude respondió {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ErrorMomentos("No pude conectarme a la API de Claude") from e

        costo = costo_usd(self._modelo, r.usage)
        if r.stop_reason == "refusal":
            raise ErrorMomentos(f"Claude no quiso proponer reels para {episodio}")
        if r.stop_reason == "max_tokens":
            raise ErrorMomentos(f"La respuesta para {episodio} quedó cortada")
        datos = json.loads(next(b.text for b in r.content if b.type == "text"))
        return armar(datos, segmentos, duracion, costo)


def armar(datos: dict, segmentos: list[Segmento], duracion: float, costo: Costo) -> Propuesta:
    """Ajusta los tramos de Claude y numera los que sirven, en el orden que propuso."""
    palabras = [p for s in segmentos for p in s.palabras]
    reels: list[Reel] = []
    descartados = 0
    for r in datos["reels"]:
        ajuste = ajustar(float(r["inicio"]), float(r["fin"]), palabras, duracion)
        if not ajuste or any(ajuste[0] < x.fin and x.inicio < ajuste[1] for x in reels):
            descartados += 1
            continue
        a, b, texto = ajuste
        reels.append(Reel(len(reels) + 1, a, b, r["gancho"].strip()[:60], r["porque"].strip(), texto))
        if len(reels) == MAX_REELS:
            break
    if descartados:
        log.info("%d tramo(s) de Claude no pasaron el ajuste de 30 a 90 s", descartados)
    return Propuesta(datos["categoria"].strip(), [c.strip() for c in datos["criterios"]], reels, descartados, costo)
