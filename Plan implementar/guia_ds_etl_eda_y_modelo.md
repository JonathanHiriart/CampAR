# Especificación para Data Analyst / Data Scientist — ETL, EDA y Modelo Hedónico (TerraScout AI)

> **Cómo usar este archivo:** Podés copiar todo este documento (o adjuntarlo junto con `config/business_rules.json` y los archivos de `data/`) a tu asistente de IA para que arme el notebook definitivo (`notebooks/01_etl_y_eda.ipynb`) alineado 100% con el plan del equipo y con los datos reales ya scrapeados.

---

## 1. Contexto y Regla Crítica: CERO Datos Sintéticos

El notebook anterior (`campar_ai_etl_eda.ipynb`) tuvo que descartarse porque:
1. Leyó un archivo viejo de 5 filas (`data_raw_cordoba.csv`) del cual quedó **1 sola fila**.
2. No normalizó monedas (`ARS` vs `USD`).
3. Fabricó el EDA, las correlaciones (`r ≈ 0.72` y `ρ ≈ -0.65` puestos a mano en títulos) y las 950 filas de entrenamiento de ML usando `np.random`.
4. Exportó un `.pkl` entrenado con datos inventados y sin preprocesamiento reusable para conectar al flujo de Apify / Make / n8n.

**Regla obligatoria del proyecto y Auditoría:**
* **PROHIBIDO usar `np.random` para generar filas, precios, superficies, pendientes, NPS o oportunidades.** Todo análisis y todo entrenamiento debe correr sobre los CSVs reales de `data/raw/` y `data/aux_topografia_cordoba.csv`.
* **PROHIBIDO hardcodear reglas de negocio dentro del código.** Todas las constantes (dólar, m² mínimos/máximos, pendiente crítica, distancia al río, descuento mínimo) deben leerse desde `config/business_rules.json`.
* El notebook debe correr de punta a punta con **"Run All" sin errores de orden de celdas**.

---

## 2. Archivos Reales Disponibles en el Repositorio (Inputs Exactos)

Todos los archivos ya están en la carpeta `Capstone/` (hacer `git pull` en `main`):

1. **`config/business_rules.json`** (Reglas desacopladas):
   * `tipo_cambio_ars_usd`: `1280.0`
   * `filtros_terreno`: `superficie_minima_m2 = 500.0`, `superficie_maxima_m2 = 20000.0`, `pendiente_alerta_grados = 12.0`, `pendiente_critica_grados = 18.0`, `distancia_segura_rio_m = 80.0`
   * `arbitraje`: `umbral_descuento_minimo_pct = 0.20`, `excluir_riesgo_alto = true`
   * `palabras_clave_servicios`: `["agua corriente", "luz electrica", "escritura", "arboleda", "asfalto", "gas natural", "alambrado", "rio", "inundable"]`
   * `localidades_catalogo`: 16 localidades canónicas de Calamuchita y Punilla.

2. **`data/raw/mercadolibre_terrenos_calamuchita_punilla_raw.csv`** (**1.200 publicaciones reales**: 600 Calamuchita + 600 Punilla):
   * Columnas exactas: `id_publicacion, fecha_extraccion, valle_corredor, localidad_raw, titulo_publicacion, moneda_raw, precio_raw, superficie_raw_texto, superficie_m2_extraida, latitud, longitud, descripcion_completa, telefono_en_descripcion, vendedor_nombre, url_vendedor, es_tienda_oficial, tipo_aviso, url_busqueda, url_publicacion, url_google_maps, fuente_extraccion`
   * Cobertura real observada: GPS (`latitud`/`longitud`) en `1.177/1.200`, `descripcion_completa` en `1.188/1.200`, `url_publicacion` y `url_google_maps` en `1.200/1.200`, `telefono_en_descripcion` en `51/1.200`.

3. **`data/raw/campings_zona_real_raw.csv`** (**288 campings reales** de OSM Overpass + SoloCampings):
   * Columnas exactas: `osm_id, nombre_camping, latitud, longitud, localidad_raw, localidad_asignada, ubicacion_completa, valle_corredor, distancia_centroide_km, tiene_electricidad, tiene_agua_potable, acepta_casas_rodantes, website, telefono, operador, horario, descripcion_tags, url_busqueda_google_maps, url_osm, fuente_extraccion`

