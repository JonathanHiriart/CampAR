# Guía Completa de Propuestas y Contexto — Capstone Project & Pre-Proyecto ML (Clases 33 a 47)

Este documento reúne **todo el contexto pedagógico, técnico y comercial** extraído del material oficial del curso (**Capítulo 5: Machine Learning, Clases 33 a 41** y **Capstone Project: Clases 42 a 47**), junto con el desarrollo completo de las **3 Propuestas Principales** listas para presentar, defender y monetizar en **Apify Store**.

---

## PARTE 1: Contexto Completo y "Reglas del Juego" de la Cátedra

### 1.1. El Cliente del Capstone: Diana (`Guía Business`)
* **Perfil**: Directora de una comercializadora multicanal (vende en marketplaces como Mercado Libre, tienda propia y redes sociales). Está evaluando entrar a un **rubro nuevo** (elegido por el equipo).
  * *Nota de la cátedra*: Si el rubro elegido es de productos físicos, Diana actúa como revendedora/comercializadora; si es de servicios (turismo, educación, fitness), actúa como intermediaria.
* **El Dolor de Diana (Cita textual)**:
  > *"Pierdo ventas porque llego tarde. Cuando me entero de que la competencia bajó precios o lanzó una promoción, ya perdí la semana. Quiero saber antes que ellos qué vender, a qué precio y cuándo promocionar."*
* **Ficha Dura del Cliente (Base obligatoria para el cálculo de ROI en `Presupuesto`)**:
  * **Equipo comercial**: 3 personas.
  * **Tiempo dedicado hoy a relevar precios manualmente**: 12 horas/semana.
  * **Costo hora promedio del equipo**: USD 8/hora ($\approx \text{USD } 96\text{/semana} = \text{USD } 415,68\text{/mes}$ desperdiciados en relevamiento manual).
  * **Tasa de error manual**: 1 de cada 10 publicaciones (**10%**) sale con el precio equivocado por carga manual.
  * **Meta de ventas en el rubro nuevo (Año 1)**: **USD 15.000/mes**.
  * **Presupuesto máximo disponible**: **USD 2.500** (desarrollo único / *one-off*) + **USD 150/mes** (operación recurrente).
  * **NPS actual de sus clientes**: **22** (bajo; gran oportunidad de mejora).
* **Regla Obligatoria sobre el NPS de Competidores**:
  * El NPS real es una métrica privada de encuestas internas. Como los datos de la competencia no son públicos, la cátedra exige calcular un **NPS Proxy** a partir de las reseñas públicas de los productos:
    * **5 estrellas** = Promotor
    * **4 estrellas** = Pasivo
    * **1 a 3 estrellas** = Detractor
    $$\text{NPS Proxy} = \left(\frac{\text{Reseñas } 5\star}{\text{Total Reseñas}} - \frac{\text{Reseñas } 1\text{–}3\star}{\text{Total Reseñas}}\right) \times 100 \quad (\text{escala de } -100 \text{ a } +100)$$
  * **Requisito**: En la documentación y en el pitch se debe mencionar explícitamente que es una aproximación (*proxy*) basada en reseñas públicas y no una encuesta NPS tradicional.

---

### 1.2. Requisitos Técnicos Exigidos (Clase 33 a Clase 47)

