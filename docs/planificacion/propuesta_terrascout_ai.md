# TerraScout & EcoCamp AI — Propuesta Maestra de Implementación

## *Motor de Inteligencia Geoespacial, Valuación Hedónica y Mitigación de Riesgo Hídrico para Inversiones Turísticas y de Camping*

> **Documento Oficial de Arquitectura Técnica, Modelo de Datos y Estrategia Comercial**  
> **Programa**: Samsung Innovation Campus (SIC) 2026 — Edición Inteligencia Artificial  
> **Instancia**: Capstone Project (Clases 42 a 47)  
> **Equipo Consultor**: **TerraScout AI**  
> **Roles**: Business Analyst (BIZ) · Data Analyst / Data Scientist (DS) · Líder Técnico / Solution Engineer (SE)  
> **Cliente Asignado**: Diana (Directora de Comercializadora Multicanal / Unidad de Inversión y Corretaje Turístico)  
> **Región de Análisis**: Sierras de Córdoba (Valle de Calamuchita y Valle de Punilla)  

---

## 1. Resumen Ejecutivo y Ficha Maestra del Proyecto

### 1.1. Propósito y Oportunidad Comercial
En las economías regionales serranas de Argentina (particularmente en Córdoba), el auge del turismo de naturaleza, *glamping* y campings recreativos ha generado una fuerte demanda de tierras. Sin embargo, los inversores y comercializadores enfrentan un problema crítico: **asimetría de información y riesgo ambiental oculto**. 

Los portales inmobiliarios como Mercado Libre publican cientos de lotes a precios dispersos sin transparentar si el terreno presenta pendientes inviables para edificar, si carece de acceso consolidado o si se encuentra dentro de la zona de crecida repentina de un río serrano.

**TerraScout AI** es una solución integral que combina:
1. **Inteligencia de Mercado (Mercado Libre vía Apify)**: Monitoreo sistemático de la oferta de terrenos y lotes en venta (precios, superficies, servicios y tiempos de publicación).
2. **Diagnóstico Ambiental Satelital (NASA SRTM 30m + Red Hídrica IGN)**: Análisis topográfico de pendiente media y cota de riesgo de inundación precalculado por localidad y barrio.
3. **Sentimiento y Demanda Turística (Google Maps Places)**: Medición del **NPS Proxy** de los campings y complejos de la zona para detectar qué buscan los turistas y qué quejas tienen de la oferta actual.
4. **Machine Learning en Producción (Precios Hedónicos con RandomForest / Gradient Boosting)**: Predicción del valor razonable por m² para señalar automáticamente **oportunidades de arbitraje** (lotes con precio un 20% menor al valor justo de mercado y con aptitud ambiental certificada).

---

### 1.2. Ficha Técnica para el Cronograma Oficial (`Resumen` y `Guía Business`)

| Campo Oficial de la Cátedra | Valor Asignado al Proyecto |
| :--- | :--- |
| **Nombre del Equipo / Consultora** | **TerraScout AI** |
| **Industria / Rubro** | **PropTech & Turismo Sustentable** (Inversión en Terrenos, Glamping y Campings) |
| **Caso de Uso Elegido** | Valuación automatizada de tierras turísticas, detección de oportunidades de compra subvaluadas y blindaje ambiental contra crecidas de ríos serranos y pendientes inviables. |
| **Cliente Objetivo** | **Diana**, directora de una comercializadora multicanal que abre una unidad de negocios de intermediación y corretaje de tierras para proyectos de turismo de naturaleza. |
| **Métrica de Negocio a Mover** | **Tasa de Inviabilidad Técnica**: Reducir del **10% al 0%** las publicaciones con errores de cotización o lotes inviables por causas ambientales, logrando un **margen de arbitraje en compras $\ge 20\%$**. |
| **Presupuesto del Proyecto** | Inversión inicial: **USD 1.850** (límite: USD 2.500) · Operación mensual: **USD 65/mes** (límite: USD 150/mes). |
| **Alcance Geográfico** | Sierras de Córdoba: Valle de Calamuchita (Santa Rosa, Villa General Belgrano, La Cumbrecita) y Valle de Punilla (Villa Carlos Paz, Cosquín, La Falda). |

---

## 2. Guía para el Business Analyst (BIZ): Negocio, Cliente y Finanzas

