"""Base «Episodios» en Notion: una fila por episodio con sus títulos, descripción y capítulos de YouTube.

Machi la busca por su nombre y, si no existe, la crea al lado de «Reels propuestos» (en la misma página):
no hace falta un ID nuevo en machi.env. machi nunca escribe «Título elegido» ni «Estado» después de crear
la fila: esas columnas son del equipo.
"""

import logging
from dataclasses import dataclass
from datetime import date

import httpx

from .notion import API, VERSION, ErrorNotion, _leer_texto, _texto

log = logging.getLogger(__name__)

NOMBRE = "Episodios"
PROPUESTO = "Propuesto"

# Propiedades de la base (se crean tal cual; las que falten se agregan sin tocar las del equipo).
PROPIEDADES = {
    "Episodio": {"title": {}},
    "Proyecto": {"select": {}},
    "Título 1": {"rich_text": {}},
    "Título 2": {"rich_text": {}},
    "Título 3": {"rich_text": {}},
    "Título elegido": {"rich_text": {}},
    "Descripción": {"rich_text": {}},
    "Capítulos": {"rich_text": {}},
    "Estado": {"select": {"options": [{"name": PROPUESTO, "color": "yellow"}, {"name": "Aprobado", "color": "green"}]}},
    "Link al episodio": {"url": {}},
    "Fecha": {"date": {}},
    "ID Drive": {"rich_text": {}},
    "Trabajo": {"rich_text": {}},
}


@dataclass
class FilaEpisodio:
    episodio: str  # «Las Javis · EP20261003»
    proyecto: str
    titulos: list[str]
    descripcion: str
    capitulos: str
    link_episodio: str
    drive_id: str
    trabajo: str

    def propiedades(self) -> dict:
        t = (self.titulos + ["", "", ""])[:3]
        return {
            "Episodio": {"title": _texto(self.episodio)},
            "Proyecto": {"select": {"name": self.proyecto}},
            "Título 1": {"rich_text": _texto(t[0])},
            "Título 2": {"rich_text": _texto(t[1])},
            "Título 3": {"rich_text": _texto(t[2])},
            "Descripción": {"rich_text": _texto(self.descripcion)},
            "Capítulos": {"rich_text": _texto(self.capitulos)},
            "Link al episodio": {"url": self.link_episodio or None},
            "Fecha": {"date": {"start": date.today().isoformat()}},
            "ID Drive": {"rich_text": _texto(self.drive_id)},
            "Trabajo": {"rich_text": _texto(self.trabajo)},
        }


@dataclass(frozen=True)
class FilaExistente:
    id: str
    estado: str
    drive_id: str
    elegido: str


