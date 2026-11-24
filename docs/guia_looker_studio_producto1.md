# Guía Completa de Dashboard en Looker Studio — CampAR (Producto 1)

> Adapta el diseño analítico de Business (5 páginas, enfoque en mediana y descuento por segmento) directamente al stack **n8n → Apify → Google Drive/Sheets → Looker Studio**, con todos los bugs de datos y gráficos ya corregidos en el pipeline.

---

## 1. Fuentes de Datos a Conectar en Looker Studio

### Modo recomendado (1 sola pestaña automática desde n8n → Google Sheets)
El flujo actualizado ([`n8n_producto1_terrascout.json`](../workflows/n8n_producto1_terrascout.json)) envía directamente las **`918` filas unificadas** a la pestaña **`Datos`** de un único Google Sheet (`dashboard_consolidado`), usando `tipo_tabla` para separar:
* **`tipo_tabla = "lote"`** (`894` filas) → alimenta **Páginas 1, 2, 3, dispersión de Pág 4 y Pág 5** (aplicar este filtro en los gráficos/tarjetas de lotes).
* **`tipo_tabla = "voz_turista_estrellas"`** (`5`), **`"topico_queja_gmaps"`** (`3`), **`"infraestructura_lote"`** (`6`) y **`"eda_correlacion"`** (`10`) → alimentan los gráficos de **Página 4** usando `metrica_nombre`, `metrica_cantidad`, `metrica_porcentaje`, `eda_pearson_m2` y `eda_spearman_m2`.

### Modo alternativo (4 fuentes separadas desde `contenido_graficas_dashboard.xlsx`)

| Fuente en Looker Studio | Archivo / Pestaña | Filas | Para qué páginas se usa |
| :--- | :--- | :---: | :--- |
| **`lotes`** *(fuente principal)* | `dataset_limpio` (abrir/guardar como Google Sheet o CSV) | `894` | **Páginas 1, 2, 3, 4 (dispersión campings) y 5 (Ficha de lote)** |
| **`hoja1_localidades`** | `contenido_graficas_dashboard` → pestaña `hoja1` | `16` *(únicas)* | Vista de resumen biofísico por localidad (ya sin duplicados de valle) |
| **`hoja2_eda`** | `contenido_graficas_dashboard` → pestaña `hoja2` | `28` | Tabla/barras de correlaciones reales (Pearson, Spearman, Kendall, Info Mutua) |
| **`hoja3_turismo`** | `contenido_graficas_dashboard` → pestaña `hoja3` | `273` | **Página 4**: estrellas (`voz_turista_estrellas`), quejas (`topico_queja_gmaps`) e infraestructura real (`infraestructura_lote`) |

> **Por qué usar `lotes` como fuente principal:** responde al instante a cualquier filtro cruzado de valle, localidad, riesgo y banda de superficie, y ya trae precalculadas todas las columnas que en el diseño inicial dependían de DAX (`banda_superficie`, `banda_orden`, `riesgo_orden`, `descuento_vs_segmento_pct`, `es_oportunidad_segmento`, `fecha_extraccion` y `coordenadas_gmaps`).

### Campos a verificar al conectar `lotes` en Looker Studio
* **Geográfico (`Geo → Latitud, Longitud`):** `coordenadas_gmaps` *(ya viene formateada como `lat,lon`, lista para usar en Google Maps sin campos calculados)*.
* **URL:** `url_publicacion` y `url_google_maps` *(tipo **URL** para hacer clic directo en tablas y fichas)*.
* **Fecha:** `fecha_extraccion` *(solo informativa para mostrar en el encabezado: `2026-11-16`, sin tabla calendario porque es corte transversal)*.
* **Métricas / Campos calculados útiles en Looker Studio (sobre `lotes`):**
  * **Precio/m² Mediano:** usar agregación **Mediana** sobre `precio_m2_usd` (`19,05 USD/m²` global vs `23,22` promedio).
  * **% Con Escritura:** agregación **Promedio** sobre `tiene_escritura` con formato Porcentaje (`49,89%`, ya limpia de disclaimers inmobiliarios y negaciones).
  * **% Oportunidades (Segmento):**
    ```sql
    AVG(CASE WHEN es_oportunidad_segmento THEN 1 ELSE 0 END)
    ```
  * **Link a Aviso / Mapa (en tablas):**
    ```sql
    HYPERLINK(url_publicacion, "Ver publicación")
    ```
    ```sql
    HYPERLINK(url_google_maps, "Ver en Maps")
    ```

