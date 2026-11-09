from collections import Counter
from text_utils import tokenize

with conn.cursor() as cur, cur.copy(
        "COPY inverted_index (term, book_id, occurrences) FROM STDIN") as copy:
    for gid, path in livres:
        compte = Counter(tokenize(open(BOOKS_DIR / path).read()))
        for term in sorted(compte):
            copy.write_row((term, gid, compte[term]))