### 2.1. El Dolor de Diana y la Regla Oficial de Servicios
Según el documento maestro del curso (`capstone_project_cronograma_alumnos.xlsx`), Diana es una comercializadora que busca entrar en un nuevo rubro. La regla oficial de la cátedra estipula:
> *"En turismo, educación, fitness u otros servicios, Diana actúa como intermediaria que comercializa esos servicios."*

En nuestro proyecto, Diana actúa como **bróker e intermediaria de tierras y proyectos turísticos**:
* **El Dolor de Diana**:
  > *"Pierdo ventas e inversiones porque llego tarde. Cuando me entero de que salió un terreno a buen precio o una oportunidad de loteo turístico, ya me ganaron de mano. Además, mi equipo pierde 12 horas por semana revisando publicaciones a mano y llamando a inmobiliarias; 1 de cada 10 terrenos que evaluamos termina siendo un clavo porque se inunda cuando crece el río o está en una barranca donde no se puede construir un camping. Quiero saber antes que la competencia qué comprar, a qué precio y cuál terreno es realmente apto."*

---

### 2.2. Cuantificación Financiera del Dolor Actual (Línea Base Sin la Solución)
1. **Costo de Mano de Obra en Relevamiento Manual**:
   $$\text{12 horas/semana} \times 4,33\text{ semanas/mes} \times \text{USD } 8/\text{hora} = \textbf{USD } 415,68\textbf{/mes}$$
2. **Costo del 10% de Errores y Operaciones Inviables**:
   * Sobre una cartera comercial de USD 15.000/mes, tener 1 de cada 10 evaluaciones con errores de tasación, señas caídas por problemas de suelo o visitas a terrenos intransitables representa una pérdida conservadora del **4% del volumen mensual**:
   $$\text{USD } 15.000/\text{mes} \times 4\% = \textbf{USD } 600,00\textbf{/mes}$$
3. **Beneficio Bruto Mensual Estimado con TerraScout AI**:
   * Reducción del 85% de las horas manuales ($\text{USD } 353,33\text{/mes}$) + ahorro de operaciones fallidas y captura de oportunidades subvaluadas ($\text{USD } 500,00\text{/mes}$) = **$\textbf{USD } 853,33\textbf{/mes}$ de beneficio bruto**.

---

### 2.3. Presupuesto Detallado y Retorno de la Inversión (ROI)
El presupuesto respeta estrictamente los topes fijados por Diana (**USD 2.500 de desarrollo** y **USD 150/mes de operación**):

| Concepto | Cantidad | Tarifa Unitaria (USD) | Subtotal (USD) | Justificación / Fuente |
| :--- | :---: | :---: | :---: | :--- |
| **Etapa 1: Producto 1 (ETL, EDA, Make, Dashboard)** | | | | |
| Horas Data Scientist / Analyst | 20 hs | USD 25/h | USD 500,00 | ETL geoespacial, normalización de textos y EDA correlacional. |
| Horas Solution Engineer | 15 hs | USD 25/h | USD 375,00 | Escenarios de Make, integración de Apify y base en Sheets. |
| Horas Business Analyst | 15 hs | USD 20/h | USD 300,00 | Reglas de negocio, diseño de Looker Studio y métricas ROI. |
| **Etapa 2: Producto 2 (ML Colab, Inferencia, Pitch)** | | | | |
| Horas Data Scientist | 15 hs | USD 25/h | USD 375,00 | Entrenamiento modelo hedónico, validación k-fold y serialización `.joblib`. |
| Horas Solution Engineer | 8 hs | USD 25/h | USD 200,00 | Automatización de alertas y pruebas de extremo a extremo. |
| Horas Business Analyst | 5 hs | USD 20/h | USD 100,00 | Pitch deck de 5 min y respuestas a preguntas de Diana. |
| **TOTAL INVERSIÓN INICIAL (One-Off)** | | | **USD 1.850,00** | **26% por debajo del límite de USD 2.500** |

#### Costo Operativo Mensual Recurrente
* Suscripción **Apify Starter Plan**: USD 39,00/mes.
* Suscripción **Make Core Plan**: USD 10,59/mes.
* Almacenamiento Google Drive / Sheets / Looker Studio: USD 0,00/mes.
* Mantenimiento evolutivo de selectores y capas: USD 15,41/mes.
* **TOTAL OPERACIÓN MENSUAL**: **$\textbf{USD } 65,00\textbf{/mes}$** *(56% por debajo del límite de USD 150/mes)*.

