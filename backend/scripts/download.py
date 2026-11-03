#!/usr/bin/env python3
import pathlib
import sys, time
import urllib.request
import json 
import re # regex juste pour clean_book()

HERE = pathlib.Path(__file__).resolve().parent
BOOKS_DIR = HERE.parent.parent / "data" / "books"
DATA_FILE = BOOKS_DIR / "catalogue.json"

PAUSE_SECONDS = 3  # be polite with gutenberg.org: one file at a time, with a pause

def read_books(fichier: pathlib.Path = DATA_FILE) -> dict:
    # dictionary gutenberg_id : url
    dico = {}
    with open(fichier) as f:
        contenu = json.load(f)

    for book in contenu:
        dico.update({book["gutenberg_id"]: book["url"]})

    return dico

# def normalize(data: bytes) -> bytes:
#     """Drop the UTF-8 BOM and turn CRLF/CR line endings into LF."""
#     if data.startswith(b"\xef\xbb\xbf"):
#         data = data[3:]
#     data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
#     return data if data.endswith(b"\n") else data + b"\n"

def clean_book(text: str) -> str:
    """
    Remove the Project Gutenberg header and footer from a book's text
    """
    start = re.search(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", text)
    end = re.search(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG", text)
    if start and end:
        return text[start.end():end.start()]
    return text

def download(id, url):
    target = BOOKS_DIR / f"pg{id}.txt"
    if target.exists():
        print(f"  déjà téléchargé: {target.name} ({target.stat().st_size / 1e6:.2f} MB)")
        return target
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())
        # TODO decider telechargement avec ou sans nettoyage d'entete & pied de page de Gutenberg
        # target.write_bytes(clean_book(response.read().decode('utf-8')).encode('utf-8'))
    print(f"  téléchargé: {target.name} ({target.stat().st_size / 1e6:.2f} MB)")
    time.sleep(PAUSE_SECONDS)
    return target

def main():
    BOOKS_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    dico = read_books()
    for book_id in dico.keys():
        try:
            total += download(book_id, dico.get(book_id) ).stat().st_size
        except Exception as error:  # one missing book is not fatal
            print(f"  FAILED pg{book_id}: {error}", file=sys.stderr)
    print(f"livres téléchargés dans data/books/ ({total / 1e6:.1f} MB in total)")

if __name__ == "__main__":
    main()
