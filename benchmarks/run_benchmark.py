#!/usr/bin/env python3
"""
Benchmark principal : pour chaque taille de bibliothèque N (200, 500, 1000, 1664)
  1. charge les livres (nettoyage + tokenisation + index inversé)        -> build_times.json
  2. construit le graphe de Jaccard (script du projet, tel quel)        -> build_times.json
  3. calcule le PageRank (fonction du projet, telle quelle + référence)  -> build_times.json
  4. mesure les temps de réponse de l'API (HTTP, uvicorn réel)           -> query_timings.csv

Les bibliothèques de taille croissante sont EMBOÎTÉES (200 ⊂ 500 ⊂ 1000 ⊂ 1664),
tirées au hasard avec une graine fixe : la seule variable qui change entre deux
mesures est donc N.

Rien n'est modifié dans le projet : tout se passe dans une base séparée `daar_bench`.

Exemples :
    python benchmarks/run_benchmark.py                      # protocole complet
    python benchmarks/run_benchmark.py --sizes 200 500 --reps 10 --reps-text 2   # test rapide
"""
import argparse
import csv
import math
import os
import random
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg
import requests

import centrality_lib as cl
from common import (BACKEND, DEFAULT_ADMIN_URL, REPO, RESULTS, SEED, SIZES, ApiServer,
                    machine_info, recreate_database, save_json, load_json, summarize)

sys.path.insert(0, str(BACKEND / "scripts"))   # load_books fait « from tokenizer import tokenize »
import load_books  # noqa: E402  (code du projet, utilisé tel quel)

CSV_PATH = RESULTS / "query_timings.csv"
CSV_FIELDS = ["size", "family", "mode", "qname", "query", "rep", "warmup",
              "client_ms", "server_ms", "total", "returned", "http"]

# Patterns identiques pour l'index et le texte (syntaxe commune Python `re` / POSIX ARE de PostgreSQL :
# pas d'ancres ni de \b, qui n'ont pas le même sens dans les deux moteurs).
FIXED_REGEX = {
    "rx_union": r"s(a|g|r)+on",          # union + étoile (cf. cours)
    "rx_alt": r"(king|queen)dom",        # alternation
    "rx_class": r"un[a-z]{3,8}ing",      # classe de caractères + répétition bornée : beaucoup de correspondances
}


# ----------------------------------------------------------------------------
# 1. Chargement incrémental
# ----------------------------------------------------------------------------
def list_book_files(books_dir: Path):
    files = sorted(books_dir.rglob("*.txt"))
    random.Random(SEED).shuffle(files)
    return files


class Loader:
    """Charge les livres dans l'ordre aléatoire fixé, en mesurant le temps."""

    def __init__(self, conn, books_dir, files):
        self.conn, self.books_dir, self.files = conn, books_dir, files
        self.pos = 0
        self.accepted = []           # ids Gutenberg acceptés, dans l'ordre
        self.rejected = 0
        self.t_total = 0.0

    def load_until(self, n):
        t_inc, count_before = 0.0, len(self.accepted)
        while len(self.accepted) < n and self.pos < len(self.files):
            path = self.files[self.pos]
            self.pos += 1
            t0 = time.perf_counter()
            status = load_books.load_book(self.conn, path, self.books_dir)
            dt = time.perf_counter() - t0
            if status.startswith("ok") or status == "already loaded":
                gid = int(re.search(r"\d+", path.stem).group())
                self.accepted.append(gid)
                t_inc += dt
            else:
                self.rejected += 1
                t_inc += dt          # le coût de lecture/tokenisation d'un rejet compte aussi
        t0 = time.perf_counter()
        self.conn.execute("ANALYZE")
        t_analyze = time.perf_counter() - t0
        self.t_total += t_inc
        return {"loaded_now": len(self.accepted) - count_before, "load_s_increment": t_inc,
                "load_s_cumulative": self.t_total, "analyze_s": t_analyze}


def corpus_stats(conn, books_dir, ids):
    q = conn.execute
    tokens = q("SELECT COALESCE(sum(word_count),0) FROM books").fetchone()[0]
    rows = q("SELECT count(*) FROM inverted_index").fetchone()[0]
    distinct = q("SELECT count(DISTINCT term) FROM inverted_index").fetchone()[0]
    sz_idx = q("SELECT pg_total_relation_size('inverted_index')").fetchone()[0]
    sz_books = q("SELECT pg_total_relation_size('books')").fetchone()[0]
    paths = [r[0] for r in q("SELECT file_path FROM books")]
    text_bytes = sum((books_dir / p).stat().st_size for p in paths if (books_dir / p).exists())
    return {"n_books": len(paths), "tokens": int(tokens), "index_rows": int(rows),
            "distinct_terms": int(distinct), "index_bytes": int(sz_idx),
            "books_table_bytes": int(sz_books), "text_bytes": int(text_bytes)}


