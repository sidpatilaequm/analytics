"""Excel-style expressions for KPI boxes.

    =SUM(net) - SUM(tax)
    =ROUND(SUM(net) / COUNT(invoice_no), 2)
    =IF(SUM(net) > 0, SUM(tax) / SUM(net) * 100, 0)
    =[Gross spend] - [Tax]           <- another box, by its title

Two jobs, and they run at different times:

  * ``aggregate_pairs`` is asked, before any query runs, which aggregates the
    expression needs. The query builder turns those into one SELECT, so a
    formula over five columns is still a single trip to the database.
  * ``evaluate`` then folds those results, plus any referenced boxes, into a
    number.

Parsing is a plain recursive descent — small enough to read in one sitting,
and it reports the first thing it does not understand rather than guessing.
The browser carries the same grammar so a formula validates as you type.
"""

import re

AGG_FN = {
    "SUM": "SUM", "AVG": "AVG", "AVERAGE": "AVG", "COUNT": "COUNT",
    "COUNTD": "COUNT DISTINCT", "COUNTDISTINCT": "COUNT DISTINCT",
    "MIN": "MIN", "MAX": "MAX",
}
SCALAR_FN = {"ROUND", "ABS", "SQRT", "POWER", "IF", "AND", "OR", "NOT",
             "MAX", "MIN", "SUM"}


class FormulaError(ValueError):
    pass


# --------------------------------------------------------------------------
# tokeniser
# --------------------------------------------------------------------------
_TWO = ("<=", ">=", "<>")


def tokenise(src):
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "[":
            j = src.find("]", i)
            if j < 0:
                raise FormulaError("unclosed [")
            out.append(("ref", src[i + 1:j].strip()))
            i = j + 1
            continue
        if ch in "\"'":
            j = src.find(ch, i + 1)
            if j < 0:
                raise FormulaError("unclosed quote")
            out.append(("str", src[i + 1:j]))
            i = j + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            out.append(("num", float(src[i:j])))
            i = j
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_."):
                j += 1
            out.append(("id", src[i:j]))
            i = j
            continue
        if src[i:i + 2] in _TWO:
            out.append(("op", src[i:i + 2]))
            i += 2
            continue
        if ch in "+-*/^(),%<>=":
            out.append(("op", ch))
            i += 1
            continue
        raise FormulaError(f"unexpected character {ch}")
    return out


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def parse(src):
    src = (src or "").strip().lstrip("=")
    if not src:
        raise FormulaError("empty formula")
    toks = tokenise(src)
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def eat(val=None):
        nonlocal pos
        tk = peek()
        if tk is None or (val is not None and tk[1] != val):
            raise FormulaError(f"expected {val or 'more input'}")
        pos += 1
        return tk

    def expr():
        return cmp_()

    def cmp_():
        node = add()
        while peek() and peek()[0] == "op" and peek()[1] in ("<", ">", "<=", ">=", "=", "<>"):
            op = eat()[1]
            node = ("bin", op, node, add())
        return node

    def add():
        node = mul()
        while peek() and peek()[0] == "op" and peek()[1] in ("+", "-"):
            op = eat()[1]
            node = ("bin", op, node, mul())
        return node

    def mul():
        node = power()
        while peek() and peek()[0] == "op" and peek()[1] in ("*", "/"):
            op = eat()[1]
            node = ("bin", op, node, power())
        return node

    def power():
        node = unary()
        if peek() and peek()[0] == "op" and peek()[1] == "^":
            eat()
            node = ("bin", "^", node, power())
        if peek() and peek()[0] == "op" and peek()[1] == "%":
            eat()
            node = ("bin", "/", node, ("num", 100.0))
        return node

    def unary():
        if peek() and peek()[0] == "op" and peek()[1] in ("-", "+"):
            op = eat()[1]
            return ("un", op, unary())
        return primary()

    def primary():
        tk = peek()
        if tk is None:
            raise FormulaError("the formula ends early")
        kind, val = tk
        if kind == "num":
            eat()
            return ("num", val)
        if kind == "str":
            eat()
            return ("str", val)
        if kind == "ref":
            eat()
            return ("ref", val)
        if kind == "op" and val == "(":
            eat("(")
            node = expr()
            eat(")")
            return node
        if kind == "id":
            eat()
            if peek() and peek()[0] == "op" and peek()[1] == "(":
                eat("(")
                args = []
                if not (peek() and peek()[0] == "op" and peek()[1] == ")"):
                    args.append(expr())
                    while peek() and peek()[0] == "op" and peek()[1] == ",":
                        eat(",")
                        args.append(expr())
                eat(")")
                return ("call", val.upper(), args)
            if val.upper() in ("TRUE", "FALSE"):
                return ("num", 1.0 if val.upper() == "TRUE" else 0.0)
            return ("ref", val)
        raise FormulaError(f"unexpected {val}")

    node = expr()
    if pos < len(toks):
        raise FormulaError(f"unexpected {toks[pos][1]}")
    return node