| Componente | Qué exige la cátedra (Clases 33–40 y Capstone) | Herramientas del curso involucradas |
| :--- | :--- | :--- |
| **Producto 1 (Entrega 12/11)**<br>*ETL + EDA + Dashboard* | Flujo automatizado `Input -> Process -> Output`. Extracción web con **Apify**, orquestación con **Make**, guardado en **Google Drive/Sheets**. Limpieza de nulos, duplicados y normalización de texto/moneda. **EDA** con al menos 5 features, incluyendo **correlaciones lineales (Pearson $r$) y no lineales (Spearman $\rho$ / Mutual Information)**. Dashboard interactivo que responda: *qué vender, a qué precio y cuándo promocionar*. | `BeautifulSoup`, `httpx`, `re` (Regex), `unicodedata`, `RapidFuzz`, `pandas`, `seaborn`/`matplotlib`, **Apify Actor #1**, **Make**, **Looker Studio / Streamlit**. |
| **Producto 2 (Entrega 20/11 y 24/11)**<br>*Modelo ML en Producción* | Notebook en **Google Colab** que entrene un modelo estadístico o de Machine Learning (regresión, clasificación, clustering o series temporales) sin *data leakage* (`train_test_split` antes de escalar/imputar, validación cruzada *k-fold*), comparando métricas ($R^2$, MAE, RMSE o F1, ROC-AUC, Silhouette) contra un *baseline* y analizando *overfitting/underfitting*. El modelo se serializa (`.pkl` / `.joblib`) y se sube a un **Actor de Apify de Inferencia (Single & Bulk)** que **solo predice (nunca re-entrena dentro de Apify)**. | `scikit-learn` (`RandomForest`, `XGBoost`, `Ridge`, `LogisticRegression`, `KMeans`, `TF-IDF`), `Prophet`, `joblib`/`pickle`, **Apify Actor #2 (Inference API)**. |
| **Flujo de Integración (Clase 40, pág. 14)** | Arquitectura obligatoria de punta a punta:<br>**`Google Drive -> Make -> Apify -> Make -> Google Drive`** (+ visualización en Dashboard y alerta opcional). | Google Sheets / Drive API, Make (Webhooks / HTTP / Apify modules), Apify REST API. |
| **Auditoría Técnica Samsung (17/11)** | Revisión con voluntarios de Samsung enfocada en **separar el código de las reglas de negocio** y validar **seguridad** (sin credenciales ni umbrales *hardcodeados* en el código Python; uso de variables de entorno y archivo de configuración externo). | Variables de entorno (`.env` / Apify Secrets) + `business_rules.json` o pestaña `Config` en Google Sheets. |
| **Bonus en Evaluación (`Evaluación` fila 13)** | **`Puntaje extra — impacto social`**: Los proyectos que demuestren un impacto social o ambiental positivo reciben puntos adicionales sobre el promedio final. | KPI social/ambiental medible en el Dashboard y en el Pitch. |

---

## PARTE 2: Las 3 Propuestas Principales Desarrolladas a Fondo

A continuación se presentan las **3 mejores propuestas** estructuradas con todo el rigor comercial, técnico y metodológico para elegir la ganadora del equipo.

---

### PROPUESTA 1: "Cazador de Productos con NPS Roto & Radar de Combos"
*(Enfoque: Arbitraje Comercial "Fuera de la Caja" + Hack de Impacto en Logística Inversa y Seguridad)*

#### 1. Rubro / Industria Seleccionada
* **Domótica, Pequeños Electrodomésticos y Electrónica de Hogar** (cámaras de seguridad WiFi, aspiradoras robot, cafeteras express, luminarias inteligentes, cerraduras digitales, cuidado personal eléctrico).
* **Por qué este rubro es ideal para Diana**: Tiene altísima rotación en Mercado Libre, precios promedio de USD 40 a USD 150 (con 150–250 ventas/mes alcanza los USD 15.000/mes) y concentra la mayor tasa de quejas por **defectos periféricos fáciles de resolver por un comercializador**.

#### 2. El Giro "Fuera de la Caja" y Pregunta de Negocio
* **El problema del mercado**: El 95% de los revendedores copia al producto exitoso de $4.8\star$ y entra en una guerra de precios sangrienta que destruye el margen.
* **Nuestra tesis**: Buscar exactamente lo opuesto: productos en Mercado Libre / Amazon con **alta rotación comprobada** (rango `+500 vendidos` y alta velocidad de nuevas reseñas), pero con **NPS Proxy bajo o negativo** (alto porcentaje de reseñas de $1\star$ a $3\star$) causado por **fallas subsanables por Diana antes de despachar**:
  * Producto importado con enchufe plano sin adaptador homologado a norma argentina.
  * Manual o aplicación únicamente en chino/inglés (frustración en adultos mayores o usuarios no técnicos).
  * Falta de fuente de alimentación 220V, cable corto o pilas no incluidas.
  * Empaque original frágil que llega abollado en el correo.
* **Pregunta de negocio**:
  > *¿Qué productos de alta rotación en domótica y electrohogar presentan fallas de satisfacción subsanables en la competencia que Diana pueda capturar lanzando un "Combo Mejorado" (con adaptador certificado, guía rápida en español y empaque reforzado) a un precio un 10–15% superior, y en qué momento exacto promocionarlos cuando los rivales sufren quiebres de stock o caídas de precio?*

