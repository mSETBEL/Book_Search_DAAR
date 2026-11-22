# Book_Search_DAAR 
## Dépendances
- Python 3 avec fastapi, uvicorn 
- Docker

## Commandes pour construire l'application (depuis zéro):
```bash
python3 -m venv venv
source venv/bin/activate 
pip install -r backend/requirements.txt
python scripts/hf_download.py --objectif <nbre de livres> # script de téléchargement des livres en local
docker compose up --build -d
docker compose run --rm backend python scripts/load_books.py
docker compose run --rm backend python -m scripts.build_graph
docker compose run --rm backend python -m scripts.compute_pagerank
```

## Pour se connecter à l'application web depuis d'autres appareils
Les appareils doivent être connectés sur le même WIFI,
 le plus simple est qu'ils soient tous sur le même partage de connexion 

### Lancer le serveur depuis la machine principale
```bash
docker compose up --build -d
cd backend/
STATIC_DIR=../frontend/static \
DATABASE_URL=postgresql://daar:<MOT_DE_PASSE>@localhost:5432/daar \
BOOKS_DIR=../database/books \
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

On devrait voir affiché `INFO:  Application startup complete.` : le serveur est bien lancé. 

### Connexion de l'appareil (téléphone, tablette ou ordinateur)
Dans un navigateur: `http://<@IP de la machine serveur>`

#### Pour trouver l’adresse IP de la machine serveur
- macOS : `ipconfig getifaddr en0`
- Windows : `ipconfig` 
- Linux : `hostname -I`

## Partie authentification 
Pour créer un utilisateur : 
```bash
docker compose run --rm backend python -m scripts.create_user alice
```

## Partie tests de performances 
Si ce n'est pas déjà fait
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt -r benchmarks/requirements-bench.txt
```
PostgreSQL dédié aux mesures, même version et mêmes réglages par défaut que docker-compose.yml.
Port 55432 pour ne pas gêner la vraie base.
```bash
docker run -d --name daar-bench-pg -e POSTGRES_PASSWORD=bench -p 55432:5432 postgres:16-alpine
```
Lancer tous les tests
```bash
bash benchmarks/run_all.sh
```
