"""TerraScout AI — Apify Actor: Scraper de terrenos en Sierras de Córdoba
+ Búsqueda difusa de infraestructura y servicios (RapidFuzz / fallback difflib)
+ Detección de tópicos de quejas turísticas en campings (TF-IDF + KMeans, scikit-learn).

Arquitectura conforme a la plantilla oficial SIC Capstone:
- normalize(text)
- tokenize(text)
- split_sentences(content)
- SentenceIndex
- fuzzy_count(index, query, scorer_name, threshold)
- find_topics(sentences, top_n, n_clusters, n_terms, n_examples, stop_words, extra_stop_words)
- extraer_superficie_m2(texto)
"""

from __future__ import annotations

import difflib
import logging
import math
import os
import re
import unicodedata
from collections import defaultdict
from typing import Any

# Optional external dependencies with graceful fallbacks for local test environments
try:
    from apify import Actor
    HAS_APIFY = True
except ImportError:
    HAS_APIFY = False

    class _MockActorLog:
        @staticmethod
        def info(msg: str) -> None:
            logging.info(msg)

        @staticmethod
        def warning(msg: str) -> None:
            logging.warning(msg)

        @staticmethod
        def error(msg: str) -> None:
            logging.error(msg)

    class _MockActor:
        log = _MockActorLog()

        @staticmethod
        async def get_input() -> dict[str, Any]:
            return {}

        @staticmethod
        async def push_data(data: Any) -> None:
            pass

        async def __aenter__(self) -> _MockActor:
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            pass

    Actor = _MockActor()

try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False
    fuzz = None
    process = None

# Scraper de Mercado Libre y dependencias auxiliares
try:
    from my_actor.ml_scraper import (
        extraer_superficie_m2,
        parse_mercadolibre_html,
        scrape_all_mercadolibre_valleys,
        scrape_mercadolibre_valley,
    )
except ImportError:
    from .ml_scraper import (
        extraer_superficie_m2,
        parse_mercadolibre_html,
        scrape_all_mercadolibre_valleys,
        scrape_mercadolibre_valley,
    )

# Import del camping scraper
try:
    from my_actor.camping_scraper import scrape_all_real_campings
except ImportError:
    try:
        from .camping_scraper import scrape_all_real_campings
    except ImportError:
        scrape_all_real_campings = None


# ---------------------------------------------------------------- Constantes y Expresiones Regulares
DEFAULT_THRESHOLD = 85.0
SHORT_QUERY_LEN = 3
SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+')
TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)*")

SPANISH_STOP_WORDS = {
    'de', 'la', 'que', 'el', 'en', 'y', 'a', 'los', 'del', 'se', 'las', 'por', 'un', 'para',
    'con', 'no', 'una', 'su', 'al', 'lo', 'como', 'mas', 'pero', 'sus', 'le', 'ya', 'o',
    'este', 'si', 'porque', 'esta', 'entre', 'cuando', 'muy', 'sin', 'sobre', 'tambien',
    'me', 'hasta', 'hay', 'donde', 'quien', 'desde', 'todo', 'nos', 'durante', 'todos',
    'uno', 'les', 'ni', 'contra', 'otros', 'ese', 'eso', 'ante', 'ellos', 'e', 'esto',
    'mi', 'antes', 'algunos', 'unos', 'yo', 'otro', 'otras', 'otra', 'tanto', 'esa',
    'estos', 'mucho', 'quienes', 'nada', 'muchos', 'cual', 'poco', 'ella', 'estar',
    'estas', 'algunas', 'algo', 'nosotros', 'mis', 'tu', 'te', 'ti', 'tus', 'ellas',
    'nosotras', 'vosotros', 'vosotras', 'os', 'mio', 'mia', 'mios', 'mias', 'tuyo',
    'tuya', 'tuyos', 'tuyas', 'suyo', 'suya', 'suyos', 'suyas', 'nuestro', 'nuestra',
    'nuestros', 'nuestras', 'vuestro', 'vuestra', 'vuestros', 'vuestras', 'esos', 'esas',
    'es', 'son', 'fue', 'era', 'ser', 'tiene', 'tienen', 'buen', 'bueno', 'buena', 'bien'
}