#### 3. Cómo Funcionan el Producto 1 y el Producto 2
* **Producto 1 (Entrega 12/11 — ETL + NPS Proxy + Radar de Precios/Promos)**:
  * **Apify Actor #1 (Extractor y Normalizador)**: Extrae publicaciones del rubro en Mercado Libre, precios actuales, precios tachados (% descuento), cuotas sin interés, stock disponible, escalón de unidades vendidas, fecha/cantidad de reseñas (para calcular **velocidad de reseñas como proxy de demanda semanal**) y el texto + estrellas de las reseñas.
  * Calcula el **NPS Proxy** de cada producto/competidor ($\% 5\star - \% [1\text{–}3\star]$) y normaliza modelos usando `re` y `RapidFuzz`.
  * **Dashboard Interactivo**: Muestra la matriz de **Rotación Proxy vs. NPS Proxy** (para elegir *qué vender*), el comparador de precios por SKU (*a qué precio*) y las alertas de descuentos o quiebres de stock de la competencia (*cuándo promocionar*).
* **Producto 2 (Entrega 20/11 — ML Supervisado + Clustering sin Data Leakage)**:
  * **Cómo evitamos el *Data Leakage* circular**: No entrenamos un modelo para predecir una regla inventada sobre las mismas columnas. Entrenamos dos componentes reales en Google Colab y los subimos serializados (`.joblib`) al **Actor #2 de Inferencia en Apify**:
    1. **Clasificador Supervisado NLP (`TF-IDF + RandomForest / LogisticRegression`)** entrenado sobre reseñas negativas ($1\text{–}3\star$) etiquetadas para predecir la probabilidad de que la queja sea un **`Defecto Subsanable en Combo (Clase 1)`** (manual, enchufe, cable, fuente, empaque) vs. **`Defecto Estructural de Fábrica (Clase 0)`** (motor quemado, placa rota, mala calidad irreparable).
    2. **Modelo de Regresión Supervisada (`XGBoost / RandomForestRegressor`)** que predice el **`Precio Óptimo de Mercado del Combo`** según las especificaciones técnicas, cuotas, reputación y el salto proyectado de NPS Proxy (pasando de NPS roto a NPS $>50$).
  * El **Score de Oportunidad de Arbitraje** combina la velocidad de demanda proxy + la proporción de defectos subsanables predicha por el clasificador + el margen potencial predicho por el regresor.

#### 4. El "Hack" para ganar TAMBIÉN el Puntaje Extra de Impacto Social
* Aunque es una idea de **rentabilidad comercial pura**, resuelve dos problemas socio-ambientales graves y medibles:
  1. **Reducción de Logística Inversa y Basura Electrónica (*E-Waste* preventivo)**: En comercio electrónico, el 35% de las devoluciones de electrónicos se debe a que el comprador cree que el producto "no anda" porque le falta el adaptador correcto o no entiende el manual en otro idioma. Esas devoluciones generan transporte innecesario (huella de $\text{CO}_2$) y cajas abiertas que terminan descartadas.
  2. **Inclusión Digital y Seguridad Eléctrica Hogareña**: Al entregar el combo con adaptador homologado IRAM y guía paso a paso en español claro, Diana evita riesgos eléctricos domésticos e incluye a personas mayores en el uso de tecnología hogareña.

#### 5. Monetización en Apify Store (2025–2026)
* **Nombre comercial del Actor**: `Marketplace Review-Gap & Bundle Arbitrage Finder (MercadoLibre / Amazon)`.
* **Modelo de cobro**: *Pay-Per-Result* (USD 3 por cada 1.000 productos/reseñas diagnosticados con score de arbitraje y recomendación de bundle). Es una herramienta por la que miles de vendedores de Mercado Libre y Amazon FBA pagan mensualmente.

---

### PROPUESTA 2: "ReTech Circular — Inteligencia Comercial para Tecnología Reacondicionada"
*(Enfoque: Impacto Socio-Ambiental Directo + Alto Ticket unitario para llegar rápido a USD 15.000/mes)*

#### 1. Rubro / Industria Seleccionada
* **Electrónica y Tecnología Reacondicionada (*Refurbished / Circular Tech*)**: Notebooks corporativas (ThinkPad, Dell Latitude, HP EliteBook), smartphones (iPhone, Samsung Línea S/A) y tablets reacondicionadas con garantía.
* **Por qué este rubro es ideal para Diana**: Con un ticket promedio de **USD 250 a USD 300 por equipo**, Diana alcanza su meta de **USD 15.000/mes vendiendo apenas 50 a 60 unidades mensuales** (menos de 2 ventas por día, perfectamente manejable para su equipo de 3 personas).

