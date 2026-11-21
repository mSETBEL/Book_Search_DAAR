"""
Lancer en local (depuis backend/) :
    DATABASE_URL=postgresql://daar:mdpTest@localhost:5432/daar BOOKS_DIR=../database/books \
    STATIC_DIR=../frontend/static uvicorn app.main:app --reload

Le client web est servi par le conteneur front (nginx) : cette API ne renvoie que du JSON.
Le format de chaque réponse suit exactement front/static/mock.json.
"""

import os
import time
from pathlib import Path
import re

import psycopg
from psycopg.rows import dict_row, DictRow
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from scripts import tokenizer

# ============================================================
# Configuration
# ============================================================

DATABASE_URL = os.environ["DATABASE_URL"]
BOOKS_DIR = Path(os.environ.get("BOOKS_DIR", "/database/books"))

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

def compter(texte, regex):
    return sum(1 for _ in regex.finditer(texte))


def candidats(conn, terms):
    """Livres dont chaque mot est dans l'auteur, le titre ou l'index inversé."""
    voulus = set(terms)
 
    # 1. Occurrences de chaque mot dans le texte des livres (index inversé)
    occ = {}  # id du livre -> {mot: occurrences}
    for r in conn.execute(
            "SELECT book_id, term, occurrences FROM inverted_index "
            "WHERE term = ANY(%s)", (terms,)):
        occ.setdefault(r["book_id"], {})[r["term"]] = r["occurrences"]
 
    # 2. Auteur et titre de tous les livres
    livres = []
    for b in conn.execute(
            "SELECT gutenberg_id AS id, title, author, file_path, "
            "pagerank AS centrality FROM books"):
        dans_auteur = voulus & set(tokenizer.tokenize(b["author"] or ""))
        dans_titre = voulus & set(tokenizer.tokenize(b["title"] or ""))
        dans_texte = set(occ.get(b["id"], {}))
        if voulus - (dans_auteur | dans_titre | dans_texte):
            continue  # un mot n'est trouvé nulle part : on écarte le livre
        b["author_hits"] = len(dans_auteur)
        b["title_hits"] = len(dans_titre)
        b["occurrences"] = sum(occ.get(b["id"], {}).values())
        b["matched_in"] = [nom for nom, trouve in (
            ("author", dans_auteur), ("title", dans_titre),
            ("text", dans_texte)) if trouve]
        livres.append(b)
    return livres

def candidats_regex(conn, regex):
    """Livres dont le regex est dans l'auteur, le titre ou l'index inversé."""
    livres = []
    for b in conn.execute(
            "SELECT gutenberg_id AS id, title, author, file_path, "
            "pagerank AS centrality FROM books"):
        dans_auteur = regex.search(b["author"] or "")
        dans_titre = regex.search(b["title"] or "")
        dans_texte = conn.execute(
            "SELECT 1 FROM inverted_index WHERE book_id = %s AND term ~* %s",
            (b["id"], regex.pattern)).fetchall()
        if not (dans_auteur or dans_titre or dans_texte):
            continue  # le regex n'est trouvé nulle part : on écarte le livre
        occurrences = len(dans_texte)  # nombre de mots de l'index inversé qui matchent
        b["author_hits"] = 1 if dans_auteur else 0
        b["title_hits"] = 1 if dans_titre else 0
        b["occurrences"] = occurrences
        b["matched_in"] = [nom for nom, trouve in (
                    ("author", dans_auteur), ("title", dans_titre),
                    ("text", dans_texte)) if trouve]
        livres.append(b)
    return livres

def candidats_regex_text(conn, regex):
    """Livres dont le regex est dans le texte"""

    tous = conn.execute(
        "SELECT gutenberg_id AS id, title, author, file_path, "
        "pagerank AS centrality FROM books ORDER BY gutenberg_id").fetchall()
    livres = []
    for b in tous:
        try:
            n = compter((lire_livre(b["file_path"])),regex)
        except OSError:
            continue  # fichier absent : on passe au suivant
        if n > 0:
            b["occurrences"] = n
            livres.append(b)
    return livres

def classer_texte(livres):
    """Classe les livres par occurrences du regex dans le texte (lecture complète)."""
    if not livres :
        return []
    return sorted(livres, key=lambda l: (l["occurrences"], l["centrality"] or 0),
                      reverse=True)