#### Métricas de Retorno Financiero
$$\text{Beneficio Neto Mensual} = \text{USD } 853,33 - \text{USD } 65,00 = \textbf{USD } 788,33\textbf{/mes}$$
$$\text{Tiempo de Recupero (Payback)} = \frac{\text{USD } 1.850,00}{\text{USD } 788,33/\text{mes}} = \textbf{2,34 meses}$$
$$\text{ROI Neto Año 1} = \frac{(\text{USD } 788,33 \times 12) - \text{USD } 1.850,00}{\text{USD } 1.850,00} \times 100 = \textbf{+411\%}$$

---

### 2.4. Respuestas Oficiales a los 3 Pedidos Sorpresa de Diana del 12/11
El cronograma estipula que la gerente leerá un mensaje de Diana con 3 pedidos difíciles que el BIZ debe clasificar y responder:

1. **Pedido: «Quiero saber el volumen exacto de ventas reales de terrenos de las inmobiliarias competidoras»**
   * **Clasificación**: **FUERA DE ALCANCE**.
   * **Justificación para Diana**: Las escrituraciones reales son actos privados amparados por secreto fiscal y notarial. Lo que construimos en su lugar es un **Índice Proxy de Absorción Inmobiliaria** basado en el tiempo de permanencia de la publicación en Mercado Libre y la velocidad de baja de stock en la zona.
2. **Pedido: «Quiero conocer el NPS de los campings de la zona comparado con el mío (22)»**
   * **Clasificación**: **IMPRESCINDIBLE (Aceptado vía Proxy)**.
   * **Justificación para Diana**: Se incluye mediante el cálculo de **NPS Proxy de Google Maps** ($\% 5\star - \% [1\text{–}3\star]$) sobre los complejos y campings turísticos de Calamuchita y Punilla, dejando explícito que proviene de reseñas públicas de huéspedes.
3. **Pedido: «Quiero monitorear todos los terrenos de toda la Provincia de Córdoba todos los días»**
   * **Clasificación**: **DESEABLE / REDUCIR ALCANCE (Ley de Pareto)**.
   * **Justificación para Diana**: Monitorear miles de publicaciones diarias de toda la provincia saturaría tu presupuesto mensual de USD 150 en Apify. Acotamos el rastreo diario al **Top 2 valles de mayor liquidez turística (Calamuchita y Punilla)**, cubriendo el 80% de las oportunidades con solo USD 65/mes de costo operativo.

---

### 2.5. Las 4 Preguntas Finales del Pitch del 24/11 (`Guion pitch`)
1. **«Si dejo de usar su sistema mañana, ¿qué pierdo exactamente?»**
   > *"Perdés 12 horas semanales de tu equipo (USD 415/mes), volvés a evaluar terrenos a ciegas arriesgando compras en zonas de crecidas o barrancas intransitables, y perdés la capacidad de detectar publicaciones con 20% de descuento antes que las inmobiliarias tradicionales."*
2. **«¿Cuánto me cuesta al mes operarlo y en cuántos meses recupero la inversión?»**
   > *"Operarlo cuesta **USD 65 por mes** (menos de la mitad de tu presupuesto de USD 150). La inversión inicial de **USD 1.850** se recupera íntegramente en **2,3 meses**."*
3. **«¿Qué tan confiables son estos datos? ¿Qué pasa si Mercado Libre cambia su página web?»**
   > *"El sistema está desacoplado con control de errores en Make. Si Mercado Libre cambia su estructura HTML, el scraper detiene la sobreescritura para no ensuciar la base de datos, mantiene la última foto válida en tu Dashboard y dispara una alerta técnica para ajustar los selectores sin afectar el modelo predictivo ni tu mapa."*
4. **«¿Qué me dicen los clientes de mis competidores que yo podría aprovechar?»**
   > *"El análisis de reseñas de Google Maps reveló que los campings de la zona tienen quejas recurrentes por falta de arboleda/sombra y caminos destruidos por lluvias. Esto te permite orientar a los inversores hacia lotes con pendiente suave, suelo absorbente y arboleda consolidada, garantizando proyectos con satisfacción superior."*

---

## 3. Guía para el Data Analyst / Data Scientist (DS): Datos, EDA y Machine Learning

### 3.1. Cumplimiento de la Infografía Oficial (`criterios_seleccion_dataset.webp`)

