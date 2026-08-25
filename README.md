# NexD Designer

React front end · Python (Flask) middleware · MySQL.

Design report formats, bind boxes to database tables, apply Excel formulas,
and publish a link other systems can embed.

`nexd-designer-v14.html` in this folder is the single-file build — same
document model, no server. Definitions move between the two unchanged.

---

## Where things run

| Concern | Where |
|---|---|
| Document editing, layout, styling | React |
| SQL generation, joins, filters | Python |
| Formula evaluation | Python (the browser also parses, to validate as you type) |
| Definitions | MySQL (`nexd_designer`) |
| Report data | Whatever `data_connections` points at |

React sends the definition and the filter state. Python builds the SQL, runs
it read-only, evaluates any formula, and returns finished values. The browser
never receives a row it is not entitled to, which is what makes a role-scoped
link meaningful rather than decorative.

---

## The part that matters most

`querybuilder.py` turns a saved definition into SQL. Definitions come from a
browser, so they are untrusted input.

Values are always bound as parameters. **Identifiers cannot be** — no database
lets you parameterise a table or column name — so every one is checked against
the live schema introspected from `INFORMATION_SCHEMA` before it reaches a
query. Anything not in that catalogue is rejected rather than escaped and
hoped for.

Verified against these, all rejected:

```
invoices; DROP TABLE users      net; DROP
invoices`--                     1=1
'; DELETE FROM x; --            net` , (SELECT 1)
invoices UNION SELECT 1         users        (not in schema)
```

Aggregates, operators and join types are checked against fixed sets, and a
join cannot reference a table that has not been joined yet.

---

## Setup

### 1 · MySQL

```bash
mysql -u root -p < backend/schema.sql

mysql -u root -p -e "
CREATE USER 'nexd_designer'@'localhost' IDENTIFIED BY 'a-strong-password';
GRANT SELECT,INSERT,UPDATE,DELETE ON nexd_designer.* TO 'nexd_designer'@'localhost';

-- the reporting account is read-only on purpose
CREATE USER 'nexd_reader'@'localhost' IDENTIFIED BY 'another-strong-password';
GRANT SELECT ON your_reporting_db.* TO 'nexd_reader'@'localhost';
FLUSH PRIVILEGES;"
```

### 2 · Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
export DESIGNER_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
export JWT_SECRET="$(openssl rand -hex 32)"
export META_DB_PASSWORD='a-strong-password'
export ALLOWED_ORIGINS='http://localhost:5173'

flask --app app run --port 5000        # production: gunicorn -w 4 app:app
```

**Back `DESIGNER_KEY` up somewhere outside the database.** Lose it and every
stored connection password becomes unreadable — the rows survive, but you
would re-enter each one.

Create the first user:

```bash
python -c "
from werkzeug.security import generate_password_hash as h
import mysql.connector, os
c=mysql.connector.connect(host='localhost',user='nexd_designer',
  password=os.environ['META_DB_PASSWORD'],database='nexd_designer')
cur=c.cursor()
cur.execute('''INSERT INTO users (username,email,full_name,password_hash,role)
  VALUES ('admin','admin@example.com','Administrator',%s,'admin')''',(h('ChooseAStrongOne!'),))
c.commit()"
```

### 3 · Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173
```

Vite proxies `/api` to port 5000 in dev, so there is no CORS preflight while
developing. For production, `npm run build` and serve `dist/` behind the same
origin as the API.

### 4 · First run

Sign in, open **System Settings**, add a connection to your reporting
database and press **Test connection**. The catalogue fills from
`INFORMATION_SCHEMA` and every table and column picker comes alive.

---

## API

```
POST   /api/auth/login

GET    /api/connections                 POST /api/connections
PUT    /api/connections/:id             DELETE /api/connections/:id
POST   /api/connections/:id/test
GET    /api/catalog

GET    /api/processes                   POST /api/processes
GET    /api/processes/:key              PUT  /api/processes/:key
DELETE /api/processes/:key

POST   /api/processes/:key/execute-all  -- whole page, one round trip
POST   /api/processes/:key/preview-sql  -- what a box will run
GET    /api/processes/:key/filters/:client_id/options

POST   /api/processes/:key/publish      POST /api/processes/:key/unpublish
GET    /api/r/:key-:token               -- what a published link resolves to
```

`execute-all` runs value boxes first, so a formula can reference another box
by name.

---

## Formulas

A KPI can be a single aggregate, a typed number, or an expression:

```
=SUM(net) - SUM(tax)
=ROUND(SUM(net) / COUNT(invoice_no), 2)
=IF(SUM(net) > 0, SUM(tax) / SUM(net) * 100, 0)
=[Gross spend] - [Tax]            <- another box, by its title
```

`SUM AVG COUNT COUNTD MIN MAX` over columns; `ROUND ABS SQRT POWER IF AND OR
NOT` for the arithmetic. Bracketed names that are not columns are box
references.

`formula.py` is asked, before any query runs, which aggregates the expression
needs. The query builder folds those into a single SELECT, so a formula over
five columns is still one trip to the database.

The browser carries the same grammar so a formula is validated as you type —
a mistyped column, an unknown function or a self-reference is named before
anything is saved. Only the server's result is ever displayed.

---

## Safety rails already in place

- Report queries run inside `SET SESSION TRANSACTION READ ONLY`.
- `MAX_EXECUTION_TIME` caps a runaway query (`QUERY_TIMEOUT_MS`, default 15s).
- Results are capped at `MAX_ROWS` (default 5000).
- Connection passwords are Fernet-encrypted; `clean()` drops every bytes
  column before serialising, so no endpoint can leak ciphertext.
- Every save writes a row to `process_versions`, so a published report can be
  pinned to a version and an edit never silently changes a live report.
- Every open of a published link is recorded in `publication_access`.

---

## One thing to finish before production

`/api/r/:key-:token` accepts `?role=` from the query string. That is a
*request*, not proof. The endpoint must verify the caller is entitled to that
role from a session or a signed assertion before trusting it, or anyone can
type `?role=cfo`. The role lock inside `filter_conditions()` prevents widening
scope *within* a role; it cannot stop someone claiming a different one. That
check belongs in `resolve_public()`, and it is marked with a comment there.

---

## Layout

```
backend/
  schema.sql        MySQL: users, connections, processes, versions, publications
  db.py             pools, Fernet encryption, schema introspection
  querybuilder.py   definition -> SQL, with the identifier guard
  formula.py        Excel-style expression engine
  app.py            Flask API
frontend/src/
  model.js          document factories, migration, formatting
  store.jsx         reducer — every edit is an action
  api.js            one place that talks to the middleware
  App.jsx           shell, page buttons, debounced/abortable execution loop
  styles.css        the whole visual language
  components/
    Canvas.jsx      report name, filter bar, sections
    Box.jsx         box rendering, toolbar, three-tab settings panel
    Panels.jsx      shared controls, format panel, join + WHERE editor
    Views.jsx       report list and system settings
  charts/Chart.jsx  SVG chart engine, six types, no chart library
nexd-designer-v14.html   the single-file build
```

---

## What is not built

- Only MySQL is wired up. The connection form offers PostgreSQL, SQL Server
  and Oracle, and the schema stores the choice, but `db.py` dials MySQL. Add
  a driver per engine in `_pool_for` and `introspect`.
- Roles are modelled in the API surface but there is no role-source table
  picker in this front end yet; `filter_conditions()` already honours
  `role_bound` filters when a role row is passed in.
- The published link resolves to a definition; rendering a read-only public
  page from it is a small addition on top of `Canvas` in preview mode.