4. **`data/raw/google_maps_campings_places_raw.csv`** (**237 lugares reales de Google Maps vía Apify**):
   * Columnas exactas: `place_id, nombre_camping, valle_corredor, localidad_raw, latitud, longitud, total_score, reviews_count, stars_1, stars_2, stars_3, stars_4, stars_5, nps_proxy, telefono, website, url_google_maps`

5. **`data/raw/google_maps_campings_reviews_raw.csv`** (**1.754 reseñas reales de Google Maps**):
   * Columnas exactas: `id_review, place_id, nombre_camping, valle_corredor, localidad_raw, estrellas_rating, fecha_reseña, texto_reseña`

6. **`data/raw/topicos_nlp_real_raw.json`** (salida NLP sobre 16.358 oraciones):
   * Incluye `topics` (10 clusters generales), `topics_quejas_gmaps` (3 clusters sobre 625 oraciones de reseñas `1★–3★`) y `fuzzy_counts`.

7. **`data/aux_topografia_cordoba.csv`** (**16 localidades canónicas**, tabla de referencia satelital/cartográfica):
   * Columnas exactas: `id_localidad, valle_corredor, barrio_localidad, latitud_centroide, longitud_centroide, altitud_msnm, pendiente_media_grados, ndvi_sombra_verano, distancia_rio_m, distancia_ruta_asfalto_km, riesgo_ambiental, fuente_satelital`
   * *(Nota metodológica: es una tabla auxiliar de referencia por localidad; documentarlo explícitamente y opcionalmente cruzar/validar contra datos IGN/NASA si se desea mayor granularidad).*

---

## 3. Pipeline Esperado Paso a Paso (`notebooks/01_etl_y_eda.ipynb`)

### Paso 1: Configuración y carga de reglas
* Leer `config/business_rules.json` en un diccionario `RULES` y usarlo para todos los umbrales.
* Cargar los CSVs reales desde `data/raw/` y `data/aux_topografia_cordoba.csv` (compatibilidad con ejecución local en `Capstone/` o Colab).

### Paso 2: ETL y Limpieza Real sobre los 1.200 terrenos
1. **Normalización monetaria (`precio_usd`):**
   * Convertir `precio_raw` a numérico.
   * Inspeccionar valores únicos de `moneda_raw` (`USD`, `U$S`, `ARS`, `$`, etc.).
   * Si está en pesos argentinos (`ARS` o `$`), dividir por `RULES["tipo_cambio_ars_usd"]` (`1280.0`).
   * Descartar filas con `precio_usd` nulo o `<= 0` (regla anti-imputación ciega de precios).
2. **Superficie (`superficie_m2`):**
   * Usar `superficie_m2_extraida` y, solo donde sea nula, intentar rescate con Regex (`re`) sobre `superficie_raw_texto`, `titulo_publicacion` y `descripcion_completa` (sin confundir distancias como `"a 300 metros del río"` con m²).
   * Aplicar filtros de dominio de `business_rules.json`: conservar `500.0 <= superficie_m2 <= 20000.0` (documentando cuántos registros se descartan por nulos, cocheras/chicos `< 500` y campos rurales `> 20.000`).
3. **Target (`precio_m2_usd`):**
   * Calcular `precio_m2_usd = round(precio_usd / superficie_m2, 2)` y revisar outliers extremos de `precio_m2_usd` con criterio IQR o percentiles (documentando qué se filtra y por qué).
4. **Deduplicación real:**
   * Primero por `id_publicacion`.
   * Luego detectar posibles avisos duplicados de distintas inmobiliarias sobre el mismo lote (por ejemplo, misma localidad + superficie casi igual + precio muy similar o similitud alta de `titulo_publicacion`). Documentar antes/después del conteo de filas.
5. **Features de texto (`score_servicios`, `tiene_escritura`, `tiene_servicios`):**
   * Usar `titulo_publicacion + " " + descripcion_completa` junto con detección textual / `RapidFuzz` para calcular:
     * Indicadores reales (ej. `tiene_agua`, `tiene_luz`, `tiene_escritura`, `tiene_arboleda`, `tiene_rio`).
     * `score_servicios` (entero `0` a `3`: suma de Agua + Luz + Escritura, según el contrato del Producto 1).

