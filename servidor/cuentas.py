"""Cuentas y sesiones sobre SQLite (cuentas.db, junto a salidas/, fuera de git).

Sin dependencias externas: hash de clave con hashlib.scrypt (stdlib) + sal por
usuario, tokens de sesion con secrets. Una conexion por operacion
(check_same_thread=False + WAL) para que el threadpool de FastAPI pueda entrar
en paralelo sin compartir cursores.

Tablas:
  usuarios(email UNICO, sal, hash, plan, expira, creado)
  sesiones(token UNICO, email, expira)

Los tiempos (expira/creado) se guardan como epoch en segundos (REAL). Un plan
con expira < ahora se trata como "free" al resolverlo (plan_vigente). Las
sesiones expiradas se borran de forma oportunista al consultarlas.

Contrato PUBLICO (lo importa la fase de pagos, NO cambiar sus firmas):
  cambiar_plan(email, plan, dias=365)  y  obtener_usuario(email)
"""
import re
import sqlite3
import time
import hashlib
import secrets
from pathlib import Path

from .config import BASE
from .planes import PLANES

DB = BASE / "cuentas.db"

# validacion de entrada: email razonable y clave de al menos 8 caracteres
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CLAVE_MIN = 8

# parametros de scrypt (cost razonable para login interactivo, stdlib)
_SCRYPT = dict(n=16384, r=8, p=1, dklen=32)

# duracion por defecto de una sesion (30 dias, igual que la cookie)
SESION_DIAS = 30

_init_hecho = False


def _con():
    """Conexion nueva a cuentas.db (una por operacion). La primera vez crea el
    esquema y activa WAL."""
    global _init_hecho
    con = sqlite3.connect(str(DB), check_same_thread=False, timeout=10)
    con.row_factory = sqlite3.Row
    if not _init_hecho:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("""CREATE TABLE IF NOT EXISTS usuarios(
            email  TEXT PRIMARY KEY,
            sal    TEXT NOT NULL,
            hash   TEXT NOT NULL,
            plan   TEXT NOT NULL DEFAULT 'free',
            expira REAL,
            creado REAL NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS sesiones(
            token  TEXT PRIMARY KEY,
            email  TEXT NOT NULL,
            expira REAL NOT NULL)""")
        con.commit()
        _init_hecho = True
    return con


def _hash(clave, sal):
    """scrypt de la clave con la sal (bytes) del usuario -> hex."""
    return hashlib.scrypt(clave.encode("utf-8"), salt=sal, **_SCRYPT).hex()


def registrar(email, clave):
    """Alta de un usuario nuevo en plan free. Devuelve (ok, motivo).

    Valida email y longitud de clave; rechaza duplicados."""
    email = (email or "").strip().lower()
    clave = clave or ""
    if not RE_EMAIL.match(email):
        return False, "email invalido"
    if len(clave) < CLAVE_MIN:
        return False, "la clave debe tener al menos %d caracteres" % CLAVE_MIN
    sal = secrets.token_bytes(16)
    con = _con()
    try:
        con.execute(
            "INSERT INTO usuarios(email, sal, hash, plan, expira, creado)"
            " VALUES(?,?,?,?,?,?)",
            (email, sal.hex(), _hash(clave, sal), "free", None, time.time()))
        con.commit()
    except sqlite3.IntegrityError:
        return False, "ese email ya esta registrado"
    finally:
        con.close()
    return True, "ok"


def verificar(email, clave):
    """Comprueba credenciales. Devuelve el email (normalizado) si son validas,
    o None. Comparacion de hash en tiempo constante."""
    email = (email or "").strip().lower()
    con = _con()
    try:
        fila = con.execute(
            "SELECT sal, hash FROM usuarios WHERE email=?", (email,)).fetchone()
    finally:
        con.close()
    if not fila:
        return None
    calc = _hash(clave or "", bytes.fromhex(fila["sal"]))
    if secrets.compare_digest(calc, fila["hash"]):
        return email
    return None


def crear_sesion(email, dias=SESION_DIAS):
    """Crea un token de sesion para el email y lo persiste. Devuelve el token."""
    token = secrets.token_urlsafe(32)
    expira = time.time() + dias * 86400
    con = _con()
    try:
        con.execute("INSERT INTO sesiones(token, email, expira) VALUES(?,?,?)",
                    (token, email, expira))
        con.commit()
    finally:
        con.close()
    return token