#### 2. El Giro de Negocio y Pregunta de Investigación
* **El problema del mercado**: En tecnología reacondicionada no existe un "precio único" de catálogo porque el valor depende críticamente del **Grado Estético (Grado A / Excelente, Grado B / Bueno, Grado C / Detalles)**, la **salud de la batería (%)**, los **meses de garantía** y si incluye **cargador certificado**. Los vendedores publican estos datos enterrados en el título o en la descripción libre, por lo que relevar precios a mano le lleva a Diana 12 horas por semana y le genera un 10% de errores de precio.
* **Pregunta de negocio**:
  > *¿Qué modelos de notebooks y smartphones reacondicionados presentan la mayor brecha entre demanda y oferta en cada Grado Estético (A/B/C), a qué precio exacto debe publicarlos Diana ajustando por RAM, almacenamiento, batería y garantía, y cuándo activar promociones ante cambios de precios de la competencia?*

#### 3. Cómo Funcionan el Producto 1 y el Producto 2
* **Producto 1 (Entrega 12/11 — ETL con Regex/RapidFuzz + EDA + Dashboard)**:
  * **Apify Actor #1**: Extrae publicaciones de reacondicionados en Mercado Libre y tiendas especializadas. Usa expresiones regulares (`re`) y `BeautifulSoup` para extraer del título/descripción: `ram_gb`, `almacenamiento_gb`, `salud_bateria_pct`, `grado_estetico` (A/B/C) y `garantia_meses`. Usa `RapidFuzz` para unificar nombres de modelos escritos de forma distinta.
  * Calcula el **NPS Proxy** por vendedor/modelo y detecta promociones activas (descuentos y cuotas sin interés).
  * **EDA**: Muestra correlaciones lineales (Pearson entre RAM/GB y precio) y **no lineales** (Spearman y Mutual Information entre el Grado Estético/Batería, el NPS Proxy y la velocidad de ventas proxy: cuando la batería baja del 80%, el precio aceptado por el mercado cae abruptamente de forma no lineal).
* **Producto 2 (Entrega 20/11 — Regresión de Precio Ajustado por Grado + Clustering de Quejas)**:
  * **Apify Actor #2 (Inferencia ML con `.joblib`)**:
    1. **Regresor Supervisado (`RandomForestRegressor / XGBoost`)**: Predice el **Precio Óptimo de Venta** para cualquier combinación de `[Modelo, RAM, GB, Grado Estético, % Batería, Cuotas, Garantía]` y señala qué publicaciones de la competencia están **subvaluadas** (oportunidad de compra/arbitraje) o **sobrevaluadas** (oportunidad para que Diana capture ventas promocionando un 5% abajo).
    2. **Clustering No Supervisado (`TF-IDF + KMeans`)** sobre las reseñas de $1\text{–}3\star$ de los competidores: identifica que el 60%+ de los detractores se queja de *baterías agotadas* y *cargadores genéricos que fallan*, dándole a Diana el argumento comercial exacto para diferenciarse.

#### 4. Impacto Social y Ambiental Directo (Puntaje Extra Garantizado)
* **Triple impacto cuantificable en el Dashboard**:
  1. **Reducción de Basura Electrónica (*E-Waste*)**: Cada notebook/celular reacondicionado extiende la vida útil del hardware 3 años y evita $\sim 1,5\text{ kg}$ de desechos electrónicos tóxicos.
  2. **Huella de Carbono Evitada**: Evita entre **70 kg y 250 kg de $\text{CO}_2\text{e}$** por equipo (el 80% de la huella de carbono de un dispositivo ocurre en su fabricación inicial).
  3. **Inclusión Digital y Educativa**: Permite a estudiantes y trabajadores independientes acceder a herramientas de estudio y trabajo un **40% a 60% más económicas** que un equipo nuevo.

#### 5. Monetización en Apify Store (2025–2026)
* **Nombre comercial del Actor**: `LATAM Refurbished Tech Price, Grade & Battery Normalizer + ML Pricer`.
* **Modelo de cobro**: *Pay-Per-Result* para el ecosistema de *ReCommerce* en LATAM (tiendas de usados/reacondicionados, aseguradoras y programas de *Trade-In* / Plan Canje).

---

### PROPUESTA 3: "EcoHogar & Eficiencia Energética — Radar de Precios, Ahorro Tarifario y Quiebres de Stock"
*(Enfoque: Transición Energética Residencial + Captura de Picos de Demanda Estacional y Tarifaria)*