# Corredores y Localidades de Calamuchita y Punilla
CALAMUCHITA_LOCALITIES = [
    "Santa Rosa de Calamuchita",
    "Villa General Belgrano",
    "La Cumbrecita",
    "Villa Rumipal",
    "Villa del Dique",
    "Embalse",
    "Los Reartes",
    "Villa Yacanto",
]

PUNILLA_LOCALITIES = [
    "Villa Carlos Paz",
    "Cosquín",
    "La Falda",
    "Villa Giardino",
    "La Cumbre",
    "Capilla del Monte",
    "Tanti",
    "Huerta Grande",
]

ALL_LOCALITIES = CALAMUCHITA_LOCALITIES + PUNILLA_LOCALITIES


# ---------------------------------------------------------------- Fallbacks para Similitud Difusa
def _fallback_ratio(s1: str, s2: str) -> float:
    return difflib.SequenceMatcher(None, s1, s2).ratio() * 100.0


def _fallback_partial_ratio(s1: str, s2: str) -> float:
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    if not s1:
        return 100.0 if not s2 else 0.0
    n1 = len(s1)
    best = 0.0
    for i in range(len(s2) - n1 + 1):
        sub = s2[i:i + n1]
        r = difflib.SequenceMatcher(None, s1, sub).ratio() * 100.0
        if r > best:
            best = r
    return best


def _fallback_token_sort_ratio(s1: str, s2: str) -> float:
    t1 = ' '.join(sorted(s1.split()))
    t2 = ' '.join(sorted(s2.split()))
    return _fallback_ratio(t1, t2)


def _fallback_token_set_ratio(s1: str, s2: str) -> float:
    t1 = ' '.join(sorted(set(s1.split())))
    t2 = ' '.join(sorted(set(s2.split())))
    return _fallback_ratio(t1, t2)


def _fallback_wratio(s1: str, s2: str) -> float:
    # Heurística ponderada simple para WRatio fallback
    r = _fallback_ratio(s1, s2)
    pr = _fallback_partial_ratio(s1, s2)
    ts = _fallback_token_sort_ratio(s1, s2)
    return max(r, pr * 0.9, ts * 0.95)


FALLBACK_SCORERS = {
    'ratio': _fallback_ratio,
    'partial_ratio': _fallback_partial_ratio,
    'token_sort_ratio': _fallback_token_sort_ratio,
    'token_set_ratio': _fallback_token_set_ratio,
    'WRatio': _fallback_wratio,
}

if HAS_RAPIDFUZZ:
    SCORERS = {
        'ratio': fuzz.ratio,
        'partial_ratio': fuzz.partial_ratio,
        'token_sort_ratio': fuzz.token_sort_ratio,
        'token_set_ratio': fuzz.token_set_ratio,
        'WRatio': fuzz.WRatio,
    }
else:
    SCORERS = FALLBACK_SCORERS