### Paso 3: JOIN Espacial y Cruce Multi-Fuente (Fenómeno 1 + Fenómeno 2)
* **Localidad y topografía (`aux_topografia_cordoba.csv`):**
  * Para los terrenos con `latitud` y `longitud` (`1.177/1.200`), asignar la `barrio_localidad` más cercana usando **distancia Haversine** contra `latitud_centroide`/`longitud_centroide`. Para los 23 sin GPS, usar `RapidFuzz` sobre `localidad_raw`.
  * Traer `pendiente_media_grados`, `ndvi_sombra_verano`, `distancia_rio_m` y `riesgo_ambiental`.
* **Competencia física (`campings_zona_real_raw.csv` — 288 campings):**
  * Calcular para cada terreno con GPS: `campings_5km` (cantidad real de campings a `<= 5.0 km` por Haversine) y `distancia_camping_min_km`.
* **Demanda y calidad turística (`google_maps_campings_places_raw.csv` — 237 lugares):**
  * Calcular `nps_proxy_zona` para cada terreno como el promedio (idealmente ponderado por `reviews_count` o simple, documentando el criterio) de `nps_proxy` de los lugares de Google Maps a `<= 5.0 km` (con fallback documentado a `10 km` o al promedio de la localidad/valle si un terreno puntual no tiene campings con `nps_proxy` en 5 km).

### Paso 4: EDA Real (Correlaciones Calculadas + Gráficos Reales)
* **Prohibido poner valores estimados o fijos en los títulos.** Calcular e imprimir los valores reales de:
  * **Correlación lineal de Pearson ($r$)** y **correlación monótona de Spearman ($\rho$)** + **Mutual Information** entre features (`superficie_m2`, `score_servicios`, `pendiente_media_grados`, `ndvi_sombra_verano`, `distancia_rio_m`, `campings_5km`, `nps_proxy_zona`) y targets (`precio_usd`, `precio_m2_usd`).
* **Visualizaciones mínimas:**
  1. Embudo de limpieza (cuántas filas entraron `1.200` → cuántas quedaron en cada paso).
  2. Distribución de `precio_usd`, `superficie_m2` y `precio_m2_usd` por `valle_corredor` y por `barrio_localidad`.
  3. Scatter / regresión real de `superficie_m2` vs `precio_usd` (con Pearson real en el título).
  4. Relación real de `pendiente_media_grados` vs `precio_m2_usd` marcando la línea vertical de `12°` y `18°` (`Spearman` real).
  5. Heatmap de correlaciones (Pearson y Spearman) y relación entre `ndvi_sombra_verano`, `campings_5km` y `nps_proxy_zona` sobre los 237 campings reales.
* **Interpretación honesta:** Si alguna correlación esperada (por ejemplo, pendiente vs precio) resulta débil porque `aux_topografia_cordoba.csv` tiene solo 16 valores únicos por localidad, **reportarlo explícitamente como hallazgo y limitación metodológica**.

### Paso 5: Exportación del Dataset Limpio de Producto 1 (Para Looker Studio y Make)
Exportar `data/processed/terrascout_dataset_producto1.csv` asegurando las **12 columnas del contrato oficial** + columnas operativas de contacto/trazabilidad para Diana:

* **12 columnas oficiales:**
  1. `id_registro` (`id_publicacion`)
  2. `valle_corredor`
  3. `barrio_localidad`
  4. `precio_usd`
  5. `superficie_m2`
  6. `precio_m2_usd`
  7. `score_servicios`
  8. `pendiente_media_grados`
  9. `ndvi_sombra_verano`
  10. `distancia_rio_m`
  11. `riesgo_ambiental`
  12. `nps_proxy_zona`
* **Columnas extra recomendadas para Dashboard y Alertas a Diana:**
  * `titulo_publicacion`, `latitud`, `longitud`, `campings_5km`, `telefono_en_descripcion`, `url_publicacion`, `url_google_maps`, `vendedor_nombre`, `gap_arbitraje_pct`, `es_oportunidad`.

