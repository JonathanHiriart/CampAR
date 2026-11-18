# TerraScout & EcoCamp AI — Capstone Project (Samsung Innovation Campus 2026)

> **Inteligencia Geoespacial y Radar de Oportunidades para Tierras Turísticas (Campings / Glampings) en las Sierras de Córdoba.**

---

## 1. La Idea del Proyecto

En los valles de **Punilla y Calamuchita (Córdoba)**, evaluar dónde comprar o comercializar terrenos para proyectos turísticos de camping/glamping suele hacerse de manera manual e imprecisa: hay avisos duplicados, precios mezclados en pesos y dólares, zonas con pendientes extremas o riesgo ambiental, y poca visibilidad sobre qué reclaman hoy los turistas en los campings vecinos.

**TerraScout AI** resuelve esa pregunta de negocio en dos entregas:
* **Pregunta central (Producto 1):** *¿Dónde y qué terrenos en Punilla y Calamuchita conviene comprar o intermediar hoy para campings/glampings, combinando precio por m² subvaluado (`≥ 20%` bajo la mediana de su zona), aptitud topográfica/ambiental y demanda turística insatisfecha?*
* **Qué tenemos armado hoy (Producto 1):**
  * Base real sin datos sintéticos (`1.200` avisos crudos → **`894` terrenos únicos validados**, **`244` oportunidades detectadas**).
  * Cruce geográfico real con `288` campings, `237` perfiles y `1.754` reseñas de Google Maps, más topografía/riesgo ambiental de `16` localidades.
  * **Dos Actores productivos en Apify Cloud (`APIFY ETL` y `APIFY EDA`)** conectados automáticamente mediante **n8n → Google Drive** hasta dejar listo el archivo multi-hoja para graficar.
* **Qué queda para cerrar y avanzar a Producto 2:**
  * Conectar el archivo final `contenido_graficas_dashboard.xlsx` (`hoja1`, `hoja2`, `hoja3`) en **Looker Studio** para armar el tablero visual.
  * Entrenar el modelo predictivo de valuación hedónica sobre `log(precio_m2_usd)` (Producto 2) y automatizar el refresco periódico de datos nuevos.

> Si querés leer la explicación completa en lenguaje simple (el plan seguido y qué resuelve cada archivo para perfiles no técnicos), revisá [**Documentación Completa del Proyecto**](./docs/DOCUMENTACION_COMPLETA.md).

---

## 2. Cómo Usar Todo

### Opción A — Flujo automático en la nube (n8n + Apify + Google Drive)
1. **Datos de entrada (1 solo archivo):** subí [`data/raw/dataset_raw_consolidado.xlsx`](./data/raw/dataset_raw_consolidado.xlsx) a Google Drive (o abrilo con Google Sheets) y compartilo como *Cualquiera con el enlace → Lector*.
2. **Importar el flujo:** en **n8n**, importá [`workflows/n8n_producto1_terrascout.json`](./workflows/n8n_producto1_terrascout.json).
3. **Configurar:** en el nodo `Config`, completá tu `apify_token`, el link de entrada `raw_workbook_url` (o dejalo vacío para usar el fallback embebido) y los IDs de tus carpetas de Drive; vinculá tu credencial de Google Drive en los nodos `2` y `4` (recomendado usar `Operation: Update` tras la primera subida para conservar siempre el mismo `File ID` hacia Looker Studio).
4. **Ejecutar:** apretá *Execute workflow* y n8n corre el pipeline completo (`ETL → Drive Limpio → EDA → Drive Dashboard`). Ver detalle técnico en [**Guía Make / n8n**](./docs/flujo_make_n8n_producto1.md) y paso a paso de vistas en [**Guía Looker Studio**](./docs/guia_looker_studio_producto1.md).

### Opción B — Ejecución y pruebas en local (Python)

```bash
# 1. Crear archivo de entorno local (sin subir credenciales a Git)
cp .env.example .env

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Correr el pipeline completo Producto 1 (ETL -> dataset_limpio.csv -> EDA -> Dashboard CSVs/XLSX)
python3 src/run_producto1_pipeline.py

# 4. Ejecutar toda la suite de verificación (33 tests)
PYTHONPATH=terrascout_actor python3 -m pytest tests/test_scraper_node.py tests/test_producto1_actors.py -v

# 5. (Opcional) Re-ejecutar extracción en vivo hacia data/raw/
PYTHONPATH=terrascout_actor python3 src/run_scraper_node.py --max-items-per-valley 600 --max-pages-per-valley 15
```