# ----------------------------------------------------------------------------
# 2. Graphe de Jaccard : script du projet exécuté tel quel
# ----------------------------------------------------------------------------
def run_build_graph(database_url):
    env = dict(os.environ, DATABASE_URL=database_url, PYTHONUNBUFFERED="1")
    t0 = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "scripts.build_graph"], cwd=BACKEND, env=env,
                       capture_output=True, text=True)
    wall = time.perf_counter() - t0
    if p.returncode != 0:
        raise RuntimeError("build_graph a échoué :\n" + p.stderr[-3000:])
    out = p.stdout
    m_kw = re.search(r"keywords for \d+ books: ([\d.]+)s", out)
    m_nb = re.search(r"neighbours: ([\d.]+)s", out)
    m_ed = re.search(r"(\d+) edges stored, (\d+) books without any neighbour, average degree ([\d.]+)", out)
    return {"graph_wall_s": wall,
            "graph_keywords_s": float(m_kw.group(1)) if m_kw else None,
            "graph_neighbors_s": float(m_nb.group(1)) if m_nb else None,
            "graph_write_and_other_s": (wall - float(m_kw.group(1)) - float(m_nb.group(1)))
            if (m_kw and m_nb) else None,
            "edges": int(m_ed.group(1)) if m_ed else None,
            "isolated_books": int(m_ed.group(2)) if m_ed else None,
            "avg_degree": float(m_ed.group(3)) if m_ed else None}


# ----------------------------------------------------------------------------
# 3. PageRank (projet tel quel) + référence
# ----------------------------------------------------------------------------
def _nan_none(x):
    return None if (x is None or (isinstance(x, float) and math.isnan(x))) else x


def run_pagerank(conn, impl):
    ids, meta, edges = cl.load_graph(conn)
    proj, t_proj = cl.project_pagerank(edges, ids)
    ref, t_ref, iters = cl.pagerank_reference(edges, ids)
    chosen = proj if impl == "project" else ref
    with conn.cursor() as cur:
        cur.executemany("UPDATE books SET pagerank=%s WHERE gutenberg_id=%s",
                        [(v, k) for k, v in chosen.items()])
    import numpy as np
    pv = np.array([proj[i] for i in ids])
    rv = np.array([ref[i] for i in ids])
    return {"pagerank_project_s": t_proj, "pagerank_reference_s": t_ref,
            "pagerank_reference_iterations": iters, "pagerank_stored": impl,
            "pagerank_spearman_project_vs_reference": _nan_none(cl.spearman(pv, rv)) if len(ids) > 2 else None,
            "pagerank_project_max_over_min": float(pv.max() / pv.min()) if pv.min() > 0 else None,
            "pagerank_reference_max_over_min": float(rv.max() / rv.min()) if rv.min() > 0 else None}


# ----------------------------------------------------------------------------
# 4. Requêtes
# ----------------------------------------------------------------------------
def select_queries(conn, n0):
    """Choisit les requêtes UNE FOIS (sur la plus petite bibliothèque) ; comme les
    bibliothèques sont emboîtées, ces termes existent dans toutes les tailles."""
    rng = random.Random(SEED)
    df = [(t, c) for t, c in conn.execute(
        "SELECT term, count(*) FROM inverted_index GROUP BY term")
        if re.fullmatch(r"[a-z]{4,12}", t)]

    def closest(frac, exclude=()):
        target = max(2, round(frac * n0))
        best = min(abs(c - target) for t, c in df if t not in exclude)
        pool = [t for t, c in df if abs(c - target) == best and t not in exclude]
        return rng.choice(sorted(pool))

    rare = closest(0.01)
    mid = closest(0.10)
    freq1 = closest(0.50)
    freq2 = closest(0.50, exclude={freq1})
    books = [b for b in conn.execute("SELECT title, author FROM books WHERE author IS NOT NULL ORDER BY gutenberg_id")
             if re.search(r"[A-Za-z]{3,}", b[1])]
    title, author = rng.choice(books)
    surname = re.findall(r"[A-Za-z]{3,}", author)[0].lower()
    words = sorted(re.findall(r"[A-Za-z]{5,}", title), key=len, reverse=True)
    title_word = (words[0] if words else surname).lower()

    kw = {"kw_rare": rare, "kw_mid": mid, "kw_freq": freq1,
          "kw_2words": f"{mid} {freq1}", "kw_3words": f"{mid} {freq1} {freq2}",
          "kw_author": surname, "kw_title": title_word}
    rx = {"rx_literal_rare": rare, "rx_literal_mid": mid, **FIXED_REGEX}
    df_map = dict(df)
    info = {"keyword": kw, "regex": rx,
            "df_at_n0": {k: df_map.get(v) for k, v in
                         [("rare", rare), ("mid", mid), ("freq1", freq1), ("freq2", freq2)]},
            "n0": n0, "author_example": author, "title_example": title}
    return info


