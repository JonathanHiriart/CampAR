# Automatización en n8n — CampAR (Producto 1 y Producto 2)

Esta carpeta contiene los flujos listos para importar en **n8n** que orquestan los Actores de Apify, Google Drive y Google Sheets sin pasos manuales.

---

## 1. Flujo Producto 1 ([`n8n_producto1_terrascout.json`](./n8n_producto1_terrascout.json))

**Secuencia:** `Trigger -> Config -> 0. Limpiar Sheet -> 1. APIFY ETL -> 2. DRIVE Dataset Limpio -> 3. APIFY EDA -> 4. Google Sheets Dashboard`

1. En **n8n**, hacé clic en **Import from file** y seleccioná [`workflows/n8n_producto1_terrascout.json`](./n8n_producto1_terrascout.json).
2. Abrí el nodo **`Config`** y completá:
   * `apify_token`: tu token personal de Apify (nunca subirlo a Git).
   * `raw_workbook_url`: link público de Google Sheets/Drive con [`data/raw/dataset_raw_consolidado.xlsx`](../data/raw/dataset_raw_consolidado.xlsx) *(o dejalo vacío para usar el fallback embebido en el actor)*.
   * `folder_limpio_id`: ID de la carpeta de Google Drive donde se guarda `dataset_limpio.csv`.
   * `google_sheet_id` y `google_sheet_tab`: ID del Google Sheet conectado a Looker Studio.
3. Vinculá tus credenciales de Google Drive y Google Sheets en los nodos `0`, `2` y `4` y apretá **Execute workflow**.

---

## 2. Flujo Producto 2 ([`n8n_producto2_terrascout.json`](./n8n_producto2_terrascout.json))

**Secuencia:** `Trigger (Manual / Schedule) -> Config -> 0. Limpiar Sheet ML -> 1. APIFY ETL -> 2. DRIVE Dataset Limpio -> 3. APIFY ML (Producto 2) -> 4. Google Sheets Oportunidades ML`

1. Desplegá el Actor 3 en Apify Cloud desde la raíz del repo:
   ```bash
   cd actors/apify_ml && apify push
   ```
2. Importá [`workflows/n8n_producto2_terrascout.json`](./n8n_producto2_terrascout.json) en **n8n**.
3. En el nodo **`Config`**, completá:
   * `apify_token`: tu token de Apify.
   * `apify_ml_actor_id`: el ID devuelto por Apify al desplegar `terrascout-ml-actor` (ya desplegado en Apify Cloud como `9bGh3PnH5lMWm3cjc`).
   * `model_pkl_url`: pegá la URL pública de `models/terrascout_pipeline.pkl` (el modelo pre-entrenado con `src/training.py`) para que el Actor 3 ejecute únicamente inferencia en la nube.
   * `google_sheet_id` y `google_sheet_tab` (por defecto `Oportunidades_ML`).
4. *(Opcional — Alerta Telegram/Email)*: agregá un nodo **Telegram** o **Gmail** al final leyendo el campo `resumen_telegram` publicado en `metricas_producto2.json` del Key-Value Store del Actor 3.

---

## 3. Flujo Unificado para Demo ([`n8n_terrascout_completo.json`](./n8n_terrascout_completo.json))

Ejecuta **ambos productos en una sola corrida** (ideal para la demo técnica de 2 minutos y medir el costo total de punta a punta), reutilizando un único run de `APIFY ETL` y bifurcando en paralelo:

```text
Trigger -> Config -> 1. APIFY ETL -> 2. DRIVE Dataset Limpio
                                          ├─► 3A. Limpiar Sheet Dashboard -> 4A. APIFY EDA (P1) -> 5A. Google Sheets Dashboard
                                          └─► 3B. Limpiar Sheet ML        -> 4B. APIFY ML (P2)  -> 5B. Google Sheets Oportunidades ML
```

1. Importá [`workflows/n8n_terrascout_completo.json`](./n8n_terrascout_completo.json) en **n8n** *(los dos flujos individuales siguen disponibles arriba por separado)*.
2. Completá en **`Config`**: `apify_token`, `raw_workbook_url`, `folder_limpio_id`, `apify_ml_actor_id`, `model_pkl_url`, `google_sheet_id`, `sheet_tab_p1` (`Datos`) y `sheet_tab_p2` (`Oportunidades_ML`).
3. **Costo estimado por corrida unificada (3 Actores en Apify a 1 GB / `~10 s` c/u):** `~0.0085 CU` ≈ **`USD 0.0025`** por ejecución completa.

> Para el detalle completo de conexiones Apify/Make/n8n y el armado del tablero visual, ver [`docs/flujo_make_n8n_producto1.md`](../docs/flujo_make_n8n_producto1.md) y [`docs/guia_looker_studio_producto1.md`](../docs/guia_looker_studio_producto1.md).
