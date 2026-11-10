"""Captions de cada reel: reglas compartidas de skill-hunter, columnas de Notion y fallos que no tumban el trabajo."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from machi import captions
from machi.notion import Fila
from machi.pipeline import Reels


def _fila(**kw) -> Fila:
    base = dict(reel="EP1_Reel001", proyecto="X", episodio="EP1", orden=1, inicio=0, fin=40, gancho="g", porque="p",
                texto="t", categoria="c", criterios="k", archivo="", link_episodio="", drive_id="d", trabajo="j")
    return Fila(**{**base, **kw})


class Reglas(unittest.TestCase):
    def test_quita_el_comentario_y_deja_los_marcadores(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / captions.REGLAS
            ruta.parent.mkdir(parents=True)
            ruta.write_text("<!--\nnota\n-->\nEres redactor.\n{nombre}\n{fichas}\n", encoding="utf-8")
            texto = captions.leer_reglas(Path(d))
        self.assertNotIn("nota", texto)
        self.assertTrue(texto.startswith("Eres redactor."))
        self.assertIn("{fichas}", texto)

    def test_sin_archivo_es_un_error_claro(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(captions.ErrorCaption):
            captions.leer_reglas(Path(d))

    def test_las_reglas_reales_de_skill_hunter(self):
        boveda = Path(__file__).resolve().parents[2] / "skill-hunter"
        if not (boveda / captions.REGLAS).exists():
            self.skipTest("no está skill-hunter junto a machi")
        texto = captions.leer_reglas(boveda)
        self.assertIn("{nombre}", texto)
        self.assertIn("{fichas}", texto)
        self.assertNotIn("<!--", texto)


class Columnas(unittest.TestCase):
    def test_sin_caption_no_toca_las_columnas(self):
        props = _fila().propiedades()
        self.assertNotIn("Caption", props)
        self.assertNotIn("Hashtags", props)

    def test_con_caption_las_escribe(self):
        props = _fila(caption="Hola", hashtags="#a #b").propiedades()
        self.assertEqual(props["Caption"]["rich_text"][0]["text"]["content"], "Hola")
        self.assertEqual(props["Hashtags"]["rich_text"][0]["text"]["content"], "#a #b")


class _RedactorQueFalla:
    def escribir(self, *a):
        raise captions.ErrorCaption("La API de Claude respondió 529")


class _RedactorSinContenido:
    def escribir(self, *a):
        return captions.Caption("", [], True, captions.Costo())


class Fallos(unittest.TestCase):
    def _reels(self, redactor):
        r = Reels.__new__(Reels)
        r.redactor = redactor
        return r

    def test_un_caption_que_falla_se_avisa_y_no_tumba(self):
        avisos: list[str] = []
        with self.assertLogs("machi.pipeline", "WARNING"):
            c = self._reels(_RedactorQueFalla())._caption(SimpleNamespace(), "EP1_Reel001", "g", "t", avisos)
        self.assertIsNone(c)
        self.assertEqual(len(avisos), 1)
        self.assertIn("EP1_Reel001", avisos[0])

    def test_sin_contenido_se_avisa(self):
        avisos: list[str] = []
        c = self._reels(_RedactorSinContenido())._caption(SimpleNamespace(), "EP1_Reel002", "g", "t", avisos)
        self.assertTrue(c.sin_contenido)
        self.assertIn("sin contenido", avisos[0])

    def test_proyecto_sin_fichas_se_avisa(self):
        proyecto = SimpleNamespace(nombre="Loft", fichas=lambda: "")
        partes = self._reels(None)._avisos_resultado(proyecto, [])
        self.assertIn("Loft no tiene fichas de marca", partes[0])


if __name__ == "__main__":
    unittest.main()