---

## 3. Apartado Técnico y Estructura del Repositorio

### Arquitectura Técnica (Producto 1)
1. **Reglas desacopladas (`config/business_rules.json`):** tipo de cambio ARS/USD (`1280.0`), rango de superficie (`500–20.000 m²`), pendiente alerta (`12°`), umbral de oportunidad (`20%` bajo mediana zonal), exclusión de riesgo `ALTO` y vocabulario de infraestructura.
2. **Actor 1 — `terrascout-etl-actor` (`ypvpGbmD1vpqraNXA`, Python 3.14 en Apify):**
   * Soporta ingesta desde **1 único libro Google Sheets / `.xlsx`** (`raw_workbook_url`) o URLs individuales de Google Drive (`#gid=` incluido) con fallback local embebido (`fallback_data/`).
   * Normalización monetaria, regex defensiva de superficie (evita capturar distancias al río), IQR conservador en `precio_m2_usd`, deduplicación por ID + coordenada redondeada (`1.200 → 894` filas, `74.5%` retención) y **JOIN espacial vectorizado Haversine** (topografía, densidad de campings a `5 km`, NPS proxy ponderado por reseñas).
3. **Actor 2 — `terrascout-eda-actor` (`YZH8ti7zjLt6410Hx`, Python 3.14 en Apify):**
   * Calcula estadísticas zonales con coordenadas GPS, correlaciones lineales y no lineales (**Pearson, Spearman, Kendall e Información Mutua**), validación de asimetría (`skew = 2.214 → -0.40` con `log(precio_m2_usd)`), cruce `valle × riesgo` y síntesis de `1.754` reseñas/tópicos NLP.
   * Exporta `csv_1_localidades_y_riesgo.csv` (`hoja1`), `csv_2_correlaciones_y_distribuciones.csv` (`hoja2`), `csv_3_oportunidades_y_voz_turista.csv` (`hoja3`) y `contenido_graficas_dashboard.xlsx`, más URLs públicas firmadas en `etl_funnel.json` y `eda_summary.json` (y soporte directo `/run-sync?outputRecordKey=...` para n8n).

### Estructura de Carpetas

```text
Capstone/
├── README.md                              # Visión general, uso rápido y arquitectura
├── config/
│   └── business_rules.json                # Reglas y umbrales desacoplados
├── actors/
│   ├── apify_etl/                         # Actor 1: APIFY ETL (limpieza + Haversine + fallback)
│   └── apify_eda/                         # Actor 2: APIFY EDA (correlaciones + CSVs + XLSX)
├── terrascout_actor/                      # Scraper Apify original (ML, OSM, SoloCampings, GMaps, NLP)
├── workflows/
│   └── n8n_producto1_terrascout.json      # Workflow n8n de 6 nodos listo para importar
├── data/
│   ├── aux_topografia_cordoba.csv         # Relieve, NDVI y riesgo de 16 localidades
│   ├── raw/                               # Fuentes reales + dataset_raw_consolidado.xlsx (7 pestañas)
│   └── processed/                         # dataset_limpio.csv + dashboard/{csv_1,csv_2,csv_3,.xlsx}
├── src/
│   ├── run_producto1_pipeline.py          # Ejecutor local del pipeline ETL + EDA
│   └── run_scraper_node.py                # CLI de extracción en vivo hacia data/raw/
├── tests/
│   ├── test_producto1_actors.py           # Tests ETL, EDA, XLSX y cero np.random
│   └── test_scraper_node.py               # Tests unitarios de scrapers y datos reales
└── docs/
    ├── DOCUMENTACION_COMPLETA.md          # Explicación no técnica de plan y archivos
    ├── guia_looker_studio_producto1.md    # Guía paso a paso del tablero en Looker Studio
    ├── flujo_make_n8n_producto1.md        # Guía Make / n8n + conexión Apify
    ├── diagrama_flujo_producto1.png       # Diagrama de referencia de la cátedra
    └── planificacion/                     # Propuesta base, marco satelital y guías de producto
```
