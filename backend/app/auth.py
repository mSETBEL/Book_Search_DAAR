"""Authentification : comptes utilisateurs, sessions par cookie, protection de l'API.

Principe
--------
* Les mots de passe ne sont JAMAIS stockés : seulement un hachage scrypt salé (bibliothèque standard,
  aucune dépendance supplémentaire).
* À la connexion, le serveur crée une session : un jeton aléatoire est envoyé au navigateur dans un
  cookie HttpOnly (illisible par JavaScript) ; seule l'empreinte SHA-256 du jeton est stockée en base.
* Un middleware refuse (401) toute route /api/* sans session valide, sauf la liste PUBLIC_PATHS.
* nginx utilise aussi /api/auth/check (auth_request) pour protéger les pages elles-mêmes.

Variables d'environnement (toutes facultatives) :
    SESSION_DAYS        durée d'une session en jours               (défaut 7)
    COOKIE_SECURE       true si le site est servi en HTTPS         (défaut false)
    ALLOW_REGISTRATION  false pour fermer les inscriptions         (défaut true)
    AUTH_DISABLED       true pour DÉSACTIVER l'authentification    (défaut false ; tests/benchmarks seulement)
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

DATABASE_URL = os.environ["DATABASE_URL"]


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "oui")


COOKIE_NAME = "daar_session"
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "7"))
COOKIE_SECURE = _flag("COOKIE_SECURE", "false")
ALLOW_REGISTRATION = _flag("ALLOW_REGISTRATION", "true")
AUTH_DISABLED = _flag("AUTH_DISABLED", "false")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
PASSWORD_MIN, PASSWORD_MAX = 8, 128

# Routes /api/* accessibles sans être connecté
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/register",
                "/api/auth/logout", "/api/auth/config"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    username       TEXT NOT NULL,
    password_hash  TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users (lower(username));

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,               -- SHA-256 du jeton (le jeton lui-même n'est jamais stocké)
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


# ============================================================
# Base de données
# ============================================================
def _conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)


def init_schema(retries: int = 10, delay: float = 2.0):
    """Crée les tables users/sessions si besoin (base déjà existante : pas besoin de la recréer)."""
    for attempt in range(retries):
        try:
            with _conn() as conn:
                conn.execute(SCHEMA)
            return
        except psycopg.OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


# ============================================================
# Mots de passe (scrypt)
# ============================================================
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salt).decode(),
                                          base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64),
                                n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except Exception:
        return False


# Hachage factice : sert à dépenser le même temps quand l'identifiant n'existe pas
# (évite de révéler par le temps de réponse quels comptes existent).
_DUMMY_HASH = hash_password("mot-de-passe-factice")


def validate_credentials(username: str, password: str):
    """Retourne un message d'erreur, ou None si tout est valide."""
    if not USERNAME_RE.match(username):
        return "Le nom d'utilisateur doit faire 3 à 32 caractères (lettres, chiffres, . _ -)."
    if not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        return f"Le mot de passe doit faire entre {PASSWORD_MIN} et {PASSWORD_MAX} caractères."
    return None


# ============================================================
# Sessions
# ============================================================
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM sessions WHERE expires_at < now()")   # nettoyage au passage
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) "
        "VALUES (%s, %s, now() + make_interval(days => %s::int))",
        (_token_hash(token), user_id, SESSION_DAYS))
    return token


def user_from_token(token):
    if not token:
        return None
    with _conn() as conn:
        return conn.execute(
            "SELECT u.id, u.username FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = %s AND s.expires_at > now()", (_token_hash(token),)).fetchone()


def _set_cookie(response, token: str):
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=COOKIE_SECURE, path="/")


def _error(code: str, message: str, status: int):
    return JSONResponse(status_code=status, content={"error": code, "message": message})


# ============================================================
# Limitation des tentatives (en mémoire, par processus)
# ============================================================
class RateLimiter:
    def __init__(self, max_events: int, window_s: int):
        self.max, self.window = max_events, window_s
        self.events = defaultdict(deque)

    def _purge(self, key):
        q, limit = self.events[key], time.monotonic() - self.window
        while q and q[0] < limit:
            q.popleft()
        return q

    def blocked(self, key) -> bool:
        return len(self._purge(key)) >= self.max

    def add(self, key):
        self._purge(key).append(time.monotonic())

    def reset(self, key):
        self.events.pop(key, None)


_login_failures = RateLimiter(max_events=5, window_s=300)     # 5 échecs / 5 min par (IP, identifiant)
_registrations = RateLimiter(max_events=10, window_s=3600)    # 10 inscriptions / heure par IP


def _client_ip(request: Request) -> str:
    # nginx place l'adresse du client dans X-Real-IP ; l'API n'est pas exposée directement.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "?")


# ============================================================
# Middleware : protège toutes les routes /api/*
# ============================================================
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if AUTH_DISABLED or not path.startswith("/api/") or path in PUBLIC_PATHS:
        return await call_next(request)
    user = await run_in_threadpool(user_from_token, request.cookies.get(COOKIE_NAME))
    if user is None:
        return _error("unauthorized", "Connexion requise.", 401)
    request.state.user = user
    return await call_next(request)


# ============================================================
# Routes /api/auth/*
# ============================================================
router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


@router.get("/config")
def auth_config():
    """Public : permet à la page de connexion de savoir si l'inscription est ouverte."""
    return {"registration_open": ALLOW_REGISTRATION}


@router.post("/register")
def register(body: Credentials, request: Request):
    if not ALLOW_REGISTRATION:
        return _error("registration_closed", "Les inscriptions sont fermées.", 403)
    ip = _client_ip(request)
    if _registrations.blocked(ip):
        return _error("too_many_requests", "Trop d'inscriptions depuis cette adresse, réessayez plus tard.", 429)
    username = body.username.strip()
    problem = validate_credentials(username, body.password)
    if problem:
        return _error("invalid_credentials", problem, 400)
    try:
        with _conn() as conn:
            row = conn.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
                               (username, hash_password(body.password))).fetchone()
            token = create_session(conn, row["id"])
    except psycopg.errors.UniqueViolation:
        return _error("username_taken", "Ce nom d'utilisateur est déjà pris.", 409)
    _registrations.add(ip)
    response = JSONResponse(status_code=201, content={"ok": True, "username": username})
    _set_cookie(response, token)
    return response


@router.post("/login")
def login(body: Credentials, request: Request):
    username = body.username.strip()
    key = (_client_ip(request), username.lower())
    if _login_failures.blocked(key):
        return _error("too_many_requests", "Trop de tentatives. Réessayez dans quelques minutes.", 429)
    with _conn() as conn:
        user = conn.execute("SELECT id, username, password_hash FROM users WHERE lower(username) = lower(%s)",
                            (username,)).fetchone()
        ok = verify_password(body.password, user["password_hash"] if user else _DUMMY_HASH)
        if not (user and ok):
            _login_failures.add(key)
            return _error("bad_credentials", "Identifiant ou mot de passe incorrect.", 401)
        token = create_session(conn, user["id"])
    _login_failures.reset(key)
    response = JSONResponse(content={"ok": True, "username": user["username"]})
    _set_cookie(response, token)
    return response


@router.post("/logout")
def logout(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with _conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/me")
def me(request: Request):
    """Protégé par le middleware : renvoie l'utilisateur connecté."""
    if AUTH_DISABLED:
        return {"username": "(authentification désactivée)"}
    return {"username": request.state.user["username"]}


@router.get("/check")
def check():
    """Utilisé par nginx (auth_request) : 200 si la session est valide, 401 sinon (via le middleware)."""
    return {"ok": True}
