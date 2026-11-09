"""
Lancer en local (depuis backend/) :
    DATABASE_URL=postgresql://daar:mdpTest@localhost:5432/daar BOOKS_DIR=../data/books \
    STATIC_DIR=../frontend/static uvicorn app.main:app --reload

Le client web est servi par le conteneur front (nginx) : cette API ne renvoie que du JSON.
Le format de chaque réponse suit exactement front/static/mock.json.
"""

import os
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row, DictRow
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.algorithms.matching import boyer_moore
from scripts import tokenizer

# ============================================================
# Configuration
# ============================================================

DATABASE_URL = os.environ["DATABASE_URL"]
BOOKS_DIR = Path(os.environ.get("BOOKS_DIR", "/data/books"))

MAX_RESULTATS = 20      # nombre de livres renvoyés par recherche
NB_SUGGESTIONS = 5
MAX_VERIF_PHRASE = 50   # livres vérifiés au maximum par Boyer-Moore pour une phrase

app = FastAPI(title="Moteur de recherche DAAR")

# ============================================================
# Outils
# ============================================================

def db() -> psycopg.Connection[DictRow]:
    """Connexion à PostgreSQL. Les lignes sont renvoyées sous forme de dictionnaires."""
    return psycopg.Connection[DictRow].connect(DATABASE_URL, row_factory=dict_row)

def erreur(code, message, status=400):
    """Même format que les erreurs de mock.json."""
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def duree_ms(start):
    return round((time.perf_counter() - start) * 1000, 2)


def lire_livre(file_path):
    return (BOOKS_DIR / file_path).read_text(encoding="utf-8", errors="replace")


# ============================================================
# Adaptateurs : traduisent les fonctions de l'équipe vers le format de l'API
# ============================================================

def bm_occurrences(texte, motif):
    """
    Adapte boyer_moore.search(text, pat) -> int.

    HYPOTHÈSE À VÉRIFIER : search renvoie le NOMBRE d'occurrences.
    Si elle renvoie la POSITION de la première occurrence (-1 si absent),
    remplacer la ligne par :
        return 1 if boyer_moore.search(texte, motif) >= 0 else 0
    """
    return boyer_moore.search(texte, motif)


def classer(livres):
    """
    Classement PROVISOIRE : occurrences, puis PageRank en cas d'égalité.
    Le score est le nombre d'occurrences ramené entre 0 et 1.
    À remplacer par la fonction de classement de B dès que sa signature est connue.
    """
    if not livres:
        return []
    max_occ = max(l["occurrences"] for l in livres) or 1
    for l in livres:
        l["score"] = round(l["occurrences"] / max_occ, 4)
    return sorted(livres, key=lambda l: (l["occurrences"], l["centrality"] or 0), reverse=True)


def suggestions(conn, top_ids, k=NB_SUGGESTIONS):
    """Voisins les plus proches des meilleurs résultats dans le graphe de Jaccard."""
    if not top_ids:
        return []
    return conn.execute("""
        SELECT * FROM (
            SELECT DISTINCT ON (b.gutenberg_id)
                   b.gutenberg_id AS id, b.title, b.author, e.distance,
                   CASE WHEN e.book_a = ANY(%(ids)s) THEN e.book_a ELSE e.book_b END AS neighbor_of
            FROM jaccard_edges e
            JOIN books b
              ON b.gutenberg_id = CASE WHEN e.book_a = ANY(%(ids)s) THEN e.book_b ELSE e.book_a END
            WHERE (e.book_a = ANY(%(ids)s) OR e.book_b = ANY(%(ids)s))
              AND b.gutenberg_id <> ALL(%(ids)s)
            ORDER BY b.gutenberg_id, e.distance
        ) voisins
        ORDER BY distance
        LIMIT %(k)s
    """, {"ids": top_ids, "k": k}).fetchall()


# ============================================================
# Routes
# ============================================================

@app.get("/health")
def health():
    """Vérifie que l'API répond (utilisable par un healthcheck Docker)."""
    return {"status": "ok"}


