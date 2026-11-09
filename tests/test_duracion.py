"""Duración de los reels por proyecto (`reels_duracion` en el README) y su efecto en el ajuste de tramos."""
import unittest
from pathlib import Path

from machi import momentos, proyectos
from machi.transcribir import Palabra


def _palabras(total_s: float, paso: float = 0.5) -> list[Palabra]:
    n = int(total_s / paso)
    return [Palabra(texto=f"p{i}", inicio=i * paso, fin=i * paso + 0.4) for i in range(n)]


class LeerDuracion(unittest.TestCase):
    def test_sin_campo_es_30_a_90(self):
        self.assertEqual(proyectos.leer_reels_duracion(None), (30.0, 90.0))

    def test_campo_valido(self):
        self.assertEqual(proyectos.leer_reels_duracion([30, 120]), (30.0, 120.0))

    def test_campo_invalido_vuelve_al_defecto(self):
        for malo in ([120, 30], [30], "30-120", [0, 60], ["a", "b"], 90):
            with self.subTest(malo=malo), self.assertLogs("machi.proyectos", "WARNING"):
                self.assertEqual(proyectos.leer_reels_duracion(malo, "x"), (30.0, 90.0))

    def test_las_javis_tiene_30_a_120(self):
        boveda = Path(__file__).resolve().parents[2] / "skill-hunter"
        if not (boveda / "proyectos").exists():
            self.skipTest("no está skill-hunter junto a machi")
        cargados = proyectos.cargar(boveda)
        self.assertEqual(cargados["lasjavis"].reels_duracion, (30.0, 120.0))
        otros = {c: p.reels_duracion for c, p in cargados.items() if c != "lasjavis"}
        self.assertTrue(all(d == (30.0, 90.0) for d in otros.values()), otros)


class AjustarConRango(unittest.TestCase):
    def test_un_tramo_de_110_s_pasa_con_120_y_se_recorta_con_90(self):
        palabras = _palabras(300)
        con_120 = momentos.ajustar(10, 120, palabras, 300, 30, 120)
        self.assertIsNotNone(con_120)
        self.assertLessEqual(con_120[1] - con_120[0], 120)
        self.assertGreater(con_120[1] - con_120[0], 90)
        con_90 = momentos.ajustar(10, 120, palabras, 300, 30, 90)
        self.assertIsNotNone(con_90)
        self.assertLessEqual(con_90[1] - con_90[0], 90)

    def test_defecto_sigue_siendo_30_a_90(self):
        palabras = _palabras(300)
        self.assertIsNone(momentos.ajustar(10, 35, palabras, 300))  # 25 s: muy corto
        self.assertIsNotNone(momentos.ajustar(10, 50, palabras, 300))


if __name__ == "__main__":
    unittest.main()