def timed_get(sess, url, params):
    t0 = time.perf_counter()
    r = sess.get(url, params=params, timeout=3600)
    client_ms = (time.perf_counter() - t0) * 1000
    js = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    return client_ms, js, r.status_code


def bench_one(sess, size, rows, family, mode, qname, query, url, params, reps):
    for rep in range(-1, reps):           # rep = -1 : échauffement (jeté des statistiques)
        client_ms, js, code = timed_get(sess, url, params)
        rows.append({"size": size, "family": family, "mode": mode, "qname": qname, "query": query,
                     "rep": rep, "warmup": int(rep < 0), "client_ms": round(client_ms, 2),
                     "server_ms": js.get("time_ms"), "total": js.get("total"),
                     "returned": len(js.get("results", [])) if isinstance(js, dict) else None,
                     "http": code})
    s = summarize([r["server_ms"] for r in rows
                   if r["qname"] == qname and r["mode"] == mode and r["size"] == size
                   and not r["warmup"] and r["server_ms"] is not None])
    print(f"    {mode:<12} {qname:<16} {query!r:<34} serveur {s.get('mean', float('nan')):9.1f} ms "
          f"± {s.get('std', 0):7.1f}   résultats={rows[-1]['total']}", flush=True)


def vocab_alternative(conn, size, rows, patterns, reps):
    """Piste d'amélioration (NON implémentée dans le projet) : regex d'abord sur le
    vocabulaire distinct, puis jointure avec l'index inversé. Mesuré en SQL direct."""
    t0 = time.perf_counter()
    conn.execute("DROP TABLE IF EXISTS bench_vocab")
    conn.execute("CREATE TABLE bench_vocab AS SELECT DISTINCT term FROM inverted_index")
    conn.execute("CREATE INDEX ON bench_vocab (term)")
    conn.execute("ANALYZE bench_vocab")
    t_build = time.perf_counter() - t0
    for qname, pat in patterns.items():
        for rep in range(-1, reps):
            t0 = time.perf_counter()
            n = conn.execute(
                "SELECT count(DISTINCT i.book_id) FROM bench_vocab v "
                "JOIN inverted_index i ON i.term = v.term WHERE v.term ~* %s", (pat,)).fetchone()[0]
            ms = (time.perf_counter() - t0) * 1000
            rows.append({"size": size, "family": "regex", "mode": "index_vocab", "qname": qname,
                         "query": pat, "rep": rep, "warmup": int(rep < 0), "client_ms": round(ms, 2),
                         "server_ms": round(ms, 2), "total": n, "returned": None, "http": 0})
    return t_build


def run_queries(database_url, books_dir, size, queries, reps, reps_idx, reps_text, conn):
    rows = []
    with ApiServer(database_url, books_dir) as srv, requests.Session() as sess:
        base = srv.base
        print(f"  -- recherche par mots-clés ({reps} répétitions)")
        for qname, q in queries["keyword"].items():
            bench_one(sess, size, rows, "keyword", "keyword", qname, q, base + "/api/search",
                      {"q": q}, reps)
        print(f"  -- regex sur l'index ({reps_idx} répétitions)")
        for qname, rx in queries["regex"].items():
            bench_one(sess, size, rows, "regex", "index", qname, rx, base + "/api/search/advanced",
                      {"regex": rx, "scope": "index"}, reps_idx)
        print(f"  -- regex sur le texte complet ({reps_text} répétitions)")
        for qname, rx in queries["regex"].items():
            bench_one(sess, size, rows, "regex", "text", qname, rx, base + "/api/search/advanced",
                      {"regex": rx, "scope": "text"}, reps_text)
        print("  -- autres routes")
        some_id = conn.execute("SELECT gutenberg_id FROM books ORDER BY gutenberg_id LIMIT 1").fetchone()[0]
        for qname, path in [("popular", "/api/popular"), ("book_detail", f"/api/books/{some_id}"),
                            ("health", "/api/health")]:
            bench_one(sess, size, rows, "other", "other", qname, path, base + path, {}, reps)
    print(f"  -- piste d'amélioration : regex sur le vocabulaire distinct ({reps_idx} répétitions)")
    t_vocab = vocab_alternative(conn, size, rows, queries["regex"], reps_idx)
    return rows, t_vocab


