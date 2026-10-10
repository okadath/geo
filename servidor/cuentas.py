"""Cuentas, sesiones y enlaces magicos sobre SQLite (cuentas.db, fuera de git).

Sin contrasenas: se entra con un enlace magico de un solo uso enviado por
correo (ver correo.py y rutas_cuentas). Tokens con secrets. Una conexion por
operacion (check_same_thread=False + WAL) para que el threadpool de FastAPI
pueda entrar en paralelo sin compartir cursores.

Tablas:
  usuarios(email UNICO, sal, hash, plan, expira, creado)
      sal/hash son restos del login con clave: se conservan pero son
      opcionales (NULL en los usuarios nuevos).
  sesiones(token UNICO, email, expira)
  enlaces(token UNICO, email, volver, creado, usado)
      usado = epoch del consumo o NULL; caducan a los ENLACE_MIN minutos.
  guardados(email, tipo, sello, x, y, query, creado)
      UNICO(email, tipo, sello, x, y). tipo in {mundo, battlemap}; para
      "mundo" x = y = -1 y query = ''.
  renders_dia(...)  la crea limites.py en esta misma BD.

Los tiempos (expira/creado/usado) se guardan como epoch en segundos (REAL). Un
plan con expira < ahora se trata como "free" al resolverlo (plan_vigente). Las
sesiones expiradas se borran de forma oportunista al consultarlas.

Esquema y migraciones: TODO pasa por `_migrar(con)`, que se ejecuta una vez por
proceso y es idempotente. Para anadir una tabla nueva basta con anadir su
CREATE TABLE IF NOT EXISTS a `_TABLAS`; para anadir una columna a una tabla
existente, una linea `_columna(con, tabla, columna, decl)` en `_migrar`.

Contrato PUBLICO (lo importa la fase de pagos, NO cambiar sus firmas):
  cambiar_plan(email, plan, dias=365), obtener_usuario(email),
  asegurar_usuario(email)
"""
import re
import sqlite3
import time
import secrets

from .config import DB_CUENTAS
from .planes import PLANES

DB = DB_CUENTAS    # TECTO_DB o BASE/cuentas.db (ver config)

# validacion de entrada: email razonable
RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_MAX = 254

# duracion por defecto de una sesion (30 dias, igual que la cookie)
SESION_DIAS = 30

# enlaces magicos: caducidad, tope por correo y hora, destino por defecto
ENLACE_MIN = 15
ENLACES_HORA = 5
VOLVER_DEFECTO = "/yo"
VOLVER_MAX = 512

# guardados: tipos validos y tope de la query de un battlemap
TIPOS_GUARDADO = ("mundo", "battlemap")
QUERY_MAX = 200

# esquema de usuarios SIN NOT NULL en sal/hash (BDs nuevas y migradas)
_USUARIOS = """CREATE TABLE IF NOT EXISTS {nombre}(
    email  TEXT PRIMARY KEY,
    sal    TEXT,
    hash   TEXT,
    plan   TEXT NOT NULL DEFAULT 'free',
    expira REAL,
    creado REAL NOT NULL)"""

# resto de tablas: anadir aqui las nuevas (CREATE ... IF NOT EXISTS)
_TABLAS = [
    """CREATE TABLE IF NOT EXISTS sesiones(
        token  TEXT PRIMARY KEY,
        email  TEXT NOT NULL,
        expira REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS enlaces(
        token  TEXT PRIMARY KEY,
        email  TEXT NOT NULL,
        volver TEXT NOT NULL,
        creado REAL NOT NULL,
        usado  REAL)""",
    "CREATE INDEX IF NOT EXISTS enlaces_email ON enlaces(email, creado)",
    """CREATE TABLE IF NOT EXISTS guardados(
        email  TEXT NOT NULL,
        tipo   TEXT NOT NULL,
        sello  TEXT NOT NULL,
        x      INTEGER NOT NULL DEFAULT -1,
        y      INTEGER NOT NULL DEFAULT -1,
        query  TEXT NOT NULL DEFAULT '',
        creado REAL NOT NULL,
        UNIQUE(email, tipo, sello, x, y))""",
]

_init_hecho = False


def _ahora():
    """Reloj de los enlaces (las pruebas lo parchean para simular caducidad)."""
    return time.time()


def _existe_tabla(con, nombre):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (nombre,)).fetchone() is not None


def _columna(con, tabla, columna, decl):
    """ALTER TABLE ... ADD COLUMN tolerante: no hace nada si ya existe."""
    cols = {f["name"] for f in con.execute("PRAGMA table_info(%s)" % tabla)}
    if columna not in cols:
        con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tabla, columna, decl))


