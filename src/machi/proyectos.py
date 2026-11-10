"""Lectura de proyectos y fichas de marca desde skill-hunter.

Cada proyecto es skill-hunter/proyectos/<carpeta>/ con un README.md cuyo
frontmatter trae `comando` y `drive`. Todo lo que haya en marca/ se le entrega
a Claude: agregar una ficha nueva no requiere tocar código.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)


class ErrorProyecto(Exception):
    codigo = "proyecto"


@dataclass(frozen=True)
class Proyecto:
    comando: str
    nombre: str
    drive: str  # nombre de la carpeta del proyecto en el disco compartido
    carpeta: Path
    vocabulario: list[str] = field(default_factory=list)
    original: str = "mp4"  # extensión del archivo que el editor importa a Resolve (el proxy siempre es .mov)
    reels_duracion: tuple[float, float] = (30.0, 90.0)  # segundos (mín, máx) de cada reel

    def fichas(self) -> str:
        """Todas las fichas de marca/, concatenadas en orden alfabético."""
        partes = []
        for f in sorted((self.carpeta / "marca").glob("*.md")):
            partes.append(f"<ficha nombre=\"{f.name}\">\n{f.read_text(encoding="utf-8").strip()}\n</ficha>")
        return "\n\n".join(partes)

    def youtube(self) -> tuple[str, str]:
        """(guía, pie) de proyectos/<proyecto>/youtube.md: el estilo de títulos y descripción, y el texto fijo del final.
        Sin la ficha, ("", "")."""
        ficha = self.carpeta / "youtube.md"
        if not ficha.exists():
            return "", ""
        texto = ficha.read_text(encoding="utf-8")
        fm: dict = {}
        if texto.startswith("---"):
            _, cabecera, texto = texto.split("---", 2)
            try:
                fm = yaml.safe_load(cabecera) or {}
            except yaml.YAMLError as e:
                log.warning("Frontmatter inválido en %s: %s", ficha, e)
        return texto.strip(), str(fm.get("pie") or "").strip()


def _frontmatter(readme: Path) -> dict:
    texto = readme.read_text(encoding="utf-8")
    if not texto.startswith("---"):
        return {}
    try:
        return yaml.safe_load(texto.split("---", 2)[1]) or {}
    except yaml.YAMLError as e:
        log.warning("Frontmatter inválido en %s: %s", readme, e)
        return {}


REELS_DURACION_POR_DEFECTO = (30.0, 90.0)


def leer_reels_duracion(valor, proyecto: str = "") -> tuple[float, float]:
    """`reels_duracion: [mín, máx]` (segundos) del README. Sin el campo, o si no sirve, 30 a 90 s."""
    if valor is None:
        return REELS_DURACION_POR_DEFECTO
    try:
        minimo, maximo = (float(x) for x in valor)
        if 0 < minimo < maximo:
            return minimo, maximo
    except (TypeError, ValueError):
        pass
    log.warning("reels_duracion de %s no sirve (%r): uso 30 a 90 s. Debe ser [mín, máx] en segundos, con 0 < mín < máx", proyecto, valor)
    return REELS_DURACION_POR_DEFECTO


def actualizar(skill_hunter: Path) -> bool:
    """git pull de skill-hunter. Si falla, sigue con la copia local."""
    r = subprocess.run(
        ["git", "-C", str(skill_hunter), "pull", "--ff-only", "-q"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode:
        log.warning("git pull de skill-hunter falló, uso la copia local: %s", r.stderr.strip())
    return r.returncode == 0


def cargar(skill_hunter: Path) -> dict[str, Proyecto]:
    proyectos = {}
    for readme in sorted((skill_hunter / "proyectos").glob("*/README.md")):
        if readme.parent.name.startswith("_"):
            continue
        fm = _frontmatter(readme)
        if not fm.get("activo", True) or not fm.get("comando") or not fm.get("drive"):
            continue
        p = Proyecto(
            comando=str(fm["comando"]).strip().lower(),
            nombre=str(fm.get("nombre", readme.parent.name)),
            drive=str(fm["drive"]),
            carpeta=readme.parent,
            vocabulario=[str(v) for v in fm.get("vocabulario") or []],
            original=str(fm.get("original") or "mp4").strip().lstrip(".").lower(),
            reels_duracion=leer_reels_duracion(fm.get("reels_duracion"), readme.parent.name),
        )
        proyectos[p.comando] = p
    return proyectos


def buscar(skill_hunter: Path, comando: str) -> Proyecto:
    proyectos = cargar(skill_hunter)
    if comando not in proyectos:
        disponibles = ", ".join(sorted(proyectos)) or "ninguno"
        raise ErrorProyecto(f'No existe el proyecto "{comando}". Disponibles: {disponibles}')
    return proyectos[comando]
