"""Configuración de machi, leída de variables de entorno.

En producción el servicio las carga desde C:\\ProgramData\\toaction\\machi.env.
En desarrollo: `machi --env <archivo>` con un .env propio.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _req(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise RuntimeError(f"Falta la variable de entorno {nombre}")
    return valor


def _opt(nombre: str, defecto: str) -> str:
    return os.environ.get(nombre, "").strip() or defecto


def cargar_env(ruta: Path) -> None:
    """Lee un archivo KEY=valor (como systemd EnvironmentFile). No pisa variables ya definidas."""
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip("'\""))


@dataclass(frozen=True)
class Config:
    # API interna
    host: str
    puerto: int
    token: str
    datos: Path  # base de datos de trabajos, modelos y archivos temporales

    # Google Drive
    google_sa: Path
    drive_disco: str

    # skill-hunter
    skill_hunter: Path

    # Whisper y ffmpeg
    whisper_modelo: str
    ffmpeg: str

    # Claude
    anthropic_key: str
    claude_modelo: str
    claude_esfuerzo: str
    claude_esfuerzo_captions: str

    # Notion
    notion_token: str
    notion_db: str

    version: str = field(default="0.1.0")

    @classmethod
    def desde_entorno(cls) -> "Config":
        return cls(
            host=_opt("MACHI_HOST", "0.0.0.0"),
            puerto=int(_opt("MACHI_PUERTO", "8706")),
            token=_req("MACHI_TOKEN"),
            datos=Path(_opt("MACHI_DATOS", r"C:\ProgramData\toaction\machi")),
            google_sa=Path(_req("GOOGLE_SA_FILE")),
            drive_disco=_opt("DRIVE_DISCO", "MESA DE TRABAJO"),
            skill_hunter=Path(_req("SKILL_HUNTER_DIR")),
            whisper_modelo=_opt("WHISPER_MODELO", "large-v3"),
            ffmpeg=_opt("FFMPEG", "ffmpeg"),
            anthropic_key=_req("ANTHROPIC_API_KEY"),
            claude_modelo=_opt("CLAUDE_MODELO", "claude-opus-5-5"),
            claude_esfuerzo=_opt("CLAUDE_ESFUERZO", "high"),
            claude_esfuerzo_captions=_opt("CLAUDE_ESFUERZO_CAPTIONS", "medium"),
            notion_token=_req("NOTION_TOKEN"),
            notion_db=_req("NOTION_DB_ID"),
        )