def write_csv(all_rows):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(all_rows)


def read_csv_excluding(sizes):
    if not CSV_PATH.exists():
        return []
    with open(CSV_PATH, encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if int(r["size"]) not in sizes]


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--books-dir", type=Path, default=REPO / "database" / "books")
    ap.add_argument("--admin-url", default=DEFAULT_ADMIN_URL,
                    help="PostgreSQL de benchmark (défaut : conteneur dédié, port 55432)")
    ap.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    ap.add_argument("--reps", type=int, default=30, help="répétitions, recherche par mots-clés")
    ap.add_argument("--reps-index", type=int, default=10, help="répétitions, regex sur l'index")
    ap.add_argument("--reps-text", type=int, default=5, help="répétitions, regex sur le texte")
    ap.add_argument("--pagerank-impl", choices=["project", "reference"], default="project",
                    help="quel PageRank est écrit dans books.pagerank (défaut : celui du projet)")
    ap.add_argument("--skip-queries", action="store_true")
    ap.add_argument("--keep-queries", action="store_true",
                    help="réutiliser results/queries_selected.json (obligatoire si on ne relance "
                         "qu'une partie des tailles, pour garder les mêmes requêtes)")
    args = ap.parse_args()

    sizes = sorted(args.sizes)
    files = list_book_files(args.books_dir)
    print(f"{len(files)} fichiers .txt trouvés dans {args.books_dir}")
    if not files:
        sys.exit("Aucun livre : remplir database/books/ d'abord.")

    url = recreate_database(args.admin_url, fresh=True)
    print("Base de benchmark :", url.rsplit("@", 1)[-1])
    save_json("machine.json", machine_info())

    build_results, all_rows = load_json("build_times.json", []), read_csv_excluding(sizes)
    build_results = [b for b in build_results if b["size"] not in sizes]
    queries = load_json("queries_selected.json") if args.keep_queries else None

    with psycopg.connect(url, autocommit=True) as conn:
        loader = Loader(conn, args.books_dir, files)
        for size in sizes:
            print(f"\n================ N = {size} livres ================")
            info = loader.load_until(size)
            if len(loader.accepted) < size:
                print(f"  !! seulement {len(loader.accepted)} livres valides (>= 10 000 mots) : taille ignorée")
                break
            rec = {"size": size, **info, "rejected_so_far": loader.rejected,
                   **corpus_stats(conn, args.books_dir, loader.accepted)}
            print(f"  chargement : +{info['loaded_now']} livres en {info['load_s_increment']:.1f}s "
                  f"(cumul {info['load_s_cumulative']:.1f}s) ; {rec['index_rows']:,} lignes d'index")

            print("  graphe de Jaccard (scripts.build_graph du projet)…", flush=True)
            rec.update(run_build_graph(url))
            print(f"    total {rec['graph_wall_s']:.1f}s (mots-clés {rec['graph_keywords_s']}s, "
                  f"voisins {rec['graph_neighbors_s']}s, écriture/autre {rec['graph_write_and_other_s']}s)")

            print("  PageRank…", flush=True)
            rec.update(run_pagerank(conn, args.pagerank_impl))
            print(f"    projet {rec['pagerank_project_s']:.1f}s | référence creuse {rec['pagerank_reference_s']:.3f}s "
                  f"| Spearman projet/référence = {rec['pagerank_spearman_project_vs_reference']}")
            conn.execute("ANALYZE")

            if not args.skip_queries:
                if queries is None:
                    queries = select_queries(conn, size)
                    save_json("queries_selected.json", queries)
                    print("  requêtes choisies :", queries["keyword"], queries["regex"])
                rows, t_vocab = run_queries(url, args.books_dir, size, queries, args.reps,
                                            args.reps_index, args.reps_text, conn)
                rec["vocab_table_build_s"] = t_vocab
                all_rows = [r for r in all_rows if int(r["size"]) != size] + rows
                write_csv(all_rows)
            build_results.append(rec)
            save_json("build_times.json", sorted(build_results, key=lambda b: b["size"]))
    print("\nTerminé. Résultats dans", RESULTS)


if __name__ == "__main__":
    main()
