# Documentación General del Proyecto — TerraScout AI (Producto 1)

> **Para todo el equipo (técnico y no técnico):** este documento resume qué problema resuelve TerraScout AI, cuál fue el plan que seguimos para construirlo y **para qué sirve cada carpeta y archivo** sin tecnicismos innecesarios.

---

## 1. ¿Qué hace nuestro sistema en palabras simples?

En los valles de **Calamuchita y Punilla (Sierras de Córdoba)** hay cientos de terrenos publicados en internet, pero evaluar cuáles sirven para desarrollar o comercializar un **camping o glamping** es lento y riesgoso:
* Los avisos mezclan precios en **pesos y dólares**, repiten el mismo terreno varias veces y esconden costos o fallas (terrenos muy empinados, zonas inundables o sin agua/luz).
* Por otro lado, en Google Maps miles de turistas dejan reseñas quejando de lo que **les falta a los campings actuales** (baños, sombra, atención, acceso al río).

**TerraScout AI** junta toda esa información real, la limpia automáticamente, la cruza por ubicación geográfica y entrega un **Excel/tablas listas para graficar** que responden:
1. **¿Dónde hay demanda insatisfecha?** Localidades con turismo activo y campings actuales con calificaciones bajas o quejas concretas.
2. **¿Qué lotes convienen hoy?** Terrenos publicados **al menos un 20% más baratos** que el valor típico de su zona, con superficie apta (`500 a 20.000 m²`), pendiente moderada (`≤ 12°`) y sin riesgo ambiental alto.
3. **¿A qué precio referencia comparar?** Mediana real en USD por `m²` de cada localidad (`894` terrenos validados y `244` oportunidades detectadas).

---

## 2. El Plan que Seguimos Paso a Paso (Cómo llegamos hasta acá)

| Paso | Qué hicimos | Qué problema resolvió |
| :--- | :--- | :--- |
| **1. Ordenar las reglas del negocio** | Guardamos todas las decisiones (valor del dólar, tamaño mínimo/máximo del lote, descuento mínimo del 20%, pendiente máxima) en un solo archivo de configuración ([`config/business_rules.json`](../config/business_rules.json)). | Si mañana cambia el dólar o queremos ser más exigentes con la pendiente, **se cambia un número ahí** sin tocar ni romper el código. |
| **2. Conseguir datos 100% reales** | Reemplazamos las pruebas con datos inventados por extracciones reales de **Mercado Libre (`1.200` avisos)**, **campings (`288`)**, **Google Maps (`237` lugares y `1.754` reseñas)** y **topografía de `16` localidades**. | Todo el análisis y las oportunidades que ve el equipo son **terrenos reales con link directo a la publicación y al mapa**. |
| **3. Separar la Limpieza (ETL) del Análisis (EDA)** | Siguiendo el diagrama de la cátedra ([`diagrama_flujo_producto1.png`](./diagrama_flujo_producto1.png)), dividimos el trabajo en **2 módulos en la nube (Apify)**: uno que **limpia y cruza** (`APIFY ETL`) y otro que **calcula estadísticas y arma el Excel del tablero** (`APIFY EDA`). | Cada etapa queda ordenada y reutilizable: el Producto 1 queda listo para visualizar, y el Dataset Limpio queda preparado para entrenar modelos en el Producto 2. |
| **4. Consolidar la entrada en 1 solo archivo** | Creamos [`data/raw/dataset_raw_consolidado.xlsx`](../data/raw/dataset_raw_consolidado.xlsx) con **7 pestañas** (terrenos, campings, lugares, topografía, reseñas, reglas y tópicos de quejas). | En lugar de subir y conectar 7 links distintos a mano, podés usar **1 solo Google Sheet / Excel** como entrada del sistema. |
| **5. Automatizar todo con n8n y Google Drive** | Armamos un flujo de **6 pasos en línea recta** ([`workflows/n8n_producto1_terrascout.json`](../workflows/n8n_producto1_terrascout.json)) que llama al ETL, guarda el archivo limpio en Drive, llama al EDA y guarda el Excel final del Dashboard en Drive (con opción `Update` para pisar siempre el mismo archivo). | Con un clic en n8n se actualiza todo automáticamente sin descargar ni subir archivos a mano, y Looker Studio nunca pierde la conexión con el Excel. |
| **6. Verificar todo antes de entregar** | Probamos ambos robots en vivo en Apify Cloud (`SUCCEEDED`), auditamos las cuentas estadísticas (`log(precio_m2_usd)`, correlaciones reales) y dejamos **33 pruebas automáticas** (`pytest`). | Garantiza que el sistema no se caiga en la demo ni dependa de rutas locales de una sola computadora. |

