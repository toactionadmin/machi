"""Prueba de viabilidad del armado preliminar (Fase 5, punto 3): ¿Resolve gratis importa un FCPXML multicámara?

Genera dos archivos con las mismas tres cámaras sincronizadas por audio (desfases medidos con scripts de la prueba):
  A) multicámara (<mc-clip>), B) cámaras apiladas en pistas (clips conectados en carriles).
Uso: python scripts/prueba_armado_fcpxml.py <carpeta de salida>
No toca los originales: solo lee los proxies y escribe los dos .fcpxml.
"""

import sys
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import quoteattr

BASE = Path(r"C:\Users\MyBox Computacion\DaVinci Resolve Media\EP002\Rescatando Motores\Show\EP002\Originales\S08\Proxy")
# Cada cámara: archivo, cuadros por segundo reales (num/den), timecode de inicio, cuadros totales, duración y desfase hacia la referencia (s).
# Desfase: la cámara empieza esos segundos DESPUÉS de la referencia (CamC), medido por correlación de audio.
CAMARAS = [
    {"id": "aC", "nombre": "Cam C", "archivo": "EP002_CamC_S08P01T01.mov", "fps": (24000, 1001), "tc": "04:56:22:04", "df": False, "cuadros": 46284, "desfase": 0.0},
    {"id": "aR", "nombre": "Cam R", "archivo": "EP002_CamR_S08P01T01.mov", "fps": (24000, 1001), "tc": "12:32:03:04", "df": False, "cuadros": 46164, "desfase": 2.687},
    {"id": "aL", "nombre": "Cam L", "archivo": "EP002_CamL_S08P01T01.mov", "fps": (30000, 1001), "tc": "21:07:31;19", "df": True, "cuadros": 57795, "desfase": 0.953},
]
SEC_FPS = (24000, 1001)  # la secuencia
INICIO_S, LARGO_S = 300.0, 180.0  # tramo de la referencia que se arma


def tc_cuadros(tc: str, df: bool, nominal: int) -> int:
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    n = ((h * 60 + m) * 60 + s) * nominal + f
    if df:  # drop frame 29.97: se saltan 2 cuadros por minuto, salvo cada décimo
        minutos = h * 60 + m
        n -= 2 * (minutos - minutos // 10)
    return n


def t(cuadros: int, fps: tuple[int, int]) -> str:
    return f"{cuadros * fps[1]}/{fps[0]}s"


def cuadros_de(seg: float, fps: tuple[int, int]) -> int:
    return round(seg * fps[0] / fps[1])


def preparar() -> list[dict]:
    for c in CAMARAS:
        nominal = round(c["fps"][0] / c["fps"][1])
        c["tc0"] = tc_cuadros(c["tc"], c["df"], nominal)
        c["entra"] = cuadros_de(INICIO_S - c["desfase"], c["fps"])      # cuadro del archivo donde entra
        c["largo"] = cuadros_de(LARGO_S, c["fps"])
        c["start"] = t(c["tc0"] + c["entra"], c["fps"])
        c["dur"] = t(c["largo"], c["fps"])
        c["ruta"] = "file:///" + quote(str(BASE / c["archivo"]).replace("\\", "/"), safe="/:")
    return CAMARAS


def recursos() -> str:
    out = ['    <format id="r1" name="FFVideoFormat1080p2398" frameDuration="1001/24000s" width="1920" height="1080"/>',
           '    <format id="r30" name="FFVideoFormat1080p2997" frameDuration="1001/30000s" width="1920" height="1080"/>']
    for c in CAMARAS:
        fmt = "r1" if c["fps"][0] == 24000 else "r30"
        canales = 2 if c["id"] != "aL" else 1
        out.append(
            f'    <asset id="{c["id"]}" name={quoteattr(c["archivo"])} start="{t(c["tc0"], c["fps"])}" duration="{t(c["cuadros"], c["fps"])}" '
            f'hasVideo="1" hasAudio="1" format="{fmt}" audioSources="1" audioChannels="{canales}" audioRate="48000">\n'
            f'      <media-rep kind="original-media" src={quoteattr(c["ruta"])}/>\n    </asset>')
    return "\n".join(out)


def multicam() -> str:
    largo_seq = cuadros_de(LARGO_S, SEC_FPS)
    angulos = "\n".join(
        f'        <mc-angle name={quoteattr(c["nombre"])} angleID="{c["id"]}">\n'
        f'          <asset-clip ref="{c["id"]}" offset="0s" name={quoteattr(c["archivo"])} start="{c["start"]}" duration="{c["dur"]}" tcFormat="{"DF" if c["df"] else "NDF"}"/>\n'
        f'        </mc-angle>' for c in CAMARAS)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
{recursos()}
    <media id="m1" name="Prueba multicam">
      <multicam format="r1" tcFormat="NDF" tcStart="0s">
{angulos}
      </multicam>
    </media>
  </resources>
  <library>
    <event name="MACHI PRUEBA">
      <project name="Prueba A multicam">
        <sequence format="r1" duration="{t(largo_seq, SEC_FPS)}" tcStart="0s" tcFormat="NDF">
          <spine>
            <mc-clip ref="m1" offset="0s" name="Prueba multicam" duration="{t(largo_seq, SEC_FPS)}">
              <mc-source angleID="aC" srcEnable="all"/>
            </mc-clip>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""


def apiladas() -> str:
    largo_seq = cuadros_de(LARGO_S, SEC_FPS)
    ref, otras = CAMARAS[0], CAMARAS[1:]
    # Los clips conectados llevan el offset en el tiempo local del clip padre: su `start` (el timecode donde entra).
    hijos = "\n".join(
        f'              <asset-clip ref="{c["id"]}" lane="{i}" offset="{ref["start"]}" name={quoteattr(c["archivo"])} start="{c["start"]}" duration="{t(largo_seq, SEC_FPS)}" tcFormat="{"DF" if c["df"] else "NDF"}"/>'
        for i, c in enumerate(otras, 1))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
{recursos()}
  </resources>
  <library>
    <event name="MACHI PRUEBA">
      <project name="Prueba B apiladas">
        <sequence format="r1" duration="{t(largo_seq, SEC_FPS)}" tcStart="0s" tcFormat="NDF">
          <spine>
            <asset-clip ref="{ref["id"]}" offset="0s" name={quoteattr(ref["archivo"])} start="{ref["start"]}" duration="{t(largo_seq, SEC_FPS)}" tcFormat="NDF">
{hijos}
            </asset-clip>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    salida = Path(sys.argv[1])
    salida.mkdir(parents=True, exist_ok=True)
    preparar()
    (salida / "Prueba_A_multicam.fcpxml").write_text(multicam(), encoding="utf-8")
    (salida / "Prueba_B_apiladas.fcpxml").write_text(apiladas(), encoding="utf-8")
    print(f"Listo: {salida}")


if __name__ == "__main__":
    main()
