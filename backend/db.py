"""Pools, encryption and schema introspection.

Two kinds of connection live here and they are deliberately different:

  * the *metadata* pool holds definitions and is read/write;
  * a *reporting* pool is created per data_connection, is opened with a
    read-only account, and every query it runs is wrapped in a read-only
    transaction with a statement timeout and a row cap.

Introspection matters more than it looks. Report definitions arrive from a
browser, so every table and column name in them is untrusted input. No
database lets you bind an identifier as a parameter, so the only safe move is
to check each one against the catalogue this module reads from
INFORMATION_SCHEMA. Anything not in that catalogue never reaches a query.
"""

import os
import threading
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling
from cryptography.fernet import Fernet, InvalidToken

# --------------------------------------------------------------------------
# encryption
# --------------------------------------------------------------------------
_key = os.environ.get("DESIGNER_KEY", "")
if not _key:
    raise RuntimeError(
        "DESIGNER_KEY is not set. Generate one with:\n"
        "  python -c \"from cryptography.fernet import Fernet;"
        "print(Fernet.generate_key().decode())\"\n"
        "Back it up outside the database — lose it and every stored "
        "connection password becomes unreadable."
    )
_fernet = Fernet(_key.encode() if isinstance(_key, str) else _key)


def encrypt(text: str) -> bytes:
    return _fernet.encrypt((text or "").encode("utf-8"))


def decrypt(blob) -> str:
    if not blob:
        return ""
    try:
        return _fernet.decrypt(bytes(blob)).decode("utf-8")
    except InvalidToken:
        raise RuntimeError(
            "A stored password could not be decrypted. DESIGNER_KEY has "
            "changed since it was written."
        )


def clean(row):
    """Drop every bytes column before a row is serialised.

    Ciphertext must never leave the process, and it is far too easy to add an
    endpoint that returns `SELECT *`. Filtering centrally means no endpoint
    can leak it by accident.
    """
    if row is None:
        return None
    if isinstance(row, list):
        return [clean(r) for r in row]
    return {k: v for k, v in row.items() if not isinstance(v, (bytes, bytearray))}


# --------------------------------------------------------------------------
# metadata pool
# --------------------------------------------------------------------------
_meta_pool = None
_meta_lock = threading.Lock()


def meta_pool():
    global _meta_pool
    if _meta_pool is None:
        with _meta_lock:
            if _meta_pool is None:
                _meta_pool = pooling.MySQLConnectionPool(
                    pool_name="nexd_meta",
                    pool_size=int(os.environ.get("META_POOL_SIZE", 5)),
                    host=os.environ.get("META_DB_HOST", "localhost"),
                    port=int(os.environ.get("META_DB_PORT", 3306)),
                    user=os.environ.get("META_DB_USER", "nexd_designer"),
                    password=os.environ.get("META_DB_PASSWORD", ""),
                    database=os.environ.get("META_DB_NAME", "nexd_designer"),
                    autocommit=False,
                    charset="utf8mb4",
                )
    return _meta_pool


@contextmanager
def meta(dict_rows=True):
    conn = meta_pool().get_connection()
    cur = conn.cursor(dictionary=dict_rows)
    try:
        yield cur, conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def q1(sql, args=()):
    with meta() as (cur, _):
        cur.execute(sql, args)
        return cur.fetchone()


def qall(sql, args=()):
    with meta() as (cur, _):
        cur.execute(sql, args)
        return cur.fetchall()


def execute(sql, args=()):
    with meta() as (cur, conn):
        cur.execute(sql, args)
        return cur.lastrowid


# --------------------------------------------------------------------------
# reporting pools, one per data_connection
# --------------------------------------------------------------------------
_report_pools = {}
_report_lock = threading.Lock()

QUERY_TIMEOUT_MS = int(os.environ.get("QUERY_TIMEOUT_MS", 15000))
MAX_ROWS = int(os.environ.get("MAX_ROWS", 5000))


