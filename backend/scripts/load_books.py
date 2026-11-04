"""back/scripts/load_books.py

Reads Gutenberg .txt files from BOOKS_DIR, cleans them, counts the words
and fills the tables `books` and `inverted_index`.

Run inside the backend container:
    docker compose exec backend python -m scripts.load_books
    docker compose exec backend python -m scripts.load_books --limit 5

Safe to re-run: books already in the database are skipped.
"""
import argparse
import os
import re
import time
from collections import Counter
from pathlib import Path

import psycopg

MIN_WORDS = 10_000  # same rule as the CHECK constraint in init.sql
WORD_RE = re.compile(r"[^\W\d_]+")  # runs of letters (accents included)


# --- reading and cleaning -------------------------------------------------
def read_text(path: Path) -> str:
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")  # some old Gutenberg files


def split_gutenberg(text: str):
    """Return (header_lines, body_lines) without the licence boilerplate."""
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("*** START OF")), None)
    header = lines[: start if start is not None else 200]
    body_from = start + 1 if start is not None else 0
    end = next((i for i in range(body_from, len(lines))
                if lines[i].startswith("*** END OF")), len(lines))
    return header, lines[body_from:end]


def header_field(header, key):
    prefix = key + ":"
    for line in header:
        if line.startswith(prefix):
            return line[len(prefix):].strip() or None
    return None


def tokenize(text: str):
    """Replace with algorithms.tokenizer.tokenize once it exists: the SAME
    function must be used here and when parsing a user's query."""
    return WORD_RE.findall(text.lower())


# --- database ---------------------------------------------------------------
def load_book(conn, path: Path, books_dir: Path):
    m = re.search(r"\d+", path.stem)
    if not m:
        return "skipped (no id in filename)"
    gid = int(m.group())

    header, body = split_gutenberg(read_text(path))
    tokens = tokenize("\n".join(body))
    if len(tokens) < MIN_WORDS:
        return f"rejected ({len(tokens)} words < {MIN_WORDS})"
    counts = Counter(tokens)

    with conn.transaction():  # one book = one atomic unit
        cur = conn.execute(
            """INSERT INTO books (gutenberg_id, title, author, langue,
                                  word_count, file_path)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (gutenberg_id) DO NOTHING
               RETURNING gutenberg_id""",
            (gid,
             header_field(header, "Title") or f"Book {gid}",
             header_field(header, "Author"),
             header_field(header, "Language"),
             len(tokens),
             str(path.relative_to(books_dir))))
        if cur.fetchone() is None:
            return "already loaded"
        with conn.cursor() as c, c.copy(
                "COPY inverted_index (term, book_id, occurrences) "
                "FROM STDIN") as copy:
            for term, n in counts.items():
                copy.write_row((term, gid, n))
    return f"ok ({len(tokens)} words, {len(counts)} distinct)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.environ.get("BOOKS_DIR", "/data/books"))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    books_dir = Path(args.dir)
    files = sorted(books_dir.rglob("*.txt"))[: args.limit]
    print(f"{len(files)} files found in {books_dir}")

    t0 = time.time()
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        for k, path in enumerate(files, 1):
            status = load_book(conn, path, books_dir)
            print(f"[{k}/{len(files)}] {path.name}: {status}")
        conn.execute("ANALYZE")  # refresh planner statistics
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()