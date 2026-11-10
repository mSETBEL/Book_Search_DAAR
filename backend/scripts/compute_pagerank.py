import os
import time

import psycopg

from app.algorithms.ranking.pagerank import pagerank

TELEPORT = 0.15  # evaporation factor
ITERATIONS = 100  # number of iterations for power iteration

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
        scores = pagerank(edges, book_ids, s=TELEPORT , t=ITERATIONS)
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