def _pool_for(conn_row):
    cid = conn_row["id"]
    with _report_lock:
        if cid not in _report_pools:
            _report_pools[cid] = pooling.MySQLConnectionPool(
                pool_name=f"nexd_rpt_{cid}",
                pool_size=int(os.environ.get("REPORT_POOL_SIZE", 4)),
                host=conn_row["host"],
                port=int(conn_row["port"] or 3306),
                user=conn_row["username"],
                password=decrypt(conn_row.get("password_enc")),
                database=conn_row["database_name"],
                autocommit=True,
                charset="utf8mb4",
                ssl_disabled=not bool(conn_row.get("use_ssl")),
            )
    return _report_pools[cid]


def forget_pool(cid):
    """Called when a connection's details change, so the next query redials."""
    with _report_lock:
        _report_pools.pop(cid, None)


@contextmanager
def reporting(conn_row):
    pool = _pool_for(conn_row)
    conn = pool.get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        # A report has no business writing. This is belt and braces on top of
        # the read-only grant the account should already have.
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        yield cur
    finally:
        try:
            cur.execute("SET SESSION TRANSACTION READ WRITE")
        except Exception:
            pass
        cur.close()
        conn.close()


def run_report_query(conn_row, sql, params):
    """Run one generated query under a timeout and a row cap."""
    hinted = sql
    if hinted.lstrip().upper().startswith("SELECT"):
        hinted = hinted.replace(
            "SELECT", f"SELECT /*+ MAX_EXECUTION_TIME({QUERY_TIMEOUT_MS}) */", 1
        )
    with reporting(conn_row) as cur:
        cur.execute(hinted, params)
        rows = cur.fetchmany(MAX_ROWS)
        # drain anything above the cap so the connection is reusable
        while cur.fetchmany(MAX_ROWS):
            pass
        return rows

@contextmanager
def writing(conn_row):
    pool = _pool_for(conn_row)
    conn = pool.get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

def run_write_query(conn_row, sql, params):
    with writing(conn_row) as cur:
        cur.execute(sql, params)
        return cur.rowcount
def test_connection(conn_row):
    """Actually dial the database. Returns (ok, note)."""
    try:
        c = mysql.connector.connect(
            host=conn_row["host"],
            port=int(conn_row["port"] or 3306),
            user=conn_row["username"],
            password=decrypt(conn_row.get("password_enc")),
            database=conn_row["database_name"],
            connection_timeout=6,
            ssl_disabled=not bool(conn_row.get("use_ssl")),
        )
        cur = c.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()
        cur.close()
        c.close()
        return True, "Connected."
    except Exception as exc:  # noqa: BLE001 - the message is for the operator
        return False, str(exc)[:480]


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------
_TYPE_MAP = {
    "int": "number", "bigint": "number", "smallint": "number",
    "mediumint": "number", "tinyint": "number", "decimal": "number",
    "numeric": "number", "float": "number", "double": "number",
    "date": "date", "datetime": "date", "timestamp": "date",
    "bit": "bool", "boolean": "bool",
}


def introspect(conn_row):
    """Read the live catalogue: [{name, columns:[{name, type}]}].

    This is the allowlist the query builder validates against, and it is also
    what the designer's Tables & columns panel shows once a connection is up.
    """
    sql = (
        "SELECT TABLE_NAME AS t, COLUMN_NAME AS c, DATA_TYPE AS d "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = %s "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION"
    )
    tables = {}
    with reporting(conn_row) as cur:
        cur.execute(sql, (conn_row["database_name"],))
        for row in cur.fetchall():
            tables.setdefault(row["t"], []).append(
                {"name": row["c"], "type": _TYPE_MAP.get(row["d"].lower(), "text")}
            )
    return [{"name": t, "columns": cols} for t, cols in tables.items()]


def catalogue_index(tables):
    """{table: {column, ...}} — the shape querybuilder wants."""
    return {t["name"]: {c["name"] for c in t["columns"]} for t in tables}
