"""TerraScout AI — Scraper de Mercado Libre Inmuebles (Sierras de Córdoba).

Extrae publicaciones reales de terrenos y lotes en los valles de Calamuchita y Punilla.
Utiliza decodificación estructurada de datos embebidos (_n.ctx.r) con fallback
a JSON-LD (schema.org/RealEstateListing).

CERO DATOS SINTÉTICOS.
"""

from __future__ import annotations

import datetime
import json
import logging
import random
import re
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

SUPERFICIE_RE = re.compile(
    r'(?i)(\d+(?:[.,]\d+)?)\s*(m2|mts2|metros\s*cuadrados|mts|m²|ha|hectareas)\b'
)

DEFAULT_VALLEY_URLS: dict[str, str] = {
    "Valle de Calamuchita": "https://inmuebles.mercadolibre.com.ar/terrenos-lotes/cordoba/calamuchita/",
    "Valle de Punilla": "https://inmuebles.mercadolibre.com.ar/terrenos-lotes/cordoba/punilla/",
}

HTTP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def extraer_superficie_m2(texto: str | None) -> float | None:
    """Extrae la superficie en m2 a partir de texto libre o etiqueta cruda.

    Maneja:
    - m2, mts2, metros cuadrados, mts, m²
    - ha, hectareas (conversión: 1 ha = 10.000 m2)
    - Puntos y comas de miles y decimales ('1.500 m2' -> 1500, '0.5 ha' -> 5000)
    """
    if not texto or not isinstance(texto, str):
        return None

    match = SUPERFICIE_RE.search(texto)
    if not match:
        return None

    num_str, unit = match.group(1), match.group(2).lower()
    is_ha = "ha" in unit or "hectarea" in unit

    # Separador de miles (ej. '1.500 m2' o '1,500 m2' con 3 dígitos tras el punto)
    if "." in num_str and not is_ha:
        parts = num_str.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            try:
                return float(parts[0] + parts[1])
            except ValueError:
                pass
    if "," in num_str and not is_ha:
        parts = num_str.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            try:
                return float(parts[0] + parts[1])
            except ValueError:
                pass

    clean_str = num_str.replace(",", ".")
    try:
        val = float(clean_str)
        if is_ha:
            val *= 10000.0
        return round(val, 2)
    except ValueError:
        return None


