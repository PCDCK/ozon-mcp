"""BM25 full-text search across the catalog.

The index uses field boosting via document repetition: each method's
``summary`` is repeated 4x, ``path`` and ``operation_id`` 3x each, ``section``
and ``tag`` 2x each, and ``description`` 1x. BM25Okapi doesn't support
explicit field weights, so repetition is the standard workaround and gives
us roughly the same effect.

CamelCase tokenization splits operation_ids like ``FinanceAPI_FinanceTransactionListV3``
into ``[finance, api, finance, transaction, list, v3]`` so substring matches
on individual words work even when the user types only one component.

Russian and English go through Snowball stemmers so morphological forms
collapse to the same root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import snowballstemmer
from rank_bm25 import BM25Okapi

from ozon_mcp.schema.catalog import Catalog
from ozon_mcp.schema.extractor import Method

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_CAMEL_RE = re.compile(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[a-z]+|\d+")
_RU_STEMMER = snowballstemmer.stemmer("russian")
_EN_STEMMER = snowballstemmer.stemmer("english")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")

# Field boost weights — higher = more important. BM25Okapi has no field
# concept, so we implement boosting by repeating each field's tokens this
# many times in the document.
_BOOST_SUMMARY = 4
_BOOST_PATH = 3
_BOOST_OPERATION_ID = 3
_BOOST_SECTION = 2
_BOOST_TAG = 2
_BOOST_DESCRIPTION = 1

# Tokens that appear in operation_ids without adding semantic value. We
# strip them when measuring "op_id precision" so a name like
# `ProductAPI_GetProductList` is judged on (Product, Get, List) not on
# (Api, Product, Get, List). Both raw and stemmed forms are listed because
# English Snowball turns "api" → "ap".
_OP_ID_NOISE = frozenset(
    {
        "api", "ap",
        "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10",
    }
)

# op_id camel-tokens that indicate a read-style method. When one of these
# fires we nudge the final score so that "list / info / details / …"
# methods surface above sibling writes for generic natural-language queries
# like "товары" or "order". Matched on the raw camel tokens BEFORE stemming
# so we don't need to worry about Snowball "list" → "list" etc.
_GET_KEYWORDS = frozenset(
    {
        "get", "list", "fetch", "info", "details",
        "search", "find", "summary", "stat", "analytics",
    }
)

# op_id camel-tokens that indicate a mutating method. Paired with
# safety != "read" this demotes writes when the query is ambiguous.
_WRITE_KEYWORDS = frozenset(
    {
        "create", "add", "update", "delete", "remove",
        "cancel", "archive", "import", "upload", "set",
    }
)

# Lightweight morphological expansion for single-form Russian queries. Russian
# Snowball does not collapse all noun cases to the same stem (e.g. "остаток"
# → "остаток" but "остатки" → "остатк"), so a nominal singular query misses
# methods whose summary uses the plural — and those are exactly how Ozon
# writes most list endpoints ("Список товаров", "Остатки на складе", etc.).
# Expanding the query with common sibling forms fixes the single-word case
# without replacing Snowball everywhere.
_RUSSIAN_QUERY_EXPANSIONS: dict[str, list[str]] = {
    # Singular nouns → sibling plural/variant forms. Expansion is additive
    # (we keep the original form too) so we never *lose* matches; we only
    # broaden recall. Keep expansions tightly scoped to direct synonyms —
    # throwing "склад" onto an "остаток" query pulls in stock-update methods
    # whose summary mentions "на складах" and drowns out the pure
    # GetProductInfoStocks viewer.
    "остаток": ["остатки", "остаток"],
    "товар": ["товары", "товар"],
    "заказ": ["заказы", "заказ", "отправление", "отправления"],
    "цена": ["цены", "цена"],
    "склад": ["склады", "склад"],
    "акция": ["акции", "акция"],
    "отчёт": ["отчёты", "отчёт"],
    "отчет": ["отчёты", "отчёт"],
    "возврат": ["возвраты", "возврат"],
}


def _expand_russian_query(query: str) -> str:
    """Expand known single-form Russian keywords with sibling morphology.

    Walks whitespace-separated tokens, and for each token present in
    _RUSSIAN_QUERY_EXPANSIONS appends the canonical plural/variant forms.
    Leaves the original query (and its casing — matters for CamelCase
    op_id queries like ``FinanceTransactionList``) untouched; additions
    are only appended.
    """
    raw_tokens = query.split()
    if not raw_tokens:
        return query
    expanded: list[str] = list(raw_tokens)
    for token in raw_tokens:
        variants = _RUSSIAN_QUERY_EXPANSIONS.get(token.lower())
        if variants:
            expanded.extend(variants)
    return " ".join(expanded)


def _camel_tokens(text: str) -> list[str]:
    """Split an identifier into lowercased CamelCase/underscore tokens."""
    return [t.lower() for t in _CAMEL_RE.findall(text)]


@dataclass
class SearchResult:
    method: Method
    score: float


class SearchIndex:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self._methods: list[Method] = list(catalog.methods)
        documents = [self._document(m) for m in self._methods]
        # b=0.3 reduces the BM25 length-normalization penalty so a long
        # operation_id (e.g. PostingAPI_GetFboPostingList) doesn't lose to
        # a much shorter one (PostingAPI_GetFboPosting) just for being longer.
        self._bm25 = BM25Okapi(documents, b=0.3, k1=1.5)

    def search(
        self,
        query: str,
        *,
        section: str | None = None,
        api: str | None = None,
        limit: int = 10,
        include_deprecated: bool = False,
    ) -> list[SearchResult]:
        # Expand common Russian single-form nouns to their sibling morphology
        # before tokenization so `остаток` also reaches methods written with
        # `остатки` in the summary. No-op for queries that hit none of the
        # expansion keys.
        expanded_query = _expand_russian_query(query)
        tokens = _tokenize_query(expanded_query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        query_lower = query.lower().strip()
        # Use plain-stemmed tokens for matching natural-language fields
        # (summary, description), and camel-split tokens for matching
        # operation_ids and paths. Never mix the two — `getfbopostinglist`
        # as a single token would never match anything in the index.
        query_plain = set(_tokenize(expanded_query))
        query_camel = set(_tokenize_with_camel(expanded_query))

        adjusted: list[tuple[int, float]] = []
        for i, s in enumerate(scores):
            m = self._methods[i]
            mult = 1.0

            if m.deprecated:
                mult *= 0.3

            summary_lower = m.summary.lower().strip()
            if summary_lower:
                # 1. Exact equality with summary — strongest signal of canonicity.
                if query_lower == summary_lower:
                    mult *= 8.0
                # 2. Substring match in summary — bonus inversely proportional
                #    to summary length so the shortest matching summary wins.
                elif len(query_lower) >= 3 and query_lower in summary_lower:
                    ratio = len(query_lower) / len(summary_lower)
                    mult *= 1.0 + 4.0 * ratio  # 1x..5x

            # 3. Summary token superset — every query word appears in summary.
            summary_tokens_cached: set[str] = (
                set(_tokenize(m.summary)) if query_plain else set()
            )
            if query_plain and query_plain.issubset(summary_tokens_cached):
                mult *= 2.0

            # 4. operation_id token superset — every query word appears in
            #    the CamelCase-split op_id. The bonus is inversely proportional
            #    to "noise" (extra tokens in the op_id), so a shorter and more
            #    focused op_id wins. This is the PRIMARY bridge between
            #    English queries and Russian summaries.
            op_lower = m.operation_id.lower()
            if query_camel:
                op_tokens = set(_tokenize_with_camel(m.operation_id)) - _OP_ID_NOISE
                if op_tokens and query_camel.issubset(op_tokens):
                    precision = len(query_camel) / len(op_tokens)
                    mult *= 1.0 + 6.0 * precision  # 1x..7x
                elif op_tokens:
                    # Partial overlap: boost proportionally to how much of the
                    # query is covered by the op_id tokens.
                    overlap = query_camel & op_tokens
                    if len(overlap) >= 2 and len(overlap) >= len(query_camel) * 0.5:
                        mult *= 1.0 + 1.5 * (len(overlap) / len(op_tokens))

            # 4b. Adjacency bonus: if the user's query (without spaces) appears
            #    as a literal substring of the operation_id (lowercase),
            #    that's a very strong canonicity signal — the agent typed the
            #    exact concatenation that Ozon uses to name the method.
            #    "product list" → "productlist" → in "getproductlist" ✓
            #                                   not in "certificateproductslist"
            query_concat = re.sub(r"\W+", "", query.lower())
            if len(query_concat) >= 5 and query_concat in op_lower:
                mult *= 2.5

            # 5. Path query — when the query looks like a URL path, prefer
            #    methods whose path literally contains the query as substring.
            if "/" in query_lower and query_lower.strip("/") in m.path.lower().strip("/"):
                mult *= 4.0

            # 6. Safety-aware reranking. Most BI agent intents are
            #    "find me a method to fetch X", so read methods should beat
            #    writes at comparable text relevance. Previous 1.05x was too
            #    mild — a short write op_id (AddProducts, OrderCreate) could
            #    still edge out the read sibling for generic single-word
            #    queries like "товары" / "заказ".
            if m.safety == "read":
                mult *= 1.35

            # 6b. Op-id verb heuristics. Independent of the `safety` field,
            #    explicit "get / list / info / details / ..." hints in the
            #    op_id are a strong signal of read intent; "create / update /
            #    delete / ..." verbs on non-read methods deserve a gentle
            #    penalty so the ambiguous-query ranking prefers the viewer
            #    over the mutator.
            op_camel = set(_camel_tokens(m.operation_id))
            if op_camel & _GET_KEYWORDS:
                mult *= 1.1
            if m.safety != "read" and op_camel & _WRITE_KEYWORDS:
                mult *= 0.85

            # 6c. Destructive methods should never win an ambiguous
            #    single-word query ("товары" / "order") — an agent that
            #    really wants to delete something will say so explicitly.
            if m.safety == "destructive":
                mult *= 0.6

            # 6d. Canonical-viewer heuristic: short read summaries like
            #    "Список товаров" or "Список складов" are the textbook
            #    entry points for browsing. When a read method's summary is
            #    tiny (≤3 stemmed tokens) and fully covers the query, give
            #    it a decisive boost over longer siblings whose summary
            #    happens to contain the same noun ("Удалить товары из
            #    акции"). This is what an agent intuitively expects when
            #    asking for "товары" / "заказ" / "склад".
            if (
                m.safety == "read"
                and query_plain
                and query_plain.issubset(summary_tokens_cached)
                and 0 < len(summary_tokens_cached) <= 3
            ):
                mult *= 2.5

            # 6e. Section-name hit. Ozon groups related methods into
            #    human-readable sections like "Prices and stocks of
            #    goods" that carry the domain vocabulary even when an
            #    individual summary does not (the Russian summary may
            #    use a synonym while the section name carries the
            #    canonical keyword). Honour that grouping: if every
            #    query token (stemmed) appears in the section name AND
            #    the method is read, nudge it up so the canonical read
            #    method in the right section rises above siblings whose
            #    summary has an incidental keyword match.
            if m.safety == "read" and query_plain:
                section_tokens = set(_tokenize(m.section))
                if query_plain.issubset(section_tokens):
                    mult *= 1.4

            # 6f. Description-subset match. Curated descriptions (see
            #    descriptions_overrides.yaml) often carry the domain
            #    vocabulary that the concise summary omits. Reward methods
            #    whose description fully covers the stemmed query — a
            #    strong signal that the method is actually about the
            #    queried concept even if the summary uses different
            #    terminology.
            if m.safety == "read" and query_plain and m.description:
                description_tokens = set(_tokenize(m.description))
                if query_plain.issubset(description_tokens):
                    mult *= 1.25

            adjusted.append((i, s * mult))
        ranked = sorted(adjusted, key=lambda x: -x[1])
        results: list[SearchResult] = []
        for idx, score in ranked:
            if score <= 0:
                break
            m = self._methods[idx]
            if not include_deprecated and m.deprecated:
                continue
            if section and section.lower() not in m.section.lower() and section.lower() not in m.tag.lower():
                continue
            if api and m.api != api:
                continue
            results.append(SearchResult(method=m, score=float(score)))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _document(m: Method) -> list[str]:
        out: list[str] = []
        # Boosted fields (high weight)
        out.extend(_tokenize(m.summary) * _BOOST_SUMMARY)
        out.extend(_tokenize_with_camel(m.path) * _BOOST_PATH)
        out.extend(_tokenize_with_camel(m.operation_id) * _BOOST_OPERATION_ID)
        out.extend(_tokenize(m.section) * _BOOST_SECTION)
        out.extend(_tokenize(m.tag) * _BOOST_TAG)
        # Description gets the natural weight of 1.
        out.extend(_tokenize(m.description) * _BOOST_DESCRIPTION)
        return out


def _tokenize(text: str) -> list[str]:
    """Tokenize plain text with stemming. Skips single-char tokens."""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        if len(raw) <= 1:
            continue
        if _CYRILLIC_RE.search(raw):
            out.append(_RU_STEMMER.stemWord(raw))
        else:
            out.append(_EN_STEMMER.stemWord(raw))
    return out


def _tokenize_with_camel(text: str) -> list[str]:
    """Tokenize text including CamelCase splitting.

    For ``FinanceAPI_FinanceTransactionListV3`` this yields
    ``[finance, api, finance, transaction, list, v3]`` after stemming.
    Useful for operation_ids and paths where individual words are concatenated.
    """
    out: list[str] = []
    # First split on whitespace + non-word boundaries
    for chunk in _TOKEN_RE.findall(text):
        # Then split CamelCase within each chunk
        for word in _CAMEL_RE.findall(chunk):
            w = word.lower()
            if len(w) <= 1:
                continue
            if _CYRILLIC_RE.search(w):
                out.append(_RU_STEMMER.stemWord(w))
            else:
                out.append(_EN_STEMMER.stemWord(w))
    return out


def _tokenize_query(query: str) -> list[str]:
    """Tokenize a user query.

    Combines the plain tokenizer with CamelCase splitting so that a single
    typed-as-one identifier like ``FinanceTransactionList`` becomes a useful
    multi-token query, while regular phrases like ``финансовые транзакции``
    still work normally.
    """
    plain = _tokenize(query)
    camel = _tokenize_with_camel(query)
    if not plain:
        return camel
    if not camel:
        return plain
    # Dedupe while preserving order: plain tokens first (most natural-language
    # weight), then camel tokens that aren't already covered.
    seen = set(plain)
    out = list(plain)
    for t in camel:
        if t not in seen:
            out.append(t)
            seen.add(t)
    return out
