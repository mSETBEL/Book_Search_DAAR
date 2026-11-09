import json, time, requests

url = "https://gutendex.com/books/?languages=en&mime_type=text/plain"
catalogue = []
# TODO plus tard, augmenter le nbre de livres
# while url and len(catalogue) < 2000:
while url and len(catalogue) < 20:
    page = requests.get(url, timeout=45).json()
    for b in page["results"]:
        txt = next((u for m, u in b["formats"].items() if m.startswith("text/plain")), None)
        if txt:
            catalogue.append({
                "gutenberg_id": b["id"],
                "title": b["title"],
                "author": b["authors"][0]["name"] if b["authors"] else None,
                "langue": "en",
                "url": txt,
            })
    url = page["next"]
    time.sleep(2)  # pour ne pas surcharger le serveur

json.dump(catalogue, open("database/books/catalogue.json", "w"), indent=1)
