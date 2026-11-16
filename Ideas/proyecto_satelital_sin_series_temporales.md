# Mapa satelital de riesgo y aptitud territorial en Argentina (sin series temporales)

**Idea 3: información satelital (vegetación, humedad de suelo, temperatura, focos de calor) + datos públicos argentinos y de NASA, aplicada como diagnóstico espacial.**

> Nota técnica: la humedad del suelo y la vegetación no salen directamente de la radiancia óptica. El **NDVI/EVI** (vigor de la vegetación) se calcula con reflectancia en rojo e infrarrojo cercano. La **humedad de suelo** se estima con microondas (temperatura de brillo de SMAP, retrodispersión SAR de SAOCOM o Sentinel-1). El proyecto debe presentarse así.

---

## 1. Idea central

En lugar de **predecir o monitorear en el tiempo**, el proyecto **diagnostica y mapea en el espacio**: toma una "foto" resumida por zona (departamento, celda de grilla, parcela) y la cruza con eventos o variables del terreno para producir un **índice de riesgo o de aptitud**.

- **Fenómeno 1:** condiciones ambientales medidas desde satélite (vegetación, humedad, temperatura superficial, precipitación acumulada, relieve).
- **Fenómeno 2:** eventos, usos o resultados en el terreno (focos de calor y áreas quemadas, inundaciones registradas, rendimientos, atractivos turísticos, precios de tierra).
- **Cruce:** qué combinación de condiciones se asocia con riesgo alto o con alta aptitud, y cuánto vale eso en dinero.

## 2. Pregunta de negocio

¿Dónde conviene asegurar, invertir, construir, comprar o promocionar según el estado de la vegetación, la humedad y el riesgo ambiental, y cuánto dinero se evita perder o se gana al decidir con esta información?

## 3. Por qué es factible sin series temporales

| Enfoque | Qué se hace | Técnica |
|---|---|---|
| Corte transversal | Un valor resumen por zona y campaña o temporada (NDVI máximo, humedad media, precipitación acumulada) | Correlación y regresión múltiple entre zonas |
| Antes y después | Comparar dos fechas alrededor de un evento (incendio, inundación) | Diferencia de índices (dNDVI, NBR) y superficie afectada |
| Anomalía precalculada | Usar productos que ya traen la desviación respecto del promedio histórico | Lectura directa, sin modelar la serie |
| Modelos tabulares | Cada fila (zona y campaña) como observación independiente | Regresión logística, árbol de decisión, random forest |
| Análisis espacial | Agrupar zonas parecidas y detectar concentraciones | k-means, DBSCAN, Moran local, Getis-Ord |
| Índice compuesto | Score con variables ponderadas y umbrales, validado con eventos reales | Reglas transparentes y fáciles de explicar |

**Combinación recomendada:** corte transversal por campaña + 2 o 3 eventos con detección de cambio + índice compuesto validado contra eventos reales.

**Cuidado al validar:** separar por año o por región, no al azar, para no inflar los resultados.

## 4. Cómo encaja con los criterios del proyecto

| Criterio | Cómo se cumple |
|---|---|
| 700 a 2.000 registros | Departamentos × campañas (ej. 300 × 3 a 5), o celdas de grilla sobre una región |
| ~10 features | NDVI medio, humedad de suelo, temperatura superficial, precipitación acumulada, pendiente, altitud, distancia a agua, focos de calor, superficie afectada, zona |
| Pocos nulos | Agregar por zona y evitar fechas con nubosidad |
| Máximo 2 fuentes | Una de NASA y una argentina |
| Dos fenómenos | Condiciones satelitales y eventos o usos en el terreno |
| Geográfico | Muy fuerte |
| Viabilidad técnica, analítica y de negocio | Alta si se acota a una región y un caso de uso |

## 5. Fuentes de datos

**NASA (fuente 1, elegir lo mínimo necesario):**
- MODIS/VIIRS: NDVI, EVI, temperatura superficial.
- SMAP: humedad de suelo (resolución gruesa, escala regional).
- GPM IMERG: precipitación.
- FIRMS: focos de calor activos.
- SRTM u otro modelo de elevación: altitud y pendiente.
- Landsat o HLS para más detalle espacial.

**Argentina (fuente 2):**
- CONAE (SAOCOM, mapas de humedad e inundaciones).
- SMN (estaciones y precipitación).
- Plan Nacional de Manejo del Fuego (áreas quemadas).
- Ministerio de Agricultura (rendimientos y superficie sembrada).
- IGN y datos.gob.ar (límites, rutas, red hídrica).
- Parques Nacionales y catastros provinciales, según el caso de uso.