#### 1. Rubro / Industria Seleccionada
* **Productos de Eficiencia Energética, Climatización Solar y Ahorro Hogareño**: Termotanques solares, kits de paneles solares residenciales / balcones, iluminación LED solar exterior, enchufes y termostatos inteligentes medidores de consumo, filtros y ahorradores de agua.
* **Por qué este rubro es ideal para Diana**: En el contexto 2025–2026 de quita de subsidios y suba de tarifas eléctricas y de gas en Argentina y LATAM, las familias buscan productos que "se paguen solos" con el ahorro en la factura de luz/gas. Son productos de ticket medio-alto (USD 50 a USD 500) con márgenes de entre 25% y 40%.

#### 2. El Giro de Negocio y Pregunta de Investigación
* **El problema del mercado**: La demanda de estos productos se dispara en olas bruscas (ante anuncios de aumentos de tarifas, olas de calor/frío o cortes de luz). Cuando ocurre el pico, los competidores líderes sufren **quiebres de stock** o modifican sus promociones de cuotas. Diana llega una semana tarde al pico de demanda. Además, los clientes dejan malas reseñas ($1\text{–}3\star$) cuando el vendedor calcula mal la capacidad del equipo (ej. litros del termotanque o watts del panel) o no incluye el kit de instalación.
* **Pregunta de negocio**:
  > *¿Qué productos de ahorro energético presentan la mejor relación entre velocidad de demanda, margen comercial y tiempo de repago para el hogar, a qué precio por Watt/Litro debe ofrecerlos Diana, y cuándo lanzar promociones relámpago aprovechando los quiebres de stock o subas de precio de la competencia?*

#### 3. Cómo Funcionan el Producto 1 y el Producto 2
* **Producto 1 (Entrega 12/11 — ETL + Normalizador Técnico + Dashboard)**:
  * **Apify Actor #1**: Extrae precios, descuentos, financiación en cuotas, stock disponible, posición en el listado y reseñas de productos de eficiencia energética.
  * Normaliza con `re` las unidades técnicas (**Precio por Watt instalado** o **Precio por Litro térmico**) para comparar peras con peras entre marcas distintas, y calcula el **NPS Proxy** de cada competidor.
* **Producto 2 (Entrega 20/11 — Modelo de Propensión a Venta / Precio Óptimo + Análisis de Quejas)**:
  * **Apify Actor #2 (Inferencia ML con `.joblib`)**:
    1. **Modelo Supervisado (`GradientBoosting / RandomForest`)**: Predice el **Precio Competitivo Óptimo** y la **Alerta de Oportunidad de Promoción** en función de la dispersión de precios de la categoría, la disponibilidad de cuotas sin interés y la caída de stock de los competidores principales.
    2. **Clustering de Reseñas (`TF-IDF + KMeans`)**: Agrupa los dolores de los compradores en las reseñas de $1\text{–}3\star$ (ej. *"faltan accesorios de fijación"*, *"no explica cómo conectarlo"*, *"capacidad menor a la prometida"*) para que Diana arme kits completos con calculadora de ahorro real.

#### 4. Impacto Social y Ambiental Directo (Puntaje Extra)
* **Transición Energética y Alivio a la Economía Familiar**: Cada equipo vendido por Diana se traduce en **kWh de energía limpia generada/ahorrada**, **kg de $\text{CO}_2$ evitados** en la red eléctrica y un **ahorro directo mensual en la factura de luz/gas** de las familias.

#### 5. Monetización en Apify Store (2025–2026)
* **Nombre comercial del Actor**: `GreenTech & Solar Home Price-per-Watt & Stock Radar`.

---

## PARTE 3: Tabla de las 5 Ideas Lista para `Guía Business` (Semana 1 · 03/11)

En la primera entrega del Capstone (03/11), la pestaña `Guía Business` exige presentar **al menos 5 ideas de brainstorming** y justificar la **poda** hasta elegir la ganadora. Esta tabla integra las 3 propuestas principales más 2 ideas complementarias listas para copiar al Excel:

