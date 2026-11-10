# Prueba de viabilidad del armado preliminar (Fase 5, 2026-11-10)

Scripts sueltos (no son parte del servicio) con que se probó sincronizar cámaras por audio y generar un FCPXML multicámara.
Resultados y conclusiones: `skill-hunter/stack/plan-postproduccion.md`, sección «Fase 5».

1. `1_sync_grueso_envolvente.py <referencia> <cámara> ...`: desfase grueso (±15 min) por correlación de la envolvente de energía.
2. `2_sync_fino_onda.py <referencia> <cámara> <pista> <desfase_grueso_s>`: afina a milisegundos con la forma de onda filtrada a la voz y mide la deriva en tres tramos.
3. `3_fcpxml_multicam_y_apiladas.py <carpeta>`: genera dos FCPXML de prueba (multicámara y cámaras apiladas) con las tres cámaras de «Rescatando Motores» EP002 S08.

Se corren con el entorno de Machi (`.venv\Scripts\python`). Un desfase positivo significa que la cámara empezó a grabar esos segundos después de la referencia.
