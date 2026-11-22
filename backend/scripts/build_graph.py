"""backend/scripts/build_graph.py

Builds the Jaccard graph and stores it in `jaccard_edges`.

    docker compose exec backend python -m scripts.build_graph
    docker compose exec backend python -m scripts.build_graph --keywords 300 --k 15
    docker compose exec backend python -m scripts.build_graph --method minhash

Steps
  1. Represent each book by its N most significant terms (tf-idf), read
     from `inverted_index`.
  2. For every book, find its k most similar books (Jaccard similarity of
     the keyword sets). Exact comparison, or MinHash approximation.
  3. Store the edges: each pair once, book_a < book_b,
     distance = 1 - similarity. A pair is kept if EITHER book lists the
     other among its k nearest neighbours.

Safe to re-run: the table is emptied and refilled in one transaction.
Needs the index on inverted_index(book_id) from init.sql, otherwise the
per-book reads are very slow.

Run order:  load_books -> build_graph -> compute_pagerank
"""
import argparse
import os
import time

import psycopg

from algorithms.jaccard import (make_hash_params, minhash_signature,
                                top_k_neighbors, top_k_neighbors_minhash,
                                top_n_keywords)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", type=int, default=500,
                    help="keywords kept per book (default 500)")
    ap.add_argument("--k", type=int, default=10,
                    help="nearest neighbours kept per book (default 10)")
    ap.add_argument("--threshold", type=float, default=0.0,
                    help="ignore pairs with similarity <= threshold")
    ap.add_argument("--method", choices=["exact", "minhash"], default="exact")
    ap.add_argument("--hashes", type=int, default=128,
                    help="MinHash signature length (minhash only)")
    args = ap.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        book_ids = [r[0] for r in conn.execute(
            "SELECT gutenberg_id FROM books ORDER BY gutenberg_id")]
        n_docs = len(book_ids)
        if n_docs < 2:
            print("Need at least 2 books in the database.")
            return

        # 1. keywords ------------------------------------------------------
        t0 = time.perf_counter()
        doc_freq = dict(conn.execute(
            "SELECT term, count(*) FROM inverted_index GROUP BY term"))
        keywords = {}
        for i, book_id in enumerate(book_ids, 1):
            counts = dict(conn.execute(
                "SELECT term, occurrences FROM inverted_index "
                "WHERE book_id = %s", (book_id,)))
            keywords[book_id] = top_n_keywords(
                counts, n=args.keywords, doc_freq=doc_freq, n_docs=n_docs)
            if i % 100 == 0:
                print(f"  keywords: {i}/{n_docs}")
        t_keywords = time.perf_counter() - t0
        print(f"keywords for {n_docs} books: {t_keywords:.1f}s")

        # 2. nearest neighbours -------------------------------------------
        t0 = time.perf_counter()
        if args.method == "exact":
            neighbors = top_k_neighbors(keywords, k=args.k,
                                        threshold=args.threshold)
        else:
            params = make_hash_params(args.hashes)
            signatures = {b: minhash_signature(words, params)
                          for b, words in keywords.items()}
            neighbors = top_k_neighbors_minhash(signatures, k=args.k,
                                                threshold=args.threshold)
        t_graph = time.perf_counter() - t0
        print(f"neighbours ({args.method}): {t_graph:.1f}s")

        # 3. edges: one row per unordered pair ------------------------------
        edges = {}
        for a, found in neighbors.items():
            for b, similarity in found:
                key = (a, b) if a < b else (b, a)
                edges[key] = 1.0 - similarity

        with conn.transaction():
            conn.execute("TRUNCATE jaccard_edges")
            with conn.cursor() as cur, cur.copy(
                    "COPY jaccard_edges (book_a, book_b, distance) "
                    "FROM STDIN") as copy:
                for (a, b), distance in edges.items():
                    copy.write_row((a, b, distance))
        conn.execute("ANALYZE jaccard_edges")

    linked = {x for pair in edges for x in pair}
    print(f"{len(edges)} edges stored, {n_docs - len(linked)} books without "
          f"any neighbour, average degree {2 * len(edges) / n_docs:.1f}")


if __name__ == "__main__":
    main()