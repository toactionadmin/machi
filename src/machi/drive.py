"""Acceso a Google Drive con escritura limitada.

La cuenta machi-drive es Colaboradora de todo el disco compartido, pero machi solo
entra a <disco>/<Proyecto>/MULTIMEDIA/SHOWS/<episodio>/SHOW/Originales:
- lee únicamente el .mp4 de Proxy/ (tiene que haber uno solo), y
- escribe únicamente archivos EP…_ReelNNN.fcpxml en Timelines/ (la crea si falta).
Cualquier otro archivo o destino se rechaza (ver `Episodio`).
"""

import io
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

log = logging.getLogger(__name__)

CARPETA = "application/vnd.google-apps.folder"
_KW = dict(supportsAllDrives=True, includeItemsFromAllDrives=True)
# Ruta fija del episodio: SHOWS/<episodio>/SHOW/Originales/{Proxy,Timelines}
SHOWS = ("MULTIMEDIA", "SHOWS")
ORIGINALES = ("SHOW", "Originales")
PROXY, TIMELINES = "Proxy", "Timelines"
# "EP20261031" o "EP001", comparado ya normalizado.
EPISODIO = re.compile(r"^ep\d+$")
# Lo único que machi puede escribir: EP20261031_Reel001.fcpxml
ARCHIVO_REEL = re.compile(r"^EP\d+_Reel\d{3}\.fcpxml$")


class ErrorDrive(Exception):
    codigo = "drive"