# ---------------------------------------------------------------- Normalización y Tokenización
def normalize(text: str) -> str:
    """Minúsculas y sin acentos: 'Ingeniería' -> 'ingenieria'."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', str(text).lower())
    return ''.join(c for c in text if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    """Extrae tokens normalizados."""
    if not text:
        return []
    return [normalize(t) for t in TOKEN_RE.findall(str(text))]


def split_sentences(content: dict[str, str] | list[str]) -> list[str]:
    """Divide oraciones respetando signos de puntuación (. ! ?) y limpiando tags HTML."""
    sentences: list[str] = []
    if isinstance(content, dict):
        texts = content.values()
    elif isinstance(content, list):
        texts = content
    else:
        texts = [content]

    for text in texts:
        if not text:
            continue
        clean_text = re.sub(r"<[^>]+>", " ", str(text))
        for line in clean_text.splitlines():
            sentences.extend(s.strip() for s in SENTENCE_SPLIT.split(line) if s.strip())
    return sentences


# ---------------------------------------------------------------- Índice de N-Gramas
class SentenceIndex:
    """Índice de n-gramas -> oraciones donde aparecen.

    Permite comparar secuencias de n palabras consecutivas para consultas unigramas o frases.
    """

    def __init__(self, content: dict[str, str] | list[str]):
        self.sentences = split_sentences(content)
        self._tokens = [tokenize(s) for s in self.sentences]
        self._ngrams: dict[int, dict[str, list[int]]] = {}

    def ngrams(self, n: int) -> dict[str, list[int]]:
        if n not in self._ngrams:
            index = defaultdict(list)
            for i, toks in enumerate(self._tokens):
                for j in range(len(toks) - n + 1):
                    index[' '.join(toks[j:j + n])].append(i)
            self._ngrams[n] = dict(index)
        return self._ngrams[n]


# ---------------------------------------------------------------- Contador Difuso
def fuzzy_count(
    index: SentenceIndex,
    query: str,
    scorer_name: str = 'ratio',
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Busca menciones exactas o difusas de una query en el corpus indexado."""
    empty: dict[str, Any] = {'count': 0, 'sentences': [], 'variants': {}}
    q_tokens = tokenize(query)
    if not q_tokens:
        return empty

    q = ' '.join(q_tokens)
    if len(q) <= SHORT_QUERY_LEN:
        scorer_name, threshold = 'ratio', 100.0

    vocab = index.ngrams(len(q_tokens))
    if not vocab:
        return empty

    if len(q) > SHORT_QUERY_LEN:
        min_cand_len = max(4, int(len(q) * 0.55))
        choices = [c for c in vocab if len(c) >= min_cand_len]
    else:
        choices = list(vocab)

    if not choices:
        return empty

    if HAS_RAPIDFUZZ:
        scorer = SCORERS.get(scorer_name, fuzz.ratio)
        matches = process.extract(q, choices, scorer=scorer, score_cutoff=threshold, limit=None)
    else:
        scorer_func = FALLBACK_SCORERS.get(scorer_name, _fallback_ratio)
        matches = []
        for choice in choices:
            score = scorer_func(q, choice)
            if score >= threshold:
                matches.append((choice, score, None))

    count = 0
    hit_ids: set[int] = set()
    variants: dict[str, dict[str, Any]] = {}
    for form, score, _ in sorted(matches, key=lambda m: (-m[1], m[0])):
        occurrences = vocab[form]
        count += len(occurrences)
        hit_ids.update(occurrences)
        variants[form] = {'count': len(occurrences), 'score': round(float(score), 1)}

    return {
        'count': count,
        'sentences': [index.sentences[i] for i in sorted(hit_ids)],
        'variants': variants,
    }


# ---------------------------------------------------------------- Tópicos (TF-IDF + KMeans)
MIN_SENTENCE_TOKENS = 3
MAX_AUTO_CLUSTERS = 10


def topic_terms(centroid: Any, terms: Any, n: int) -> list[str]:
    """Términos de mayor peso del centroide sin redundancia unigrama/bigrama."""
    picked: list[str] = []
    for i in centroid.argsort()[::-1]:
        if centroid[i] <= 0 or len(picked) >= n:
            break
        term = terms[i]
        if any(term in p.split() or p in term.split() for p in picked):
            continue
        picked.append(term)
    return picked