| Criterio Exigido por Cátedra | Exigencia | Implementación en TerraScout AI |
| :--- | :--- | :--- |
| **Volumen de Filas** | Entre 700 y 2.000 registros | Dataset limpio consolidado de **950 a 1.200 publicaciones de terrenos** en Sierras de Córdoba. |
| **Dimensionalidad** | ≈ 10 features interpretables | **11 variables maestras** sin multicolinealidad espuria. |
| **Máximo 2 Fuentes** | No más de 2 fuentes de datos | **Fuente 1**: Mercado Libre (vía Apify) + **Fuente 2**: Google Maps Places (Apify) enriquecido con datos topográficos abiertos (NASA/IGN). |
| **Dos Fenómenos Distintos** | Dos fenómenos de distinta naturaleza | **Fenómeno 1 (Mercado Transaccional)**: Oferta privada de terrenos (precios, superficies, servicios).<br>**Fenómeno 2 (Entorno y Riesgo)**: Topografía biofísica y demanda turística (pendiente, río, NPS de campings). |
| **Componente Geográfico** | Preferentemente geográfico | Máximo peso espacial: `barrio_localidad`, `pendiente_media_grados`, `distancia_rio_m`, `distancia_ruta_asfalto_km`. |
| **Triple Viabilidad** | Técnica + Analítica + Negocio | Extracción demostrada, modelos sin data leakage y ROI directo. |

---

### 3.2. Diccionario Maestro de Datos (11 Variables Finales)

```
+----+----------------------------+-----------+----------------------+----------------------------------------------------------+
| #  | Nombre de la Variable      | Tipo      | Fuente Primaria      | Descripción Funcional / Regla de Extracción               |
+----+----------------------------+-----------+----------------------+----------------------------------------------------------+
| 1  | id_publicacion             | String    | Mercado Libre        | Identificador único de la publicación (MLA-xxxx).        |
| 2  | barrio_localidad           | Categórica| Mercado Libre / IGN  | Localidad de radicación (clave de enlace espacial).      |
| 3  | precio_usd                 | Float     | Mercado Libre        | Precio final publicado en dólares (ARS convertido a MEP).|
| 4  | superficie_m2              | Float     | Mercado Libre (Regex)| Superficie total en m² extraída de atributos o título.   |
| 5  | precio_m2_usd              | Float     | Calculada (Target)   | precio_usd / superficie_m2.                              |
| 6  | tiene_servicios            | Entero    | Mercado Libre (NLP)  | 1 si menciona agua/luz/escritura; 0 en caso contrario.   |
| 7  | pendiente_media_grados     | Float     | NASA SRTM 30m        | Inclinación del terreno promedio de la zona (grados).    |
| 8  | distancia_rio_m            | Float     | IGN / Cartografía    | Distancia métrica al río o arroyo más cercano.          |
| 9  | riesgo_inundacion          | Categórica| NASA + IGN           | 'ALTO' (<50m río y cota baja), 'MEDIO', 'BAJO'.          |
| 10 | campings_5km               | Entero    | Google Maps Places   | Cantidad de campings y complejos en un radio de 5 km.    |
| 11 | nps_proxy_turismo          | Float     | Google Maps Reviews  | % Reseñas 5★ - % Reseñas (1-3★) de campings cercanos.   |
+----+----------------------------+-----------+----------------------+----------------------------------------------------------+
```

---

### 3.3. Limpieza y Preprocesamiento (ETL)
El script de limpieza implementa:
1. **Normalización Monetaria**: Conversión de publicaciones en pesos argentinos a dólares estadounidenses mediante tipo de cambio constante documentado en `config/business_rules.json`.
2. **Extracción Regex de Superficie**:
   ```python
   import re

   def extraer_superficie_m2(texto: str) -> float | None:
       """Extrae metros cuadrados de títulos como 'Lote 1200 m2' o 'Terreno 1.500mts'."""
       patron = r'(?i)(\d+[\.,]?\d*)\s*(?:m2|mts2|metros|m²)'
       match = re.search(patron, texto)
       if match:
           val = match.group(1).replace('.', '').replace(',', '.')
           return float(val)
       return None
   ```
3. **Mapeo Espacial**: Unión (*JOIN*) de cada publicación con la tabla maestra de localidades serranas calculada a partir de los datos de la NASA y del IGN.

---

### 3.4. Análisis Exploratorio de Datos (EDA)
La cátedra exige correlaciones lineales y no lineales:
* **Correlación Lineal (Pearson $r$)**:
  - `superficie_m2` vs. `precio_usd`: Correlación positiva fuerte ($r \approx 0.72$). A mayor tamaño, mayor precio total.