def _migrar_usuarios(con):
    """sal/hash pasan a opcionales. SQLite no quita NOT NULL con ALTER, asi
    que si la tabla vieja los tiene se recrea copiando filas (usuarios_v2 ->
    rename) en una sola transaccion. Idempotente."""
    # resto de una migracion interrumpida a medias (sin usuarios, con v2)
    if _existe_tabla(con, "usuarios_v2") and not _existe_tabla(con, "usuarios"):
        con.execute("ALTER TABLE usuarios_v2 RENAME TO usuarios")
    con.execute(_USUARIOS.format(nombre="usuarios"))
    info = {f["name"]: f for f in con.execute("PRAGMA table_info(usuarios)")}
    if not (info["sal"]["notnull"] or info["hash"]["notnull"]):
        return
    con.commit()
    con.executescript(
        "BEGIN;"
        "DROP TABLE IF EXISTS usuarios_v2;"
        + _USUARIOS.format(nombre="usuarios_v2") + ";"
        "INSERT INTO usuarios_v2(email, sal, hash, plan, expira, creado)"
        " SELECT email, sal, hash, plan, expira, creado FROM usuarios;"
        "DROP TABLE usuarios;"
        "ALTER TABLE usuarios_v2 RENAME TO usuarios;"
        "COMMIT;")


def _migrar(con):
    """Crea/actualiza el esquema completo. Idempotente; _con() lo llama una
    vez por proceso. Tablas nuevas -> _TABLAS; columnas nuevas -> _columna."""
    _migrar_usuarios(con)
    for sql in _TABLAS:
        con.execute(sql)
    # columnas anadidas despues de crear una tabla, p. ej.:
    #   _columna(con, "usuarios", "nombre", "TEXT")
    con.commit()


def _con():
    """Conexion nueva a cuentas.db (una por operacion). La primera vez activa
    WAL y aplica el esquema/migraciones."""
    global _init_hecho
    con = sqlite3.connect(str(DB), check_same_thread=False, timeout=10)
    con.row_factory = sqlite3.Row
    if not _init_hecho:
        con.execute("PRAGMA journal_mode=WAL")
        _migrar(con)
        _init_hecho = True
    return con


def normalizar_email(email):
    """Email en minusculas y sin espacios si tiene forma valida; si no, None."""
    email = str(email or "").strip().lower()
    if len(email) > EMAIL_MAX or not RE_EMAIL.match(email):
        return None
    return email


def volver_seguro(volver):
    """Ruta relativa segura a la que redirigir tras el enlace: empieza por "/"
    pero no por "//", sin "\\", sin esquema, sin espacios ni caracteres de
    control. Cualquier otra cosa -> VOLVER_DEFECTO ("/yo")."""
    v = volver if isinstance(volver, str) else ""
    if (not v.startswith("/") or v.startswith("//") or "\\" in v
            or len(v) > VOLVER_MAX
            or any(ord(c) <= 0x20 or ord(c) == 0x7f for c in v)):
        return VOLVER_DEFECTO
    # sin esquema: ningun ":" en la ruta (antes de ? o #)
    if ":" in v.split("?", 1)[0].split("#", 1)[0]:
        return VOLVER_DEFECTO
    return v


def asegurar_usuario(email):
    """Crea el usuario (plan free, sin clave) si no existe. Devuelve su fila
    como dict, o None si el email no es valido. CONTRATO PUBLICO (webhook de
    pagos y enlace magico)."""
    email = normalizar_email(email)
    if not email:
        return None
    con = _con()
    try:
        con.execute(
            "INSERT OR IGNORE INTO usuarios(email, sal, hash, plan, expira,"
            " creado) VALUES(?, NULL, NULL, 'free', NULL, ?)",
            (email, time.time()))
        con.commit()
    finally:
        con.close()
    return obtener_usuario(email)


def enlaces_ultima_hora(email):
    """Enlaces pedidos para este email en los ultimos 60 minutos."""
    email = (email or "").strip().lower()
    con = _con()
    try:
        fila = con.execute(
            "SELECT COUNT(*) AS n FROM enlaces WHERE email=? AND creado>=?",
            (email, _ahora() - 3600)).fetchone()
    finally:
        con.close()
    return int(fila["n"])


def crear_enlace(email, volver=None):
    """Genera y persiste un token de enlace magico (32 bytes en hex) para el
    email; `volver` se sanea con volver_seguro. Devuelve el token. De paso
    purga los enlaces de mas de un dia (ya no cuentan ni para el limite)."""
    email = (email or "").strip().lower()
    token = secrets.token_hex(32)
    ahora = _ahora()
    con = _con()
    try:
        con.execute("DELETE FROM enlaces WHERE creado < ?", (ahora - 86400,))
        con.execute(
            "INSERT INTO enlaces(token, email, volver, creado, usado)"
            " VALUES(?, ?, ?, ?, NULL)",
            (token, email, volver_seguro(volver), ahora))
        con.commit()
    finally:
        con.close()
    return token


def consumir_enlace(token):
    """Marca usado un enlace vigente (sin usar y de menos de ENLACE_MIN
    minutos) y devuelve {"email", "volver"}; None si no existe, ya se uso o
    caduco. El UPDATE condicional garantiza un solo uso aun con carreras."""
    if not token or not isinstance(token, str):
        return None
    ahora = _ahora()
    con = _con()
    try:
        cur = con.execute(
            "UPDATE enlaces SET usado=? WHERE token=? AND usado IS NULL"
            " AND creado>=?", (ahora, token, ahora - ENLACE_MIN * 60))
        con.commit()
        if cur.rowcount != 1:
            return None
        fila = con.execute("SELECT email, volver FROM enlaces WHERE token=?",
                           (token,)).fetchone()
    finally:
        con.close()
    return {"email": fila["email"], "volver": volver_seguro(fila["volver"])}


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