def find_topics(
    sentences: list[str],
    top_n: int = 3,
    n_clusters: int = 0,
    n_terms: int = 5,
    n_examples: int = 3,
    stop_words: str | None = 'spanish',
    extra_stop_words: list[str] | None = None,
) -> dict[str, Any]:
    """Descubre tópicos latentes en oraciones usando TF-IDF + KMeans + silhouette_score."""
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
    from sklearn.metrics import silhouette_score

    docs = list(dict.fromkeys(s for s in sentences if len(tokenize(s)) >= MIN_SENTENCE_TOKENS))
    empty: dict[str, Any] = {'n_clusters': 0, 'silhouette': None, 'n_sentences': len(docs), 'items': []}
    if len(docs) < 2:
        return empty

    extra_stops = extra_stop_words or []
    if stop_words == 'spanish':
        stops = set(SPANISH_STOP_WORDS)
    elif stop_words == 'english':
        stops = set(ENGLISH_STOP_WORDS)
    else:
        stops = set()
    stops |= {normalize(w) for w in extra_stops}

    vectorizer = TfidfVectorizer(
        preprocessor=normalize,
        tokenizer=lambda s: [t for t in tokenize(s) if t not in stops and len(t) > 1 and not t.isdigit()],
        token_pattern=None,
        lowercase=False,
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=1,
    )
    try:
        X = vectorizer.fit_transform(docs)
    except ValueError:
        return empty
    terms = vectorizer.get_feature_names_out()

    def fit(k: int):
        km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(X)
        sil = silhouette_score(X, km.labels_, metric='cosine') if 1 < k < len(docs) else None
        return km, sil

    max_k = len(docs) - 1
    if n_clusters <= 0:
        upper = min(MAX_AUTO_CLUSTERS, max_k, max(top_n, int(np.sqrt(len(docs)))))
        candidates = range(min(top_n, max_k), upper + 1)
        fits = [fit(k) for k in candidates if k >= 2]
        km, sil = max(fits, key=lambda f: f[1] if f[1] is not None else -1) if fits else fit(1)
    else:
        km, sil = fit(max(1, min(n_clusters, max_k)))

    k = km.n_clusters
    Actor.log.info(f'KMeans: {len(docs)} oraciones, {X.shape[1]} términos, k={k}, silhouette={sil}')

    sizes = np.bincount(km.labels_, minlength=k)
    distances = km.transform(X)

    items = []
    for c in np.argsort(-sizes)[:top_n]:
        members = np.where(km.labels_ == c)[0]
        closest = members[np.argsort(distances[members, c])][:n_examples]
        items.append({
            'size': int(sizes[c]),
            'share': round(float(sizes[c]) / len(docs), 3),
            'terms': topic_terms(km.cluster_centers_[c], terms, n_terms),
            'sentences': [docs[i] for i in closest],
        })
    items = [{'rank': rank, **item} for rank, item in enumerate(items, 1)]

    return {
        'n_clusters': int(k),
        'silhouette': round(float(sil), 3) if sil is not None else None,
        'n_sentences': len(docs),
        'items': items,
    }


