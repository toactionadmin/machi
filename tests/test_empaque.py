"""Empaque de YouTube: capítulos, descripción, ficha del proyecto y el trabajo completo con piezas simuladas."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from machi import empaque, episodios, proyectos
from machi.pipeline import Empaque
from machi.trabajo import Costo, Trabajo


def _caps(*pares):
    return [{"inicio": t, "titulo": x} for t, x in pares]


class Capitulos(unittest.TestCase):
    def test_el_primero_siempre_en_cero_y_en_orden(self):
        r = empaque.limpiar_capitulos(_caps((95, "Segundo"), (3, "Intro"), (200, "Tercero")), 600)
        self.assertEqual(r, [(0.0, "Intro"), (95.0, "Segundo"), (200.0, "Tercero")])

    def test_descarta_los_muy_juntos_y_los_del_final(self):
        r = empaque.limpiar_capitulos(_caps((0, "A"), (10, "B"), (60, "C"), (130, "D"), (595, "E")), 600)
        self.assertEqual([x[1] for x in r], ["A", "C", "D"])  # B a 10 s de A; E a 5 s del final

    def test_con_menos_de_tres_no_hay_capitulos(self):
        self.assertEqual(empaque.limpiar_capitulos(_caps((0, "A"), (100, "B")), 600), [])

    def test_ignora_titulos_vacios_y_tiempos_fuera_de_rango(self):
        r = empaque.limpiar_capitulos(_caps((0, "A"), (50, " "), (100, "B"), (200, "D"), (9999, "C")), 600)
        self.assertEqual([x[1] for x in r], ["A", "B", "D"])  # el vacío se ignora; C se recorta a 600 s, a menos de 10 s del final

    def test_formato_de_tiempo(self):
        self.assertEqual(empaque.tiempo(185, 600), "3:05")
        self.assertEqual(empaque.tiempo(3725, 4000), "1:02:05")
        self.assertEqual(empaque.texto_capitulos([(0, "Intro"), (185, "Tema")], 600), "0:00 Intro\n3:05 Tema")


class Descripcion(unittest.TestCase):
    def test_ensambla_en_orden_y_omite_lo_vacio(self):
        d = empaque.ensamblar("Resumen.", "0:00 Intro", "Síguenos: x", ["#a", "#b"])
        self.assertEqual(d, "Resumen.\n\n0:00 Intro\n\nSíguenos: x\n\n#a #b")
        self.assertEqual(empaque.ensamblar("Resumen.", "", "", []), "Resumen.")

    def test_armar_avisa_titulos_largos_y_pocos(self):
        datos = {"titulos": ["x" * 80, "corto"], "resumen": " r ", "capitulos": [], "hashtags": ["a", "#b", "#c", "#d"]}
        p = empaque.armar(datos, 600, Costo())
        self.assertEqual(p.hashtags, ["#a", "#b", "#c"])
        self.assertEqual(len(p.avisos), 3)  # 2 títulos en vez de 3, uno de 80 caracteres, sin capítulos
        self.assertEqual(p.resumen, "r")


class FichaYoutube(unittest.TestCase):
    def _proyecto(self, carpeta: Path) -> proyectos.Proyecto:
        return proyectos.Proyecto(comando="x", nombre="X", drive="X", carpeta=carpeta)

    def test_sin_ficha(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self._proyecto(Path(d)).youtube(), ("", ""))

    def test_con_ficha_lee_guia_y_pie(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "youtube.md").write_text('---\npie: |\n  Redes: a\n  Crédito: b\n---\n\n# Ficha\n\nTítulos cortos.\n', encoding="utf-8")
            guia, pie = self._proyecto(Path(d)).youtube()
        self.assertTrue(guia.startswith("# Ficha"))
        self.assertEqual(pie, "Redes: a\nCrédito: b")

    def test_las_javis_real(self):
        boveda = Path(__file__).resolve().parents[2] / "skill-hunter"
        if not (boveda / "proyectos").exists():
            self.skipTest("no está skill-hunter junto a machi")
        guia, pie = proyectos.cargar(boveda)["lasjavis"].youtube()
        self.assertIn("Títulos", guia)
        self.assertEqual(pie, "")
        self.assertTrue((boveda / empaque.REGLAS).exists())


class Columnas(unittest.TestCase):
    def test_la_fila_trae_tres_titulos_aunque_falten(self):
        f = episodios.FilaEpisodio("X · EP1", "X", ["uno"], "d", "c", "", "id", "j")
        props = f.propiedades()
        self.assertEqual(props["Título 1"]["rich_text"][0]["text"]["content"], "uno")
        self.assertEqual(props["Título 3"]["rich_text"], [])
        self.assertNotIn("Título elegido", props)  # del equipo: nunca se escribe
        self.assertNotIn("Estado", props)


class _Notion:
    def __init__(self, existente=None):
        self.existente, self.guardado = existente, None

    def buscar(self, nombre):
        return self.existente

    def guardar(self, fila, pagina_id=None):
        self.guardado = (fila, pagina_id)
        return "https://notion/fila"

    def url(self):
        return "https://notion/base"


class _Empacador:
    def proponer(self, proyecto, codigo, segmentos, duracion, enfoque):
        return empaque.Paquete(["T1", "T2", "T3"], "Resumen.", [(0.0, "Intro"), (100.0, "A"), (200.0, "B")],
                               [], Costo(usd=0.1), [])


class Flujo(unittest.TestCase):
    def _trabajo(self, **par):
        return Trabajo(id="trb_1", tipo="empaque", servicio="machi", parametros={"proyecto": "x", **par},
                       solicitante={"canal": "api", "nombre": "prueba"})

    def _empaque(self, existente=None):
        e = Empaque.__new__(Empaque)
        e.cfg = SimpleNamespace(claude_modelo="m")
        e._guardar, e._cancelado = (lambda t: None), (lambda i: False)
        e.episodios, e.empacador = _Notion(existente), _Empacador()
        e._transcripcion = lambda t, ep, voc: (SimpleNamespace(duracion=600.0), [])
        return e

    def _args(self, pie=""):
        proyecto = SimpleNamespace(nombre="Las Javis", comando="lasjavis", vocabulario=[], youtube=lambda: ("guía", pie))
        ep = SimpleNamespace(nombre="EP20261003", video=SimpleNamespace(id="v1", link="https://drive/v"))
        return proyecto, ep

    def test_arma_la_fila_con_descripcion_lista_para_pegar(self):
        e, (proyecto, ep) = self._empaque(), self._args("Redes: x")
        t = self._trabajo()
        e._episodio(t, proyecto, ep, False)
        fila, pagina = e.episodios.guardado
        self.assertIsNone(pagina)
        self.assertEqual(fila.episodio, "Las Javis · EP20261003")
        self.assertEqual(fila.titulos, ["T1", "T2", "T3"])
        self.assertEqual(fila.descripcion, "Resumen.\n\n0:00 Intro\n1:40 A\n3:20 B\n\nRedes: x")
        self.assertEqual(fila.capitulos, "0:00 Intro\n1:40 A\n3:20 B")
        self.assertEqual(t.resultado.costo.usd, 0.1)

    def test_avisa_si_falta_el_pie(self):
        e, (proyecto, ep) = self._empaque(), self._args("")
        t = self._trabajo()
        e._episodio(t, proyecto, ep, False)
        self.assertIn("falta `pie`", t.resultado.resumen)

    def test_si_ya_existe_no_lo_rehace_y_avisa_si_cambio_el_proxy(self):
        e = self._empaque(episodios.FilaExistente(id="p1", estado="Propuesto", drive_id="otro", elegido=""))
        proyecto, ep = self._args()
        t = self._trabajo()
        e._episodio(t, proyecto, ep, False)
        self.assertIsNone(e.episodios.guardado)
        self.assertIn("ya tiene empaque", t.resultado.resumen)
        self.assertIn("proxy", t.resultado.resumen)

    def test_rehacer_actualiza_la_misma_fila(self):
        e = self._empaque(episodios.FilaExistente(id="p1", estado="Aprobado", drive_id="v1", elegido="T2"))
        proyecto, ep = self._args("x")
        t = self._trabajo(rehacer=True)
        e._episodio(t, proyecto, ep, False)
        self.assertEqual(e.episodios.guardado[1], "p1")
        self.assertIn("Aprobado", t.resultado.resumen)


if __name__ == "__main__":
    unittest.main()
