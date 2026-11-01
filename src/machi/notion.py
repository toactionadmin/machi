"""Base «Reels propuestos» en Notion (API 2025-09-03, con data sources).

Una fila por reel. El episodio se reconoce por el ID del .mp4 en Drive: si ya tiene
filas, machi no lo rehace (salvo con --rehacer). machi nunca escribe en
«Notas del editor» después de crear la fila: esa columna es del equipo.
"""

import logging
from dataclasses import dataclass
from datetime import date

import httpx

log = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
LIMITE_TEXTO = 2000  # máximo de caracteres por bloque de texto en Notion

PROPUESTO, DESCARTADO = "Propuesto", "Descartado"

# Propiedades de la base. scripts/crear_base_notion.py la crea con exactamente esto.
PROPIEDADES = {
    "Reel": {"title": {}},
    "Proyecto": {"select": {}},
    "Episodio": {"rich_text": {}},
    "Orden": {"number": {}},
    "Inicio": {"rich_text": {}},
    "Fin": {"rich_text": {}},
    "Duración (s)": {"number": {}},
    "Gancho": {"rich_text": {}},
    "Por qué": {"rich_text": {}},
    "Texto": {"rich_text": {}},
    "Categoría": {"rich_text": {}},
    "Criterios": {"rich_text": {}},
    "Archivo FCPXML": {"url": {}},
    "Link al episodio": {"url": {}},
    "Notas del editor": {"rich_text": {}},
    "Estado": {
        "select": {
            "options": [
                {"name": PROPUESTO, "color": "yellow"},
                {"name": "Con notas", "color": "orange"},
                {"name": "Ajustado", "color": "green"},
                {"name": DESCARTADO, "color": "gray"},
            ]
        }
    },
    "Fecha": {"date": {}},
    "ID Drive": {"rich_text": {}},
    "Trabajo": {"rich_text": {}},
}


class ErrorNotion(Exception):
    codigo = "notion"


def _texto(contenido: str) -> list[dict]:
    trozos = [contenido[i : i + LIMITE_TEXTO] for i in range(0, len(contenido), LIMITE_TEXTO)][:100]
    return [{"type": "text", "text": {"content": t}} for t in trozos]


def _leer_texto(prop: dict) -> str:
    return "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))


def tiempo(s: float) -> str:
    """Segundos → «12:34.5» (minutos:segundos del episodio)."""
    return f"{int(s // 60)}:{s % 60:04.1f}"


@dataclass
class Fila:
    reel: str  # EP20261031_Reel001
    proyecto: str
    episodio: str
    orden: int
    inicio: float
    fin: float
    gancho: str
    porque: str
    texto: str
    categoria: str
    criterios: str
    archivo: str  # link al FCPXML en Drive
    link_episodio: str
    drive_id: str
    trabajo: str

    def propiedades(self) -> dict:
        return {
            "Reel": {"title": _texto(self.reel)},
            "Proyecto": {"select": {"name": self.proyecto}},
            "Episodio": {"rich_text": _texto(self.episodio)},
            "Orden": {"number": self.orden},
            "Inicio": {"rich_text": _texto(tiempo(self.inicio))},
            "Fin": {"rich_text": _texto(tiempo(self.fin))},
            "Duración (s)": {"number": round(self.fin - self.inicio, 1)},
            "Gancho": {"rich_text": _texto(self.gancho)},
            "Por qué": {"rich_text": _texto(self.porque)},
            "Texto": {"rich_text": _texto(self.texto)},
            "Categoría": {"rich_text": _texto(self.categoria)},
            "Criterios": {"rich_text": _texto(self.criterios)},
            "Archivo FCPXML": {"url": self.archivo or None},
            "Link al episodio": {"url": self.link_episodio or None},
            "Fecha": {"date": {"start": date.today().isoformat()}},
            "ID Drive": {"rich_text": _texto(self.drive_id)},
            "Trabajo": {"rich_text": _texto(self.trabajo)},
        }


@dataclass(frozen=True)
class FilaExistente:
    id: str
    orden: int
    estado: str
    trabajo: str


class Notion:
    def __init__(self, token: str, base_id: str):
        self._http = httpx.Client(
            base_url=API,
            timeout=30,
            headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION},
        )
        self._base_id = base_id
        self._fuente: str | None = None
        self.url_base: str = ""

    def _pedir(self, metodo: str, ruta: str, **kw) -> dict:
        r = self._http.request(metodo, ruta, **kw)
        if r.status_code >= 400:
            raise ErrorNotion(f"Notion respondió {r.status_code}: {r.json().get('message', r.text)}")
        return r.json()

    def _data_source(self) -> str:
        if not self._fuente:
            base = self._pedir("GET", f"/databases/{self._base_id}")
            self._fuente = base["data_sources"][0]["id"]
            self.url_base = base.get("url", "")
            self._asegurar_columnas()
        return self._fuente

    def _asegurar_columnas(self) -> None:
        """Agrega a la base las columnas que falten. No borra ni toca las que el equipo agregó."""
        actuales = self._pedir("GET", f"/data_sources/{self._fuente}")["properties"]
        cambios = {n: d for n, d in PROPIEDADES.items() if n not in actuales}
        if cambios:
            log.info("Agrego columnas a Notion: %s", ", ".join(cambios))
            self._pedir("PATCH", f"/data_sources/{self._fuente}", json={"properties": cambios})

    def del_episodio(self, drive_id: str) -> list[FilaExistente]:
        """Filas que ya tiene un episodio (por el ID de su .mp4 en Drive)."""
        filas, cursor = [], None
        while True:
            cuerpo: dict = {"filter": {"property": "ID Drive", "rich_text": {"equals": drive_id}}, "page_size": 100}
            if cursor:
                cuerpo["start_cursor"] = cursor
            r = self._pedir("POST", f"/data_sources/{self._data_source()}/query", json=cuerpo)
            for p in r["results"]:
                pr = p["properties"]
                filas.append(FilaExistente(
                    id=p["id"],
                    orden=int((pr.get("Orden") or {}).get("number") or 0),
                    estado=((pr.get("Estado") or {}).get("select") or {}).get("name", ""),
                    trabajo=_leer_texto(pr.get("Trabajo", {})),
                ))
            if not r.get("has_more"):
                return filas
            cursor = r["next_cursor"]

    def guardar(self, fila: Fila, pagina_id: str | None = None) -> str:
        """Crea la fila (estado Propuesto), o la actualiza si es del mismo trabajo. Devuelve su URL."""
        props = fila.propiedades()
        if pagina_id:
            p = self._pedir("PATCH", f"/pages/{pagina_id}", json={"properties": props})
        else:
            props["Estado"] = {"select": {"name": PROPUESTO}}
            p = self._pedir(
                "POST",
                "/pages",
                json={"parent": {"type": "data_source_id", "data_source_id": self._data_source()}, "properties": props},
            )
        return p.get("url", "")

    def descartar(self, pagina_id: str) -> None:
        """Con --rehacer, las filas anteriores quedan como Descartado (con sus notas intactas)."""
        self._pedir("PATCH", f"/pages/{pagina_id}", json={"properties": {"Estado": {"select": {"name": DESCARTADO}}}})

    def url(self) -> str:
        self._data_source()
        return self.url_base
