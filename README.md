# TerraScout & EcoCamp AI — Capstone Project (Samsung Innovation Campus 2026)

> **Motor de Inteligencia Geoespacial, Valuación Hedónica y Mitigación de Riesgo Ambiental para Inversiones Inmobiliarias y Turísticas en Sierras de Córdoba**

---

## Documentación Principal del Proyecto

1. [**Plan Maestro de Cierre e Implementación del Producto 1 (`plan_implementacion_producto_1_terrascout_ai.md`)**](./plan_implementacion_producto_1_terrascout_ai.md)
   * **¿Qué debemos cerrar hoy antes de programar?** (Checklist de 6 definiciones críticas).
   * **Integración con el Actor de ejemplo de la cátedra (`tarea_ejemplo_apify`)**: Uso de `httpx2`, `BeautifulSoup`, `re`, `RapidFuzz` (`fuzzy_count`) y `scikit-learn` (`TfidfVectorizer` + `KMeans` + `silhouette_score`).
   * **División detallada de tareas por rol**:
     * **Software / Solution Engineer (SE — Líder Técnico)**
     * **Data Analyst / Data Scientist (DS)**
     * **Business Analyst (BIZ)**
2. [**Propuesta Maestra Formalizada (`propuesta_terrascout_ai_georadar_inmobiliario_turistico.md`)**](./propuesta_terrascout_ai_georadar_inmobiliario_turistico.md)
   * Ficha técnica del cliente (**Diana**), cuantificación del dolor comercial, presupuesto (**USD 1.850** one-off + **USD 65/mes**) y **ROI Neto Año 1 (+411%, Payback 2,34 meses)**.
   * Diccionario de datos de las **11–12 variables maestras** (2 fuentes y 2 fenómenos en corte transversal espacial).
   * Respuestas a los 3 pedidos sorpresa del 12/11 y guion de las 4 preguntas finales del Pitch del 24/11.
3. [**Marco Metodológico Satelital sin Series Temporales (`proyecto_satelital_sin_series_temporales.md`)**](./proyecto_satelital_sin_series_temporales.md)
   * Fundamento técnico del corte transversal con datos NASA (SRTM 30m, MODIS/VIIRS NDVI por reflectancia rojo/NIR) e IGN (Red Hídrica y Rutas), casos de uso y declaración de limitaciones.

---

## Resumen de Responsabilidades por Rol (Producto 1)

| Rol | Foco en el Producto 1 | Entregables Clave |
| :--- | :--- | :--- |
| **Software / Solution Engineer (SE — Líder Técnico)** | Arquitectura del Actor en Apify (basado en `tarea_ejemplo_apify`), desacoplamiento de reglas (`config/business_rules.json`), automatización en **Make.com** y repositorio **GitHub**. | Actor Apify (`RapidFuzz` + `TF-IDF/KMeans`), `business_rules.json`, escenario Make (5 nodos con control de errores) y carga automática en Google Sheets. |
| **Data Analyst / Data Scientist (DS)** | Preprocesamiento satelital (`aux_topografia_cordoba.csv`), limpieza ETL (`re`, nulos, duplicados, outliers) y **EDA con correlaciones lineales (Pearson) y no lineales (Spearman)**. | Dataset limpio (`950–1.200 filas x 12 columnas`), Notebook `01_etl_y_eda.ipynb`, análisis de quiebre no lineal en pendientes $>12^\circ$ y documentación de limitaciones. |
| **Business Analyst (BIZ)** | Caso de negocio de Diana, planilla oficial del Capstone (`capstone_project_cronograma_alumnos.xlsx`), **Dashboard en Looker Studio** y defensa comercial. | Pestañas `Resumen`, `Guía Business`, `Presupuesto` (+411% ROI), Dashboard interactivo (3 vistas + NPS Proxy) y respuestas a los 3 pedidos sorpresa de Diana. |
