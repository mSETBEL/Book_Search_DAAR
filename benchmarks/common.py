"""Utilitaires partagés par tous les scripts de benchmark.

AUCUN fichier du projet n'est modifié : les scripts importent le code du
backend (backend/app, backend/scripts) tel quel et le font tourner sur une
base de données PostgreSQL SÉPARÉE (daar_bench), jamais sur la vraie base.
"""
import json
import os
import platform
import statistics as st
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse


HERE = Path(__file__).resolve().parent
REPO = HERE.parent                      # racine du dépôt (contient backend/, database/)
BACKEND = REPO / "backend"
SCHEMA_SQL = REPO / "database" / "schema.sql"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

# URL « administrateur » du PostgreSQL de benchmark (conteneur dédié, cf. README)
DEFAULT_ADMIN_URL = os.environ.get(
    "BENCH_ADMIN_URL", "postgresql://postgres:bench@localhost:55432/postgres")
BENCH_DB = "daar_bench"

SIZES = [200, 500, 1000, 1664]
SEED = 42


# --------------------------------------------------------------------------
def db_url(admin_url: str, dbname: str = BENCH_DB) -> str:
    u = urlparse(admin_url)
    return urlunparse(u._replace(path="/" + dbname))


def recreate_database(admin_url: str, dbname: str = BENCH_DB, fresh: bool = True):
    """Crée (ou recrée) la base de benchmark et applique database/schema.sql."""
    import psycopg
    with psycopg.connect(admin_url, autocommit=True) as c:
        exists = c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,)).fetchone()
        if exists and fresh:
            c.execute(f'DROP DATABASE "{dbname}" WITH (FORCE)')
            exists = None
        if not exists:
            c.execute(f'CREATE DATABASE "{dbname}"')
            created = True
        else:
            created = False
    if created:
        with psycopg.connect(db_url(admin_url, dbname), autocommit=True) as c:
            c.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    return db_url(admin_url, dbname)


# --------------------------------------------------------------------------
def summarize(xs):
    """moyenne, écart type, min, médiane, p95, max (en unités d'entrée)."""
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return {}
    p95 = xs[min(n - 1, int(round(0.95 * (n - 1))))]
    return {"n": n, "mean": st.fmean(xs), "std": st.stdev(xs) if n > 1 else 0.0,
            "min": xs[0], "median": st.median(xs), "p95": p95, "max": xs[-1]}


def machine_info() -> dict:
    info = {"platform": platform.platform(), "python": sys.version.split()[0],
            "machine": platform.machine(), "cpu_count": os.cpu_count()}
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    try:  # nom du CPU (Linux)
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                info["cpu"] = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass
    if platform.system() == "Darwin":
        try:
            info["cpu"] = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        except Exception:
            pass
    return info


def save_json(name: str, obj):
    (RESULTS / name).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(name: str, default=None):
    p = RESULTS / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


# --------------------------------------------------------------------------
class ApiServer:
    """Lance l'API FastAPI du projet (uvicorn, 1 worker, comme le Dockerfile)
    sur une base donnée, et l'arrête proprement."""

    def __init__(self, database_url: str, books_dir: Path, port: int = 8765):
        self.port = port
        self.env = dict(os.environ, DATABASE_URL=database_url, BOOKS_DIR=str(books_dir),
                        PYTHONUNBUFFERED="1")
        self.env.pop("STATIC_DIR", None)
        self.proc = None
        self.base = f"http://127.0.0.1:{port}"

    def __enter__(self):
        import requests
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(self.port), "--log-level", "warning"],
            cwd=BACKEND, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(120):
            if self.proc.poll() is not None:
                raise RuntimeError("uvicorn s'est arrêté : " + self.proc.stderr.read().decode()[-2000:])
            try:
                if requests.get(self.base + "/api/health", timeout=1).ok:
                    return self
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("L'API ne répond pas")

    def __exit__(self, *a):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except Exception:
                self.proc.kill()