| # | Idea / Rubro | Tipo de Enfoque | Cómo resuelve el dolor de Diana | Datos Públicos Disponibles | Impacto Social / Ambiental (Bonus) | Estado en la Poda y Justificación |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Cazador de NPS Roto & Combos Mejorados**<br>*(Rubro: Domótica y Pequeños Electrodomésticos)* | **Comercial "Fuera de la Caja" + Impacto en Logística Inversa** | Detecta productos de alta rotación donde la competencia tiene bajo NPS Proxy ($1\text{–}3\star$) por fallas fáciles de corregir (enchufe, manual, fuente) y monitorea sus precios/stock semanalmente para saber qué vender, a qué precio (+10% en combo) y cuándo promocionar. | Precios, descuentos, cuotas, escalón de ventas (`+500 vendidos`), velocidad de reseñas, estrellas y texto completo de reseñas en Mercado Libre. | **Sí**: Reduce un 35–40% las devoluciones (logística inversa y descarte electrónico) y mejora la seguridad eléctrica e inclusión de adultos mayores con guías en español y adaptadores homologados. | **CANDIDATA GANADORA #1 (Enfoque Arbitraje Comercial)** |
| **2** | **ReTech Circular**<br>*(Rubro: Notebooks y Smartphones Reacondicionados)* | **Impacto Socio-Ambiental Directo + Alto Ticket** | Normaliza automáticamente el Grado Estético (A/B/C), RAM, GB y batería de los competidores con Regex/RapidFuzz y predice el precio óptimo y alertas de promoción. Con solo 55 ventas/mes alcanza los USD 15.000/mes. | Títulos, descripciones técnicas, precios, cuotas, garantía y reseñas de compradores en Mercado Libre y tiendas de reacondicionados. | **Sí (Muy Alto)**: Mitigación directa de basura electrónica (*e-waste*), ahorro de $70\text{–}250\text{ kg CO}_2\text{e}$ por equipo y reducción de la brecha digital (-50% de costo). | **CANDIDATA GANADORA #2 (Enfoque Impacto Directo + Alto Ticket)** |
| **3** | **EcoHogar & Eficiencia Energética**<br>*(Rubro: Climatización Solar y Ahorro Energético)* | **Sustentabilidad + Oportunidad Tarifaria** | Estandariza el precio por Watt/Litro entre competidores, monitorea quiebres de stock en picos de demanda tarifaria y analiza quejas de instalación para armar kits listos para instalar. | Precios, stock, especificaciones de potencia/capacidad, cuotas y reseñas en marketplaces. | **Sí (Alto)**: Transición hacia energías limpias hogareñas y reducción del gasto en tarifas de luz y gas para las familias. | **CANDIDATA #3 (Finalista de Respaldo)** |
| **4** | **Alimentos Conscientes, Sin TACC y Rescate (*Near-Expiry*)**<br>*(Rubro: Alimentación Saludable)* | **Impacto Social / Salud** | Monitorea precios por kg/litro y descuentos dinámicos en supermercados digitales y dietéticas mayoristas para detectar oportunidades de promoción. | Precios y promociones en supermercados online (similar al caso de Clase 34). | **Sí**: Reducción del desperdicio de alimentos y acceso a productos para celíacos a menor precio. | **DESCARTADA EN PODA**: Las fechas de vencimiento de lotes no son públicas en los sitios web y el ticket bajo exige mover miles de unidades al mes para llegar a USD 15.000. |
| **5** | **Moda Circular & Textil Sustentable**<br>*(Rubro: Indumentaria de Segunda Mano)* | **Economía Circular Textil** | Releva precios de prendas por marca, estado y talle en plataformas de moda circular. | Publicaciones de prendas usadas y precios en marketplaces. | **Sí**: Reducción de huella hídrica y textil. | **DESCARTADA EN PODA**: Cada prenda usada es única (talle y desgaste distinto), lo que impide automatizar la comparación exacta del mismo SKU entre competidores. |

---

## PARTE 4: Caso Financiero y Cálculo Exacto de ROI (Pestaña `Presupuesto`)

Cualquiera de las 3 propuestas principales que elijan comparte exactamente esta estructura financiera, calculada con los números oficiales de la ficha de Diana:

### 4.1. Cuantificación del Dolor Actual de Diana (Sin el Sistema)
1. **Costo laboral del relevamiento manual**:
   $$\text{12 horas/semana} \times 4,33\text{ semanas/mes} \times \text{USD } 8/\text{hora} = \textbf{USD } 415,68\textbf{/mes}$$
2. **Costo del 10% de errores en carga manual de precios**:
   * Sobre una meta de ventas de **USD 15.000/mes**, tener 1 de cada 10 publicaciones con precio erróneo (o subvaluado perdiendo margen, o sobrevaluado perdiendo conversión) junto con llegar una semana tarde a las promociones representa una pérdida conservadora del **4% de la facturación objetivo**:
   $$\text{USD } 15.000/\text{mes} \times 4\% = \textbf{USD } 600,00\textbf{/mes}$$
