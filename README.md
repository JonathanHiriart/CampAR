# TerraScout & EcoCamp AI — Capstone Project (Samsung Innovation Campus 2026)

> **Motor de Inteligencia Geoespacial, Valuación Hedónica y Mitigación de Riesgo Ambiental para Inversiones Inmobiliarias y Turísticas en Sierras de Córdoba**

---

## Documentación Principal del Proyecto

1. [**Plan Maestro de Cierre e Implementación del Producto 1**](./Plan%20implementar/plan_implementacion_producto_1_terrascout_ai.md)
   * Checklist de definiciones críticas antes de programar.
   * Integración de `httpx`, `BeautifulSoup`, `re`, `RapidFuzz` (`fuzzy_count`) y `scikit-learn` (`TfidfVectorizer` + `KMeans` + `silhouette_score`).
   * División de tareas por rol: **Software / Solution Engineer (SE)**, **Data Analyst / Data Scientist (DS)** y **Business Analyst (BIZ)**.
2. [**Propuesta Maestra Formalizada**](./Ideas/propuesta_terrascout_ai_georadar_inmobiliario_turistico.md)
   * Caso de negocio (**Diana**), presupuesto (**USD 1.850** one-off + **USD 65/mes**) y **ROI Neto Año 1 (+411%, Payback 2,34 meses)**.
   * Diccionario de datos de las **11–12 variables maestras** (2 fuentes y 2 fenómenos en corte transversal espacial).
3. [**Marco Metodológico Satelital sin Series Temporales**](./Ideas/proyecto_satelital_sin_series_temporales.md)
   * Fundamento técnico del corte transversal con datos NASA (SRTM 30m, MODIS/VIIRS NDVI) e IGN (Red Hídrica y Rutas).

---

## Nodo de Extracción Real (Producto 1 — Cero Datos Dummy)

* **`terrascout_actor/`**: Actor de Apify adaptado del estándar de la cátedra:
  * [`my_actor/ml_scraper.py`](./terrascout_actor/my_actor/ml_scraper.py): Scraper paginado en vivo de **Mercado Libre Inmuebles** para Valle de Calamuchita y Valle de Punilla.
  * [`my_actor/camping_scraper.py`](./terrascout_actor/my_actor/camping_scraper.py): Extractor en vivo de campings reales desde **OpenStreetMap Overpass API** + **SoloCampings Córdoba** y conector opcional a Google Maps vía Apify (`compass/crawler-google-places`).
  * [`my_actor/main.py`](./terrascout_actor/my_actor/main.py): Normalización de texto, `SentenceIndex`, `fuzzy_count`, `find_topics` (`TF-IDF + KMeans`) y extracción de superficie (`re`).
* **`src/run_scraper_node.py`**: Ejecutor CLI del pipeline completo que guarda los datos reales en `data/raw/`.
* **`config/business_rules.json`**: Reglas de negocio y parámetros desacoplados del código Python (cumplimiento Auditoría Samsung 17/11).
* **`data/`**:
  * [`data/aux_topografia_cordoba.csv`](./data/aux_topografia_cordoba.csv): Métricas satelitales y cartográficas precalculadas por localidad (16 localidades).
  * `data/raw/mercadolibre_terrenos_calamuchita_punilla_raw.csv`: 1.200 publicaciones reales de terrenos (600 Calamuchita + 600 Punilla).
  * `data/raw/campings_zona_real_raw.csv`: 296 campings reales georreferenciados en la zona.
  * `data/raw/topicos_nlp_real_raw.json`: Clusters TF-IDF + KMeans y menciones de servicios reales.

---

## Configuración Segura y Ejecución Local

> **Importante**: Nunca subas archivos `.env`, tokens ni credenciales reales al repositorio.

```bash
# 1. Configurar variables de entorno locales a partir de la plantilla
cp .env.example .env
# (Opcional) Completar APIFY_TOKEN en .env para habilitar reseñas de Google Maps vía Apify

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar extracción real (Mercado Libre + Campings + NLP)
PYTHONPATH=terrascout_actor python3 src/run_scraper_node.py --max-items-per-valley 600 --max-pages-per-valley 15

# 4. Ejecutar suite de verificación
PYTHONPATH=terrascout_actor python3 -m pytest tests/test_scraper_node.py -v
```
