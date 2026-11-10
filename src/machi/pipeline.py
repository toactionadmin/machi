"""Trabajo "reels": Drive → ffmpeg → Whisper (GPU) → Claude → FCPXML en Drive → Notion.

Sin episodio, solo lista los episodios del proyecto y cuáles ya tienen reels.
"""

import json
import logging
import re
import shutil
from collections.abc import Callable
from dataclasses import asdict

from . import fcpxml, proyectos
from .captions import Caption, ErrorCaption, Redactor, sumar
from .cola import Cancelado
from .config import Config
from .drive import EPISODIO, Drive, Episodio, normalizar
from .momentos import Editor
from .notion import DESCARTADO, Fila, Notion
from .trabajo import Costo, Enlace, Resultado, Trabajo
from .transcribir import (InfoVideo, Palabra, Segmento, Transcriptor, esperar_render,
                          extraer_audio, leer_video)

log = logging.getLogger(__name__)

# Etapas que informa el progreso (progreso.etapa / progreso.etapas). Las usan los procesos de Gyo.
ETAPAS = ("drive", "transcripcion", "momentos", "captions", "lineas", "notion")

# Lo que publica GET /capacidades: Netero lo usará para saber qué hace cada servicio.
CAPACIDADES = {
    "reels": {
        "descripcion": "Reels verticales de un episodio de <Proyecto>/MULTIMEDIA/SHOWS/<episodio>, "
                       "como FCPXML en SHOW/Originales/Timelines y filas en «Reels propuestos»",
        "parametros": {
            "proyecto": {"tipo": "texto", "requerido": True, "descripcion": "Código del proyecto en skill-hunter (ej. lasjavis)"},
            "episodio": {"tipo": "texto", "requerido": False, "descripcion": "Carpeta del episodio (EP20261031, EP001); sin ella, solo lista los episodios"},
            "enfoque": {"tipo": "texto", "requerido": False, "descripcion": "Qué buscar, ej. \"momentos de humor\""},
            "rehacer": {"tipo": "booleano", "requerido": False, "descripcion": "Vuelve a proponer aunque ya tenga reels (exige episodio)"},
        },
    }
}


def codigo_episodio(carpeta: str) -> str:
    """'ep20261031' o 'EP20261031' → 'EP20261031' (prefijo de los archivos de reels)."""
    return "EP" + re.sub(r"\D", "", carpeta)