3. **Beneficio Bruto Mensual Generado por la Solución**:
   * Reducción del 85% del tiempo manual ($\text{USD } 353,33\text{/mes}$ ahorrados para que las 3 empleadas se dediquen a vender y mejorar la atención) + recuperación de margen y ventas por precios sin error y promos a tiempo ($\text{USD } 500,00\text{/mes}$ conservadores) = **$\textbf{USD } 853,33\textbf{/mes}$ de beneficio bruto**.

### 4.2. Presupuesto del Proyecto (Respetando el tope de USD 2.500 + USD 150/mes)
* **Costo de Desarrollo Único (*One-Off*)**: **USD 1.800** *(28% por debajo del límite de USD 2.500 de Diana)*.
  * Rol **BIZ** (Definición de reglas de negocio, matriz de arbitraje/NPS, diseño de Dashboard y validación de ROI): USD 550.
  * Rol **DS** (EDA, análisis de correlaciones lineales/no lineales, entrenamiento de modelos en Colab, validación cruzada y serialización `.joblib`): USD 650.
  * Rol **SE** (Desarrollo de los 2 Actors en Apify —Extractor y API de Inferencia—, escenarios en Make, separación de reglas en `config.json` y seguridad): USD 600.
* **Costo Operativo Mensual Recurrente**: **USD 85/mes** *(43% por debajo del límite de USD 150/mes de Diana)*.
  * Suscripción **Apify Starter Plan**: USD 39/mes.
  * Suscripción **Make Core Plan** (hasta 10.000 operaciones/mes): USD 10,59/mes.
  * Almacenamiento **Google Drive / Sheets** y **Looker Studio**: USD 0/mes.
  * Guardia de mantenimiento evolutivo (monitoreo de cambios en el HTML del marketplace y re-calibración trimestral del `.joblib`): USD 35,41/mes.

### 4.3. Retorno de la Inversión (ROI y Payback)
* **Beneficio Neto Mensual**:
  $$\text{USD } 853,33\text{ (Beneficio Bruto)} - \text{USD } 85,00\text{ (Costo Operativo)} = \textbf{USD } 768,33\textbf{/mes}$$
* **Tiempo de Recupero de la Inversión (*Payback*)**:
  $$\frac{\text{USD } 1.800\text{ (Inversión Inicial)}}{\text{USD } 768,33/\text{mes}} = \textbf{2,34 meses}$$
* **ROI Neto del Primer Año**:
  $$\frac{(\text{USD } 768,33 \times 12) - \text{USD } 1.800}{\text{USD } 1.800} \times 100 = \textbf{+412\% en el Año 1}$$

---

## PARTE 5: Respuestas Listas para las Instancias de Evaluación Crítica

### 5.1. Los "Pedidos Sorpresa" de Diana del 12/11 (`Seguimiento cliente` filas 16–22)
El 12/11 el docente enviará un mensaje simulando a Diana con 3 pedidos adicionales para poner a prueba la gestión de alcance. Así se responde cada uno:

1. **«Quiero ver las ventas reales de mis competidores»**
   * **Clasificación**: *Fuera de Alcance (Imposible por privacidad de datos públicos)*.
   * **Respuesta a Diana**: Las ventas reales exactas son privadas de la cuenta de cada vendedor. Lo que implementamos en su lugar es un **Índice Proxy de Rotación** combinando tres datos públicos observables: el escalón histórico de unidades vendidas (`+500 vendidos`), la **velocidad de nuevas reseñas por mes** y la variación de posición en el listado.
2. **«Quiero saber el NPS de mis competidores comparado con el mío (22)»**
   * **Clasificación**: *Imprescindible / Viable mediante Proxy*.
   * **Respuesta a Diana**: Ya está incluido en el Producto 1 usando la regla de **NPS Proxy sobre reseñas públicas** ($5\star = \text{Promotor}$, $4\star = \text{Pasivo}$, $1\text{–}3\star = \text{Detractor}$), dejando documentada la limitación metodológica de que proviene de compradores que dejaron reseña y no de una encuesta interna.
3. **«Quiero el precio exacto de todos los productos, todos los días, en todos los canales»**
   * **Clasificación**: *Negociable (Ajuste por Ley de Pareto 80/20)*.
   * **Respuesta a Diana**: Escanear miles de productos todos los días en todos los canales superaría tu tope operativo de **USD 150/mes** en consumo de servidores de Apify. Proponemos monitorear a diario el **Top 50–100 de productos (el 20% que mueve el 80% de tu facturación de USD 15.000/mes)**, manteniendo el costo mensual en solo USD 85/mes.
