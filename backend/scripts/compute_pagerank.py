"""backend/scripts/compute_pagerank.py

Reads the Jaccard graph from `jaccard_edges`, runs PageRank, and writes the
score of every book into books.pagerank.

Run it after the graph is built, and again whenever the graph changes:
    docker compose exec backend python -m scripts.compute_pagerank

Uses pagerank() from algorithms/pagerank.py (the sparse version).
"""
import os
import time

import psycopg

from algorithms.pagerank import pagerank

TELEPORT = 0.15  # s = 1 - damping; try 0.05 / 0.15 / 0.30 for the report


def main():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        book_ids = [r[0] for r in conn.execute("SELECT gutenberg_id FROM books")]
        rows = conn.execute(
            "SELECT book_a, book_b, distance FROM jaccard_edges").fetchall()
        if not rows:
            print("jaccard_edges is empty: build the graph first.")
            return

        # Edges are stored once (a < b) as a distance. PageRank wants a
        # weight where larger = more related, in both directions.
        edges = []
        for a, b, distance in rows:
            similarity = 1.0 - distance
            edges.append((a, b, similarity))
            edges.append((b, a, similarity))

        t0 = time.perf_counter()
        scores = pagerank(edges, book_ids, s=TELEPORT)
        elapsed = time.perf_counter() - t0

        with conn.transaction():
            conn.cursor().executemany(
                "UPDATE books SET pagerank = %s WHERE gutenberg_id = %s",
                [(score, book_id) for book_id, score in scores.items()])

    best = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:5]
    print(f"{len(book_ids)} books, {len(rows)} edges, "
          f"PageRank in {elapsed * 1000:.1f} ms")
    print("top 5:", [(b, round(s, 5)) for b, s in best])


if __name__ == "__main__":
    main()