"""Crée un compte depuis la ligne de commande (utile si ALLOW_REGISTRATION=false).

    docker compose run --rm backend python -m scripts.create_user alice
    (le mot de passe est demandé de façon masquée)
"""
import argparse
import getpass
import sys

import psycopg

from app import auth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    ap.add_argument("--password", help="déconseillé : visible dans l'historique du shell")
    args = ap.parse_args()
    password = args.password or getpass.getpass("Mot de passe : ")
    problem = auth.validate_credentials(args.username, password)
    if problem:
        sys.exit(problem)
    auth.init_schema()
    try:
        with auth._conn() as conn:
            conn.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                         (args.username, auth.hash_password(password)))
    except psycopg.errors.UniqueViolation:
        sys.exit("Ce nom d'utilisateur existe déjà.")
    print(f"Compte « {args.username} » créé.")


if __name__ == "__main__":
    main()