# ---------------------------------------------------------------------------
#  Guardados (mundos y battlemaps). Las rutas validan tipo/sello/x/y antes de
#  llamar; aqui solo se normaliza lo propio del esquema (mundo -> x=y=-1).
# ---------------------------------------------------------------------------
def sanear_query(query):
    """Query de un battlemap (p. ej. "tema=bosque&px=1024"): texto sin
    caracteres de control, sin "?" inicial y de QUERY_MAX caracteres como
    mucho. Cualquier no-texto -> ''."""
    if not isinstance(query, str):
        return ""
    q = "".join(c for c in query if ord(c) > 0x1f and ord(c) != 0x7f)
    return q.strip().lstrip("?")[:QUERY_MAX]


def _clave_guardado(tipo, x, y, query):
    if tipo == "mundo":
        return -1, -1, ""
    return int(x), int(y), sanear_query(query)


def _fila_guardado(f):
    """Fila de la BD -> dict publico (x/y/query a None en los mundos)."""
    mundo = f["tipo"] == "mundo"
    return {"tipo": f["tipo"], "sello": f["sello"],
            "x": None if mundo else f["x"], "y": None if mundo else f["y"],
            "query": None if mundo else f["query"], "creado": f["creado"]}


def listar_guardados(email):
    """Guardados del usuario, del mas reciente al mas antiguo."""
    con = _con()
    try:
        filas = con.execute(
            "SELECT tipo, sello, x, y, query, creado FROM guardados"
            " WHERE email=? ORDER BY creado DESC, rowid DESC",
            (email,)).fetchall()
    finally:
        con.close()
    return [_fila_guardado(f) for f in filas]


def contar_guardados(email):
    con = _con()
    try:
        fila = con.execute("SELECT COUNT(*) AS n FROM guardados WHERE email=?",
                           (email,)).fetchone()
    finally:
        con.close()
    return int(fila["n"])


def anadir_guardado(email, tipo, sello, x=None, y=None, query=""):
    """Anade un guardado; idempotente por (email, tipo, sello, x, y). Si ya
    existia se actualiza su query (battlemap) y se conserva su fecha.
    Devuelve (guardado_dict, nuevo_bool)."""
    x, y, query = _clave_guardado(tipo, x, y, query)
    con = _con()
    try:
        cur = con.execute(
            "INSERT OR IGNORE INTO guardados(email, tipo, sello, x, y, query,"
            " creado) VALUES(?,?,?,?,?,?,?)",
            (email, tipo, sello, x, y, query, time.time()))
        nuevo = cur.rowcount == 1
        if not nuevo:
            con.execute(
                "UPDATE guardados SET query=? WHERE email=? AND tipo=?"
                " AND sello=? AND x=? AND y=?",
                (query, email, tipo, sello, x, y))
        con.commit()
        fila = con.execute(
            "SELECT tipo, sello, x, y, query, creado FROM guardados"
            " WHERE email=? AND tipo=? AND sello=? AND x=? AND y=?",
            (email, tipo, sello, x, y)).fetchone()
    finally:
        con.close()
    return _fila_guardado(fila), nuevo


def quitar_guardado(email, tipo, sello, x=None, y=None):
    """Quita un guardado. Devuelve True si existia."""
    x, y, _ = _clave_guardado(tipo, x, y, "")
    con = _con()
    try:
        cur = con.execute(
            "DELETE FROM guardados WHERE email=? AND tipo=? AND sello=?"
            " AND x=? AND y=?", (email, tipo, sello, x, y))
        con.commit()
    finally:
        con.close()
    return cur.rowcount > 0


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
#  CLI: python3 -m servidor.cuentas listar | alta <email>
#                                   | plan <email> <plan> [--dias N]
#  (sin claves: los usuarios entran con enlace magico)
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

    if argv[0] == "alta":
        # alta sin clave (idempotente): entrara con enlace magico
        if len(argv) < 2:
            print("uso: alta <email>")
            return 2
        usr = asegurar_usuario(argv[1])
        if not usr:
            print("email invalido: %s" % argv[1])
            return 1
        print("usuario %s (plan %s)" % (usr["email"], usr["plan"]))
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
        if plan in PLANES:
            asegurar_usuario(email)    # se crea sin clave si no existe
        ok, motivo = cambiar_plan(email, plan, dias)
        print(motivo if not ok else
              "plan de %s -> %s (vence en %d dias)" % (email, plan, dias)
              if plan != "free" else "plan de %s -> free" % email)
        return 0 if ok else 1

    print("uso: python3 -m servidor.cuentas"
          " [listar | alta <email> | plan <email> <plan> [--dias N]]")
    return 2


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