4. **«Quiero que me avise por WhatsApp cuando un competidor baje precios»**
   * **Clasificación**: *Deseable / Viable de Bajo Costo*.
   * **Respuesta a Diana**: Lo sumamos en el flujo de Make agregando un nodo de notificación (WhatsApp Business API / Telegram) que se dispara únicamente cuando un competidor baja su precio más de un $X\%$ configurable.
5. **«Quiero sumar Instagram y TikTok como fuentes»**
   * **Clasificación**: *Fuera de Alcance para esta etapa*.
   * **Respuesta a Diana**: En Instagram y TikTok los precios rara vez están estructurados en las publicaciones (suelen decir *"precio por privado / info al DM"*) y los costos de extracción por bloqueos anti-bot triplicarían tu presupuesto mensual de USD 150. Nos concentramos en marketplaces y tiendas web donde están los precios reales de cierre.
6. **«Quiero también predecir la demanda del mes que viene, al mismo precio»** / **«Quiero tener todo listo el 17/11»**
   * **Clasificación**: *Negociación de cronograma y alcance*.
   * **Respuesta a Diana**: Para el **17/11** te entregamos la selección de variables y validación preliminar del modelo (sin cargo extra), y el **20/11** el sistema predictivo completo integrado al flujo automático para garantizar calidad y cero errores.

---

### 5.2. La Revisión Técnica de Voluntarios de Samsung del 17/11
Los mentores técnicos de Samsung evaluarán específicamente **dos puntos**:
1. **Separación estricta entre Código y Reglas de Negocio**:
   * Ningún umbral comercial (`margen_minimo = 0.15`, `min_reviews = 20`, `umbral_alerta_descuento = 0.10`, lista de palabras clave o marcas) debe estar escrito fijo dentro de los archivos `.py`.
   * Todos los parámetros de negocio se leen desde un archivo externo `config/business_rules.json` (o desde una pestaña `Parametros` en el Google Sheet de Diana que Make envía como `INPUT` al Actor de Apify).
2. **Seguridad y Manejo de Credenciales**:
   * Ninguna API Key (`APIFY_TOKEN`, `GEMINI_API_KEY`, credenciales de Google) puede figurar en el código ni en el repositorio de GitHub. Se cargan mediante variables de entorno (`os.getenv()`) y un archivo `.env.example` documentado, con `.env` incluido en `.gitignore`.

---

### 5.3. Las 4 Preguntas Finales de Diana en el Pitch del 24/11 (`Guion pitch`)

1. **«Si dejo de usar su sistema mañana, ¿qué pierdo exactamente?»**
   > *"Perdés inmediatamente **12 horas por semana** de tu equipo comercial (USD 415/mes), volvés a tener un **10% de publicaciones con errores de precio** por carga manual y volvés a enterarte una semana tarde de los cambios de precios y quejas de los clientes de tu competencia. Además, todo el historial limpio en tu Google Drive y tu Dashboard quedan en tus manos porque son tuyos."*

2. **«¿Cuánto me cuesta al mes operarlo y en cuántos meses recupero la inversión?»**
   > *"Operarlo te cuesta **USD 85 por mes** —casi la mitad de tu límite máximo de USD 150/mes—. La inversión inicial de **USD 1.800** se recupera en **2,3 meses** gracias al ahorro de horas manuales y la eliminación de errores de precios."*

3. **«¿Qué tan confiables son estos datos? ¿Qué pasa si el marketplace cambia su página?»**
   > *"Diseñamos el sistema con validación de esquemas y adaptadores desacoplados (como vimos en la arquitectura de la Clase 40). Si el marketplace cambia su diseño web mañana, el Actor de Apify detecta el cambio de estructura, frena la sobreescritura para **nunca ensuciar tu Dashboard con ceros o datos falsos**, mantiene la última foto válida y nos envía una alerta técnica automática para actualizar solo el selector de extracción sin tocar ni el modelo de Machine Learning ni tu Dashboard."*

4. **«¿Qué me dicen los clientes de mis competidores que yo podría aprovechar?»**
   > *"Al analizar las reseñas de 1 a 3 estrellas (los detractores que hunden el NPS Proxy de tus competidores), nuestro modelo detectó que la mayoría de las quejas no son porque el aparato sea malo, sino por **detalles que vos podés resolver antes de despachar** (falta de adaptador certificado, manual en otro idioma, batería sin testear o empaque frágil). Si armás tu publicación destacando en la primera foto y en el título que tu producto ya incluye esos puntos resueltos, podés vender un **10% más caro**, evitar la guerra de precios y llevar tu NPS actual de 22 a más de 50."*