Verificar siempre disponibilidad, actualización y licencia de cada fuente antes de un uso comercial. Una forma de reducir el trabajo de procesamiento es usar Google Earth Engine, que ya incluye varios de estos productos.

## 6. Casos de uso

### 6.1 Seguros y agro (caso base)
- Zonificación de riesgo de sequía, exceso hídrico e incendio para tarificar.
- Índice para seguros paramétricos (el pago se dispara al cruzar un umbral).
- Riesgo de crédito agropecuario y priorización de monitoreo.

### 6.2 Incendios e inundaciones
- Mapa de zonas con vegetación seca y baja humedad para prevención de incendios.
- Mapa de zonas anegables para obras, caminos, energía y municipios.

### 6.3 Zonas de camping en la Patagonia para promover el turismo local

**Pregunta:** ¿qué zonas combinan buenas condiciones (acceso, agua, abrigo, paisaje, bajo riesgo) y hoy están poco aprovechadas o poco promocionadas?

| Variable | Fuente posible | Qué aporta |
|---|---|---|
| Vegetación (NDVI) | MODIS/VIIRS | Cobertura de bosque, sombra, paisaje |
| Humedad de suelo y vegetación seca | SMAP o proxy de NDVI | Riesgo de incendio y suelo anegado |
| Distancia a ríos y lagos | IGN o OpenStreetMap | Acceso a agua y atractivo |
| Pendiente y altitud | SRTM | Aptitud para acampar y acceso |
| Distancia a rutas y localidades | IGN o OpenStreetMap | Accesibilidad |
| Superficie afectada por incendios | Manejo del Fuego | Zonas a evitar o recuperar |
| Oferta existente (campings, refugios, alojamientos) | Datos provinciales o de turismo | Brecha entre oferta y potencial |

- **Producto:** mapa de aptitud para camping con un score por celda, y ranking de zonas con alto potencial y poca oferta.
- **Quién paga o se beneficia:** municipios y direcciones de turismo, cooperativas y emprendedores locales, comunidades originarias que gestionan territorio, operadores de turismo aventura, plataformas de reservas.
- **Impacto social:** distribuir el turismo hacia localidades menos visitadas, generar ingresos locales y descomprimir sitios saturados.
- **Salvaguardas:** excluir áreas protegidas con restricciones, zonas de riesgo (incendio, crecida) y territorios con regulaciones comunitarias. Un mapa que "promueve" nuevos sitios puede aumentar la presión sobre ecosistemas frágiles, así que conviene declarar capacidad de carga y restricciones.

### 6.4 Análisis de terrenos en la Patagonia para decidir cuáles conviene comprar

**Pregunta:** ¿qué terrenos ofrecen mejor relación entre precio, riesgo ambiental y potencial de uso (turismo, vivienda, producción)?

| Variable | Fuente posible | Qué aporta |
|---|---|---|
| Precio por hectárea o por lote | Portales inmobiliarios o catastro (verificar términos de uso) | Costo de entrada |
| Vegetación y estado del suelo | MODIS/VIIRS, SMAP | Aptitud de uso y riesgo |
| Pendiente, altitud, orientación | SRTM | Edificabilidad y exposición al viento |
| Distancia a agua, rutas, servicios y localidades | IGN o OpenStreetMap | Accesibilidad y valor de uso |
| Riesgo de incendio e inundación | FIRMS, Manejo del Fuego, CONAE | Pérdida potencial |
| Entorno turístico | Datos provinciales | Potencial de renta |

- **Producto:** ranking de terrenos o zonas con un índice de oportunidad (potencial dividido por precio y riesgo), mapa de calor y fichas por lote.
- **Quién paga:** inversores, desarrolladoras, inmobiliarias, estudios de tasación, emprendedores de turismo, bancos.
- **Aspectos legales a verificar antes de cualquier operación:** régimen de tierras rurales (Ley 26.737 y su reglamentación, con límites a la titularidad extranjera), títulos y dominio, zonificación municipal, servidumbres de paso y acceso, áreas protegidas, aptitud de uso del suelo y estado de agua y servicios. El satélite no reemplaza la verificación catastral, el estudio de títulos ni la inspección en el lugar.
- **Esto es información general y no asesoramiento financiero ni legal.** Una decisión de compra requiere consultar a un profesional (escribano, abogado, tasador).