def _parse_jsonld(html: str, valle_corredor: str, fecha_extraccion: str) -> list[dict[str, Any]]:
    """Fallback: extrae publicaciones de scripts schema.org JSON-LD."""
    listings: list[dict[str, Any]] = []
    scripts = re.findall(
        r'<script[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    for script_text in scripts:
        try:
            data = json.loads(script_text.strip())
        except Exception:
            continue

        raw_items: list[Any] = []
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                raw_items = data["@graph"]
            elif data.get("@type") == "RealEstateListing":
                raw_items = [data]
        elif isinstance(data, list):
            raw_items = data

        for item in raw_items:
            if not isinstance(item, dict) or item.get("@type") != "RealEstateListing":
                continue

            name = str(item.get("name") or "")
            offers = item.get("offers") or {}
            price = offers.get("price")
            currency = offers.get("priceCurrency")
            url = str(offers.get("url") or item.get("mainEntityOfPage") or "")
            if url and not url.startswith(("http://", "https://")):
                url = f"https://{url}"

            m_id = re.search(r"MLA-?(\d+)", url)
            pub_id = f"MLA{m_id.group(1)}" if m_id else f"MLA_{abs(hash(url)) % 1000000000}"

            address = item.get("address") or {}
            loc_parts = [
                str(p)
                for p in [address.get("addressLocality"), address.get("addressRegion")]
                if p
            ]
            location_str = ", ".join(loc_parts)

            seller_obj = item.get("seller") or {}
            seller_name = seller_obj.get("name") if isinstance(seller_obj, dict) else None

            surf_m2 = extraer_superficie_m2(name)

            listings.append({
                "id_publicacion": str(pub_id),
                "fecha_extraccion": fecha_extraccion,
                "valle_corredor": valle_corredor,
                "localidad_raw": location_str,
                "titulo_publicacion": name,
                "moneda_raw": str(currency) if currency else "",
                "precio_raw": price,
                "superficie_raw_texto": f"{surf_m2} m²" if surf_m2 else "",
                "superficie_m2_extraida": surf_m2,
                "vendedor_nombre": str(seller_name) if seller_name else None,
                "es_tienda_oficial": False,
                "tipo_aviso": "CLASICO",
                "url_publicacion": url,
                "fuente_extraccion": "MercadoLibre Córdoba",
            })
    return listings


def parse_mercadolibre_html(
    html: str,
    valle_corredor: str,
    fecha_extraccion: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Parsea el HTML de búsqueda de Mercado Libre Inmuebles.

    Extrae listings estructurados reales desde `_n.ctx.r` embebido en <script>,
    con fallback a schema.org JSON-LD.
    Retorna (listings, page_count).
    """
    if fecha_extraccion is None:
        fecha_extraccion = datetime.date.today().isoformat()

    # 1. Estrategia primaria: _n.ctx.r decodificado con raw_decode
    idx = html.find("_n.ctx.r=")
    if idx != -1:
        start_pos = idx + len("_n.ctx.r=")
        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(html[start_pos:])
            app_props = data.get("appProps", {})
            page_props = app_props.get("pageProps", {})
            initial_state = page_props.get("initialState", {})
            results = initial_state.get("results", [])
            pagination = initial_state.get("pagination", {})
            page_count = int(pagination.get("page_count", 1))

            listings: list[dict[str, Any]] = []
            for item in results:
                polycard = item.get("polycard", {})
                meta = polycard.get("metadata", {})
                pub_id = meta.get("id")
                if not pub_id:
                    continue

                components = polycard.get("components", [])
                comp_map = {
                    c.get("type"): c
                    for c in components
                    if isinstance(c, dict) and c.get("type")
                }

                # Título
                title = comp_map.get("title", {}).get("title", {}).get("text") or ""

                # Precio y moneda
                price_comp = comp_map.get("price", {}).get("price", {})
                current_price = price_comp.get("current_price", {})
                precio_raw = current_price.get("value")
                moneda_raw = current_price.get("currency")
                if precio_raw is None:
                    precio_raw = meta.get("signal", {}).get("prc")
                if moneda_raw is None:
                    moneda_raw = meta.get("signal", {}).get("prc_currency")

                # Atributos de superficie
                attrs_comp = comp_map.get("attributes_list", {}).get("attributes_list", {})
                texts = attrs_comp.get("texts", [])
                superficie_raw_texto = texts[0] if texts else ""
                superficie_m2_extraida = extraer_superficie_m2(superficie_raw_texto)
                if superficie_m2_extraida is None and title:
                    superficie_m2_extraida = extraer_superficie_m2(title)

                # Localidad / Ubicación
                localidad_raw = comp_map.get("location", {}).get("location", {}).get("text") or ""

                # Vendedor
                seller_text = comp_map.get("seller", {}).get("seller", {}).get("text")
                if seller_text:
                    cleaned_seller = re.sub(r"\{.*?\}", "", seller_text).strip()
                    vendedor_nombre = cleaned_seller if cleaned_seller else None
                else:
                    vendedor_nombre = None

                # Tienda oficial
                es_tienda_oficial = bool(meta.get("signal", {}).get("official_store", False))

                # Tipo de aviso (EMPRENDIMIENTO / CLASICO / pill)
                pill_text = comp_map.get("pill", {}).get("pill", {}).get("text")
                tipo_aviso = pill_text.strip() if pill_text else "CLASICO"

                # URL de la publicación
                raw_url = meta.get("url", "")
                if raw_url and not raw_url.startswith(("http://", "https://")):
                    url_pub = f"https://{raw_url}"
                else:
                    url_pub = raw_url

                listings.append({
                    "id_publicacion": str(pub_id),
                    "fecha_extraccion": fecha_extraccion,
                    "valle_corredor": valle_corredor,
                    "localidad_raw": localidad_raw,
                    "titulo_publicacion": title,
                    "moneda_raw": str(moneda_raw) if moneda_raw is not None else "",
                    "precio_raw": precio_raw,
                    "superficie_raw_texto": superficie_raw_texto,
                    "superficie_m2_extraida": superficie_m2_extraida,
                    "vendedor_nombre": vendedor_nombre,
                    "es_tienda_oficial": es_tienda_oficial,
                    "tipo_aviso": tipo_aviso,
                    "url_publicacion": url_pub,
                    "fuente_extraccion": "MercadoLibre Córdoba",
                })

            if listings:
                return listings, page_count
        except Exception as exc:
            logger.warning("Fallo al parsear _n.ctx.r: %s. Intentando fallback JSON-LD.", exc)

    # 2. Estrategia secundaria: schema.org JSON-LD
    jsonld_listings = _parse_jsonld(html, valle_corredor, fecha_extraccion)
    return jsonld_listings, 1


def _fetch_html(url: str, timeout: int = 15) -> str:
    """Realiza la petición HTTP con headers realistas."""
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def scrape_mercadolibre_valley(
    base_url: str,
    valle_corredor: str,
    max_items: int = 800,
    max_pages: int = 20,
    delay_seconds: float = 0.35,
) -> list[dict[str, Any]]:
    """Scrapes publicaciones reales de Mercado Libre para un valle específico.

    Pagina desde page 1 hasta max_pages o hasta agotar resultados / alcanzar max_items.
    Deduplica por id_publicacion y añade delay con jitter para comportamiento cortés.
    """
    clean_base = base_url.rstrip("/") + "/"
    all_listings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    total_pages = max_pages

    logger.info(
        "Iniciando scrape de %s: base_url=%s, max_items=%d, max_pages=%d",
        valle_corredor,
        clean_base,
        max_items,
        max_pages,
    )

    for page in range(1, max_pages + 1):
        if len(seen_ids) >= max_items:
            logger.info("Alcanzado max_items=%d para %s.", max_items, valle_corredor)
            break

        if page > total_pages:
            logger.info("Alcanzada última página disponible (%d) para %s.", total_pages, valle_corredor)
            break

        # Construcción de URL de página
        if page == 1:
            page_url = clean_base
        else:
            offset = 48 * (page - 1) + 1
            page_url = f"{clean_base.rstrip('/')}/_Desde_{offset}_NoIndex_True"

        try:
            html = _fetch_html(page_url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, Exception) as exc:
            logger.warning(
                "Error en petición a %s (página %d): %s. Deteniendo paginación.",
                page_url,
                page,
                exc,
            )
            break

        listings, detected_pages = parse_mercadolibre_html(html, valle_corredor)
        if detected_pages > 0:
            total_pages = min(total_pages, detected_pages)

        new_count = 0
        for item in listings:
            pub_id = item["id_publicacion"]
            if pub_id not in seen_ids:
                seen_ids.add(pub_id)
                all_listings.append(item)
                new_count += 1
                if len(seen_ids) >= max_items:
                    break

        logger.info(
            "Página %d/%d (%s): %d publicaciones parseadas, %d nuevas añadidas (acumulado: %d)",
            page,
            total_pages,
            valle_corredor,
            len(listings),
            new_count,
            len(all_listings),
        )

        # Si una página no aportó nuevos items, detener paginación limpia
        if new_count == 0:
            logger.info("Página %d no aportó nuevos registros. Deteniendo paginación.", page)
            break

        # Delay cortés con jitter antes de la próxima página
        if page < total_pages and len(seen_ids) < max_items:
            jitter = random.uniform(0.05, 0.15)
            time.sleep(delay_seconds + jitter)

    return all_listings[:max_items]


def scrape_all_mercadolibre_valleys(
    urls_by_valley: dict[str, str] | None = None,
    max_items_per_valley: int = 800,
    max_pages_per_valley: int = 20,
) -> list[dict[str, Any]]:
    """Scrapes publicaciones de todos los valles configurados.

    Retorna la lista unificada deduplicada por id_publicacion.
    """
    targets = urls_by_valley or DEFAULT_VALLEY_URLS
    combined: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for valley_name, url in targets.items():
        valley_items = scrape_mercadolibre_valley(
            base_url=url,
            valle_corredor=valley_name,
            max_items=max_items_per_valley,
            max_pages=max_pages_per_valley,
        )
        for item in valley_items:
            pub_id = item["id_publicacion"]
            if pub_id not in seen_ids:
                seen_ids.add(pub_id)
                combined.append(item)

    logger.info(
        "Scrape completo de valles finalizado: total %d publicaciones únicas.",
        len(combined),
    )
    return combined