### Paso 6: Modelado Hedónico Real + Exportación Pickle `.pkl` (Para el Siguiente Nodo / Producto 2)
1. **Split estricto anti-leakage:** `train_test_split(X, y, test_size=0.20, random_state=42)` (o estratificado por `valle_corredor` / cuantiles de precio) **antes** de imputar, escalar o encodear. Target: `np.log(precio_m2_usd)` (evaluando métricas en escala real `USD/m²` tras `np.exp`).
2. **Construir un `sklearn.pipeline.Pipeline` + `ColumnTransformer` completo** (que incluya variables numéricas y categóricas reales, por ej. `valle_corredor`, `barrio_localidad`, `superficie_m2`, `score_servicios`, `pendiente_media_grados`, `ndvi_sombra_verano`, `distancia_rio_m`, `campings_5km`, `nps_proxy_zona`, con `OneHotEncoder(handle_unknown="ignore")` e imputadores entrenados solo en `train`).
3. **Comparar modelos con 5-Fold Cross-Validation** sobre `X_train` y evaluar en `X_test`:
   * Baseline (DummyRegressor mediana)
   * `Ridge`
   * `RandomForestRegressor`
   * `HistGradientBoostingRegressor`
   * Elegir objetivamente el ganador por mejor desempeño en CV y test (`R²`, `MAE`, `RMSE` en `USD/m²`).
4. **Motor de Arbitraje Out-of-Fold (sobre datos reales):**
   * Usar `cross_val_predict` (sobre `train`) y predicciones en `test` contra el **`precio_m2_usd` real publicado** (¡nunca multiplicado por `np.random`!).
   * Calcular:
     `gap_arbitraje_pct = (precio_modelo_m2 - precio_m2_usd) / precio_modelo_m2`
   * Aplicar regla desde `business_rules.json`: `gap_arbitraje_pct >= 0.20` (`20%`) y `pendiente_media_grados <= 12.0` (y `riesgo_ambiental != "ALTO"`).
   * Mostrar las **top 10 oportunidades reales** con su `id_registro`, `barrio_localidad`, `precio_usd`, `superficie_m2`, `gap_arbitraje_pct` y `url_publicacion` para verificar manualmente que son lotes reales atractivos.
5. **Serialización en Pickle lista para producción (`models/terrascout_pipeline.pkl`):**
   * Requisito de cátedra: exportar con **`pickle`** (`with open("models/terrascout_pipeline.pkl", "wb") as f: pickle.dump(...)`), guardando un diccionario o `Pipeline` que incluya:
     * `pipeline`: el `Pipeline` completo (`ColumnTransformer` + modelo ganador entrenado),
     * `feature_columns`: lista exacta de columnas de entrada esperadas,
     * `target_log_transformed`: `True`,
     * `sklearn_version` y `metrics`: versión de `scikit-learn` y métricas reales en test/CV.
   * **¿Por qué así?** Para que el nodo siguiente (una API FastAPI o script en Make/n8n/Apify) cargue `pickle.load(...)`, reciba un diccionario JSON con un lote nuevo sacado por el scraper y obtenga al instante `precio_justo_m2_usd` y `es_oportunidad` sin reescribir transformaciones manuales.

---

## 4. Checklist de Aceptación (Qué vamos a revisar antes de integrarlo)

- [ ] No hay llamadas a `np.random` para generar datasets, pendientes ni precios.
- [ ] Todos los umbrales vienen de `config/business_rules.json`.
- [ ] El notebook ejecuta **"Run All"** limpio de arriba hacia abajo sin errores.
- [ ] Se reporta exactamente cuántos de los `1.200` lotes quedaron tras cada filtro ETL.
- [ ] Todas las correlaciones (Pearson, Spearman, Mutual Information) son reales y coinciden con los gráficos.
- [ ] Se genera `data/processed/terrascout_dataset_producto1.csv` listo para Google Sheets / Looker Studio.
- [ ] Se genera `models/terrascout_pipeline.pkl` (con `pickle.dump`) incluyendo `Pipeline` + `feature_columns` reales, y una celda de prueba final carga el `.pkl` con `pickle.load` y predice 3 lotes reales para demostrar que funciona bien.
