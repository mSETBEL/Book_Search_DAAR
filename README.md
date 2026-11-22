# Book_Search_DAAR 
> rapport : https://www.overleaf.com/project/6adbb2fed75dded5e5cea2a1/share#1135ca6eb90859bd6edad5feb742bd1c998719aae1a2b5d9 

## Dépendances
- Python 3 avec fastapi, uvicorn 
- Docker

## Commandes pour construire l'application (depuis zéro):
```bash
python3 -m venv venv
source venv/bin/activate 
pip install -r requirements.txt
python scripts/hf_download.py --objectif <nbre de livres> # script de téléchargement des livres en local
docker compose up --build -d
docker compose run --rm backend python scripts/load_books.py
docker compose run --rm backend python -m scripts.build_graph
docker compose run --rm backend python -m scripts.compute_pagerank
```

## Pour se connecter à l'appli web depuis d'autres appareils
Les appareils doivent être connectés sur le même WIFI,
 le plus simple est qu'ils soient tous sur le même partage de connexion 

### Lancer le serveur depuis la machine principale
(peut-être qu'il faudrait en faire un script pour simplifier le lancement du serveur? le soucis c'est que ça *dépend du mot de passe dans le .env* donc jsp trop)

```bash
docker compose up --build -d
cd backend/
STATIC_DIR=../frontend/static \
DATABASE_URL=postgresql://daar:<MOT_DE_PASSE>@localhost:5432/daar \
BOOKS_DIR=../database/books \
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

On devrait voir affiché `INFO:  Application startup complete.` : le serveur est bien lancé. 

### Connexion de l'appareil (téléphone, tablette..)
dans un navigateur: `http://<@IP de la machine sur laquelle le serveur tourne>`
> j'ai pas testé sur un ordi mais ça devrait fonctionner aussi 

#### Trouver l’adresse IP de l’ordinateur serveur
- macOS : `ipconfig getifaddr en0`
- Windows : `ipconfig` 
- Linux : `hostname -I`

## Commandes utiles

Pour lancer une requête sur la base de données:
```bash
docker compose exec db psql -U daar -d daar -c <requête SQL>
```
Pour voir toutes les tables de la base de données:
```bash
docker compose exec db psql -U daar -d daar -c "\dt;"
```

Pour arrêter les conteneurs sans supprimer les données de la base : 
```bash
docker compose down
```


## Partie authentification 
Pour créer un utilisateur : 
docker compose run --rm backend python -m scripts.create_user alice

## TO DO LIST 
- partie algos (backend) :
  - implementer recherche simple : lookup dans l’index
  - implémenter recherche avancée : appliquer la RegEx sur le vocabulaire de l’index (rapide), bonus: sur le texte complet (lent, à mesurer tests de perf) 
  - implementer graphe de Jaccard : distance entre ensembles de mots des livres, avec arête si la distance est sous un seuil (seuil à définir)
  - Centralité : PageRank est le plus simple et supporte bien un graphe non connexe. Closeness pose problème sur un graphe non connexe. Betweenness (algorithme de Brandes, O(VE)) est plus coûteux. Le plus sûr est d’implémenter PageRank, et une deuxième mesure si le temps le permet, pour pouvoir comparer dans le rapport.
  - Classement : combiner occurrences et centralité, et documenter la formule.
  - Suggestion : voisins dans le graphe de Jaccard des 2-3 meilleurs résultats

- partie data:
  - Récupérer au moins livres de min 10 000 mots (commencer par 10)
  - Nettoyer les en-têtes et pieds de page Gutenberg, puis tokeniser (minuscules, ponctuation, mots vides)
  - Construire l’index inversé : mot → {livre : nombre d’occurrences}.

- partie client/serveur (frontend):
  - API REST branchée sur l’index et le graphe précalculés
 
- tests de perf:
  - temps de réponse en fonction de la taille de la bibliothèque (200, 500, 1000, 1664 livres), recherche simple contre RegEx sur l’index et sur le texte complet, temps de construction du graphe.
  - Pertinence : subjectif, tester si on aime les résultats
  - Exemples de centralité sur un échantillon de livres