---

## 2. Filtros Globales (Barra Superior Compartida en Páginas 1, 2, 3 y 5)

Activá **Aplicar a nivel de informe** (excepto en los gráficos de contexto de `hoja3` en Página 4, que son a nivel Sierras de Córdoba):
1. `valle_corredor` *(Valle de Calamuchita / Valle de Punilla — ya corregidas las 5 filas que estaban cruzadas)*
2. `barrio_localidad` *(16 localidades)*
3. `riesgo_ambiental` *(ordenado usando `riesgo_orden`: `1 BAJO`, `2 MEDIO`, `3 ALTO`)*
4. `banda_superficie` *(ordenado por `banda_orden`: `<= 1.000 m2`, `1.001 - 3.000 m2`, `3.001 - 10.000 m2`, `> 10.000 m2`)*
5. Control deslizante sobre `precio_usd`
6. *(Opcional)* Casilla fija de `es_oportunidad_segmento` (`TRUE / FALSE`)

---

## 3. Diseño Página por Página

### Página 1 — Panorama del Mercado *(Título: "¿Dónde y a qué precio está la oferta hoy?")*
* **Fuente:** `lotes` (`dataset_limpio`) + tarjeta de fecha (`MAX(fecha_extraccion)`).
* **4 Tarjetas KPI:**
  1. `id_registro` *(Recuento distinto → `894`)*
  2. `precio_m2_usd` *(Mediana → `USD 19,05 / m²`)*
  3. `% Oportunidades (Segmento)` *(Promedio → `25,06%`, `224` lotes)*
  4. `% Con Escritura` *(Promedio → `49,89%`, `446` lotes)*
* **Mapa de Google Maps:**
  * Ubicación: `coordenadas_gmaps`
  * Color de burbuja: `riesgo_ambiental` (semáforo: `BAJO` verde, `MEDIO` amarillo, `ALTO` rojo) o `descuento_vs_segmento_pct`
  * Tamaño: `superficie_m2` o `descuento_vs_segmento_pct`
  * Tooltip: `barrio_localidad`, `precio_usd`, `superficie_m2`, `precio_m2_usd`, `descuento_vs_segmento_pct`, `riesgo_ambiental`
  * *Nota:* `249` lotes comparten coordenadas aproximadas en `59` puntos; configurar transparencia del 60–70% en burbujas.
* **Barras horizontales — Ranking de localidades:**
  * Dimensión: `barrio_localidad`
  * Métrica 1: `MEDIAN(precio_m2_usd)` · Métrica 2 (tooltip): `COUNT_DISTINCT(id_registro)`
  * *Nota visual:* *Los Reartes* (`196`) y *Villa Carlos Paz* (`173`) concentran `369/894` lotes; *Villa General Belgrano* (`11`), *Embalse* (`18`) y *Huerta Grande* (`18`) tienen muestra chica.

---

### Página 2 — Precio y Oportunidad Real *(Título: "El tamaño explica gran parte del precio/m²; comparamos lotes del mismo segmento")*
* **Fuente:** `lotes` (`dataset_limpio`).
* **Gráfico de dispersión (Efecto Tamaño — `Spearman = -0,51`):**
  * Dimensión: `id_registro` · Eje X: `superficie_m2` *(activar **Escala logarítmica**)* · Eje Y: `precio_m2_usd` *(activar **Escala logarítmica**)*
  * Desglose por color: `riesgo_ambiental`
* **Tabla dinámica / Matriz de calor (`localidad × banda_superficie`):**
  * Dimensión de fila: `barrio_localidad`
  * Dimensión de columna: `banda_superficie` *(ordenar por `banda_orden` ascendente)*
  * Métrica: `% Oportunidades (Segmento)` *(con **Mapa de calor** en estilo)* o `AVG(descuento_vs_segmento_pct)` + `COUNT_DISTINCT(id_registro)` (`n`).
  * *Por qué funciona sin bugs:* `descuento_vs_segmento_pct` ya hace fallback automático a la mediana zonal cuando una celda tiene `< 5` lotes.