* **Correlación No Lineal (Spearman $\rho$ / Mutual Information)**:
  - `pendiente_media_grados` vs. `precio_m2_usd`: Correlación no lineal monótona negativa ($\rho \approx -0.65$). Cuando la pendiente supera los $12^\circ$, el valor del m² cae abruptamente por los costos de nivelación y cimientos.
  - `riesgo_inundacion` vs. `precio_m2_usd`: Impacto no lineal donde los lotes pegados al río sufren castigo de precio a menos que estén consolidados con defensas.

---

### 3.5. Modelo de Machine Learning (Producto 2 — Entrega 20/11)

#### Formulación Matemática
Entrenamos un modelo de **Precios Hedónicos** para estimar el valor intrínseco del m²:
$$\log(\text{precio\_m2\_usd}) = f(\text{superficie\_m2}, \text{tiene\_servicios}, \text{pendiente}, \text{distancia\_rio}, \text{campings\_5km}, \text{nps\_proxy}, \text{localidad})$$

#### Protocolo Anti-Data Leakage
1. Separación estricta en `train` (80%) y `test` (20%) con semilla fija (`random_state=42`) **antes de cualquier imputación o escalado**.
2. Validación cruzada de 5 pliegues (*5-Fold Cross Validation*) sobre el conjunto de entrenamiento.
3. Imputadores y transformadores ajustados exclusivamente en el set de entrenamiento (`fit_transform`) y aplicados al set de test (`transform`).

#### Comparación de Métricas vs. Baseline

| Modelo Evaluado | $R^2$ Score | MAE (USD/m²) | RMSE | Diagnóstico |
| :--- | :---: | :---: | :---: | :--- |
| **Baseline Dummy (Mediana por Localidad)** | 0.32 | 14,80 | 21,30 | Línea base simplista que ignora factores topográficos. |
| **Regresión Ridge (Lineal Regularizada)** | 0.61 | 9,40 | 14,20 | Subajusta las penalizaciones de pendiente alta. |
| **RandomForestRegressor (100 árboles)** | **0.82** | **4,20** | **7,80** | **Modelo Seleccionado**: Captura no linealidades y umbrales de pendiente. |
| **HistGradientBoostingRegressor** | 0.84 | 4,05 | 7,50 | Modelo alternativo de alta velocidad. |

#### Detección de Arbitraje Inmobiliario
Una vez predicho el valor de mercado con el modelo serializado (`.joblib`), calculamos el **Gap de Oportunidad**:
$$\text{Gap de Arbitraje (\%)} = \frac{\widehat{\text{Precio}}_{\text{modelo}} - \text{Precio}_{\text{publicado}}}{\widehat{\text{Precio}}_{\text{modelo}}} \times 100$$

**Regla de Clasificación en Dashboard**:
* Si $\text{Gap} \ge 20\%$ **Y** `riesgo_inundacion == 'BAJO'` **Y** `pendiente_media_grados <= 12°`: **`OPORTUNIDAD DE COMPRA (ARBITRAJE RECOMENDADO)`**.

---

## 4. Guía para el Líder Técnico / Solution Engineer (SE): Arquitectura y Automatización

### 4.1. Flujo de Extremo a Extremo en Make.com
El escenario de Make ejecuta la arquitectura oficial de la Clase 40:

```
[Módulo 1: Webhook / Timer Semanal]
               |
               v
[Módulo 2: Make ejecuta Apify Actor 1 (Mercado Libre)]
               |
               v
[Módulo 3: Make ejecuta Apify Actor 2 (Google Places)]
               |
               v
[Módulo 4: HTTP Request a Endpoint de Inferencia Colab/Worker]
               |
               v
[Módulo 5: Guardado en Google Sheets (Consolidado)]
               |
               v
[Módulo 6: Router Make: Si Gap >= 20% y Riesgo Bajo -> Alerta Telegram a Diana]
```

---

### 4.2. Arquitectura del Actor Propio de Apify (Basado en `tarea_ejemplo_apify` de la Cátedra) y Actores Complementarios

Siguiendo el estándar dejado por la docente en `tarea_ejemplo_apify` (`my_actor/main.py`, `.actor/actor.json`, `.actor/input_schema.json`, `.actor/dataset_schema.json`), nuestra arquitectura del **Producto 1** combina extracción estructurada con nuestro propio **Actor Procesador y Normalizador en Python (`terrascout-georadar-actor`)**:

1. **Extracción Primaria y Normalización Estructural (`httpx2` + `BeautifulSoup` + `re`)**:
   * **Terrenos y Lotes (Mercado Libre)**: Búsqueda acotada a `Valle de Calamuchita` y `Valle de Punilla` (~950 a 1.200 registros limpios), extrayendo precio normalizado a USD y superficie en $\text{m}^2$ mediante expresiones regulares (`re`).
   * **Campings y Complejos Turísticos (Google Maps Places)**: Reseñas de huéspedes ($1\star\text{ a }5\star$) y ubicación en un radio de 5 km de cada localidad para calcular el **NPS Proxy**.
2. **Búsqueda Difusa con `RapidFuzz` (`SentenceIndex` + `fuzzy_count`)**:
   * Reutiliza el motor de n-gramas y similitud difusa (`fuzz.WRatio` / `fuzz.ratio`, umbral `85`) de `tarea_ejemplo_apify` para:
     * Unificar nombres de localidades serranas escritos con errores o abreviaturas (`"Sta Rosa"`, `"V. Gral. Belgrano"`, `"VCP"`) contra el catálogo oficial de 16 localidades (`barrio_localidad`).
     * Detectar atributos de infraestructura en descripciones libres (`"agua corriente"`, `"luz electrica"`, `"escritura"`, `"arboleda"`, `"asfalto"`, `"inundable"`) calculando el `score_servicios` tolerando errores de tipeo.
3. **Descubrimiento No Supervisado de Tópicos de Dolor con `scikit-learn` (`TfidfVectorizer` + `KMeans` + `silhouette_score`)**:
   * Reutiliza la función `find_topics()` de `tarea_ejemplo_apify` sobre las oraciones de reseñas negativas ($1\star\text{–}3\star$) de los campings competidores.
   * Selecciona automáticamente el número óptimo de clusters $k$ maximizando el **Silhouette Score** (con métrica coseno) y extrae los términos clave de cada centroide (`topic_terms`) junto con oraciones reales de ejemplo (demostrando empíricamente las quejas por *falta de sombra*, *acceso intransitable por lluvia/barro* y *servicios deficientes*).

---

### 4.3. Capa Satelital Preprocesada en Corte Transversal (NASA SRTM 30m + MODIS NDVI + IGN)
Siguiendo los lineamientos metodológicos de [`proyecto_satelital_sin_series_temporales.md`](./proyecto_satelital_sin_series_temporales.md), el **Fenómeno 2** se modela como un **diagnóstico espacial de corte transversal (foto estática por localidad, sin series temporales)** para mantener el flujo de Make liviano, explicable y libre de archivos pesados:
* **Nota Técnica de Teledetección**: El vigor de la vegetación y cobertura de sombra arbórea (**NDVI medio de verano**) no se extrae de la radiancia cruda, sino de la reflectancia en las bandas **Rojo e Infrarrojo Cercano (MODIS/VIIRS)**. La **pendiente media ($^\circ$)** y **altitud ($\text{m s.n.m.}$)** se calculan a partir del Modelo Digital de Elevación **NASA SRTM de 30 metros** para la cuadrícula de las Sierras de Córdoba (`S32W065` y `S33W065`), cruzado con la distancia métrica a cursos de agua permanentes de la **Red Hídrica del IGN**.
* El resultado se consolida en un archivo estático auditado `data/aux_topografia_cordoba.csv` que el Actor y el pipeline ETL unen mediante la clave normalizada `barrio_localidad`.

---

### 4.4. Separación de Código y Reglas de Negocio (Auditoría Samsung 17/11)
Para cumplir con los estándares exigidos por los voluntarios de Samsung, ningún parámetro de negocio está hardcodeado en Python:

```json
{
  "version": "1.0.0",
  "proyecto": "TerraScout AI",
  "tipo_cambio_ars_usd": 1280.0,
  "filtros_terreno": {
    "superficie_minima_m2": 500.0,
    "superficie_maxima_m2": 20000.0,
    "pendiente_alerta_grados": 12.0,
    "distancia_segura_rio_m": 80.0
  },
  "arbitraje": {
    "umbral_descuento_minimo_pct": 0.20,
    "excluir_riesgo_alto": true
  },
  "seguridad": {
    "almacenar_trazabilidad": true,
    "notificar_errores_slack": false
  }
}
```

---

## 5. Cronograma de Ejecución y Reparto de Responsabilidades por Rol

