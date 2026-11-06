import argparse
import os
import time

from algorithms.jaccard import *
import psycopg

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", type=int, default=500,
                    help="keywords kept per book (default 500)")
    ap.add_argument("--k", type=int, default=10,
                    help="nearest neighbours kept per book (default 10)")
    ap.add_argument("--threshold", type=float, default=0.0,
                    help="ignore pairs with similarity <= threshold")
    args = ap.parse_args()

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        book_ids = [r[0] for r in conn.execute(
            "SELECT gutenberg_id FROM books ORDER BY gutenberg_id")]
        n_docs = len(book_ids)
        if n_docs < 2:
            print("Need at least 2 books in the database.")
            return


        # Select the keywords
        t0 = time.perf_counter()
        doc_freq = dict(conn.execute("SELECT term, count(*) FROM inverted_index GROUP BY term"))
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

        # Nearest neighbours
        t0 = time.perf_counter()
        neighbors = top_k_neighbors(keywords, k=args.k, threshold=args.threshold)
        t_graph = time.perf_counter() - t0
        print(f"neighbours: {t_graph:.1f}s")


        # Write the graph to the database
        edges ={}
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