* **Tabla accionable — Top Oportunidades para Visitar Primero:**
  * Filtro obligatorio del gráfico: `riesgo_ambiental != "ALTO"` Y `pendiente_media_grados <= 12` Y `descuento_vs_segmento_pct >= 20`.
  * Columnas: `id_registro`, `titulo_publicacion`, `barrio_localidad`, `banda_superficie`, `precio_usd`, `superficie_m2`, `precio_m2_usd`, `descuento_vs_segmento_pct`, `riesgo_ambiental`, `tiene_agua`, `tiene_luz`, `tiene_escritura`, `Link Aviso`, `Link Maps`.
  * Orden: `descuento_vs_segmento_pct` descendente. *(Cero teléfonos ni nombres de vendedores por Ley 25.326).*

---

### Página 3 — Riesgo Ambiental, Servicios y Relieve *(Título: "Qué zonas son aptas y están listas para construir")*
* **Fuente:** `lotes` (`dataset_limpio`) + `hoja1_localidades`.
* **Barras apiladas — Lotes por riesgo y localidad:**
  * Dimensión: `barrio_localidad` · Desglose: `riesgo_ambiental` (semáforo) · Métrica: `COUNT_DISTINCT(id_registro)`.
  * Destaca los `81` lotes en riesgo `ALTO` (*Tanti* `61` + *Cosquín* `20`) que quedan excluidos de compra.
* **Barras con referencia de cuartiles / mediana — Precio/m² por Riesgo Ambiental:**
  * Looker Studio no trae diagrama de caja nativo: usar **Barras agrupadas** por `riesgo_ambiental` (`riesgo_orden` asc) mostrando `MEDIAN(precio_m2_usd)` y `AVG(precio_m2_usd)` (`ALTO = 19,39` vs `BAJO = 25,22` USD/m² de promedio).
* **Barras AGRUPADAS (no al 100%) — Servicios reales por localidad:**
  * Dimensión: `barrio_localidad`
  * Métricas (formato `%`): `AVG(tiene_agua)`, `AVG(tiene_luz)`, `AVG(tiene_escritura)`
  * *Corrección aplicada:* barras agrupadas en escala `0%–100%` porque un terreno puede tener los tres servicios a la vez.
* **Gráfico de Burbujas por Localidad (Pendiente vs Precio):**
  * Fuente: `lotes` o `hoja1_localidades`
  * Dimensión (Burbuja): `barrio_localidad` *(obligatorio para ver 16 puntos)*
  * Eje X: `MEDIAN(pendiente_media_grados)` *(agregar línea de referencia en `12°`)* · Eje Y: `MEDIAN(precio_m2_usd)`
  * Tamaño: `COUNT_DISTINCT(id_registro)` · Color: `riesgo_ambiental`

---

### Página 4 — Demanda Turística, Quejas e Infraestructura *(Título: "¿Qué buscan y qué reclaman los turistas?" + Aviso de alcance)*
> **Nota visible en página:** *Las estrellas, tópicos de queja y porcentajes globales aplican a nivel Sierras de Córdoba y no cambian con los filtros de localidad.*

* **Burbujas de Oportunidad Turística por Localidad (Responde "¿Qué vender / Dónde hay demanda insatisfecha?"):**
  * Fuente: `hoja1_localidades` (`16` localidades)
  * Dimensión: `barrio_localidad` · Eje X: `nps_proxy_zona_mediana` · Eje Y: `ndvi_sombra_verano` (o `precio_m2_mediano_usd`) · Tamaño: `cantidad_lotes` · Color: `riesgo_ambiental`.
* **Dispersión campings vs precio/m² (`lotes`):**
  * Dimensión: `id_registro` · X: `campings_5km` · Y: `precio_m2_usd` · Color: `nps_proxy_zona` + línea de tendencia lineal *(aclarar correlación débil `Pearson = 0,162` como contexto honesto)*.
* **Columnas — Percepción Turística en Google Maps (`hoja3_turismo`):**
  * Filtro del gráfico: `seccion = "voz_turista_estrellas"`
  * Dimensión: `metrica_turismo_o_topico` · Métrica: `porcentaje_o_share` (`73,26%` en `5_estrellas`, `1.754` reseñas).