class Episodios:
    def __init__(self, token: str, reels_db_id: str):
        self._http = httpx.Client(
            base_url=API, timeout=30,
            headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION},
        )
        self._reels_db = reels_db_id
        self._fuente: str | None = None
        self.url_base: str = ""

    def _pedir(self, metodo: str, ruta: str, **kw) -> dict:
        r = self._http.request(metodo, ruta, **kw)
        if r.status_code >= 400:
            raise ErrorNotion(f"Notion respondió {r.status_code}: {r.json().get('message', r.text)}")
        return r.json()

    def _pagina_madre(self) -> str:
        """La página donde vive «Reels propuestos»: ahí va también «Episodios»."""
        padre = self._pedir("GET", f"/databases/{self._reels_db}").get("parent", {})
        if padre.get("type") != "page_id":
            raise ErrorNotion("«Reels propuestos» no está dentro de una página: no sé dónde crear «Episodios»")
        return padre["page_id"]

    def _buscar_base(self, pagina: str) -> dict | None:
        """La base «Episodios» que está en la misma página que «Reels propuestos»."""
        cursor = None
        while True:
            cuerpo: dict = {"query": NOMBRE, "filter": {"property": "object", "value": "data_source"}, "page_size": 100}
            if cursor:
                cuerpo["start_cursor"] = cursor
            r = self._pedir("POST", "/search", json=cuerpo)
            for ds in r["results"]:
                if "".join(t.get("plain_text", "") for t in ds.get("title", [])).strip() != NOMBRE:
                    continue
                base_id = (ds.get("parent") or {}).get("database_id")
                if not base_id:
                    continue
                base = self._pedir("GET", f"/databases/{base_id}")
                if (base.get("parent") or {}).get("page_id") == pagina and not base.get("in_trash") and not base.get("archived"):
                    return {"fuente": ds["id"], "url": base.get("url", "")}
            if not r.get("has_more"):
                return None
            cursor = r["next_cursor"]

    def _data_source(self) -> str:
        if not self._fuente:
            pagina = self._pagina_madre()
            hallada = self._buscar_base(pagina)
            if not hallada:
                log.info("Creo la base «%s» en Notion", NOMBRE)
                base = self._pedir("POST", "/databases", json={
                    "parent": {"type": "page_id", "page_id": pagina},
                    "title": [{"type": "text", "text": {"content": NOMBRE}}],
                    "initial_data_source": {"properties": PROPIEDADES},
                })
                hallada = {"fuente": base["data_sources"][0]["id"], "url": base.get("url", "")}
            self._fuente, self.url_base = hallada["fuente"], hallada["url"]
            self._asegurar_columnas()
        return self._fuente

    def _asegurar_columnas(self) -> None:
        actuales = self._pedir("GET", f"/data_sources/{self._fuente}")["properties"]
        cambios = {n: d for n, d in PROPIEDADES.items() if n not in actuales}
        if cambios:
            log.info("Agrego columnas a «%s»: %s", NOMBRE, ", ".join(cambios))
            self._pedir("PATCH", f"/data_sources/{self._fuente}", json={"properties": cambios})

    def buscar(self, episodio: str) -> FilaExistente | None:
        """La fila de un episodio («Las Javis · EP20261003»), o None."""
        r = self._pedir("POST", f"/data_sources/{self._data_source()}/query", json={
            "filter": {"property": "Episodio", "title": {"equals": episodio}}, "page_size": 1,
        })
        if not r["results"]:
            return None
        p = r["results"][0]
        pr = p["properties"]
        return FilaExistente(
            id=p["id"],
            estado=((pr.get("Estado") or {}).get("select") or {}).get("name", ""),
            drive_id=_leer_texto(pr.get("ID Drive", {})),
            elegido=_leer_texto(pr.get("Título elegido", {})),
        )

    def guardar(self, fila: FilaEpisodio, pagina_id: str | None = None) -> str:
        """Crea la fila (estado Propuesto) o renueva solo las propuestas de la existente. Devuelve su URL."""
        props = fila.propiedades()
        if pagina_id:
            p = self._pedir("PATCH", f"/pages/{pagina_id}", json={"properties": props})
        else:
            props["Estado"] = {"select": {"name": PROPUESTO}}
            p = self._pedir("POST", "/pages", json={
                "parent": {"type": "data_source_id", "data_source_id": self._data_source()}, "properties": props,
            })
        return p.get("url", "")

    def url(self) -> str:
        self._data_source()
        return self.url_base

    def listado(self, proyecto: str) -> dict[str, FilaExistente]:
        """Las filas de un proyecto por nombre de episodio (para listar cuáles ya tienen empaque)."""
        filas, cursor = {}, None
        while True:
            cuerpo: dict = {"filter": {"property": "Proyecto", "select": {"equals": proyecto}}, "page_size": 100}
            if cursor:
                cuerpo["start_cursor"] = cursor
            r = self._pedir("POST", f"/data_sources/{self._data_source()}/query", json=cuerpo)
            for p in r["results"]:
                pr = p["properties"]
                nombre = "".join(t.get("plain_text", "") for t in (pr.get("Episodio") or {}).get("title", []))
                filas[nombre] = FilaExistente(
                    id=p["id"], estado=((pr.get("Estado") or {}).get("select") or {}).get("name", ""),
                    drive_id=_leer_texto(pr.get("ID Drive", {})), elegido=_leer_texto(pr.get("Título elegido", {})),
                )
            if not r.get("has_more"):
                return filas
            cursor = r["next_cursor"]