# ---------------------------------------------------------------- Actor Main Entrypoint
async def main() -> None:
    """Punto de entrada asíncrono para la plataforma Apify.

    1. Scrapes publicaciones reales de Mercado Libre Inmuebles (Calamuchita y Punilla).
    2. Ejecuta camping_scraper para obtener campings y reseñas turísticas.
    3. Aplica RapidFuzz / SentenceIndex para evaluar servicios e infraestructura.
    4. Aplica TF-IDF + KMeans para detección de tópicos en reseñas/textos.
    5. Persiste el dataset enriquecido en Apify con CERO datos sintéticos.
    """
    async with Actor:
        actor_input = await Actor.get_input() or {}

        # Parámetros de extracción
        calamuchita_url = actor_input.get("calamuchita_url") or "https://inmuebles.mercadolibre.com.ar/terrenos-lotes/cordoba/calamuchita/"
        punilla_url = actor_input.get("punilla_url") or "https://inmuebles.mercadolibre.com.ar/terrenos-lotes/cordoba/punilla/"
        alt_url = actor_input.get("url")
        max_items_per_valley = int(actor_input.get("max_items_per_valley") or actor_input.get("max_items", 800))
        max_pages_per_valley = int(actor_input.get("max_pages_per_valley", 20))
        apify_token_env = actor_input.get("apify_token_env") or "APIFY_TOKEN"

        # Parámetros de NLP
        words = actor_input.get("words") or ["agua", "luz", "escritura", "arboleda", "asfalto", "rio"]
        scorer_name = actor_input.get("scorer") or "ratio"
        threshold = float(actor_input.get("threshold", DEFAULT_THRESHOLD))
        top_topics = int(actor_input.get("top_topics", 3))
        n_clusters = int(actor_input.get("n_clusters", 0))
        n_terms = int(actor_input.get("n_terms", 5))
        n_examples = int(actor_input.get("n_examples", 3))
        stop_words = actor_input.get("stop_words", "spanish")
        extra_stop_words = actor_input.get("extra_stop_words") or [
            "camping", "lugar", "cordoba", "muy", "mas", "anos", "hace", "dia", "dias", "bueno", "buena", "bien"
        ]

        Actor.log.info(
            f"Iniciando TerraScout Actor (Real ML Scraper): "
            f"max_items_per_valley={max_items_per_valley}, max_pages_per_valley={max_pages_per_valley}"
        )

        # 1. Extracción Real de Mercado Libre (Cero dummy data)
        if alt_url and alt_url not in [calamuchita_url, punilla_url, "https://inmuebles.mercadolibre.com.ar/terrenos-lotes/cordoba/"]:
            ml_listings = scrape_mercadolibre_valley(
                base_url=alt_url,
                valle_corredor="Córdoba",
                max_items=max_items_per_valley * 2,
                max_pages=max_pages_per_valley,
            )
        else:
            valley_targets = {
                "Valle de Calamuchita": calamuchita_url,
                "Valle de Punilla": punilla_url,
            }
            ml_listings = scrape_all_mercadolibre_valleys(
                urls_by_valley=valley_targets,
                max_items_per_valley=max_items_per_valley,
                max_pages_per_valley=max_pages_per_valley,
            )

        Actor.log.info(f"Mercado Libre: {len(ml_listings)} publicaciones reales extraídas.")

        # 2. Extracción de Campings / Google Maps
        gmaps_reviews: list[dict[str, Any]] = []
        if scrape_all_real_campings is not None:
            try:
                Actor.log.info("Invocando scrape_all_real_campings...")
                c_res = scrape_all_real_campings(apify_token=os.getenv(apify_token_env, ""))
                gmaps_reviews = c_res.get("gmaps_reviews", [])
                Actor.log.info(
                    f"Camping scraper finalizado: {c_res.get('total_campings', 0)} campings, "
                    f"{len(gmaps_reviews)} reseñas Google Maps."
                )
            except Exception as exc:
                Actor.log.warning(f"Error ejecutando camping_scraper: {exc}")
        else:
            Actor.log.info("camping_scraper no disponible en el entorno; continuando con publicaciones reales.")

        # 3. Heurística Difusa (RapidFuzz / SentenceIndex) sobre publicaciones reales
        listing_texts = [
            f"{item.get('titulo_publicacion', '')}. {item.get('localidad_raw', '')}."
            for item in ml_listings
        ]
        enhanced_listings: list[dict[str, Any]] = []
        for idx, item in enumerate(ml_listings):
            item_text = listing_texts[idx]
            item_index = SentenceIndex([item_text])
            detected_services: list[str] = []
            for word in words:
                res = fuzzy_count(item_index, word, scorer_name=scorer_name, threshold=threshold)
                if res["count"] > 0:
                    detected_services.append(word)

            enhanced_item = dict(item)
            enhanced_item["score_servicios"] = len(detected_services)
            enhanced_item["servicios_detectados"] = detected_services
            enhanced_listings.append(enhanced_item)

        # 4. Tópicos de quejas turísticas (TF-IDF + KMeans)
        review_sentences = [str(r["texto_reseña"]) for r in gmaps_reviews if r.get("texto_reseña")]

        sentences_for_topics = review_sentences if len(review_sentences) >= 2 else split_sentences(listing_texts)
        topics_res: dict[str, Any] = {}
        if len(sentences_for_topics) >= 2:
            topics_res = find_topics(
                sentences=sentences_for_topics,
                top_n=top_topics,
                n_clusters=n_clusters,
                n_terms=n_terms,
                n_examples=n_examples,
                stop_words=stop_words,
                extra_stop_words=extra_stop_words,
            )
            Actor.log.info(
                f"Tópicos detectados ({topics_res.get('n_clusters', 0)} clusters): "
                f"{len(topics_res.get('items', []))} items principales."
            )

        # 5. Persistencia en Apify Dataset
        if enhanced_listings:
            await Actor.push_data(enhanced_listings)
            Actor.log.info(f"Dataset Apify cargado con {len(enhanced_listings)} publicaciones reales.")
        else:
            await Actor.push_data({
                "status": "completed",
                "processed_items": 0,
                "topics": topics_res,
            })