### Estado actual y cierre de Producto 2
* **Producto 1 (completo):** ETL + EDA en Apify Cloud, `894` lotes limpios, `244` oportunidades bajo mediana zonal y flujo n8n listo; solo resta vincular el Excel `contenido_graficas_dashboard.xlsx` en **Looker Studio** si aún no está conectado.
* **Producto 2 (implementado y verificado):** Actor 3 [`actors/apify_ml/`](../actors/apify_ml/.actor/actor.json), ejecutor local [`src/run_producto2_pipeline.py`](../src/run_producto2_pipeline.py), workflow [`workflows/n8n_producto2_terrascout.json`](../workflows/n8n_producto2_terrascout.json), notebook [`notebooks/02_modelado_hedonico.ipynb`](../notebooks/02_modelado_hedonico.ipynb) y modelo serializado [`models/terrascout_pipeline.pkl`](../models/terrascout_pipeline.pkl) (`Ensemble 2ET+GBR+HGBR`, `R² CV = 0.5964`, `R² Test = 0.6037`, `MAE = 6.45 USD/m²`, `dif_max = 0.0`, `43` tests pasando). Solo resta desplegar el Actor 3 con `apify push` si se corre en la nube y completar la revisión manual de `validacion_30_alertas.csv`.

---

## 3. Guía Completa de Archivos y Carpetas (Qué resuelve cada uno)

### Raíz del proyecto
* [`README.md`](../README.md): Puerta de entrada del repositorio: primero explica la idea del negocio, luego cómo usar el sistema y al final el detalle técnico.
* [`.env.example`](../.env.example): Plantilla de ejemplo con las variables secretas que necesita cada integrante (como el token de Apify), sin contraseñas reales.
* [`.gitignore`](../.gitignore): Lista de seguridad para que Git **nunca suba** contraseñas (`.env`), archivos temporales ni la carpeta `_revisar_para_borrar/`.
* [`requirements.txt`](../requirements.txt): Lista de herramientas de Python necesarias si alguien quiere correr el proyecto completo en su computadora.

### `config/` — Reglas del negocio
* [`config/business_rules.json`](../config/business_rules.json): El "tablero de control" del negocio. Guarda el tipo de cambio ARS/USD, rango válido de m², pendiente alerta, descuento mínimo (`20%`) y palabras clave para detectar servicios (`agua`, `luz`, `escritura`). **Resuelve:** evitar números ocultos dentro del código.

### `data/` — Datos crudos y resultados listos
* **`data/raw/`** *(lo que entra al sistema)*:
  * `mercadolibre_terrenos_calamuchita_punilla_raw.csv`: `1.200` publicaciones reales descargadas de Mercado Libre.
  * `campings_zona_real_raw.csv`: `288` campings reales georreferenciados en la zona.
  * `google_maps_campings_places_raw.csv`: `237` perfiles de campings en Google Maps (calificación y cantidad de reseñas).
  * `google_maps_campings_reviews_raw.csv`: `1.754` comentarios reales de turistas en esos campings.
  * `topicos_nlp_real_raw.json`: Resumen de los principales temas de queja detectados en las reseñas y menciones de servicios.
  * `dataset_raw_consolidado.xlsx`: **Unión de todo lo anterior + topografía + reglas en 1 solo Excel de 7 pestañas**, creado para poder cargarlo fácilmente desde un único Google Sheets o Google Drive.
* [`data/aux_topografia_cordoba.csv`](../data/aux_topografia_cordoba.csv): Datos de relieve, sombra natural (vegetación), distancia al río y nivel de riesgo ambiental de las `16` localidades de referencia.
* **`data/processed/`** *(lo que sale del sistema ya limpio y listo)*:
  * `dataset_limpio.csv`: Base final depurada con **`894` terrenos únicos**, precios en dólares, servicios detectados, distancia a campings vecinos y marca de oportunidad (`es_oportunidad_p1`).
  * `etl_funnel.json`: Resumen paso a paso de cuántos registros quedaron en cada filtro (`1.200 → 1.178 → 927 → 918 → 894`).
  * `dashboard/csv_1_localidades_y_riesgo.csv` (`hoja1`): Tabla agregada por localidad para mapas y comparación de zonas.
  * `dashboard/csv_2_correlaciones_y_distribuciones.csv` (`hoja2`): Estadísticas reales de qué variables influyen más en el precio del terreno y cómo se distribuyen.
  * `dashboard/csv_3_oportunidades_y_voz_turista.csv` (`hoja3`): Top de lotes en oportunidad (con teléfono y links directos) + resumen de estrellas y quejas de turistas.
  * `dashboard/contenido_graficas_dashboard.xlsx`: Excel único con **`hoja1`, `hoja2` y `hoja3`** juntas para alimentar Looker Studio.