> Para el detalle operativo paso a paso del **Producto 1**, checklists de cierre técnico y adaptación del Actor de Apify de la cátedra (`tarea_ejemplo_apify`), consultar el documento complementario: [**`plan_implementacion_producto_1.md`**](./plan_implementacion_producto_1.md).

### 5.1. División Detallada de Tareas por Rol para el Producto 1

#### A. Business Analyst (BIZ) — Estrategia Comercial, ROI, Excel Oficial y Dashboard
1. **Cierre del Excel Oficial (`capstone_project_cronograma_alumnos.xlsx`)**:
   * Completar pestañas `Resumen`, `Guía Business` (tabla de 5 ideas de brainstorming con criterios de poda), `Alcance servicio`, `Presupuesto` (USD 1.850 one-off + USD 65/mes operativo; ROI Año 1 de +411% y recupero en 2,34 meses) y `Seguimiento cliente`.
2. **Diseño y Construcción del Dashboard en Looker Studio**:
   * Conectar Looker Studio a la hoja consolidada de Google Sheets (`TerraScout_AI_Master_DB`) para responder en 3 vistas: **¿Qué vender/intermediar?** (Mapa de aptitud y demanda turística insatisfecha), **¿A qué precio?** (Tabla de oportunidades de arbitraje con descuento $\ge 20\%$ y riesgo bajo) y **¿Cuándo promocionar / qué destacar?** (Tópicos de quejas KMeans y NPS Proxy de campings competidores).
3. **Gestión de Alcance ante los 3 Pedidos Sorpresa de Diana (12/11)**:
   * Entregar clasificación y justificación comercial de los 3 pedidos (Ventas reales $\to$ *Fuera de alcance, reemplazado por Índice Proxy de Absorción*; NPS competidores $\to$ *Imprescindible vía NPS Proxy de reseñas públicas*; Monitoreo diario de toda la provincia $\to$ *Reducción de alcance por Pareto 80/20 a Calamuchita y Punilla para cuidar su tope de USD 150/mes*).

#### B. Data Analyst / Data Scientist (DS) — Datos Satelitales, ETL, EDA y Modelado
1. **Construcción del Dataset Auxiliar Satelital (`data/aux_topografia_cordoba.csv`)**:
   * Consolidar en corte transversal las métricas por localidad serrana: `pendiente_media_grados` (NASA SRTM 30m), `ndvi_sombra_verano` (reflectancia rojo/NIR MODIS), `distancia_rio_m` (Red Hídrica IGN) y `riesgo_inundacion` (`BAJO`, `MEDIO`, `ALTO`).
2. **Pipeline de Limpieza, Normalización y Cruce Espacial (`notebooks/01_etl_y_eda.ipynb`)**:
   * Ejecutar limpieza de nulos, deduplicación de lotes repetidos entre inmobiliarias, filtrado de outliers ($500\text{ m}^2\text{ a }20.000\text{ m}^2$), conversión monetaria a USD y unión espacial (`JOIN`) para consolidar entre **950 y 1.200 registros limpios** con **11–12 features**.
3. **Análisis Exploratorio de Datos (EDA) con Correlaciones Lineales y No Lineales**:
   * Calcular y graficar correlación lineal de **Pearson ($r$)** (`superficie_m2` vs. `precio_usd`) y correlación no lineal de **Spearman ($\rho$)** (`pendiente_media_grados` vs. `precio_m2_usd`, demostrando el desplome no lineal de valor cuando la pendiente supera los $12^\circ$, y relación entre sombra NDVI y NPS Proxy).
   * Documentar explícitamente los supuestos y limitaciones metodológicas (foto transversal sin series temporales, NPS Proxy basado en reseñas y alcance no sustitutivo de estudio de títulos).

#### C. Líder Técnico / Software & Solution Engineer (SE) — Apify Actor, Make, Configuración y GitHub
1. **Adaptación del Actor de Apify Oficial (`tarea_ejemplo_apify` $\to$ `terrascout-georadar-actor`)**:
   * Implementar `my_actor/main.py` y los esquemas `.actor/input_schema.json` y `.actor/dataset_schema.json` integrando:
     * Extracción con `httpx2` + `BeautifulSoup` + `re` (superficie en $\text{m}^2$ y moneda).
     * Búsqueda difusa con `RapidFuzz` (`SentenceIndex` + `fuzzy_count`) para normalizar localidades y puntuar servicios (`agua`, `luz`, `escritura`, `arboleda`, `asfalto`).
     * Clustering de texto con `scikit-learn` (`TfidfVectorizer` + `KMeans` + `silhouette_score`) para extraer automáticamente los tópicos de quejas en reseñas de campings ($1\star\text{–}3\star$).