def normalizar(texto: str) -> str:
    """Compara nombres sin importar mayúsculas, tildes ni espacios de más."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


@dataclass(frozen=True)
class Video:
    id: str
    nombre: str
    link: str
    bytes: int


class Drive:
    def __init__(self, credenciales: Path, disco: str):
        creds = service_account.Credentials.from_service_account_file(
            credenciales, scopes=["https://www.googleapis.com/auth/drive"]
        )
        self._api = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._nombre_disco = disco
        self._disco_id: str | None = None

    def _hijos(self, padre: str) -> list[dict]:
        res, pagina = [], None
        while True:
            r = (
                self._api.files()
                .list(
                    q=f"'{padre}' in parents and trashed = false",
                    corpora="drive",
                    driveId=self._disco(),
                    fields="nextPageToken, files(id, name, mimeType, size, webViewLink)",
                    pageSize=200,
                    pageToken=pagina,
                    **_KW,
                )
                .execute()
            )
            res += r["files"]
            pagina = r.get("nextPageToken")
            if not pagina:
                return res

    def _disco(self) -> str:
        if not self._disco_id:
            discos = self._api.drives().list(pageSize=100).execute().get("drives", [])
            for d in discos:
                if normalizar(d["name"]) == normalizar(self._nombre_disco):
                    self._disco_id = d["id"]
                    break
            else:
                raise ErrorDrive(f'No encuentro el disco compartido "{self._nombre_disco}"')
        return self._disco_id

    def _subcarpeta(self, padre: str, nombre: str, ruta: str) -> dict:
        for f in self._hijos(padre):
            if f["mimeType"] == CARPETA and normalizar(f["name"]) == normalizar(nombre):
                return f
        raise ErrorDrive(f'No encuentro la carpeta "{ruta}/{nombre}" en Drive')

    def shows(self, carpeta_proyecto: str) -> "Shows":
        """Ubica <disco>/<proyecto>/MULTIMEDIA/SHOWS."""
        ruta = self._nombre_disco
        actual = self._subcarpeta(self._disco(), carpeta_proyecto, ruta)
        ruta += f"/{actual['name']}"
        try:
            for nombre in SHOWS:
                actual = self._subcarpeta(actual["id"], nombre, ruta)
                ruta += f"/{actual['name']}"
        except ErrorDrive as e:
            raise ErrorDrive(f"{carpeta_proyecto} no tiene episodios: {e}") from e
        return Shows(self, actual["id"], ruta)


class Shows:
    """La carpeta MULTIMEDIA/SHOWS de un proyecto. Solo se leen sus carpetas EP…"""

    def __init__(self, drive: Drive, id_: str, ruta: str):
        self._drive = drive
        self.id = id_
        self.ruta = ruta

    def episodios(self) -> list[dict]:
        """Carpetas de episodio (EP20261031, EP001…), ordenadas por nombre."""
        carpetas = [
            f for f in self._drive._hijos(self.id)
            if f["mimeType"] == CARPETA and EPISODIO.match(normalizar(f["name"]))
        ]
        return sorted(carpetas, key=lambda f: f["name"])

    def episodio(self, nombre: str) -> "Episodio":
        carpetas = self.episodios()
        elegida = next((f for f in carpetas if normalizar(f["name"]) == normalizar(nombre)), None)
        if not elegida:
            opciones = ", ".join(f["name"] for f in carpetas[-8:]) or "ninguno"
            raise ErrorDrive(f'No encuentro el episodio "{nombre}" en {self.ruta}. Episodios: {opciones}')
        ruta = f"{self.ruta}/{elegida['name']}"
        actual = elegida
        for parte in ORIGINALES:
            actual = self._drive._subcarpeta(actual["id"], parte, ruta)
            ruta += f"/{actual['name']}"
        return Episodio(self._drive, elegida["name"], actual["id"], ruta)


class Episodio:
    """SHOW/Originales de un episodio: lee el .mp4 de Proxy/ y escribe en Timelines/."""

    def __init__(self, drive: Drive, nombre: str, originales_id: str, ruta: str):
        self._drive = drive
        self.nombre = nombre  # tal como está en Drive, ej. "EP20261031"
        self.ruta = ruta
        self._originales = originales_id
        self._timelines: dict | None = None
        proxy = drive._subcarpeta(originales_id, PROXY, ruta)
        videos = [
            f for f in drive._hijos(proxy["id"])
            if f["mimeType"] != CARPETA and f["name"].lower().endswith(".mp4")
        ]
        if len(videos) != 1:
            hay = ", ".join(f["name"] for f in videos) or "ninguno"
            raise ErrorDrive(f"En {ruta}/{PROXY} tiene que haber un solo .mp4 (hay: {hay})")
        f = videos[0]
        self.video = Video(f["id"], f["name"], f.get("webViewLink", ""), int(f.get("size", 0)))

    def descargar(self, destino: Path) -> Path:
        destino.parent.mkdir(parents=True, exist_ok=True)
        pedido = self._drive._api.files().get_media(fileId=self.video.id, supportsAllDrives=True)
        with open(destino, "wb") as fh:
            dl = MediaIoBaseDownload(fh, pedido, chunksize=64 * 1024 * 1024)
            listo = False
            while not listo:
                _, listo = dl.next_chunk()
        return destino

    def timelines(self) -> dict:
        """La carpeta Timelines/ ({id, webViewLink}); la crea si no existe."""
        if self._timelines:
            return self._timelines
        for f in self._drive._hijos(self._originales):
            if f["mimeType"] == CARPETA and normalizar(f["name"]) == normalizar(TIMELINES):
                self._timelines = f
                return f
        log.info("Creo %s/%s", self.ruta, TIMELINES)
        self._timelines = self._drive._api.files().create(
            body={"name": TIMELINES, "mimeType": CARPETA, "parents": [self._originales]},
            fields="id, name, webViewLink",
            supportsAllDrives=True,
        ).execute()
        return self._timelines

    def archivos_reels(self) -> dict[str, dict]:
        """Archivos EP…_ReelNNN.fcpxml que ya hay en Timelines/, por nombre."""
        return {
            f["name"]: f for f in self._drive._hijos(self.timelines()["id"])
            if ARCHIVO_REEL.match(f["name"])
        }

    def subir(self, nombre: str, contenido: str, existentes: dict[str, dict]) -> str:
        """Crea o reemplaza un FCPXML en Timelines/. Devuelve su link."""
        if not ARCHIVO_REEL.match(nombre):
            raise ErrorDrive(f"machi solo escribe archivos EP…_ReelNNN.fcpxml, no {nombre}")
        media = MediaIoBaseUpload(io.BytesIO(contenido.encode("utf-8")), mimetype="application/xml")
        archivos = self._drive._api.files()
        if nombre in existentes:
            f = archivos.update(
                fileId=existentes[nombre]["id"], media_body=media,
                fields="id, webViewLink", supportsAllDrives=True,
            ).execute()
        else:
            f = archivos.create(
                body={"name": nombre, "parents": [self.timelines()["id"]]}, media_body=media,
                fields="id, webViewLink", supportsAllDrives=True,
            ).execute()
        return f.get("webViewLink", "")
