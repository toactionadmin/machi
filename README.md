# machi

Servicio de **toAction** que propone reels a partir de un episodio largo (podcast, show) y los deja listos para importar en DaVinci Resolve.

El nombre viene de *Hunter x Hunter*: Machi cose con hilos de Nen; corta y vuelve a unir. Corre en **Tenku**, el PC de edición (Windows 11, RTX 4090). Diseño y decisiones en skill-hunter: `stack/plan-machi.md`.

## Flujo

1. En Telegram: `/lasjavis_reels EP20261031` (opcional: `"momentos de humor"`, `--rehacer`). Sin episodio, solo lista los episodios y cuáles ya tienen reels.
2. Machi lee de Drive `MESA DE TRABAJO/<Proyecto>/MULTIMEDIA/SHOWS/<episodio>/SHOW/Originales/Proxy/` (un solo `.mp4`).
3. Transcribe con faster-whisper `large-v3` en la GPU (~1 min por episodio).
4. Claude clasifica el episodio, escribe los criterios y elige hasta 15 reels de 30 a 90 s (o el rango `reels_duracion: [mín, máx]` del README del proyecto; Las Javis: 30 a 120 s), con las fichas de `proyectos/<proyecto>/marca/`.
5. Deja un FCPXML vertical 1080×1920 por reel en `…/Originales/Timelines/` (`EP20261031_Reel001.fcpxml`; la línea en Resolve se llama igual).
6. Cada reel queda como fila en la base **«Reels propuestos»** de Notion, en estado *Propuesto*.

En Resolve: con el `.mp4` del episodio en el Media Pool, *Archivo → Importar → Línea de tiempo…* y seleccionar todos los FCPXML de `Timelines/` de una vez. Se enganchan al clip sin reconectar.

## Estructura

| Archivo | Qué hace |
|---|---|
| `api.py`, `cola.py`, `trabajo.py` | API común del stack (`/salud`, `/capacidades`, `/trabajos`), cola SQLite y formato de trabajo (igual que nostrade) |
| `pipeline.py` | El trabajo `reels` y sus etapas: `drive`, `transcripcion`, `momentos`, `lineas`, `notion` |
| `drive.py` | Drive con escritura limitada: solo lee `Proxy/` y solo escribe `EP…_ReelNNN.fcpxml` en `Timelines/` |
| `transcribir.py` | ffmpeg, ffprobe y faster-whisper en CUDA, con tiempos por palabra |
| `momentos.py` | Claude elige los reels; machi los ajusta a bordes de palabras y al rango de duración del proyecto (`reels_duracion`, por defecto 30 a 90 s) |
| `fcpxml.py` | FCPXML 1.10 de cada reel |
| `notion.py` | Base «Reels propuestos» (nunca toca «Notas del editor») |

## Desarrollo en Tenku

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\machi --env <archivo .env de desarrollo>
```

Configuración: ver `.env.example`. En producción, `C:\ProgramData\toaction\machi.env`.