### 6.5 Otros usos posibles
- Planificación de riego y de uso del suelo.
- Protección de líneas eléctricas, rutas y gasoductos frente a incendios o crecidas.
- Evaluación de recuperación de vegetación tras incendios.
- Reportes de cumplimiento para financiamiento verde.
- Turismo rural y de naturaleza (miradores, circuitos, avistaje).
- Selección de sitios para energía solar o eólica con criterio ambiental.

## 7. Cómo se vende

**Propuesta de valor:** reducir pérdidas y mejorar decisiones de ubicación con información objetiva, actualizada y de bajo costo, en lugar de visitas y estudios caros.

| Producto | Cliente | Modelo de ingresos |
|---|---|---|
| Mapa de riesgo por zona | Aseguradoras, bancos agrícolas, cooperativas | Informe por proyecto o licencia anual |
| Mapa de aptitud turística | Municipios, turismo, emprendedores | Consultoría por proyecto, tablero con suscripción |
| Ranking de terrenos | Inversores, inmobiliarias, tasadores | Reporte por zona o por lote |
| Tablero interactivo con actualización | Todos los anteriores | Suscripción mensual |

**Cómo justificar el precio:** traducir todo a dinero con supuestos declarados: pérdida evitada, prima ajustada, ingreso turístico estimado o diferencia de precio frente al potencial del terreno.

**Competidores y alternativas (verificar su estado actual antes de citarlos):** Planet Labs, Farmers Edge, Cropin, Climate FieldView, Descartes Underwriting, Satellogic, Auravant, Kilimo, servicios del INTA y de la CONAE, y consultoras de SIG y tasación.

**Diferencial posible:** foco en Argentina y en la Patagonia, integración de datos oficiales locales, costo accesible para municipios y pymes, y reporte entendible por quien decide.

## 8. Limitaciones (declararlas en el proyecto)

- **Foto, no película:** sin series temporales no hay pronóstico ni alerta anticipada. Se presenta como mapa de riesgo o aptitud, no como sistema de monitoreo.
- **Estacionalidad:** un mismo lugar puede verse muy distinto según la fecha elegida. Conviene fijar una ventana estacional comparable (por ejemplo, verano) y justificarla.
- **Resolución:** SMAP tiene resolución de decenas de kilómetros, lo que limita el análisis a escala regional. Para parcelas se necesitan productos de mayor resolución.
- **Validación:** sin datos reales de eventos o de precios no se puede calibrar ni validar el índice. El fenómeno 2 es crítico.
- **Datos de precio de terrenos:** pueden ser escasos, inconsistentes o sujetos a términos de uso que prohíben el scraping.
- **Patagonia:** nubosidad, nieve y sombras de relieve pueden afectar los índices ópticos. Revisar la calidad de cada pixel y los máscaras de nubes y nieve.
- **Correlación no es causalidad:** un índice alto no garantiza un buen terreno o un sitio seguro.
- **Un portafolio demuestra capacidad;** para cobrar se necesita validar con datos del cliente.

## 9. Plan de trabajo sugerido

1. **Definir el caso de uso y la región** (por ejemplo, camping en una provincia o un corredor, o terrenos en una localidad).
2. **Elegir las dos fuentes** y la ventana temporal fija (una temporada o campaña).
3. **Agregar por zona** (departamento o celda de grilla) y construir una tabla de 700 a 2.000 filas con ~10 variables.
4. **Limpiar:** nulos, nubes y nieve, escalas y unidades.
5. **Análisis exploratorio y espacial:** correlaciones, mapas, agrupamientos y puntos calientes.
6. **Construir el índice** (compuesto o modelo tabular) y **validarlo** contra eventos u oferta real, separando por año o región.
7. **Traducir a dinero** con supuestos declarados.
8. **Armar el entregable:** mapa de calor, ranking de zonas, tablero y un resumen de limitaciones.

## 10. Posibles títulos

- Riesgo desde el espacio: mapa satelital de riesgo y aptitud territorial para Argentina
- De la imagen al dato: dónde acampar, invertir o asegurar en la Patagonia
- Antes de decidir, mirá desde arriba: índice satelital de riesgo y oportunidad territorial

(Evitar "radiancia" en el título: el proyecto usa sobre todo índices derivados.)

## 11. Próximos pasos sugeridos

- Elegir **un solo caso de uso** para la primera versión (camping, terrenos o riesgo agro) y dejar los demás como extensiones.
- Definir la **región** y la **ventana estacional**.
- Listar las **columnas concretas** de los dos datasets y el plan de limpieza.
- Confirmar disponibilidad y licencia de cada fuente.