* **Barras horizontales — Top Quejas de Turistas (`hoja3_turismo`):**
  * Filtro del gráfico: `seccion = "topico_queja_gmaps"`
  * Dimensión: `metrica_turismo_o_topico` · Métrica: `porcentaje_o_share` *(ya limpio sin residuo `<br>`: baños/agua/río `91,5%`, atención/experiencia `5,1%`, complejo/parcelas `3,4%`)*.
* **Barras horizontales — Infraestructura Real Declarada (`hoja3_turismo`):**
  * Filtro del gráfico: `seccion = "infraestructura_lote"`
  * Dimensión: `metrica_turismo_o_topico` · Métrica: `porcentaje_o_share` *(sobre `894` lotes: Agua `62,08%`, Servicios básicos `>=2` `56,38%`, Escritura real `49,89%`, Luz `48,99%`, Río `35,68%`, Arboleda `11,86%`)*.

---

### Página 5 — Ficha de Lote *(Inspector Individual)*
* **Filtro fijo en la página:** selector desplegable de `id_registro` (o clic derecho / filtro cruzado desde la tabla Top Oportunidades de Página 2).
* **Bloques:**
  * Tarjetas con `precio_usd`, `superficie_m2`, `banda_superficie`, `precio_m2_usd`, `precio_referencia_segmento_m2`, `descuento_vs_segmento_pct`, `riesgo_ambiental`, `pendiente_media_grados`, `distancia_camping_min_km` y `nps_proxy_zona`.
  * Tabla de detalle con el `titulo_publicacion`, checklist de servicios (`tiene_agua`, `tiene_luz`, `tiene_escritura`, `tiene_arboleda`, `tiene_rio`) y los dos links clicables (`url_publicacion`, `url_google_maps`).
  * Mini mapa centrado en `coordenadas_gmaps`.

---

## 4. Prioridad Rápida si Tienen Poco Tiempo (MVP para la Demo)

Si necesitan salir en vivo rápido, armen en este orden los **9 visuales esenciales**:
1. **Pág 1:** Tarjetas KPI + Mapa de lotes (`coordenadas_gmaps`) + Barras de precio/m² por localidad.
2. **Pág 2:** Dispersión log (`superficie_m2` vs `precio_m2_usd`) + Matriz `localidad × banda_superficie` + Tabla Top Oportunidades filtrada.
3. **Pág 3:** Barras apiladas de riesgo por localidad (`81` lotes `ALTO`).
4. **Pág 4:** Burbujas por localidad (`nps_proxy_zona` vs `ndvi_sombra_verano`) + Barras de Top Quejas (`topico_queja_gmaps`) y Servicios Reales (`infraestructura_lote`).

---

## 5. Integración Producto 2 (Pestaña `Oportunidades_ML`)

El flujo unificado de n8n ([`n8n_terrascout_completo.json`](../workflows/n8n_terrascout_completo.json)) alimenta una segunda pestaña en el mismo Google Sheet llamada **`Oportunidades_ML`** con las **`894` valuaciones hedónicas** (donde **`184` lotes** califican como oportunidades ML válidas: `gap_arbitraje_pct >= 20%`, `pendiente_media_grados <= 12°` y `riesgo_ambiental != "ALTO"`).

### Métricas y columnas clave de `Oportunidades_ML`
* **`precio_modelo_m2`** y **`precio_modelo_total_usd`**: valor justo estimado por el ensamble `2ET + GBR + HGBR` (`R² Test = 0.6037`, `MAE = 6.45 USD/m²`).
* **`gap_arbitraje_pct`**: porcentaje de subvaluación frente al valor hedónico estimado.
* **`es_oportunidad_ml`**: booleano (`TRUE`/`FALSE`) que combina el umbral de arbitraje (`>= 20%`) con los filtros de viabilidad física y ambiental.
* **`flag_revision`**: marca `"REVISAR"` cuando `gap_arbitraje_pct >= 50%` (`30` casos dentro de las `184` oportunidades) para auditoría humana de posibles errores en el aviso, o `"OK"` en el resto.

### Campos calculados `HYPERLINK` recomendados en Looker Studio
Para permitir acceso directo desde las tablas de oportunidades a la publicación original y a la ubicación satelital/mapa de la zona:
* **`Ver Foto / Aviso`**:
  ```sql
  HYPERLINK(url_publicacion, "Ver Foto / Aviso")
  ```
* **`Ver Zona`**:
  ```sql
  HYPERLINK(url_google_maps, "Ver Zona")
  ```
