"""
Récupère des livres du Projet Gutenberg depuis la copie publiée sur Hugging Face
(dataset manu/project_gutenberg), car le site gutenberg.org est indisponible.

Usage, depuis backend/ :
    pip install -r requirements.txt
    python -m scripts.hf_download --objectif 1700
"""

import argparse
import json
import re
from pathlib import Path

from datasets import load_dataset

if __package__:
    from .tokenizer import tokenize
else:
    from tokenizer import tokenize

DEBUT = re.compile(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG", re.IGNORECASE)
FIN = re.compile(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG", re.IGNORECASE)
CHECKPOINT_INTERVAL = 100


def champ_entete(texte, nom):
    """Valeur d'une ligne d'en-tête Gutenberg, par exemple 'Title: Moby Dick'."""
    m = re.search(rf"^{nom}:\s*(.+)$", texte[:5000], re.MULTILINE)
    return m.group(1).strip() if m else None


def nombre_de_mots(texte):
    """Tokens retenus par le tokenizer entre les marqueurs Gutenberg."""
    d, f = DEBUT.search(texte), FIN.search(texte)
    if not (d and f):
        return 0  # format ancien sans marqueurs : écarté, le nettoyage ne saurait pas le traiter
    return len(tokenize(texte[d.end():f.start()]))


def sauvegarder_catalogue(fichier, catalogue):
    temporaire = fichier.with_name(f".{fichier.name}.tmp")
    temporaire.write_text(json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8")
    temporaire.replace(fichier)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--objectif", type=int, default=1700, help="nombre de livres à garder")
    default_output = Path(__file__).resolve().parents[2] / "database" / "books"
    p.add_argument("--sortie", default=str(default_output), help="dossier database/books")
    args = p.parse_args()
    if args.objectif <= 0:
        p.error("--objectif doit être strictement positif")

    sortie = Path(args.sortie)
    (sortie).mkdir(parents=True, exist_ok=True)

    # Catalogue existant : on le garde et on le complète, sans doublon.
    # --objectif est le nombre TOTAL de livres visé, livres déjà présents compris.
    fichier_catalogue = sortie / "catalogue.json"
    catalogue = []
    if fichier_catalogue.exists():
        catalogue = json.loads(fichier_catalogue.read_text(encoding="utf-8"))
        fichier_catalogue.with_suffix(".json.bak").write_text(
            fichier_catalogue.read_text(encoding="utf-8"), encoding="utf-8")  # copie de secours
        print(f"Catalogue existant : {len(catalogue)} livres conservés (copie dans catalogue.json.bak)")

    if len(catalogue) >= args.objectif:
        print(f"Objectif déjà atteint : {len(catalogue)} livres dans {sortie}")
        return

    # streaming=True : les lignes sont lues au fur et à mesure, sans télécharger tout le jeu.
    ds = load_dataset("manu/project_gutenberg", split="en", streaming=True)
    vus = {int(livre["gutenberg_id"]) for livre in catalogue}
    lus = 0
    ajoutes_depuis_checkpoint = 0
    for ligne in ds:
        lus += 1
        # Les identifiants ont la forme "41496-8" (numéro Gutenberg + variante du fichier).
        gid = int(ligne["id"].split("-")[0])
        if gid in vus:
            continue  # le dataset contient des doublons

        texte = ligne["text"]
        if nombre_de_mots(texte) < 10_000:
            continue

        titre = champ_entete(texte, "Title")
        if not titre:
            continue  # sans titre, le livre serait inutilisable dans l'interface

        fichier_livre = sortie / f"{gid}.txt"
        temporaire = fichier_livre.with_name(f".{fichier_livre.name}.tmp")
        temporaire.write_text(texte, encoding="utf-8")
        temporaire.replace(fichier_livre)
        catalogue.append({
            "gutenberg_id": gid,
            "title": titre,
            "author": champ_entete(texte, "Author"),
            "langue": "en",
            "url": f"https://huggingface.co/datasets/manu/project_gutenberg (id {ligne['id']})",
        })
        vus.add(gid)
        ajoutes_depuis_checkpoint += 1
        if ajoutes_depuis_checkpoint >= CHECKPOINT_INTERVAL:
            sauvegarder_catalogue(fichier_catalogue, catalogue)
            print(f"{len(catalogue)} livres gardés sur {lus} lus")
            ajoutes_depuis_checkpoint = 0
        if len(catalogue) >= args.objectif:
            break

    sauvegarder_catalogue(fichier_catalogue, catalogue)
    print(f"Terminé : {len(catalogue)} livres gardés sur {lus} lus, dans {sortie}")


if __name__ == "__main__":
    main()