### `actors/` y `terrascout_actor/` — Los robots en la nube (Apify)
* [`actors/apify_etl/`](../actors/apify_etl/.actor/actor.json) *(Actor `ypvpGbmD1vpqraNXA`)*: **Robot de Limpieza y Cruce Geográfico.** Toma los datos crudos (desde un Google Sheet único, links sueltos de Drive o su respaldo interno `fallback_data/`), limpia precios/superficies, elimina duplicados y calcula distancias a campings y zonas turísticas para entregar `dataset_limpio.csv`.
* [`actors/apify_eda/`](../actors/apify_eda/.actor/actor.json) *(Actor `YZH8ti7zjLt6410Hx`)*: **Robot de Análisis y Salidas para Dashboard.** Toma `dataset_limpio.csv` (+ reseñas y tópicos), calcula métricas estadísticas reales y genera los 3 CSVs y el Excel multi-hoja `contenido_graficas_dashboard.xlsx`.
* [`terrascout_actor/`](../terrascout_actor/.actor/actor.json): **Robot Extractor original (Scraper).** Contiene los módulos que consultan en vivo Mercado Libre, OpenStreetMap, SoloCampings y Google Maps para construir los archivos de `data/raw/`.

### `workflows/` — Automatización visual (n8n)
* [`workflows/n8n_producto1_terrascout.json`](../workflows/n8n_producto1_terrascout.json): Archivo listo para importar en **n8n** con 6 nodos en línea recta (`Trigger → Config → APIFY ETL → DRIVE Limpio → APIFY EDA → DRIVE Gráficas`). **Resuelve:** ejecutar todo el flujo automáticamente y dejar los archivos finales en Google Drive sin trabajo manual.

### `src/` — Scripts para correr en tu computadora
* [`src/run_producto1_pipeline.py`](../src/run_producto1_pipeline.py): Ejecuta localmente todo el flujo ETL + EDA en 1 segundo y regenera `dataset_raw_consolidado.xlsx`, `dataset_limpio.csv` y los archivos de `data/processed/dashboard/`.
* [`src/run_scraper_node.py`](../src/run_scraper_node.py): Ejecuta desde terminal la extracción de datos reales hacia `data/raw/`.

### `tests/` — Pruebas automáticas de calidad
* [`tests/test_producto1_actors.py`](../tests/test_producto1_actors.py): Verifica que la estructura de los actores Apify sea válida, que funcione la carga desde el Excel único consolidado, que no existan datos aleatorios inventados (`np.random`) y que el Excel de salida tenga `hoja1`, `hoja2` y `hoja3`.
* [`tests/test_scraper_node.py`](../tests/test_scraper_node.py): Valida los scrapers, el cálculo geográfico Haversine, la detección de tópicos y la integridad de los datos crudos reales.

### `docs/` — Documentación y material de diseño
* [`docs/DOCUMENTACION_COMPLETA.md`](./DOCUMENTACION_COMPLETA.md): Este resumen general pensado para todo el equipo.
* [`docs/guia_looker_studio_producto1.md`](./guia_looker_studio_producto1.md): Guía paso a paso página por página (5 páginas, KPIs, mapas y tablas) para armar el tablero final en Looker Studio.
* [`docs/flujo_make_n8n_producto1.md`](./flujo_make_n8n_producto1.md): Paso a paso técnico para conectar Make / n8n y los actores Apify.
* [`docs/diagrama_flujo_producto1.png`](./diagrama_flujo_producto1.png): Diagrama de referencia de la cátedra que guía toda la arquitectura.
* **`docs/planificacion/`**: Documentos originales de definición y sustento del proyecto TerraScout AI (`propuesta_terrascout_ai.md`, `proyecto_satelital_sin_series_temporales.md`, `plan_implementacion_producto_1.md`, `guia_ds_etl_eda_y_modelo.md`).