"""NexD Designer — Flask middleware.

The browser sends a definition and the filter state. This process builds the
SQL, runs it read-only, evaluates any formula, and returns finished values.
The browser never receives a row it is not entitled to, which is what makes a
role-scoped link meaningful rather than decorative.
"""

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.security import check_password_hash

import db
import formula
from querybuilder import BadDefinition, build, build_write, preview
app = Flask(__name__)
CORS(
    app,
    resources={r"/api/*": {"origins": os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:5173").split(",")}},
    supports_credentials=True,
)

JWT_SECRET = os.environ.get("JWT_SECRET", "")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET is not set. openssl rand -hex 32")
TOKEN_HOURS = int(os.environ.get("TOKEN_HOURS", 12))


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------
def issue(user):
    payload = {
        "sub": user["id"],
        "username": user["username"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def auth(required_role=None):
    def outer(fn):
        @wraps(fn)
        def inner(*a, **kw):
            head = request.headers.get("Authorization", "")
            if not head.startswith("Bearer "):
                return jsonify(error="sign in first"), 401
            try:
                g.user = jwt.decode(head[7:], JWT_SECRET, algorithms=["HS256"])
            except jwt.ExpiredSignatureError:
                return jsonify(error="session expired"), 401
            except jwt.InvalidTokenError:
                return jsonify(error="bad token"), 401
            if required_role == "admin" and g.user.get("role") != "admin":
                return jsonify(error="admins only"), 403
            return fn(*a, **kw)
        return inner
    return outer


@app.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    row = db.q1(
        "SELECT * FROM users WHERE username=%s AND is_active=1",
        (body.get("username", ""),),
    )
    if not row or not check_password_hash(row["password_hash"], body.get("password", "")):
        return jsonify(error="those details do not match"), 401
    return jsonify(token=issue(row), user=db.clean(
        {k: row[k] for k in ("id", "username", "full_name", "role")}))


# --------------------------------------------------------------------------
# connections
# --------------------------------------------------------------------------
@app.get("/api/connections")
@auth()
def list_connections():
    return jsonify(db.clean(db.qall(
        "SELECT * FROM data_connections ORDER BY name")))


@app.post("/api/connections")
@auth("admin")
def create_connection():
    b = request.get_json(silent=True) or {}
    cid = db.execute(
        "INSERT INTO data_connections "
        "(name,engine,host,port,database_name,username,password_enc,use_ssl,read_only) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (b.get("name", "New connection"), b.get("engine", "mysql"),
         b.get("host", ""), int(b.get("port") or 3306), b.get("database", ""),
         b.get("username", ""), db.encrypt(b.get("password", "")),
         1 if b.get("ssl") else 0, 1 if b.get("readOnly", True) else 0),
    )
    return jsonify(db.clean(db.q1("SELECT * FROM data_connections WHERE id=%s", (cid,))))


@app.put("/api/connections/<int:cid>")
@auth("admin")
def update_connection(cid):
    b = request.get_json(silent=True) or {}
    fields, args = [], []
    for key, col in (("name", "name"), ("engine", "engine"), ("host", "host"),
                     ("database", "database_name"), ("username", "username")):
        if key in b:
            fields.append(f"{col}=%s")
            args.append(b[key])
    if "port" in b:
        fields.append("port=%s")
        args.append(int(b["port"] or 3306))
    if "ssl" in b:
        fields.append("use_ssl=%s")
        args.append(1 if b["ssl"] else 0)
    if b.get("password"):
        fields.append("password_enc=%s")
        args.append(db.encrypt(b["password"]))
    if not fields:
        return jsonify(error="nothing to change"), 400
    fields.append("status='untested'")
    args.append(cid)
    db.execute(f"UPDATE data_connections SET {', '.join(fields)} WHERE id=%s", tuple(args))
    db.forget_pool(cid)
    return jsonify(db.clean(db.q1("SELECT * FROM data_connections WHERE id=%s", (cid,))))


@app.delete("/api/connections/<int:cid>")
@auth("admin")
def delete_connection(cid):
    db.execute("DELETE FROM data_connections WHERE id=%s", (cid,))
    db.forget_pool(cid)
    return jsonify(ok=True)


@app.post("/api/connections/<int:cid>/test")
@auth()
def test_conn(cid):
    row = db.q1("SELECT * FROM data_connections WHERE id=%s", (cid,))
    if not row:
        return jsonify(error="no such connection"), 404
    ok, note = db.test_connection(row)
    db.execute("UPDATE data_connections SET status=%s, status_note=%s WHERE id=%s",
               ("ok" if ok else "bad", note, cid))
    return jsonify(ok=ok, note=note)


# --------------------------------------------------------------------------
# catalogue
# --------------------------------------------------------------------------
def _connection_for(process=None, cid=None):
    if cid:
        return db.q1("SELECT * FROM data_connections WHERE id=%s", (cid,))
    if process and process.get("connection_id"):
        return db.q1("SELECT * FROM data_connections WHERE id=%s",
                     (process["connection_id"],))
    return db.q1("SELECT * FROM data_connections ORDER BY id LIMIT 1")


@app.get("/api/catalog")
@auth()
def catalog():
    row = _connection_for(cid=request.args.get("connection_id", type=int))
    if not row:
        return jsonify(tables=[], note="No connection configured yet.")
    try:
        return jsonify(tables=db.introspect(row))
    except Exception as exc:  # noqa: BLE001
        return jsonify(tables=[], note=str(exc)[:300]), 200


# --------------------------------------------------------------------------
# processes
# --------------------------------------------------------------------------
@app.get("/api/processes")
@auth()
def list_processes():
    rows = db.qall(
        "SELECT p.process_key, p.name, p.version, p.updated_at, p.connection_id, "
        "       (SELECT COUNT(*) FROM publications pub "
        "         WHERE pub.process_id = p.id AND pub.is_active = 1) AS published "
        "FROM processes p ORDER BY p.updated_at DESC")
    return jsonify(db.clean(rows))


@app.get("/api/processes/<key>")
@auth()
def get_process(key):
    row = db.q1("SELECT * FROM processes WHERE process_key=%s", (key,))
    if not row:
        return jsonify(error="no such report"), 404
    out = db.clean(row)
    out["definition"] = row["definition"] if isinstance(row["definition"], dict) \
        else json.loads(row["definition"])
    return jsonify(out)


@app.post("/api/processes")
@auth()
def create_process():
    b = request.get_json(silent=True) or {}
    key = b.get("process_key") or "rpt_" + secrets.token_hex(4)
    definition = b.get("definition") or {"name": "New Report / Dashboard",
                                         "filters": [], "sections": []}
    pid = db.execute(
        "INSERT INTO processes (process_key,name,connection_id,definition,created_by) "
        "VALUES (%s,%s,%s,%s,%s)",
        (key, definition.get("name", "New Report / Dashboard"),
         b.get("connection_id"), json.dumps(definition), g.user["sub"]),
    )
    db.execute("INSERT INTO process_versions (process_id,version,definition,saved_by) "
               "VALUES (%s,1,%s,%s)", (pid, json.dumps(definition), g.user["sub"]))
    return jsonify(process_key=key, version=1)


@app.put("/api/processes/<key>")
@auth()
def save_process(key):
    b = request.get_json(silent=True) or {}
    row = db.q1("SELECT id, version FROM processes WHERE process_key=%s", (key,))
    if not row:
        return jsonify(error="no such report"), 404
    definition = b.get("definition") or {}
    version = row["version"] + 1
    db.execute("UPDATE processes SET name=%s, connection_id=%s, definition=%s, "
               "version=%s WHERE id=%s",
               (definition.get("name", "Untitled"), b.get("connection_id"),
                json.dumps(definition), version, row["id"]))
    db.execute("INSERT INTO process_versions (process_id,version,definition,saved_by) "
               "VALUES (%s,%s,%s,%s)",
               (row["id"], version, json.dumps(definition), g.user["sub"]))
    return jsonify(process_key=key, version=version)


@app.delete("/api/processes/<key>")
@auth()
def delete_process(key):
    db.execute("DELETE FROM processes WHERE process_key=%s", (key,))
    return jsonify(ok=True)


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------
def _catalogue(conn_row):
    return db.catalogue_index(db.introspect(conn_row))


def _run_box(box, definition, state, conn_row, cat, role_row, values):
    """Return the finished payload for one box."""
    kind = box.get("kind")
    if kind == "note":
        return None

    if kind == "value" and (box.get("value") or {}).get("source") == "manual":
        return {"value": box["value"].get("manual")}

    if kind == "value" and (box.get("value") or {}).get("source") == "formula":
        src = box["src"] or {}
        cols = set()
        if src.get("base") in cat:
            cols |= cat[src["base"]]
            for j in src.get("joins") or []:
                if j.get("table") in cat:
                    cols |= {f"{j['table']}.{c}" for c in cat[j["table"]]}
        expr = box["value"].get("formula") or ""
        ok, note = formula.check(expr, cols)
        if not ok:
            return {"error": note}
        sql, params = build(box, definition.get("filters"), state, cat, role_row)
        aggregates = {}
        if sql:
            rows = db.run_report_query(conn_row, sql, params)
            if rows:
                for how, ref in formula.aggregate_pairs(expr):
                    aggregates[(how, ref)] = rows[0].get(f"{how}:{ref}")
        try:
            return {"value": formula.evaluate(expr, aggregates, values, cols)}
        except formula.FormulaError as exc:
            return {"error": str(exc)}

    sql, params = build(box, definition.get("filters"), state, cat, role_row)
    if sql is None:
        return {"value": None}
    rows = db.run_report_query(conn_row, sql, params)
    if kind == "value":
        return {"value": rows[0]["value"] if rows else None}
    if kind == "chart":
        return {"data": [{"label": str(r["category"]), "value": r["value"]} for r in rows]}
    return {"rows": rows}


@app.post("/api/processes/<key>/execute-all")
@auth()
def execute_all(key):
    body = request.get_json(silent=True) or {}
    row = db.q1("SELECT * FROM processes WHERE process_key=%s", (key,))
    if not row:
        return jsonify(error="no such report"), 404
    definition = body.get("definition") or (
        row["definition"] if isinstance(row["definition"], dict)
        else json.loads(row["definition"]))
    conn_row = _connection_for(row)
    if not conn_row:
        return jsonify(error="no data connection configured"), 400
    try:
        cat = _catalogue(conn_row)
    except Exception as exc:  # noqa: BLE001
        return jsonify(error=f"could not read the catalogue: {exc}"), 502

    state = body.get("filters") or {}
    results, values = {}, {}

    # Value boxes first, so a formula can reference another box by name.
    ordered = []
    for sec in definition.get("sections", []):
        for box in sec.get("boxes", []):
            ordered.append(box)
    ordered.sort(key=lambda b: 0 if b.get("kind") == "value" else 1)

    for box in ordered:
        try:
            payload = _run_box(box, definition, state, conn_row, cat, None, values)
        except BadDefinition as exc:
            payload = {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            payload = {"error": str(exc)[:300]}
        if payload is None:
            continue
        results[box["id"]] = payload
        if box.get("kind") == "value":
            v = payload.get("value")
            try:
                v = float(v) if v is not None and v != "" else None
            except (TypeError, ValueError):
                v = None
            if v is not None:
                values[str(box.get("title", "")).strip().lower()] = v
    return jsonify(results=results)


@app.post("/api/processes/<key>/preview-sql")
@auth()
def preview_sql(key):
    body = request.get_json(silent=True) or {}
    row = db.q1("SELECT * FROM processes WHERE process_key=%s", (key,))
    definition = body.get("definition") or {}
    conn_row = _connection_for(row)
    if not conn_row:
        return jsonify(error="no data connection configured"), 400
    cat = _catalogue(conn_row)
    box = body.get("box") or {}
    return jsonify(preview(box, definition.get("filters"), body.get("filters") or {}, cat))


@app.get("/api/processes/<key>/filters/<client_id>/options")
@auth()
def filter_options(key, client_id):
    row = db.q1("SELECT * FROM processes WHERE process_key=%s", (key,))
    if not row:
        return jsonify(error="no such report"), 404
    definition = row["definition"] if isinstance(row["definition"], dict) \
        else json.loads(row["definition"])
    flt = next((f for f in definition.get("filters", []) if f.get("id") == client_id), None)
    if not flt:
        return jsonify(options=[])
    if flt.get("optionSource") == "list":
        vals = [v.strip() for v in (flt.get("list") or "").replace(",", "\n").split("\n")]
        return jsonify(options=[{"value": v, "label": v} for v in vals if v])

    conn_row = _connection_for(row)
    if not conn_row:
        return jsonify(options=[])
    cat = _catalogue(conn_row)
    table = flt.get("optTable") if flt.get("optionSource") == "table" else flt.get("table")
    column = flt.get("optColumn") if flt.get("optionSource") == "table" else flt.get("column")
    if table not in cat or column not in cat.get(table, set()):
        return jsonify(options=[])
    sql = f"SELECT DISTINCT `{table}`.`{column}` AS v FROM `{table}` " \
          f"WHERE `{table}`.`{column}` IS NOT NULL ORDER BY v LIMIT 500"
    rows = db.run_report_query(conn_row, sql, ())
    return jsonify(options=[{"value": r["v"], "label": str(r["v"])} for r in rows])


# --------------------------------------------------------------------------
# publishing
# --------------------------------------------------------------------------
@app.post("/api/processes/<key>/write")
@auth()
def write_box(key):
    ...
@app.post("/api/processes/<key>/publish")
@auth()
def publish(key):
    row = db.q1("SELECT id, version FROM processes WHERE process_key=%s", (key,))
    if not row:
        return jsonify(error="no such report"), 404
    db.execute("UPDATE publications SET is_active=0 WHERE process_id=%s", (row["id"],))
    token = secrets.token_urlsafe(16)
    db.execute("INSERT INTO publications (process_id,token,pinned_version) "
               "VALUES (%s,%s,%s)", (row["id"], token, row["version"]))
    return jsonify(token=token, url=f"/api/r/{key}-{token}", pinned_version=row["version"])


@app.post("/api/processes/<key>/unpublish")
@auth()
def unpublish(key):
    row = db.q1("SELECT id FROM processes WHERE process_key=%s", (key,))
    if row:
        db.execute("UPDATE publications SET is_active=0 WHERE process_id=%s", (row["id"],))
    return jsonify(ok=True)


@app.get("/api/r/<path:slug>")
def resolve_public(slug):
    """What a published link resolves to.

    NOT FINISHED FOR PRODUCTION. This endpoint accepts ?role= from the query
    string. That is a *request*, not proof. Before trusting it, verify the
    caller is entitled to that role from a session or a signed assertion —
    otherwise anyone can type ?role=cfo. The role lock inside
    filter_conditions() stops someone widening their scope *within* a role;
    it cannot stop them claiming a different one. That check belongs here.
    """
    if "-" not in slug:
        return jsonify(error="bad link"), 404
    key, token = slug.rsplit("-", 1)
    pub = db.q1(
        "SELECT pub.*, p.process_key FROM publications pub "
        "JOIN processes p ON p.id = pub.process_id "
        "WHERE p.process_key=%s AND pub.token=%s AND pub.is_active=1", (key, token))
    if not pub:
        return jsonify(error="this link is not live"), 404
    db.execute("INSERT INTO publication_access (publication_id,remote_addr,role_claimed) "
               "VALUES (%s,%s,%s)",
               (pub["id"], request.remote_addr or "", request.args.get("role", "")))
    ver = db.q1("SELECT definition FROM process_versions "
                "WHERE process_id=%s AND version=%s",
                (pub["process_id"], pub["pinned_version"]))
    definition = ver["definition"] if isinstance(ver["definition"], dict) \
        else json.loads(ver["definition"])
    return jsonify(process_key=key, pinned_version=pub["pinned_version"],
                   definition=definition)


@app.get("/api/health")
def health():
    return jsonify(ok=True, service="nexd-designer")


if __name__ == "__main__":
    app.run(port=int(os.environ.get("PORT", 5000)), debug=True)
