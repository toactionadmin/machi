"""Audio con ffmpeg y transcripción con faster-whisper en la GPU (CUDA, float16).

El audio se decodifica con ffmpeg y se le pasa a Whisper como arreglo: así no
depende de PyAV, cuya versión actual no es compatible con faster-whisper 1.2.
En Windows, las DLL de cuBLAS y cuDNN vienen en los paquetes nvidia-* de pip.
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MUESTREO = 16000


def _dll_cuda() -> None:
    import nvidia.cublas
    import nvidia.cudnn

    for paquete in (nvidia.cublas, nvidia.cudnn):
        carpeta = Path(list(paquete.__path__)[0]) / "bin"
        if carpeta.is_dir():
            os.add_dll_directory(str(carpeta))
            os.environ["PATH"] = str(carpeta) + os.pathsep + os.environ["PATH"]


def extraer_audio(video: Path, ffmpeg: str = "ffmpeg") -> np.ndarray:
    pcm = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(video), "-vn", "-f", "s16le", "-ac", "1", "-ar", str(MUESTREO), "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


@dataclass(frozen=True)
class InfoVideo:
    fps: int
    cuadros: int
    timecode: str  # de inicio, ej. "00:00:00:00"
    ancho: int
    alto: int
    duracion: float  # segundos


def leer_video(video: Path, ffmpeg: str = "ffmpeg") -> InfoVideo:
    """Datos del video con ffprobe (al lado de ffmpeg, o en el PATH)."""
    ffprobe = str(Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)) if os.sep in ffmpeg else "ffprobe"
    r = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate,width,height:stream_tags=timecode:format=duration:format_tags=timecode",
         "-of", "default=nw=1", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    datos = dict(linea.split("=", 1) for linea in r.splitlines() if "=" in linea)
    num, den = (int(x) for x in datos["r_frame_rate"].split("/"))
    if num % den:
        raise ValueError(f"fps fraccionarios ({num}/{den}) todavía no están soportados")
    fps = num // den
    duracion = float(datos.get("duration", 0))
    return InfoVideo(
        fps=fps, cuadros=int(duracion * fps), timecode=datos.get("TAG:timecode", "00:00:00:00"),
        ancho=int(datos["width"]), alto=int(datos["height"]), duracion=duracion,
    )


def render_en_curso() -> bool:
    """¿Resolve (u otro programa) está usando el codificador de video de la GPU?"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.encoder", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return int(r.stdout.strip().splitlines()[0]) > 0
    except Exception:
        return False


def esperar_render(avisar, maximo_s: int = 3 * 3600) -> None:
    """Regla de la GPU: no transcribir mientras Resolve renderiza. Espera hasta 3 h."""
    inicio = time.time()
    while render_en_curso() and time.time() - inicio < maximo_s:
        avisar("Esperando que termine un render en Resolve")
        time.sleep(30)


@dataclass(frozen=True)
class Palabra:
    texto: str
    inicio: float
    fin: float


@dataclass(frozen=True)
class Segmento:
    inicio: float
    fin: float
    texto: str
    palabras: tuple[Palabra, ...]


class Transcriptor:
    """Carga el modelo al empezar un trabajo y lo libera al terminar (libera la VRAM)."""

    def __init__(self, modelo: str, cache: Path):
        self._nombre, self._cache = modelo, cache
        self._modelo = None

    def __enter__(self) -> "Transcriptor":
        _dll_cuda()
        from faster_whisper import WhisperModel

        self._modelo = WhisperModel(
            self._nombre, device="cuda", compute_type="float16", download_root=str(self._cache),
        )
        return self

    def __exit__(self, *_) -> None:
        self._modelo = None

    def transcribir(self, audio: np.ndarray, vocabulario: str = "") -> list[Segmento]:
        assert self._modelo, "usar dentro de `with Transcriptor(...)`"
        segmentos, _ = self._modelo.transcribe(
            audio, language="es", beam_size=5, word_timestamps=True,
            initial_prompt=vocabulario or None,
        )
        return [
            Segmento(
                round(s.start, 2), round(s.end, 2), s.text.strip(),
                tuple(Palabra(w.word.strip(), round(float(w.start), 2), round(float(w.end), 2)) for w in s.words or []),
            )
            for s in segmentos
        ]