@app.get("/api/search")
def api_search(q: str, limit: int = MAX_RESULTATS):
    """
    Recherche par mots-clés, dans l'index inversé.
    - plusieurs mots : livres qui contiennent TOUS les mots ;
    - entre guillemets ("white whale") : expression exacte, vérifiée par Boyer-Moore
      sur le texte des livres candidats.
    """
    start = time.perf_counter()
    # q = q.strip()
    # phrase: bool = len(q) > 2 and q.startswith('"') and q.endswith('"')

    terms = sorted(set(tokenizer.tokenize(q)))
    if not terms:
        return erreur("empty_query", "La requête ne contient aucun mot recherchable (mots trop courts ou trop courants).")

    with db() as conn:
        # 1. Index inversé : livres contenant tous les mots
        livres = conn.execute("""
            SELECT b.gutenberg_id AS id, b.gutenberg_id, b.title, b.author, b.file_path,
                   SUM(i.occurrences)::int AS occurrences,
                   b.pagerank AS centrality
            FROM inverted_index i
            JOIN books b ON b.gutenberg_id = i.book_id
            WHERE i.term = ANY(%s)
            GROUP BY b.gutenberg_id
            HAVING COUNT(DISTINCT i.term) = %s
            ORDER BY occurrences DESC
        """, (terms, len(terms))).fetchall()

        # # 2. Expression exacte : Boyer-Moore sur les meilleurs candidats
        # if phrase:
        #     motif = q.strip('"').lower()
        #     verifies = []
        #     for livre in livres[:MAX_VERIF_PHRASE]:
        #         n = bm_occurrences(lire_livre(livre["file_path"]).lower(), motif)
        #         if n > 0:
        #             livre["occurrences"] = n
        #             verifies.append(livre)
        #     livres = verifies

        # 3. Classement et suggestions
        classes = classer(livres)
        sugg = suggestions(conn, [l["id"] for l in classes[:3]])

    for l in classes:
        del l["file_path"]          # interne, pas dans le contrat

    return {
        "query": q,
        "mode": "keyword",
        "total": len(classes),
        "time_ms": duree_ms(start),
        "results": classes[:limit],
        "suggestions": sugg,
    }

# TODO recherche par regex
@app.get("/api/search/advanced")
def api_advanced(regex: str, scope: str = "index"):
    return erreur("not_implemented", "La recherche avancée n'est pas encore implémentée.", status=501)

# récup livre par son identifiant Gutenberg
@app.get("/api/books/{book_id}")
def api_book(book_id: int):
    with db() as conn:
        livre = conn.execute("""
            SELECT gutenberg_id AS id, gutenberg_id, title, author,
                   langue AS language, word_count, pagerank
            FROM books WHERE gutenberg_id = %s
        """, (book_id,)).fetchone()
        if livre is None:
            return erreur("not_found", f"Aucun livre avec l'identifiant {book_id}.", status=404)

        # Toujours renvoyer "neighbors" (liste vide si le graphe n'est pas encore calculé) :
        # app.js fait livre.neighbors.map(...) et plante si le champ est absent.
        livre["neighbors"] = conn.execute("""
            SELECT b.gutenberg_id AS id, b.title, b.author, e.distance
            FROM jaccard_edges e
            JOIN books b ON b.gutenberg_id = CASE WHEN e.book_a = %(id)s THEN e.book_b ELSE e.book_a END
            WHERE e.book_a = %(id)s OR e.book_b = %(id)s
            ORDER BY e.distance
            LIMIT 10
        """, {"id": book_id}).fetchall()
    return livre

# récup du texte pour lecture
@app.get("/api/books/{book_id}/text")
def api_book_text(book_id: int):
    with db() as conn:
        row = conn.execute("SELECT file_path FROM books WHERE gutenberg_id = %s", (book_id,)).fetchone()
    if row is None:
        return erreur("not_found", f"Aucun livre avec l'identifiant {book_id}.", status=404)
    
    return {"id": book_id, "text": lire_livre(row["file_path"])}


# ============================================================
# DÉVELOPPEMENT UNIQUEMENT : servir aussi le client web
# Activé seulement si la variable STATIC_DIR est définie.
# Dans Docker, elle ne l'est pas : c'est nginx qui sert le client.
# Toujours en dernier, après toutes les routes /api.
# ============================================================

# STATIC_DIR = os.environ.get("STATIC_DIR")
# if STATIC_DIR:
#     from fastapi.staticfiles import StaticFiles
#     app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