class Reels:
    def __init__(self, cfg: Config, guardar: Callable[[Trabajo], None], cancelado: Callable[[str], bool]):
        self.cfg = cfg
        self._guardar = guardar
        self._cancelado = cancelado
        self.drive = Drive(cfg.google_sa, cfg.drive_disco)
        self.notion = Notion(cfg.notion_token, cfg.notion_db)
        self.editor = Editor(cfg.anthropic_key, cfg.claude_modelo, cfg.claude_esfuerzo)
        self.redactor = Redactor(cfg.anthropic_key, cfg.claude_modelo, cfg.claude_esfuerzo_captions, cfg.skill_hunter)

    def validar(self, parametros: dict) -> None:
        """Errores que conviene devolver al tiro, antes de encolar."""
        proyectos.actualizar(self.cfg.skill_hunter)  # así un proyecto recién creado sirve al primer pedido
        proyecto = proyectos.buscar(self.cfg.skill_hunter, str(parametros.get("proyecto", "")).lower())
        episodio = parametros.get("episodio")
        if parametros.get("rehacer") and not episodio:
            raise ValueError("--rehacer necesita un episodio: /<proyecto>_reels EP20261031 --rehacer")
        if episodio:
            if not EPISODIO.match(normalizar(str(episodio))):
                raise ValueError(f'"{episodio}" no parece un episodio: se escribe EP20261031 o EP001')
            # Revisa que el episodio y su .mp4 existan antes de encolar, para avisar al tiro.
            self.drive.shows(proyecto.drive).episodio(str(episodio))

    def _avance(self, t: Trabajo, mensaje: str, actual: int | None = None, etapa: str | None = None) -> None:
        if self._cancelado(t.id):
            raise Cancelado
        t.progreso.mensaje = mensaje
        if actual is not None:
            t.progreso.actual = actual
        if etapa is not None:
            t.progreso.etapa = etapa
        self._guardar(t)

    @staticmethod
    def _completa(t: Trabajo, etapa: str, n: int = 1) -> None:
        t.progreso.etapas[etapa] = t.progreso.etapas.get(etapa, 0) + n

    def procesar(self, t: Trabajo) -> None:
        par = t.parametros
        # Un trabajo que ya tiene avance viene de un reinicio (la cola lo devolvió): parte de cero
        # para que los contadores de Gyo no se sumen a los de antes.
        retomado = bool(t.progreso.actual or t.progreso.etapas)
        if retomado:
            log.warning("%s se retoma tras un reinicio", t.id)
            t.progreso.actual, t.progreso.total, t.progreso.etapas = 0, 0, {}
        self._avance(t, "Retomado tras un reinicio: actualizando fichas" if retomado else "Actualizando fichas")
        proyectos.actualizar(self.cfg.skill_hunter)
        proyecto = proyectos.buscar(self.cfg.skill_hunter, str(par.get("proyecto", "")).lower())

        self._avance(t, "Buscando el episodio en Drive", etapa="drive")
        shows = self.drive.shows(proyecto.drive)
        if not par.get("episodio"):
            self._listar(t, proyecto, shows)
            return
        self._episodio(t, proyecto, shows.episodio(str(par["episodio"])), retomado)

    # --- sin episodio: solo lista ---

    def _listar(self, t: Trabajo, proyecto, shows) -> None:
        con, sin, problemas = [], [], []
        for f in shows.episodios():
            try:
                ep = shows.episodio(f["name"])
            except Exception as e:
                problemas.append({"episodio": f["name"], "error": str(e)})
                continue
            vigentes = [x for x in self.notion.del_episodio(ep.video.id) if x.estado != DESCARTADO]
            (con if vigentes else sin).append({"episodio": ep.nombre, "reels": len(vigentes)})
        partes = []
        if sin:
            partes.append("Sin reels: " + ", ".join(e["episodio"] for e in sin))
        if con:
            partes.append("Con reels: " + ", ".join(f"{e['episodio']} ({e['reels']})" for e in con))
        if problemas:
            partes.append("Con problemas: " + ", ".join(p["episodio"] for p in problemas))
        t.resultado = Resultado(
            resumen=f"Episodios de {proyecto.nombre}. " + (". ".join(partes) if partes else f"No hay episodios en {shows.ruta}"),
            enlaces=[Enlace(titulo="Reels propuestos en Notion", url=self.notion.url())],
            datos={"proyecto": proyecto.comando, "sin_reels": sin, "con_reels": con, "problemas": problemas},
        )
        t.progreso.mensaje = "Terminado"

    # --- captions ---

    def _caption(self, proyecto, reel: str, gancho: str, texto: str, avisos: list[str]) -> Caption | None:
        """El caption de un reel, o None si falla (queda vacío y se avisa; no tumba el trabajo)."""
        try:
            c = self.redactor.escribir(proyecto, reel, gancho, texto)
        except ErrorCaption as e:
            log.warning("Caption de %s: %s", reel, e)
            avisos.append(f"{reel}: {e}")
            return None
        if c.sin_contenido:
            avisos.append(f"{reel}: sin contenido para un caption")
        return c

    def _avisos_resultado(self, proyecto, avisos: list[str]) -> list[str]:
        partes = []
        if not proyecto.fichas():
            partes.append(f"{proyecto.nombre} no tiene fichas de marca: los captions salen sin su voz")
        if avisos:
            partes.append(f"{len(avisos)} caption(s) sin escribir ({'; '.join(avisos)}): se completan repitiendo el pedido")
        return partes

    def _completar_captions(self, t: Trabajo, proyecto, ep: Episodio, codigo: str, vigentes, enlaces) -> None:
        """Episodio con reels pero sin captions: los escribe sin volver a transcribir ni elegir momentos."""
        faltan = sorted((x for x in vigentes if not x.caption), key=lambda x: x.orden)
        n = len(faltan)
        t.progreso.total = n
        t.progreso.etapas = {e: n for e in ("drive", "transcripcion", "momentos", "lineas")}
        costo, avisos, hechos = Costo(), [], 0
        for x in faltan:
            nombre = x.reel or f"{codigo}_Reel{x.orden:03d}"
            self._avance(t, f"Escribiendo el caption de {nombre} ({hechos + 1}/{n})", etapa="captions")
            c = self._caption(proyecto, nombre, x.gancho, x.texto, avisos)
            self._completa(t, "captions")
            if c:
                costo = sumar(costo, c.costo)
                if c.texto:
                    self._avance(t, f"Guardando el caption de {nombre} en Notion", etapa="notion")
                    self.notion.poner_caption(x.id, c.texto, " ".join(c.hashtags))
                    hechos += 1
            self._completa(t, "notion")
            t.progreso.actual = hechos + len(avisos)
        t.resultado = Resultado(
            resumen=", ".join([f"{hechos} caption(s) escritos para {codigo}", *self._avisos_resultado(proyecto, avisos)]),
            enlaces=enlaces,
            costo=costo,
            datos={"proyecto": proyecto.comando, "episodio": ep.nombre, "captions": hechos, "avisos": avisos,
                   "modelo": self.cfg.claude_modelo},
        )
        t.progreso.mensaje = "Terminado"

    # --- con episodio ---

    def _transcripcion(self, t: Trabajo, ep: Episodio, vocabulario: str) -> tuple[InfoVideo, list[Segmento]]:
        """Descarga y transcribe, o reutiliza la transcripción guardada de ese mismo .mp4."""
        guardada = self.cfg.datos / "transcripciones" / f"{ep.video.id}.json"
        if guardada.exists():
            d = json.loads(guardada.read_text(encoding="utf-8"))
            segmentos = [Segmento(s["inicio"], s["fin"], s["texto"], tuple(Palabra(**p) for p in s["palabras"]))
                         for s in d["segmentos"]]
            return InfoVideo(**d["video"]), segmentos

        temporal = self.cfg.datos / "tmp" / t.id
        try:
            self._avance(t, f"Descargando {ep.video.nombre} ({ep.video.bytes / 1e9:.1f} GB)", etapa="drive")
            archivo = ep.descargar(temporal / "episodio.mp4")
            info = leer_video(archivo, self.cfg.ffmpeg)
            audio = extraer_audio(archivo, self.cfg.ffmpeg)
            archivo.unlink()  # el video no se necesita más
            self._completa(t, "drive")

            esperar_render(lambda m: self._avance(t, m, etapa="transcripcion"))
            self._avance(t, f"Transcribiendo {ep.nombre} ({info.duracion / 60:.0f} min)", etapa="transcripcion")
            with Transcriptor(self.cfg.whisper_modelo, self.cfg.datos / "modelos") as tr:
                segmentos = tr.transcribir(audio, vocabulario)
        finally:
            shutil.rmtree(temporal, ignore_errors=True)
        guardada.parent.mkdir(parents=True, exist_ok=True)
        guardada.write_text(
            json.dumps({"video": asdict(info), "segmentos": [asdict(s) for s in segmentos]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return info, segmentos

    def _episodio(self, t: Trabajo, proyecto, ep: Episodio, retomado: bool) -> None:
        par = t.parametros
        rehacer = bool(par.get("rehacer"))
        codigo = codigo_episodio(ep.nombre)
        enlaces = [Enlace(titulo="Reels propuestos en Notion", url=self.notion.url())]
        t.progreso.total = 1

        filas = self.notion.del_episodio(ep.video.id)
        mias = {x.orden: x for x in filas if x.trabajo == t.id}  # de este mismo trabajo (reinicio)
        anteriores = [x for x in filas if x.trabajo != t.id and x.estado != DESCARTADO]
        if anteriores and not rehacer and any(not x.caption for x in anteriores):
            self._completar_captions(t, proyecto, ep, codigo, anteriores, enlaces)
            return
        if anteriores and not rehacer:
            t.resultado = Resultado(
                resumen=f"{codigo} ya tiene {len(anteriores)} reel(s) propuestos. Para volver a proponer: --rehacer",
                enlaces=enlaces,
                datos={"proyecto": proyecto.comando, "episodio": ep.nombre, "saltado": True},
            )
            for e in ETAPAS:
                self._completa(t, e)
            t.progreso.actual, t.progreso.mensaje = 1, "Terminado"
            return

        vocabulario = ", ".join([proyecto.nombre, *proyecto.vocabulario])
        info, segmentos = self._transcripcion(t, ep, vocabulario)
        t.progreso.etapas["drive"] = 1
        self._completa(t, "transcripcion")

        self._avance(t, f"Eligiendo momentos de {codigo}", etapa="momentos")
        prop = self.editor.proponer(proyecto, codigo, segmentos, info.duracion, par.get("enfoque") or None)
        n = len(prop.reels)
        t.progreso.total = max(n, 1)
        # Lo anterior era un solo elemento (el episodio): ahora cuenta como hecho para los n reels.
        t.progreso.etapas = {"drive": n, "transcripcion": n, "momentos": n}

        captions: dict[int, Caption | None] = {}
        costo_captions, avisos = Costo(), []
        for r in prop.reels:
            nombre = f"{codigo}_Reel{r.orden:03d}"
            self._avance(t, f"Escribiendo el caption de {nombre} ({r.orden}/{n})", etapa="captions")
            captions[r.orden] = c = self._caption(proyecto, nombre, r.gancho, r.texto, avisos)
            if c:
                costo_captions = sumar(costo_captions, c.costo)
            self._completa(t, "captions")

        existentes = ep.archivos_reels()
        clip = ep.nombre_clip(proyecto.original)  # el original del Media Pool, no el proxy de Drive
        links: dict[int, str] = {}
        for r in prop.reels:
            nombre = f"{codigo}_Reel{r.orden:03d}"
            self._avance(t, f"Armando {nombre} ({r.orden}/{n})", etapa="lineas")
            contenido = fcpxml.reel(nombre, clip, info.fps, info.cuadros, info.timecode,
                                    r.inicio, r.fin, info.ancho, info.alto)
            links[r.orden] = ep.subir(f"{nombre}.fcpxml", contenido, existentes)
            self._completa(t, "lineas")
        # Con --rehacer pueden quedar archivos de más (la cuenta no puede borrar): se avisa.
        sobrantes = sorted(x for x in existentes if int(x[-10:-7]) > n)

        if rehacer:
            for x in anteriores:
                self.notion.descartar(x.id)
        criterios = "\n".join(f"• {c}" for c in prop.criterios)
        for r in prop.reels:
            nombre = f"{codigo}_Reel{r.orden:03d}"
            self._avance(t, f"Guardando {nombre} en Notion ({r.orden}/{n})", etapa="notion")
            c = captions.get(r.orden)
            previa = mias.get(r.orden)  # un reinicio no pisa un caption que ya está (o que el equipo editó)
            escribir = bool(c and c.texto and not (previa and previa.caption))
            fila = Fila(
                reel=nombre, proyecto=proyecto.nombre, episodio=ep.nombre, orden=r.orden,
                inicio=r.inicio, fin=r.fin, gancho=r.gancho, porque=r.porque, texto=r.texto,
                categoria=prop.categoria, criterios=criterios, archivo=links[r.orden],
                link_episodio=ep.video.link, drive_id=ep.video.id, trabajo=t.id,
                caption=c.texto if escribir else None, hashtags=" ".join(c.hashtags) if escribir else None,
            )
            self.notion.guardar(fila, mias[r.orden].id if r.orden in mias else None)
            self._completa(t, "notion")
            self._avance(t, f"{nombre}: listo", r.orden)

        partes = [f"{n} reel(s) propuestos para {codigo}" if n else f"Claude no encontró momentos que sirvan en {codigo}"]
        if prop.categoria:
            partes.append(f"categoría: {prop.categoria}")
        if n:
            partes.append(f"{sum(1 for c in captions.values() if c and c.texto)} caption(s)")
            partes.extend(self._avisos_resultado(proyecto, avisos))
        if rehacer and anteriores:
            partes.append(f"{len(anteriores)} anteriores quedaron como Descartado")
        if sobrantes:
            partes.append(f"quedaron {len(sobrantes)} archivo(s) de antes en Timelines ({', '.join(sobrantes)}): bórralos a mano")
        if retomado:
            partes.append("retomado tras un reinicio")
        enlaces.insert(0, Enlace(titulo=f"Timelines de {codigo} en Drive", url=ep.timelines().get("webViewLink", "")))
        t.resultado = Resultado(
            resumen=", ".join(partes),
            enlaces=enlaces,
            costo=sumar(prop.costo, costo_captions),
            datos={"proyecto": proyecto.comando, "episodio": ep.nombre, "clip": clip, "categoria": prop.categoria,
                   "criterios": prop.criterios, "reels": [asdict(r) for r in prop.reels],
                   "descartados_por_ajuste": prop.descartados, "sobrantes": sobrantes,
                   "modelo": self.cfg.claude_modelo},
        )
        t.progreso.mensaje = "Terminado"
