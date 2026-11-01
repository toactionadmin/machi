"""Líneas de tiempo FCPXML 1.10 para DaVinci Resolve (gratis): un reel vertical por archivo.

Probado en el Paso 0 (plan-machi): Resolve importa varios archivos de una vez y los
engancha al clip que ya está en el Media Pool cuando coinciden el nombre del archivo
y el timecode. Por eso el asset lleva el nombre exacto del .mp4 de Drive; su ruta no
importa (apunta a una carpeta que no existe y Resolve usa el clip del Media Pool).
"""

from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

ANCHO, ALTO = 1080, 1920


def cuadros_timecode(timecode: str, fps: int) -> int:
    """'01:00:00:00' → cuadros. Acepta ';' (drop frame) como separador, sin corregirlo."""
    h, m, s, c = (int(x) for x in timecode.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * fps + c


def reel(nombre_linea: str, clip: str, fps: int, cuadros_clip: int, timecode: str,
         inicio_s: float, fin_s: float, ancho_clip: int = 1920, alto_clip: int = 1080) -> str:
    """FCPXML de un reel vertical 1080×1920 con recorte centrado (la imagen llena el cuadro)."""

    def t(cuadros: int) -> str:
        return f"{cuadros}/{fps}s"

    tc = cuadros_timecode(timecode, fps)
    a, b = round(inicio_s * fps), round(fin_s * fps)
    largo = b - a
    src = "file:///C:/MACHI_RECONECTAR/" + quote(clip)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    <format id="r1" name="FFVideoFormat{alto_clip}p{fps}" frameDuration="1/{fps}s" width="{ancho_clip}" height="{alto_clip}"/>
    <format id="r2" name="FFVideoFormatVertical{ANCHO}x{ALTO}p{fps}" frameDuration="1/{fps}s" width="{ANCHO}" height="{ALTO}"/>
    <asset id="a1" name={quoteattr(clip)} start="{t(tc)}" duration="{t(cuadros_clip)}" hasVideo="1" hasAudio="1" format="r1" audioSources="1" audioChannels="2" audioRate="48000">
      <media-rep kind="original-media" src={quoteattr(src)}/>
    </asset>
  </resources>
  <library>
    <event name="MACHI">
      <project name={quoteattr(nombre_linea)}>
        <sequence format="r2" duration="{t(largo)}" tcStart="0s" tcFormat="NDF">
          <spine>
            <asset-clip ref="a1" name={quoteattr(clip)} offset="0s" start="{t(tc + a)}" duration="{t(largo)}" tcFormat="NDF"><adjust-conform type="fill"/></asset-clip>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
<!-- {escape(nombre_linea)} · generado por machi -->
"""