def usuario_de_token(token):
    """Usuario dueno de una sesion vigente, o None si el token no existe o
    expiro. Borra oportunisticamente las sesiones caducadas."""
    if not token:
        return None
    ahora = time.time()
    con = _con()
    try:
        con.execute("DELETE FROM sesiones WHERE expira < ?", (ahora,))
        fila = con.execute(
            "SELECT email FROM sesiones WHERE token=? AND expira >= ?",
            (token, ahora)).fetchone()
        con.commit()
        if not fila:
            return None
        usr = con.execute(
            "SELECT email, plan, expira, creado FROM usuarios WHERE email=?",
            (fila["email"],)).fetchone()
    finally:
        con.close()
    return dict(usr) if usr else None


def cerrar_sesion(token):
    """Invalida una sesion (logout). Silencioso si no existe."""
    if not token:
        return
    con = _con()
    try:
        con.execute("DELETE FROM sesiones WHERE token=?", (token,))
        con.commit()
    finally:
        con.close()


def obtener_usuario(email):
    """Fila del usuario como dict (email, plan, expira, creado) o None.
    CONTRATO PUBLICO (lo usa la fase de pagos)."""
    email = (email or "").strip().lower()
    con = _con()
    try:
        fila = con.execute(
            "SELECT email, plan, expira, creado FROM usuarios WHERE email=?",
            (email,)).fetchone()
    finally:
        con.close()
    return dict(fila) if fila else None


def cambiar_plan(email, plan, dias=365):
    """Asigna un plan al usuario con vencimiento a `dias` desde ahora (free no
    vence: expira=NULL). Devuelve (ok, motivo). CONTRATO PUBLICO (fase de
    pagos)."""
    email = (email or "").strip().lower()
    if plan not in PLANES:
        return False, "plan desconocido: %s" % plan
    expira = None if plan == "free" else time.time() + dias * 86400
    con = _con()
    try:
        cur = con.execute("UPDATE usuarios SET plan=?, expira=? WHERE email=?",
                          (plan, expira, email))
        con.commit()
    finally:
        con.close()
    if cur.rowcount == 0:
        return False, "no existe el usuario %s" % email
    return True, "ok"


def plan_vigente(usuario):
    """Plan efectivo de un usuario (dict de obtener_usuario/usuario_de_token) o
    None. Un plan de pago vencido cuenta como 'free'."""
    if not usuario:
        return "free"
    plan = usuario.get("plan") or "free"
    if plan not in PLANES:
        return "free"
    expira = usuario.get("expira")
    if plan != "free" and expira is not None and expira < time.time():
        return "free"
    return plan


# ---------------------------------------------------------------------------
#  CLI: python3 -m servidor.cuentas listar | plan <email> <plan> [--dias N]
# ---------------------------------------------------------------------------
def _fmt_fecha(epoch):
    if not epoch:
        return "-"
    return time.strftime("%Y-%m-%d", time.localtime(epoch))


def _cli(argv):
    if not argv or argv[0] == "listar":
        con = _con()
        try:
            filas = con.execute(
                "SELECT email, plan, expira, creado FROM usuarios"
                " ORDER BY creado").fetchall()
        finally:
            con.close()
        if not filas:
            print("(sin usuarios)")
            return 0
        print("%-32s %-10s %-12s %-12s %s" %
              ("email", "plan", "vigente", "expira", "creado"))
        for f in filas:
            print("%-32s %-10s %-12s %-12s %s" % (
                f["email"], f["plan"], plan_vigente(dict(f)),
                _fmt_fecha(f["expira"]), _fmt_fecha(f["creado"])))
        return 0

    if argv[0] == "plan":
        if len(argv) < 3:
            print("uso: plan <email> <free|pro|comercial> [--dias 365]")
            return 2
        email, plan = argv[1], argv[2]
        dias = 365
        if "--dias" in argv:
            try:
                dias = int(argv[argv.index("--dias") + 1])
            except (ValueError, IndexError):
                print("--dias requiere un numero")
                return 2
        ok, motivo = cambiar_plan(email, plan, dias)
        print(motivo if not ok else
              "plan de %s -> %s (vence en %d dias)" % (email, plan, dias)
              if plan != "free" else "plan de %s -> free" % email)
        return 0 if ok else 1

    print("uso: python3 -m servidor.cuentas [listar | plan <email> <plan> [--dias N]]")
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