# --------------------------------------------------------------------------
# what a formula needs before it can run
# --------------------------------------------------------------------------
def aggregate_pairs(src):
    """[(aggregate, column)] the expression asks for, deduplicated."""
    try:
        ast = parse(src)
    except FormulaError:
        return []
    found, seen = [], set()

    def walk(node):
        if not isinstance(node, tuple):
            return
        if node[0] == "call":
            fn, args = node[1], node[2]
            if fn in AGG_FN and len(args) == 1 and args[0][0] == "ref":
                key = (AGG_FN[fn], args[0][1])
                if key not in seen:
                    seen.add(key)
                    found.append(key)
                return
            for a in args:
                walk(a)
        elif node[0] == "bin":
            walk(node[2])
            walk(node[3])
        elif node[0] == "un":
            walk(node[2])

    walk(ast)
    return found


def columns_used(src):
    return [col for _, col in aggregate_pairs(src)]


def boxes_used(src, known_columns):
    """Bracketed names that are not columns are references to other boxes."""
    try:
        ast = parse(src)
    except FormulaError:
        return []
    out = []

    def walk(node):
        if not isinstance(node, tuple):
            return
        if node[0] == "ref" and node[1] not in known_columns:
            out.append(node[1])
        elif node[0] == "call":
            for a in node[2]:
                walk(a)
        elif node[0] == "bin":
            walk(node[2])
            walk(node[3])
        elif node[0] == "un":
            walk(node[2])

    walk(ast)
    return out


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _blank(*vals):
    return any(v is None for v in vals)


def evaluate(src, aggregates, boxes, columns):
    """Fold a parsed formula into a number.

    aggregates: {('SUM','net'): 600.0}
    boxes:      {'gross spend': 600.0}   (titles lower-cased)
    columns:    the set of column names that exist on this box's source
    """
    ast = parse(src)

    def run(node):
        tag = node[0]
        if tag in ("num", "str"):
            return node[1]
        if tag == "un":
            v = run(node[2])
            return -_num(v) if node[1] == "-" else _num(v)
        if tag == "bin":
            op, a, b = node[1], run(node[2]), run(node[3])
            if op == "+":
                return None if _blank(a, b) else _num(a) + _num(b)
            if op == "-":
                return None if _blank(a, b) else _num(a) - _num(b)
            if op == "*":
                return None if _blank(a, b) else _num(a) * _num(b)
            if op == "/":
                if _blank(a, b) or _num(b) == 0:
                    return None
                return _num(a) / _num(b)
            if op == "^":
                return None if _blank(a, b) else _num(a) ** _num(b)
            if op == "=":
                return 1.0 if str(a) == str(b) else 0.0
            if op == "<>":
                return 1.0 if str(a) != str(b) else 0.0
            if op == "<":
                return 1.0 if _num(a) < _num(b) else 0.0
            if op == ">":
                return 1.0 if _num(a) > _num(b) else 0.0
            if op == "<=":
                return 1.0 if _num(a) <= _num(b) else 0.0
            if op == ">=":
                return 1.0 if _num(a) >= _num(b) else 0.0
            return None
        if tag == "ref":
            name = node[1]
            if name in columns:
                raise FormulaError(
                    f'"{name}" is a column — wrap it, e.g. SUM({name})'
                )
            key = name.strip().lower()
            if key not in boxes:
                raise FormulaError(
                    f'nothing called "{name}" — not a column or a box'
                )
            return boxes[key]
        if tag == "call":
            fn, args = node[1], node[2]
            if fn in AGG_FN and len(args) == 1 and args[0][0] == "ref":
                ref = args[0][1]
                if ref not in columns:
                    raise FormulaError(f'unknown column "{ref}"')
                return aggregates.get((AGG_FN[fn], ref))
            if fn not in SCALAR_FN and fn not in AGG_FN:
                raise FormulaError(f"unknown function {fn}()")
            vals = [run(a) for a in args]
            if fn == "ROUND":
                if vals[0] is None:
                    return None
                digits = int(_num(vals[1])) if len(vals) > 1 else 0
                return round(_num(vals[0]), digits)
            if fn == "ABS":
                return None if vals[0] is None else abs(_num(vals[0]))
            if fn == "SQRT":
                return None if vals[0] is None else _num(vals[0]) ** 0.5
            if fn == "POWER":
                return None if _blank(*vals[:2]) else _num(vals[0]) ** _num(vals[1])
            if fn == "IF":
                return vals[1] if _num(vals[0]) else (vals[2] if len(vals) > 2 else 0.0)
            if fn == "AND":
                return 1.0 if all(_num(v) for v in vals) else 0.0
            if fn == "OR":
                return 1.0 if any(_num(v) for v in vals) else 0.0
            if fn == "NOT":
                return 0.0 if _num(vals[0]) else 1.0
            if fn == "SUM":
                return None if any(v is None for v in vals) else sum(_num(v) for v in vals)
            if fn == "MAX":
                return None if any(v is None for v in vals) else max(_num(v) for v in vals)
            if fn == "MIN":
                return None if any(v is None for v in vals) else min(_num(v) for v in vals)
            raise FormulaError(f"unknown function {fn}()")
        return None

    return run(ast)


def check(src, columns):
    """Validate without data. Returns (ok, message)."""
    try:
        parse(src)
    except FormulaError as exc:
        return False, str(exc)
    for _, col in aggregate_pairs(src):
        if col not in columns:
            return False, f'unknown column "{col}"'
    return True, "Parses cleanly."