def classer(livres, nb_termes):
    """Auteur > titre > occurrences ; le PageRank départage les égalités.
 
    score dans [0, 1] = 0.6 * part des mots trouvés dans l'auteur
                      + 0.3 * part des mots trouvés dans le titre
                      + 0.1 * occurrences / maximum des occurrences.
    0.6 > 0.3 + 0.1 et 0.3 > 0.1 : pour une requête d'un mot, l'ordre est
    exactement « auteur, puis titre, puis occurrences ».
    """
    if not livres:
        return []
    max_occ = max(l["occurrences"] for l in livres) or 1
    for l in livres:
        l["score"] = round(0.6 * l["author_hits"] / nb_termes
                           + 0.3 * l["title_hits"] / nb_termes
                           + 0.1 * l["occurrences"] / max_occ, 4)
    return sorted(livres, key=lambda l: (l["score"], l["centrality"] or 0),
                  reverse=True)


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
        livres = candidats(conn, terms)
        # Classement et suggestions
        classes = classer(livres, len(terms))
        sugg = suggestions(conn, [l["id"] for l in classes[:3]])



        # # Expression exacte : Boyer-Moore sur les meilleurs candidats
        # if phrase:
        #     motif = q.strip('"').lower()
        #     verifies = []
        #     for livre in livres[:MAX_VERIF_PHRASE]:
        #         n = bm_occurrences(lire_livre(livre["file_path"]).lower(), motif)
        #         if n > 0:
        #             livre["occurrences"] = n
        #             verifies.append(livre)
        #     livres = verifies
    for l in classes:
        del l["file_path"], l["author_hits"], l["title_hits"]

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

    if scope not in ("index", "text"):
        return erreur("invalid_scope", "Le paramètre 'scope' doit être 'index' ou 'text'.")

    start = time.perf_counter()
    regex = regex.strip()
    if not regex:
        return erreur("empty_query", "La requête ne contient aucun mot recherchable (mots trop courts ou trop courants).")
    regex_compiled = re.compile(regex, re.IGNORECASE)

    with db() as conn:
        if scope == "index": 
            livres = candidats_regex(conn, regex_compiled)
            classes = classer(livres, 1)
        else :
            livres = candidats_regex_text(conn, regex_compiled)
            classes = livres
            classes = classer_texte(livres)
        sugg = suggestions(conn, [l["id"] for l in classes[:3]])


    return {"query": regex,
            "mode": "regex",
            "scope": scope,
            "total": len(classes),
            "time_ms": duree_ms(start),
            "results": classes[:MAX_RESULTATS],
            "suggestions": sugg}

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

# compte une consultation de la fiche d'un livre (livres populaires)
@app.post("/api/books/{book_id}/click")
def api_click(book_id: int):
    try:
        with db() as conn:
            # 1er clic : crée la ligne avec 1 ; clics suivants : ajoute 1
            conn.execute("""
                INSERT INTO clicks (book_id, nb_clic) VALUES (%s, 1)
                ON CONFLICT (book_id) DO UPDATE SET nb_clic = clicks.nb_clic + 1
            """, (book_id,))
    except psycopg.errors.ForeignKeyViolation:
        # le livre n'existe pas dans books : la clé étrangère refuse l'insertion
        return erreur("not_found", f"Aucun livre avec l'identifiant {book_id}.", status=404)
    return {"ok": True}


# livres les plus consultés, pour la page d'accueil
@app.get("/api/popular")
def api_popular(limit: int = Query(10, ge=1, le=50)):
    with db() as conn:
        livres = conn.execute("""
            SELECT b.gutenberg_id AS id, b.title, b.author, c.nb_clic
            FROM clicks c
            JOIN books b ON b.gutenberg_id = c.book_id
            WHERE c.nb_clic > 0
            ORDER BY c.nb_clic DESC, b.title
            LIMIT %s
        """, (limit,)).fetchall()
    return {"results": livres}


@app.get("/api/health")
def api_health():
    return {"status": "ok"}

# ============================================================
# DÉVELOPPEMENT UNIQUEMENT : servir aussi le client web
# Activé seulement si la variable STATIC_DIR est définie.
# Dans Docker, elle ne l'est pas : c'est nginx qui sert le client.
# Toujours en dernier, après toutes les routes /api.
# ============================================================

STATIC_DIR = os.environ.get("STATIC_DIR")
if STATIC_DIR:
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")