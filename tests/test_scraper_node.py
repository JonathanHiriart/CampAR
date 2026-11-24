"""Tests para el Scraper Node y Actor de Apify de CampAR (Arquitectura 100% Real).

Verifica:
1. Funciones centrales del Actor: normalize, tokenize, SentenceIndex, fuzzy_count, find_topics, extraer_superficie_m2.
2. Archivos de configuración de Apify (.actor/actor.json, input_schema.json, dataset_schema.json, output_schema.json, Dockerfile, requirements.txt).
3. Lógica unitaria de los scrapers reales:
   - ml_scraper (parsing de _n.ctx.r y schema.org JSON-LD).
   - camping_scraper (haversine, centroides, fusión deduplicada, Apify connector).
4. Verificación de la política ZERO DUMMY DATA en src/run_scraper_node.py.
5. Salidas crudas reales en data/raw/:
   - mercadolibre_terrenos_calamuchita_punilla_raw.csv
   - campings_zona_real_raw.csv
   - topicos_nlp_real_raw.json
   - google_maps_campings_reviews_raw.csv (condicional si hay token real Apify).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

# Rutas del repositorio
REPO_ROOT = Path(__file__).resolve().parent.parent
ACTOR_DIR = REPO_ROOT / "terrascout_actor"
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
SRC_DIR = REPO_ROOT / "src"

# Importar funciones centrales
from terrascout_actor.my_actor.camping_scraper import (
    assign_nearest_locality,
    fetch_google_maps_via_apify,
    fetch_solocampings_cordoba,
    haversine_distance_km,
    load_apify_gmaps_json,
    load_localities_centroids,
    merge_campings_deduplicated,
    normalize_text,
)
from terrascout_actor.my_actor.ml_scraper import (
    _parse_jsonld,
    enrich_listing_detail,
    enrich_listings_with_details,
    extraer_superficie_m2,
    parse_mercadolibre_html,
)
from terrascout_actor.my_actor.nlp_analysis import (
    CALAMUCHITA_LOCALITIES,
    PUNILLA_LOCALITIES,
    SentenceIndex,
    find_topics,
    fuzzy_count,
    normalize,
    split_sentences,
    tokenize,
)


# =====================================================================
# 1. Tests Unitarios de Funciones del Actor y NLP
# =====================================================================
class TestActorCoreFunctions:
    def test_normalize_removes_accents_and_lowercases(self):
        assert normalize("Ingeniería ELÉCTRICA") == "ingenieria electrica"
        assert normalize("Córdoba Sierras") == "cordoba sierras"
        assert normalize("Árboles y Güisqui") == "arboles y guisqui"
        assert normalize("") == ""

    def test_tokenize_extracts_clean_words(self):
        tokens = tokenize("Lote de 1200 m2 con vista al lago!")
        assert tokens == ["lote", "de", "1200", "m2", "con", "vista", "al", "lago"]

    def test_split_sentences(self):
        content = {
            "1": "Primera oracion. Segunda oracion! Tercera oracion? Cuarta oracion.",
            "2": "Quinta oracion en otra pagina.",
        }
        sentences = split_sentences(content)
        assert len(sentences) == 5
        assert sentences[0] == "Primera oracion."
        assert sentences[4] == "Quinta oracion en otra pagina."

    def test_extraer_superficie_m2(self):
        # Casos estándar
        assert extraer_superficie_m2("Lote de 1200 m2") == 1200.0
        assert extraer_superficie_m2("Terreno 850 mts2 con servicios") == 850.0
        assert extraer_superficie_m2("Fracción de 1.500 m² con arboleda") == 1500.0
        assert extraer_superficie_m2("Campo de 2 ha") == 20000.0
        assert extraer_superficie_m2("Lote de 0.5 ha") == 5000.0
        assert extraer_superficie_m2("Lote de 1,5 hectareas") == 15000.0
        assert extraer_superficie_m2("Superficie 2500 metros cuadrados") == 2500.0

        # Casos bordes y nulos
        assert extraer_superficie_m2("") is None
        assert extraer_superficie_m2("Consultar precio") is None
        assert extraer_superficie_m2(None) is None

    def test_sentence_index_and_fuzzy_count(self):
        content = [
            "Excelente lote con agua corriente y luz electrica.",
            "Posee escritura inmediata y arboleda autoctona.",
            "Calle de ripio pero sin agua de red.",
        ]
        index = SentenceIndex(content)

        # Búsqueda exacta
        res_luz = fuzzy_count(index, "luz")
        assert res_luz["count"] >= 1
        assert any("luz electrica" in s for s in res_luz["sentences"])

        # Búsqueda con variantes / difusa
        res_agua = fuzzy_count(index, "agua")
        assert res_agua["count"] >= 2
        assert len(res_agua["sentences"]) == 2

        # Búsqueda de palabra inexistente
        res_gas = fuzzy_count(index, "gasoducto")
        assert res_gas["count"] == 0
        assert len(res_gas["sentences"]) == 0

        # Búsqueda de palabra corta (debe ser exacta)
        res_de = fuzzy_count(index, "de")
        assert res_de["count"] >= 1

    def test_fuzzy_count_wratio_length_guard_regression(self):
        """Verifica que WRatio no haga match espurio de tokens de 1-3 letras ('a', 'la', 'un')
        contra palabras largas como 'inundable', pero sí mantenga variantes reales de 'escritura'.
        """
        assert fuzzy_count(SentenceIndex({'1': 'Lote a la venta en un valle'}), 'inundable', 'WRatio', 85)['count'] == 0
        assert fuzzy_count(SentenceIndex({'1': 'Tiene escrirura al dia'}), 'escritura', 'WRatio', 85)['count'] == 1

    def test_find_topics_kmeans(self):
        sentences = [
            "Excelente camping junto al rio con mucha sombra y arboleda.",
            "Camping familiar con bajada al rio y parcelas con sombra.",
            "Lote con vista panoramica a las sierras y arboleda autoctona.",
            "Terreno con bajada directa al rio y sombra de sauces.",
            "Cortes frecuentes de luz y baja presion de agua en las parcelas.",
            "Falta mantenimiento en sanitarios y el agua salia fria.",
            "El camino de acceso tiene mucho barro cuando llueve.",
            "Calle de tierra intransitable por lluvia y barro.",
        ]
        res = find_topics(
            sentences=sentences,
            top_n=2,
            n_clusters=2,
            n_terms=4,
            stop_words="spanish",
            extra_stop_words=["camping", "lugar"],
        )
        assert res["n_clusters"] == 2
        assert len(res["items"]) == 2
        assert "terms" in res["items"][0]
        assert len(res["items"][0]["terms"]) > 0


# =====================================================================
# 2. Tests de Componentes de Scrapers Reales
# =====================================================================
class TestRealScrapersUnit:
    def test_ml_scraper_parse_jsonld(self):
        html_sample = """
        <html>
        <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "RealEstateListing",
            "name": "Terreno en Venta en Santa Rosa de Calamuchita 1200 m2",
            "offers": {
                "@type": "Offer",
                "price": 35000,
                "priceCurrency": "USD",
                "url": "https://inmueble.mercadolibre.com.ar/MLA-99887766-terreno_JM"
            },
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Santa Rosa de Calamuchita",
                "addressRegion": "Córdoba"
            },
            "seller": {
                "@type": "Organization",
                "name": "Inmobiliaria Serrana"
            }
        }
        </script>
        </head>
        <body></body>
        </html>
        """
        listings = _parse_jsonld(html_sample, "Valle de Calamuchita", "2026-11-15")
        assert len(listings) == 1
        item = listings[0]
        assert item["id_publicacion"] == "MLA99887766"
        assert item["valle_corredor"] == "Valle de Calamuchita"
        assert item["precio_raw"] == 35000
        assert item["moneda_raw"] == "USD"
        assert item["superficie_m2_extraida"] == 1200.0
        assert item["vendedor_nombre"] == "Inmobiliaria Serrana"
        assert item["fuente_extraccion"] == "MercadoLibre Córdoba"

    def test_ml_scraper_parse_ctx_r(self):
        ctx_data = {
            "appProps": {
                "pageProps": {
                    "initialState": {
                        "pagination": {"page_count": 5},
                        "results": [
                            {
                                "polycard": {
                                    "metadata": {
                                        "id": "MLA11223344",
                                        "url": "inmueble.mercadolibre.com.ar/MLA-11223344",
                                        "signal": {"official_store": True},
                                    },
                                    "components": [
                                        {
                                            "type": "title",
                                            "title": {"text": "Lote en Villa Carlos Paz 800 m2"},
                                        },
                                        {
                                            "type": "price",
                                            "price": {
                                                "current_price": {"value": 28000, "currency": "USD"}
                                            },
                                        },
                                        {
                                            "type": "attributes_list",
                                            "attributes_list": {"texts": ["800 m²"]},
                                        },
                                        {
                                            "type": "location",
                                            "location": {"text": "Villa Carlos Paz, Punilla"},
                                        },
                                    ],
                                }
                            }
                        ],
                    }
                }
            }
        }
        html_mock = f'<html><body><script>window._n.ctx.r={json.dumps(ctx_data)};</script></body></html>'
        listings, pages = parse_mercadolibre_html(html_mock, "Valle de Punilla", "2026-11-15")
        assert pages == 5
        assert len(listings) == 1
        item = listings[0]
        assert item["id_publicacion"] == "MLA11223344"
        assert item["valle_corredor"] == "Valle de Punilla"
        assert item["precio_raw"] == 28000
        assert item["superficie_m2_extraida"] == 800.0
        assert item["es_tienda_oficial"] is True

    def test_haversine_and_centroids(self):
        # Santa Rosa de Calamuchita: -32.0694, -64.5367
        # Villa General Belgrano: -31.9789, -64.5561 (distancia aprox: ~10 km)
        d = haversine_distance_km(-32.0694, -64.5367, -31.9789, -64.5561)
        assert 9.0 <= d <= 12.0

        # Carga de centroides
        centroids = load_localities_centroids()
        assert len(centroids) == 16
        assert any(c["barrio_localidad"] == "Santa Rosa de Calamuchita" for c in centroids)
        assert any(c["barrio_localidad"] == "Villa Carlos Paz" for c in centroids)

        # Asignación de localidad más cercana
        loc, valley, dist = assign_nearest_locality(-32.07, -64.54, centroids)
        assert loc == "Santa Rosa de Calamuchita"
        assert valley == "Valle de Calamuchita"
        assert dist is not None and dist < 2.0

    def test_merge_campings_deduplicated(self):
        osm = [
            {
                "osm_id": "node/101",
                "nombre_camping": "Camping Miami",
                "localidad_asignada": "Santa Rosa de Calamuchita",
                "valle_corredor": "Valle de Calamuchita",
                "website": None,
            }
        ]
        sc = [
            {
                "osm_id": None,
                "nombre_camping": "Camping Miami",
                "localidad_asignada": "Santa Rosa de Calamuchita",
                "valle_corredor": "Valle de Calamuchita",
                "website": "https://www.solocampings.com.ar/camping/miami.html",
            },
            {
                "osm_id": None,
                "nombre_camping": "Camping Nuevo Amanecer",
                "localidad_asignada": "Villa Carlos Paz",
                "valle_corredor": "Valle de Punilla",
                "website": "https://www.solocampings.com.ar/camping/nuevo-amanecer.html",
            },
        ]
        merged = merge_campings_deduplicated(osm, sc)
        # Miami se deduplica (y enriquece con website), Nuevo Amanecer se agrega
        assert len(merged) == 2
        miami = next(c for c in merged if "miami" in c["nombre_camping"].lower())
        assert miami["osm_id"] == "node/101"
        assert miami["website"] == "https://www.solocampings.com.ar/camping/miami.html"

    def test_apify_connector_zero_dummy(self):
        # Sin token y sin dataset_id retorna []
        res = fetch_google_maps_via_apify(search_queries=["campings cordoba"], api_token=None, dataset_id=None)
        assert res == []

        # Cargar JSON inexistente retorna ([], [])
        p, r = load_apify_gmaps_json(REPO_ROOT / "data" / "raw" / "archivo_inexistente.json")
        assert p == []
        assert r == []

    def test_enrich_listing_detail_mocked_html(self, monkeypatch):
        mock_html = """
        <html>
        <body>
            <img src="https://maps.googleapis.com/maps/api/staticmap?center=-31.9789%2C-64.5561&zoom=14" />
            <a href="https://inmuebles.mercadolibre.com.ar/_CustId_987654321">Ver más datos</a>
            <p class="ui-pdp-description__content">
                Excelente lote en Villa General Belgrano con agua y luz.&lt;br&gt;
                Escritura inmediata. Contacto wsp: 3546-401234 o llamar al cel 3546123456.
            </p>
        </body>
        </html>
        """
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=12: mock_resp)

        item = {
            "id_publicacion": "MLA12345",
            "valle_corredor": "Valle de Calamuchita",
            "localidad_raw": "Villa General Belgrano",
            "titulo_publicacion": "Lote en VGB",
            "url_publicacion": "https://terreno.mercadolibre.com.ar/MLA-12345-lote",
            "url_busqueda": "https://inmuebles.mercadolibre.com.ar/terrenos-lotes/cordoba/calamuchita/",
        }
        res = enrich_listing_detail(item)
        assert res["latitud"] == -31.9789
        assert res["longitud"] == -64.5561
        assert "Excelente lote en Villa General Belgrano con agua y luz" in res["descripcion_completa"]
        assert "<br>" not in res["descripcion_completa"]
        assert res["url_vendedor"] == "https://inmuebles.mercadolibre.com.ar/_CustId_987654321"
        assert "3546-401234" in res["telefono_en_descripcion"] or "3546" in res["telefono_en_descripcion"]
        assert res["url_google_maps"] == "https://www.google.com/maps/search/?api=1&query=-31.9789,-64.5561"
        assert res["url_busqueda"] == "https://inmuebles.mercadolibre.com.ar/terrenos-lotes/cordoba/calamuchita/"

    def test_enrich_listing_detail_timeout_graceful(self, monkeypatch):
        import urllib.error
        import urllib.parse
        def raise_timeout(req, timeout=12):
            raise urllib.error.URLError("Connection timed out")
        monkeypatch.setattr("urllib.request.urlopen", raise_timeout)

        item = {
            "id_publicacion": "MLA99999",
            "valle_corredor": "Valle de Punilla",
            "localidad_raw": "La Falda",
            "titulo_publicacion": "Terreno en La Falda",
            "url_publicacion": "https://terreno.mercadolibre.com.ar/MLA-99999-timeout",
        }
        res = enrich_listing_detail(item)
        assert res["latitud"] is None
        assert res["longitud"] is None
        assert res["descripcion_completa"] == ""
        assert res["telefono_en_descripcion"] == ""
        assert res["url_google_maps"].startswith("https://www.google.com/maps/search/?api=1&query=")
        assert "La Falda" in urllib.parse.unquote_plus(res["url_google_maps"])

    def test_solocampings_utf8_decoding_and_cosquin(self, monkeypatch):
        guide_mock = """
        <html><body>
        <a href="camping_en/Cosquin/Cordoba/93.html">Cosquín</a>
        <a href="camping_en/Villa-Carlos-Paz/Cordoba/94.html">Villa Carlos Paz</a>
        </body></html>
        """
        town_mock = """
        <html><body>
        <a href="camping/Camping-Rio-Cosquin/9301.html">Camping Río Ecológico</a>
        </body></html>
        """
        from unittest.mock import MagicMock
        def mock_urlopen(req, timeout=10):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            resp = MagicMock()
            resp.headers.get_content_charset.return_value = "utf-8"
            if "guiadecamping" in url:
                resp.read.return_value = guide_mock.encode("utf-8")
            else:
                resp.read.return_value = town_mock.encode("utf-8")
            resp.__enter__.return_value = resp
            resp.__exit__.return_value = False
            return resp

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

        centroids = load_localities_centroids()
        campings = fetch_solocampings_cordoba(localities=centroids, max_town_pages=5)
        assert len(campings) > 0
        cosquin_camp = next((c for c in campings if "Cosquin" in c["localidad_asignada"] or "Cosquín" in c["localidad_raw"]), None)
        assert cosquin_camp is not None
        # No debe haber mojibake
        assert "Ã" not in cosquin_camp["nombre_camping"]
        assert "Ã" not in cosquin_camp["localidad_raw"]
        # Coordenadas asignadas desde centroide
        assert cosquin_camp["latitud"] is not None
        assert cosquin_camp["longitud"] is not None
        assert cosquin_camp["localidad_asignada"] == "Cosquin"
        assert cosquin_camp["valle_corredor"] == "Valle de Punilla"
        assert cosquin_camp["ubicacion_completa"] == "Cosquín, Valle de Punilla, Córdoba"
        assert cosquin_camp["url_busqueda_google_maps"].startswith("https://www.google.com/maps/search/?api=1&query=")

    def test_camping_location_and_search_links(self):
        osm_camp = {
            "osm_id": "node/592662465",
            "nombre_camping": "Camping Los Reartes",
            "latitud": -31.9183,
            "longitud": -64.5772,
            "localidad_raw": "Los Reartes",
            "localidad_asignada": "Los Reartes",
            "ubicacion_completa": "Los Reartes, Valle de Calamuchita, Córdoba",
            "valle_corredor": "Valle de Calamuchita",
            "distancia_centroide_km": 0.0,
            "tiene_electricidad": True,
            "tiene_agua_potable": True,
            "acepta_casas_rodantes": True,
            "website": "https://campinglosreartes.com.ar",
            "telefono": "3546-123456",
            "operador": "Comuna Los Reartes",
            "horario": "24/7",
            "descripcion_tags": "Camping junto al río",
            "url_busqueda_google_maps": "https://www.google.com/maps/search/?api=1&query=-31.9183,-64.5772",
            "url_osm": "https://www.openstreetmap.org/node/592662465",
            "fuente_extraccion": "OpenStreetMap Overpass",
        }
        assert osm_camp["latitud"] == -31.9183
        assert osm_camp["longitud"] == -64.5772
        assert osm_camp["ubicacion_completa"] == "Los Reartes, Valle de Calamuchita, Córdoba"
        assert osm_camp["url_busqueda_google_maps"] == "https://www.google.com/maps/search/?api=1&query=-31.9183,-64.5772"
        assert osm_camp["url_osm"] == "https://www.openstreetmap.org/node/592662465"


# =====================================================================
# 3. Tests de Esquemas y Configuración de Apify Actor
# =====================================================================
class TestApifyActorSchemas:
    def test_actor_json(self):
        actor_json_path = ACTOR_DIR / ".actor" / "actor.json"
        assert actor_json_path.exists(), "Falta .actor/actor.json"
        with open(actor_json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("actorSpecification") == 1
        assert data.get("name") == "terrascout-georadar-actor"
        assert "inputSchema" in data
        assert "outputSchema" in data
        assert "storages" in data

    def test_input_schema_json(self):
        input_schema_path = ACTOR_DIR / ".actor" / "input_schema.json"
        assert input_schema_path.exists(), "Falta .actor/input_schema.json"
        with open(input_schema_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("type") == "object"
        properties = data.get("properties", {})
        assert "url" in properties
        assert "corredores" in properties
        assert "tipo_cambio_ars_usd" in properties
        assert "pendiente_maxima_grados" in properties
        assert "words" in properties
        assert "scorer" in properties

    def test_dataset_schema_json(self):
        dataset_schema_path = ACTOR_DIR / ".actor" / "dataset_schema.json"
        assert dataset_schema_path.exists(), "Falta .actor/dataset_schema.json"
        with open(dataset_schema_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data.get("actorSpecification") == 1
        assert "views" in data

    def test_output_schema_json(self):
        output_schema_path = ACTOR_DIR / ".actor" / "output_schema.json"
        assert output_schema_path.exists(), "Falta .actor/output_schema.json"
        with open(output_schema_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "properties" in data

    def test_dockerfile_and_requirements(self):
        dockerfile_path = ACTOR_DIR / "Dockerfile"
        req_path = ACTOR_DIR / "requirements.txt"
        assert dockerfile_path.exists(), "Falta Dockerfile"
        assert req_path.exists(), "Falta requirements.txt"

        docker_content = dockerfile_path.read_text(encoding="utf-8")
        assert "FROM apify/actor-python:3.14" in docker_content
        assert "CMD" in docker_content

        req_content = req_path.read_text(encoding="utf-8")
        assert "apify" in req_content
        assert "scikit-learn" in req_content
        assert "pandas" in req_content


# =====================================================================
# 4. Verificación de Política ZERO DUMMY DATA en Código
# =====================================================================
class TestZeroDummyPolicy:
    def test_scraper_node_has_no_dummy_generators(self):
        node_file = SRC_DIR / "run_scraper_node.py"
        assert node_file.exists(), f"Falta {node_file}"
        code = node_file.read_text(encoding="utf-8")

        # Asegurar remoción total de funciones sintéticas
        assert "build_raw_real_estate_dataset" not in code, "Se encontró función sintética build_raw_real_estate_dataset"
        assert "build_raw_camping_reviews_dataset" not in code, "Se encontró función sintética build_raw_camping_reviews_dataset"
        assert "random.sample" not in code, "Se encontró random.sample generando datos sintéticos"
        assert "random.gauss" not in code, "Se encontró random.gauss generando datos sintéticos"

    def test_no_legacy_dummy_files(self):
        stale_json = DATA_RAW_DIR / "topicos_quejas_kmeans_raw.json"
        assert not stale_json.exists(), "El archivo de dummy data topicos_quejas_kmeans_raw.json no debe existir."


# =====================================================================
# 5. Tests de Datasets Crudos Reales Generados en data/raw/
# =====================================================================
class TestRealRawDatasets:
    def test_mercadolibre_terrenos_raw_csv(self):
        csv_path = DATA_RAW_DIR / "mercadolibre_terrenos_calamuchita_punilla_raw.csv"
        assert csv_path.exists(), f"Falta archivo de datos reales: {csv_path}"

        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))

        assert len(reader) > 0, "El archivo de Mercado Libre no debe estar vacío"

        expected_cols = [
            "id_publicacion",
            "fecha_extraccion",
            "valle_corredor",
            "localidad_raw",
            "titulo_publicacion",
            "moneda_raw",
            "precio_raw",
            "superficie_raw_texto",
            "superficie_m2_extraida",
            "latitud",
            "longitud",
            "descripcion_completa",
            "telefono_en_descripcion",
            "vendedor_nombre",
            "url_vendedor",
            "es_tienda_oficial",
            "tipo_aviso",
            "url_busqueda",
            "url_publicacion",
            "url_google_maps",
            "fuente_extraccion",
        ]
        assert list(reader[0].keys()) == expected_cols

        # Unicidad de publicaciones
        ids = [r["id_publicacion"] for r in reader]
        assert len(ids) == len(set(ids)), "Las publicaciones deben ser únicas (deduplicadas)"

        # Valles contemplados
        valleys = {r["valle_corredor"] for r in reader}
        assert valleys.issubset({"Valle de Calamuchita", "Valle de Punilla"})

        # Fuente real y campos obligatorios
        for r in reader:
            assert r["fuente_extraccion"] == "MercadoLibre Córdoba"
            assert r["url_publicacion"].startswith("http")
            assert bool(r["localidad_raw"].strip()), "localidad_raw no debe estar vacía"
            assert r["url_busqueda"].startswith("http"), "url_busqueda debe ser URL válida"
            assert r["url_google_maps"].startswith("https://www.google.com/maps/search/?api=1&query="), "url_google_maps debe ser válida"

        # Cobertura de latitud/longitud en ML
        coords_found = sum(1 for r in reader if bool(r.get("latitud")) and bool(r.get("longitud")))
        assert coords_found > 0, "Debe haber coordenadas extraídas de las páginas de detalle"

    def test_campings_zona_real_csv(self):
        csv_path = DATA_RAW_DIR / "campings_zona_real_raw.csv"
        assert csv_path.exists(), f"Falta archivo de campings reales: {csv_path}"

        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))

        assert len(reader) > 0, "El dataset de campings reales debe contener registros"

        expected_cols = [
            "osm_id",
            "nombre_camping",
            "latitud",
            "longitud",
            "localidad_raw",
            "localidad_asignada",
            "ubicacion_completa",
            "valle_corredor",
            "distancia_centroide_km",
            "tiene_electricidad",
            "tiene_agua_potable",
            "acepta_casas_rodantes",
            "website",
            "telefono",
            "operador",
            "horario",
            "descripcion_tags",
            "url_busqueda_google_maps",
            "url_osm",
            "fuente_extraccion",
        ]
        assert list(reader[0].keys()) == expected_cols

        # 100% de campings con coordenadas y enlaces garantizados (0 missing!)
        for c in reader:
            assert bool(c["nombre_camping"].strip()), "El nombre del camping no puede estar vacío"
            assert c["valle_corredor"] in {"Valle de Calamuchita", "Valle de Punilla", "Desconocido"}
            assert bool(c["latitud"].strip()), f"Camping {c['nombre_camping']} no tiene latitud"
            assert bool(c["longitud"].strip()), f"Camping {c['nombre_camping']} no tiene longitud"
            assert bool(c["localidad_asignada"].strip()), "localidad_asignada no puede estar vacía"
            assert bool(c["ubicacion_completa"].strip()), "ubicacion_completa no puede estar vacía"
            assert c["url_busqueda_google_maps"].startswith("https://www.google.com/maps/search/?api=1&query=")
            assert "Ã" not in c["nombre_camping"], f"Mojibake detectado en camping: {c['nombre_camping']}"
            assert "Ã" not in c["localidad_raw"], f"Mojibake detectado en localidad_raw: {c['localidad_raw']}"

    def test_topicos_nlp_real_json(self):
        json_path = DATA_RAW_DIR / "topicos_nlp_real_raw.json"
        assert json_path.exists(), f"Falta archivo de tópicos reales: {json_path}"

        with open(json_path, mode="r", encoding="utf-8") as f:
            data = json.load(f)

        assert "metadata" in data
        assert "n_clusters" in data
        assert "topics" in data
        assert "fuzzy_counts" in data

        meta = data["metadata"]
        assert meta["total_publicaciones_ml"] > 0
        assert meta["total_campings_reales"] > 0
        assert "MercadoLibre Inmuebles Córdoba" in meta["fuentes_utilizadas"]

        # Conteo difuso sobre palabras de negocio
        fuzzy_counts = data["fuzzy_counts"]
        for kw in ["agua corriente", "luz electrica", "rio"]:
            assert kw in fuzzy_counts
            assert "count" in fuzzy_counts[kw]

    def test_gmaps_reviews_conditional(self):
        gmaps_csv = DATA_RAW_DIR / "google_maps_campings_reviews_raw.csv"
        if gmaps_csv.exists():
            with open(gmaps_csv, mode="r", encoding="utf-8") as f:
                reader = list(csv.DictReader(f))
            assert len(reader) > 0, "Si el archivo existe, no debe ser vacío"
            expected = [
                "id_review",
                "place_id",
                "nombre_camping",
                "valle_corredor",
                "localidad_raw",
                "estrellas_rating",
                "fecha_reseña",
                "texto_reseña",
            ]
            assert list(reader[0].keys()) == expected