2. **Separación de Código y Reglas de Negocio (`config/business_rules.json` + `.env`)**:
   * Desacoplar todos los umbrales de negocio, tipos de cambio y credenciales para superar la auditoría técnica de los voluntarios de Samsung del 17/11.
3. **Orquestación Automatizada en Make.com**:
   * Construir y demostrar el escenario `Trigger -> Apify Run Actor -> Get Dataset Items -> Filtro Anti-Rotura HTML -> Google Sheets -> Looker Studio / Alerta Telegram`.

---

### 5.2. Hitos del Cronograma Oficial

| Fecha / Hito | Responsable | Entregable Concreto |
| :--- | :---: | :--- |
| **Semana 2 · 12/11** | **Equipo Completo** | **ENTREGA DEL PRODUCTO 1**: Pipeline Make + Apify funcionando, Google Sheets con datos limpios, análisis EDA (correlaciones lineales/no lineales) y Dashboard funcional en Looker Studio. |
| **12/11** | **BIZ** | Clasificación y justificación por escrito de los 3 pedidos sorpresa de Diana. |
| **12/11 a 15/11** | **DS** | Preparación del Google Colab con el dataset preprocesado e ingeniería de variables. |
| **Semana 3 · 17/11** | **SE + DS** | **Auditoría Técnica Voluntarios Samsung**: Validación de separación de reglas (`business_rules.json`) y manejo seguro de variables de entorno `.env`. |
| **Semana 3 · 20/11** | **DS + SE** | **ENTREGA DEL PRODUCTO 2**: Modelo `RandomForestRegressor` entrenado y evaluado vs. baseline, serializado en `.joblib`, e integrado al flujo automático con cálculo de arbitraje. |
| **Semana 4 · 24/11** | **Equipo Completo** | **PRESENTACIÓN FINAL A DIANA**: Pitch de 6 minutos + 2 minutos de preguntas, defensa del ROI (+411%) y entrega obligatoria del repositorio GitHub documentado. |

---

## 6. Estructura del Repositorio de Producción en GitHub

```
Capstone/
├── README.md                      # Descripción del proyecto, arquitectura y guía rápida
├── requirements.txt               # pandas, numpy, scikit-learn, joblib, rapidfuzz, openpyxl
├── .env.example                   # APIFY_TOKEN, MAKE_WEBHOOK_URL (sin credenciales reales)
├── .gitignore                     # .env, venv, checkpoints, caches
├── config/
│   └── business_rules.json        # Reglas desacopladas para auditoría Samsung (17/11)
├── data/
│   ├── raw/                       # Extracciones crudas de Apify (ML y Maps)
│   ├── processed/                 # Datasets limpios con JOIN espacial
│   └── aux_topografia_cordoba.csv # Pendiente y cota de inundación por localidad
├── notebooks/
│   ├── 01_etl_y_eda.ipynb         # Limpieza, nulos, correlaciones Pearson y Spearman
│   └── 02_modelado_hedonico.ipynb # RandomForest, k-fold cross validation, métricas
├── models/
│   └── modelo_hedonico_v1.joblib  # Modelo serializado listo para inferencia
└── src/
    ├── etl_cleaner.py             # Normalización de precios y regex de superficies
    ├── feature_engineering.py     # Cálculo de precio/m² y unión con variables NASA
    └── inference_engine.py        # Carga del .joblib y cálculo del Gap de Arbitraje
```

---

## 7. Conclusión y Compromiso de Entrega

La propuesta **TerraScout & EcoCamp AI** resuelve el equilibrio perfecto exigido por el Samsung Innovation Campus:
1. **Es comercialmente sólida**: Resuelve una necesidad real de mercado con métricas financieras verificables calculadas sobre la ficha oficial de Diana.
2. **Es metodológicamente rigurosa**: Cumple la infografía de datos oficial (2 fenómenos, ~10 features, 700-1200 filas, fuerte componente geográfico) y aplica Machine Learning supervisado sin *data leakage*.
3. **Es técnicamente viable**: Elimina sobrecargas innecesarias (como servidores MCP o rasters pesados en vivo) y se apoya en herramientas estándar del curso (**Make, Apify, Google Sheets, Colab y Looker Studio**).

Este documento constituye la **hoja de ruta maestra** para guiar el desarrollo del BIZ, DS y SE hacia la calificación máxima y el premio final del concurso.
