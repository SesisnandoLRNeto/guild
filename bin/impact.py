#!/usr/bin/env python3
"""The backend part of a wrap-up report: data model changes, their impact on the rest of the
repo, and business rule changes, drawn as diagrams and tables.

  impact.py build  <repo> <base> [--rules FILE] [--out FILE]   an HTML section (stdout without --out)
  impact.py into   <page> <repo> <base> [--rules FILE]          put the section into a page
  impact.py detect <repo> <base>                                prints model/rules/unexplained, exit 1 if nothing
  impact.py json   <repo> <base>                                the raw findings

How it finds things, with no database and no build:
- Schema: every migration file (Liquibase formatted SQL or XML, Flyway SQL) is replayed in file
  order, once at the merge base and once on the working tree, and the two schemas are compared.
- Entities: JPA @Entity classes that changed are parsed on both sides and their fields compared.
  A field with no column, or a new column with no field, is flagged.
- Impact: git grep for every changed table and entity (and removed fields' getters) outside the
  migrations, grouped by module and layer. Changed @...Mapping lines are the changed endpoints.
- Rules: diff hunks in main code that touch validation, throws, conditions or enum constants,
  plus CHECK / NOT NULL / DEFAULT / UNIQUE changes in the schema. Code cannot say what a rule
  means, so the adventurer explains each one in plain words in a rules file:
      {"rules": [{"rule": "A rate needs a currency", "before": "optional", "after": "required",
                  "where": "RateService.java:88", "why": "finance reports per currency"}],
       "note": "the other candidates are refactors with the same behaviour"}
"""
import html
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

MIGRATION_DIR = re.compile(r"(db/changelog|db/migration|/migrations?/|liquibase|flyway)", re.I)
RULE_LINE = re.compile(
    r"\bthrow new\b|\bif\s*\(|\bcase\b|orElseThrow|requireNonNull|"
    r"@(NotNull|NotBlank|NotEmpty|Size|Min|Max|Positive|PositiveOrZero|Negative|Pattern|Email|"
    r"DecimalMin|DecimalMax|Past|Future|PastOrPresent|FutureOrPresent|AssertTrue|AssertFalse|Digits)\b")
MAPPING = re.compile(r"@(Get|Post|Put|Patch|Delete|Request)Mapping\s*(\((.*)\))?")
COL_STOP = {"CONSTRAINT", "NOT", "NULL", "DEFAULT", "PRIMARY", "REFERENCES", "UNIQUE", "CHECK",
            "GENERATED", "COLLATE"}


def git(repo, *args, check=False):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"impact: git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def natural(path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path)]


# ── schema replay ─────────────────────────────────────────────────────────────

def bare(name):
    return name.strip().strip('"').split(".")[-1].strip('"').lower()


def split_top(text, sep=","):
    out, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur).strip()); cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def column_def(text):
    """'client_id uuid CONSTRAINT x REFERENCES client (id) NOT NULL' -> name, props."""
    m = re.match(r'\s*("?[\w]+"?)\s+(.*)$', text, re.S)
    if not m:
        return None, None
    name, rest = bare(m.group(1)), m.group(2)
    words = rest.split()
    typ = []
    for w in words:
        if w.upper() in COL_STOP:
            break
        typ.append(w)
    up = rest.upper()
    ref = re.search(r"REFERENCES\s+([\w.\"]+)", rest, re.I)
    default = re.search(r"DEFAULT\s+('[^']*'|[\w.()]+)", rest, re.I)
    return name, {"type": " ".join(typ).lower() or "?", "notnull": "NOT NULL" in up or "PRIMARY KEY" in up,
                  "pk": "PRIMARY KEY" in up, "fk": bare(ref.group(1)) if ref else "",
                  "default": default.group(1) if default else "", "unique": bool(re.search(r"\bUNIQUE\b", up))}


def empty_table():
    return {"cols": {}, "checks": {}, "uniques": {}}


def apply_sql(schema, text):
    text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    for stmt in split_top(text, ";"):
        s = " ".join(stmt.split())
        if not s:
            continue
        m = re.match(r"CREATE TABLE (IF NOT EXISTS )?([\w.\"]+)\s*\((.*)\)", s, re.I | re.S)
        if m:
            t = schema.setdefault(bare(m.group(2)), empty_table())
            for item in split_top(m.group(3)):
                table_item(t, item)
            continue
        m = re.match(r"ALTER TABLE (IF EXISTS )?(ONLY )?([\w.\"]+)\s+(.*)$", s, re.I | re.S)
        if m:
            name = bare(m.group(3))
            t = schema.setdefault(name, empty_table())
            for action in split_top(m.group(4)):
                renamed = alter(schema, name, t, action)
                if renamed:
                    name, t = renamed, schema[renamed]
            continue
        m = re.match(r"DROP TABLE (IF EXISTS )?(.*?)( CASCADE| RESTRICT)?$", s, re.I)
        if m:
            for n in m.group(2).split(","):
                schema.pop(bare(n), None)
            continue
        m = re.match(r"CREATE (UNIQUE )?INDEX .*? ON ([\w.\"]+)\s*(USING \w+\s*)?\((.*)\)", s, re.I)
        if m and m.group(1):
            schema.setdefault(bare(m.group(2)), empty_table())["uniques"][f"unique ({m.group(4).strip()})"] = True


def table_item(t, item):
    up = item.upper().lstrip()
    named = re.match(r"CONSTRAINT\s+([\w\"]+)\s+(.*)$", item, re.I | re.S)
    cname, body = (bare(named.group(1)), named.group(2)) if named else ("", item)
    bu = body.upper().lstrip()
    if bu.startswith("FOREIGN KEY"):
        m = re.match(r"FOREIGN KEY\s*\(([^)]*)\)\s*REFERENCES\s+([\w.\"]+)", body, re.I)
        if m:
            for c in m.group(1).split(","):
                if bare(c) in t["cols"]:
                    t["cols"][bare(c)]["fk"] = bare(m.group(2))
    elif bu.startswith("CHECK"):
        t["checks"][cname or body] = body
    elif bu.startswith("UNIQUE"):
        t["uniques"][cname or body] = True
    elif bu.startswith("PRIMARY KEY"):
        m = re.search(r"\(([^)]*)\)", body)
        for c in (m.group(1).split(",") if m else []):
            if bare(c) in t["cols"]:
                t["cols"][bare(c)]["pk"] = True
    elif not up.startswith(("EXCLUDE", "LIKE")):
        name, props = column_def(item)
        if name:
            t["cols"][name] = props
            chk = re.search(r"CHECK\s*(\(.*\))", item, re.I)
            if chk:
                t["checks"][f"{name} check"] = f"CHECK {chk.group(1)}"


def alter(schema, name, t, action):
    a = action.strip()
    m = re.match(r"ADD (COLUMN )?(IF NOT EXISTS )?(.*)$", a, re.I | re.S)
    if m and not re.match(r"ADD (CONSTRAINT|PRIMARY|FOREIGN|UNIQUE|CHECK)\b", a, re.I):
        table_item(t, m.group(3)); return None
    m = re.match(r"ADD (.*)$", a, re.I | re.S)
    if m:
        table_item(t, m.group(1)); return None
    m = re.match(r"DROP (COLUMN )?(IF EXISTS )?([\w\"]+)", a, re.I)
    if m and m.group(3).upper() != "CONSTRAINT":
        t["cols"].pop(bare(m.group(3)), None); return None
    m = re.match(r"DROP CONSTRAINT (IF EXISTS )?([\w\"]+)", a, re.I)
    if m:
        c = bare(m.group(2))
        t["checks"].pop(c, None); t["uniques"].pop(c, None)
        for cname, col in t["cols"].items():           # a dropped <table>_<col>_fkey takes the reference away
            if c == f"{name}_{cname}_fkey":
                col["fk"] = ""
        return None
    m = re.match(r"RENAME (COLUMN )?([\w\"]+) TO ([\w\"]+)", a, re.I)
    if m and m.group(2).upper() != "TO":
        old, new = bare(m.group(2)), bare(m.group(3))
        if old in t["cols"]:
            t["cols"][new] = t["cols"].pop(old)
        return None
    m = re.match(r"RENAME TO ([\w.\"]+)", a, re.I)
    if m:
        new = bare(m.group(1)); schema[new] = schema.pop(name); return new
    m = re.match(r"ALTER (COLUMN )?([\w\"]+)\s+(.*)$", a, re.I | re.S)
    if m:
        col = t["cols"].get(bare(m.group(2)))
        op = m.group(3)
        if col is None:
            return None
        ty = re.match(r"(SET DATA )?TYPE\s+(.*?)(\s+USING.*)?$", op, re.I)
        if ty:
            col["type"] = ty.group(2).lower()
        elif re.match(r"SET NOT NULL", op, re.I):
            col["notnull"] = True
        elif re.match(r"DROP NOT NULL", op, re.I):
            col["notnull"] = False
        elif re.match(r"SET DEFAULT\s+(.*)", op, re.I):
            col["default"] = re.match(r"SET DEFAULT\s+(.*)", op, re.I).group(1)
        elif re.match(r"DROP DEFAULT", op, re.I):
            col["default"] = ""
    return None


def apply_xml(schema, text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return
    local = lambda e: e.tag.split("}")[-1]
    for e in root.iter():
        tag, a = local(e), e.attrib
        tname = bare(a.get("tableName", "")) if a.get("tableName") else ""
        if tag == "createTable":
            t = schema.setdefault(tname, empty_table())
            for c in e:
                if local(c) == "column":
                    t["cols"][bare(c.get("name"))] = xml_col(c)
        elif tag == "addColumn":
            t = schema.setdefault(tname, empty_table())
            for c in e:
                if local(c) == "column":
                    t["cols"][bare(c.get("name"))] = xml_col(c)
        elif tag == "dropColumn":
            names = [a.get("columnName")] + [c.get("name") for c in e if local(c) == "column"]
            for n in filter(None, names):
                schema.get(tname, empty_table())["cols"].pop(bare(n), None)
        elif tag == "renameColumn" and tname in schema:
            cols = schema[tname]["cols"]
            if bare(a.get("oldColumnName", "")) in cols:
                cols[bare(a["newColumnName"])] = cols.pop(bare(a["oldColumnName"]))
        elif tag == "modifyDataType" and tname in schema:
            col = schema[tname]["cols"].get(bare(a.get("columnName", "")))
            if col:
                col["type"] = a.get("newDataType", col["type"]).lower()
        elif tag in ("addNotNullConstraint", "dropNotNullConstraint") and tname in schema:
            col = schema[tname]["cols"].get(bare(a.get("columnName", "")))
            if col:
                col["notnull"] = tag == "addNotNullConstraint"
        elif tag == "addForeignKeyConstraint":
            t = schema.get(bare(a.get("baseTableName", "")))
            col = t and t["cols"].get(bare(a.get("baseColumnNames", "")))
            if col:
                col["fk"] = bare(a.get("referencedTableName", ""))
        elif tag == "dropTable":
            schema.pop(tname, None)
        elif tag == "renameTable" and bare(a.get("oldTableName", "")) in schema:
            schema[bare(a["newTableName"])] = schema.pop(bare(a["oldTableName"]))


def xml_col(c):
    props = {"type": (c.get("type") or "?").lower(), "notnull": False, "pk": False, "fk": "",
             "default": c.get("defaultValue") or c.get("defaultValueComputed") or "", "unique": False}
    for k in c:
        if k.tag.split("}")[-1] == "constraints":
            props["notnull"] = k.get("nullable") == "false" or k.get("primaryKey") == "true"
            props["pk"] = k.get("primaryKey") == "true"
            props["unique"] = k.get("unique") == "true"
            ref = k.get("referencedTableName") or (k.get("references") or "").split("(")[0]
            props["fk"] = bare(ref) if ref else ""
    return props


def migration_files(repo, ref=None):
    files = (git(repo, "ls-tree", "-r", "--name-only", ref) if ref else
             git(repo, "ls-files", "--cached", "--others", "--exclude-standard")).split()
    return sorted([f for f in files if MIGRATION_DIR.search("/" + f) and f.endswith((".sql", ".xml"))
                   and "/test/" not in f], key=natural)


def read_at(repo, path, ref=None):
    if ref:
        return git(repo, "show", f"{ref}:{path}")
    try:
        return open(os.path.join(repo, path), encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def schema_at(repo, ref=None):
    schema = {}
    for f in migration_files(repo, ref):
        text = read_at(repo, f, ref)
        (apply_xml if f.endswith(".xml") else apply_sql)(schema, text)
    return schema


def diff_schema(before, after):
    out = []
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if b == a:
            continue
        entry = {"table": name, "state": "new" if b is None else "dropped" if a is None else "changed",
                 "cols": [], "before": list((b or empty_table())["cols"]), "after": list((a or empty_table())["cols"]),
                 "checks": [], "uniques": []}
        bc, ac = (b or empty_table())["cols"], (a or empty_table())["cols"]
        for c in list(ac) + [c for c in bc if c not in ac]:
            x, y = bc.get(c), ac.get(c)
            if x == y:
                continue
            what = []
            if x and y:
                if x["type"] != y["type"]:
                    what.append(f"type {x['type']} -> {y['type']}")
                if x["notnull"] != y["notnull"]:
                    what.append("now required" if y["notnull"] else "now optional")
                if x["fk"] != y["fk"]:
                    what.append(f"references {y['fk']}" if y["fk"] else f"no longer references {x['fk']}")
                if x["default"] != y["default"]:
                    what.append(f"default {x['default'] or 'none'} -> {y['default'] or 'none'}")
                if x["unique"] != y["unique"]:
                    what.append("now unique" if y["unique"] else "no longer unique")
            entry["cols"].append({"name": c, "state": "added" if x is None else "removed" if y is None else "changed",
                                  "props": y or x, "what": what})
        for kind in ("checks", "uniques"):
            bk, ak = (b or empty_table())[kind], (a or empty_table())[kind]
            for k in set(bk) | set(ak):
                if bk.get(k) != ak.get(k):
                    entry[kind].append({"name": k, "state": "added" if k not in bk else "removed" if k not in ak else "changed",
                                        "expr": str(ak.get(k) or bk.get(k))})
        out.append(entry)
    return out


# ── JPA entities ──────────────────────────────────────────────────────────────

FIELD = re.compile(r"((?:\s*@[\w.]+(?:\((?:[^()]|\([^()]*\))*\))?\s*)*)\s*(?:private|protected|public)\s+(?!static)(?:final\s+)?"
                   r"(?:@[\w.]+\s+)*([\w<>?,.\s\[\]]+?)\s+(\w+)\s*(?:=[^;]*)?;")


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def entity_of(text):
    if not re.search(r"@Entity\b", text):
        return None
    cls = re.search(r"\bclass\s+(\w+)", text)
    table = re.search(r"@Table\s*\([^)]*name\s*=\s*\"([^\"]+)\"", text)
    fields = {}
    body = text[text.find("{", cls.end()) if cls else 0:]
    for m in FIELD.finditer(body):
        ann, typ, name = m.group(1) or "", " ".join(m.group(2).split()), m.group(3)
        if "@Transient" in ann:
            continue
        col = re.search(r"@(?:Join)?Column\s*\([^)]*name\s*=\s*\"([^\"]+)\"", ann)
        rel = re.search(r"@(ManyToOne|OneToOne|OneToMany|ManyToMany|ElementCollection|Embedded)", ann)
        fields[name] = {"type": typ, "column": (col.group(1) if col else snake(name) + ("_id" if rel and rel.group(1) in ("ManyToOne", "OneToOne") else "")).lower(),
                        "relation": rel.group(1) if rel else "", "nullable": "nullable = false" not in ann and "nullable=false" not in ann,
                        "annotations": sorted(set(re.findall(r"@(\w+)", ann)))}
    name = cls.group(1) if cls else "?"
    return {"class": name, "table": (table.group(1) if table else snake(re.sub(r"Entity$", "", name))).lower(), "fields": fields}


def changed_files(repo, base):
    out = git(repo, "diff", "--name-status", base).splitlines()
    out += [f"A\t{f}" for f in git(repo, "ls-files", "--others", "--exclude-standard").splitlines()]
    files = {}
    for line in out:
        parts = line.split("\t")
        if len(parts) >= 2:
            files[parts[-1]] = parts[0][0]
    return files


def diff_entities(repo, base, files, schema_after):
    out = []
    for f, st in files.items():
        if not f.endswith(".java") or "/test/" in f:
            continue
        before = entity_of(read_at(repo, f, base)) if st != "A" else None
        after = entity_of(read_at(repo, f)) if st != "D" else None
        if not before and not after:
            continue
        e = after or before
        bf, af = (before or {}).get("fields", {}), (after or {}).get("fields", {})
        fields = []
        for n in list(af) + [n for n in bf if n not in af]:
            x, y = bf.get(n), af.get(n)
            if x == y:
                continue
            what = []
            if x and y:
                if x["type"] != y["type"]:
                    what.append(f"type {x['type']} -> {y['type']}")
                if x["nullable"] != y["nullable"]:
                    what.append("now required" if not y["nullable"] else "now optional")
                if x["column"] != y["column"]:
                    what.append(f"column {x['column']} -> {y['column']}")
            fields.append({"name": n, "state": "added" if x is None else "removed" if y is None else "changed",
                           "type": (y or x)["type"], "column": (y or x)["column"], "what": what})
        warnings = []
        cols = schema_after.get(e["table"], {}).get("cols") if schema_after else None
        if after and cols is not None:
            for n, fl in af.items():
                if fl["relation"] in ("OneToMany", "ManyToMany", "ElementCollection", "Embedded"):
                    continue
                if fl["column"] not in cols and n in {x["name"] for x in fields}:
                    warnings.append(f"field {n} maps to column {fl['column']}, which the migrations do not create")
        if fields or warnings or not before or not after:
            out.append({"class": e["class"], "table": e["table"], "file": f,
                        "state": "new" if not before else "removed" if not after else "changed",
                        "fields": fields, "warnings": warnings})
    return out


# ── impact across the repo ────────────────────────────────────────────────────

LAYERS = [("tests", r"(^|/)src/test/|Test\.java$|IT\.java$|\.spec\.|\.test\."),
          ("API", r"(Controller|Resource|Endpoint)\w*\.java$"), ("API spec", r"openapi|swagger"),
          ("service", r"Service\w*\.java$|UseCase\w*\.java$"), ("repository", r"(Repository|Dao)\w*\.java$"),
          ("mapper", r"Mapper\w*\.java$"), ("contract", r"(Dto|Request|Response|Payload|Command|Event)\w*\.java$"),
          ("entity", r"Entity\w*\.java$"), ("SQL", r"\.sql$"), ("frontend", r"\.(ts|tsx|vue|js)$")]


def layer(path):
    for name, pat in LAYERS:
        if re.search(pat, path, re.I):
            return name
    return "other"


def module_of(path, root):
    if root and path.startswith(root):
        rest = path[len(root):].lstrip("/").split("/")
        return rest[0] if len(rest) > 1 else "(root package)"
    if "/src/test/" in "/" + path:
        return "tests"
    return path.split("/")[0] if "/" in path else "(repo root)"


def java_root(repo):
    dirs = [os.path.dirname(p) for p in git(repo, "ls-files", "*.java").split() if "src/main/java/" in p]
    if not dirs:
        return ""
    common = os.path.commonpath(dirs)
    return common


def impact(repo, schema_diff, entities, files):
    terms = {}
    for t in schema_diff:
        terms.setdefault(t["table"], {"kind": "table", "state": t["state"]})
    for e in entities:
        terms.setdefault(e["class"], {"kind": "entity", "state": e["state"]})
        for f in e["fields"]:
            if f["state"] == "removed":        # code still calling a removed field's getter breaks
                terms.setdefault("get" + f["name"][:1].upper() + f["name"][1:], {"kind": "removed field", "state": "removed"})
    root = java_root(repo)
    mig = set(migration_files(repo))
    hits = {}
    for term, meta in terms.items():
        out = git(repo, "grep", "-l", "-w", "-I", term, "--", ".", ":!*.md")
        for path in out.split():
            if path in mig:
                continue
            if meta["kind"] == "entity" and any(e["file"] == path and e["class"] == term for e in entities):
                continue
            hits.setdefault(path, set()).add(term)
    modules = {}
    for path, ts in hits.items():
        m = module_of(path, root)
        mod = modules.setdefault(m, {"files": [], "layers": {}, "terms": set()})
        mod["files"].append({"path": path, "layer": layer(path), "terms": sorted(ts), "changed": path in files})
        mod["layers"][layer(path)] = mod["layers"].get(layer(path), 0) + 1
        mod["terms"] |= ts
    for mod in modules.values():
        mod["terms"] = sorted(mod["terms"])
        mod["untouched"] = sum(1 for f in mod["files"] if not f["changed"])
    return {"terms": terms, "modules": dict(sorted(modules.items(), key=lambda kv: -len(kv[1]["files"])))}


def endpoints(repo, base):
    out = []
    diff = git(repo, "diff", "-U0", base, "--", "*.java")
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line[:1] in "+-" and not line.startswith(("+++", "---")):
            m = MAPPING.search(line)
            if m:
                out.append({"change": "added" if line[0] == "+" else "removed", "verb": m.group(1).upper(),
                            "args": (m.group(3) or "").strip(), "file": current})
    return out


def rule_candidates(repo, base, files):
    """Diff hunks in main code whose changed lines look like rules; only those lines are kept."""
    out = []
    diff = git(repo, "diff", "-U0", base, "--", "*.java", "*.kt", "*.ts", ":!*/test/*", ":!*Test.java")
    current, hunk, new_no, enums = "", None, 0, {}
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
            if current not in enums:
                enums[current] = bool(re.search(r"\benum\s+\w+", read_at(repo, current)))
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_no = int(m.group(1)) if m else 0
            hunk = {"file": current, "line": 0, "before": [], "after": []}
            out.append(hunk)
        elif hunk is not None and line[:1] in "+-" and not line.startswith(("+++", "---")):
            text = line[1:].strip()
            if text.startswith(("*", "//", "/*")):          # javadoc and comments describe rules, they are not rules
                continue
            is_rule = RULE_LINE.search(text) or (enums.get(current) and re.match(r"[A-Z][A-Z0-9_]+\s*[(,;]", text))
            if is_rule:
                (hunk["after"] if line[0] == "+" else hunk["before"]).append(text)
                if line[0] == "+" and not hunk["line"]:
                    hunk["line"] = new_no
            if line[0] == "+":
                new_no += 1
    keep = [h for h in out if h["before"] or h["after"]]
    for h in keep:
        h["line"] = h["line"] or 1
        h["before"], h["after"] = h["before"][:6], h["after"][:6]
    return keep[:25]


def schema_rules(schema_diff):
    out = []
    for t in schema_diff:
        for c in t["cols"]:
            for w in c["what"]:
                if w.startswith(("now required", "now optional", "default", "now unique", "no longer unique")):
                    out.append({"where": f"{t['table']}.{c['name']}", "what": w})
            if c["state"] == "added" and c["props"]["notnull"] and t["state"] == "changed":   # a new table's columns are just its shape
                out.append({"where": f"{t['table']}.{c['name']}", "what": "new required column"
                            + (f" (default {c['props']['default']})" if c["props"]["default"] else ", no default: existing rows need a value")})
        for k in t["checks"] + t["uniques"]:
            out.append({"where": t["table"], "what": f"{k['state']} constraint: {k['expr']}"})
    return out


def collect(repo, base_ref):
    repo = git(repo, "rev-parse", "--show-toplevel", check=True).strip()
    base = git(repo, "merge-base", "HEAD", base_ref, check=True).strip()
    before, after = schema_at(repo, base), schema_at(repo)
    sdiff = diff_schema(before, after)
    files = changed_files(repo, base)
    ents = diff_entities(repo, base, files, after)
    return {"repo": repo, "base": base_ref, "base_sha": base[:10], "schema": sdiff, "entities": ents,
            "schema_after": {t["table"]: after.get(t["table"]) or before.get(t["table"]) for t in sdiff},
            "impact": impact(repo, sdiff, ents, files), "endpoints": endpoints(repo, base),
            "rule_candidates": rule_candidates(repo, base, files), "schema_rules": schema_rules(sdiff),
            "changed_files": len(files)}


# ── drawing ───────────────────────────────────────────────────────────────────

E = html.escape


def mm(text):
    return re.sub(r"[^A-Za-z0-9_]", "_", text) or "x"


def er_diagram(d):
    lines = ["erDiagram"]
    shown = set()
    for t in d["schema"]:
        if t["state"] == "dropped":
            continue
        table = d["schema_after"].get(t["table"]) or empty_table()
        marks = {c["name"]: c["state"] for c in t["cols"]}
        lines.append(f"  {mm(t['table'])} {{")
        cols = dict(table["cols"])
        for c in t["cols"]:
            if c["state"] == "removed":
                cols[c["name"]] = c["props"]
        hidden = 0
        for name, p in cols.items():
            if t["state"] == "changed" and not (p["pk"] or p["fk"] or name in marks):
                hidden += 1                    # a changed table shows its keys and what changed
                continue
            raw = p["type"].split("(")[0].split()[0] if p["type"] != "?" else "col"
            typ = mm(raw.replace("[]", "_array"))
            key = " PK" if p["pk"] else " FK" if p["fk"] else ""
            note = {"added": "NEW", "removed": "REMOVED", "changed": "CHANGED"}.get(marks.get(name, ""), "")
            lines.append(f"    {typ} {mm(name)}{key}" + (f' "{note}"' if note else ""))
        if hidden:
            lines.append(f'    more unchanged_columns "{hidden} not shown"')
        lines.append("  }")
        shown.add(t["table"])
    for t in d["schema"]:
        table = d["schema_after"].get(t["table"]) or empty_table()
        for name, p in table["cols"].items():
            if p["fk"]:
                lines.append(f'  {mm(p["fk"])} ||--o{{ {mm(t["table"])} : "{mm(name)}"')
    return "\n".join(lines) if shown else ""


def impact_flow(d):
    mods = list(d["impact"]["modules"].items())[:12]
    if not mods:
        return ""
    lines = ["flowchart LR"]
    for term, meta in d["impact"]["terms"].items():
        shape = f'[("{E(term)}")]' if meta["kind"] == "table" else f'["{E(term)}"]'
        lines.append(f"  T_{mm(term)}{shape}")
    for name, mod in mods:
        layers = ", ".join(f"{k} {v}" for k, v in sorted(mod["layers"].items(), key=lambda kv: -kv[1]))
        lines.append(f'  M_{mm(name)}["{E(name)}<br/>{len(mod["files"])} files: {E(layers)}"]')
        for term in mod["terms"]:
            lines.append(f"  T_{mm(term)} --> M_{mm(name)}")
    return "\n".join(lines)


STYLE = """<style>
.guild-impact{--gi-ok:var(--ok,#7dcfa0);--gi-bad:var(--bad,#f7768e);--gi-warn:#e0af68;--gi-accent:var(--accent,#7aa2f7);
  --gi-card:var(--card,#161922);--gi-line:var(--line,#242835);--gi-dim:var(--dim,#9aa3b8)}
.guild-impact h2{margin-top:36px}
.guild-impact .gi-stats{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 18px}
.guild-impact .gi-stat{background:var(--gi-card);border:1px solid var(--gi-line);border-radius:8px;padding:6px 12px;font-size:13px}
.guild-impact .gi-stat b{font-size:18px;margin-right:4px}
.guild-impact .gi-tables{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(380px,1fr))}
.guild-impact .gi-table{background:var(--gi-card);border:1px solid var(--gi-line);border-radius:10px;padding:10px 12px}
.guild-impact .gi-table h3{margin:0 0 8px;font-size:14px;font-family:ui-monospace,Menlo,monospace}
.guild-impact .gi-cols{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.guild-impact .gi-cols ul{list-style:none;margin:0;padding:0;font:12.5px/1.7 ui-monospace,Menlo,monospace}
.guild-impact .gi-cols h4{margin:0 0 4px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--gi-dim)}
.guild-impact .gi-add{color:var(--gi-ok)} .guild-impact .gi-del{color:var(--gi-bad);text-decoration:line-through}
.guild-impact .gi-chg{color:var(--gi-warn)} .guild-impact .gi-why{color:var(--gi-dim);font-size:11.5px;display:block;padding-left:14px}
.guild-impact .gi-badge{font-size:10px;text-transform:uppercase;letter-spacing:.05em;border-radius:4px;padding:1px 6px;margin-left:6px;border:1px solid currentColor}
.guild-impact .gi-alert{border-left:3px solid var(--gi-warn);background:var(--gi-card);padding:10px 14px;border-radius:0 8px 8px 0;margin:10px 0}
.guild-impact .gi-alert.bad{border-color:var(--gi-bad)}
.guild-impact table{border-collapse:collapse;width:100%;font-size:13px}
.guild-impact th,.guild-impact td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--gi-line);vertical-align:top}
.guild-impact th{color:var(--gi-dim)}
.guild-impact .gi-code{font:12px/1.5 ui-monospace,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
.guild-impact td code{overflow-wrap:anywhere}
.guild-impact .gi-code .gi-del{text-decoration:none}
.guild-impact details{margin:6px 0}
.guild-impact summary{cursor:pointer;color:var(--gi-dim)}
.guild-impact .gi-bar{display:inline-block;height:8px;border-radius:4px;background:var(--gi-accent);vertical-align:middle;margin-right:6px}
</style>"""


def render(d, rules=None):
    rules = rules or {}
    explained = rules.get("rules", []) if isinstance(rules, dict) else rules
    note = rules.get("note", "") if isinstance(rules, dict) else ""
    cols = [c for t in d["schema"] for c in t["cols"]]
    count = lambda s: sum(1 for c in cols if c["state"] == s)
    mods = d["impact"]["modules"]
    unexplained = 0 if (explained or note) else len(d["rule_candidates"]) + len(d["schema_rules"])
    stats = [("tables", len(d["schema"])), ("columns added", count("added")), ("removed", count("removed")),
             ("changed", count("changed")), ("entities", len(d["entities"])), ("modules touched", len(mods)),
             ("endpoints changed", len(d["endpoints"])), ("rules explained", len(explained))] + (
             [("rules to explain", unexplained)] if unexplained else [])
    out = [f'<section class="guild-impact" data-unexplained="{unexplained}">', STYLE,
           f'<h2>Data model changes</h2><p class="lead">Compared with <code>{E(d["base"])}</code> '
           f'(merge base <code>{E(d["base_sha"])}</code>), by replaying every migration on both sides.</p>',
           '<div class="gi-stats">' + "".join(f'<span class="gi-stat"><b>{v}</b>{E(k)}</span>' for k, v in stats) + "</div>"]
    if not d["schema"] and not d["entities"]:
        out.append("<p>No schema or entity change.</p>")
    er = er_diagram(d)
    if er:
        out.append(f'<pre class="mermaid">\n{E(er)}\n</pre>')
    if d["schema"]:
        out.append('<div class="gi-tables">')
        for t in d["schema"]:
            marks = {c["name"]: c for c in t["cols"]}
            fold = t["state"] == "changed" and len(t["after"]) > 8
            li = lambda n, side: _col_li(n, marks.get(n), side, fold)
            badge = {"new": "gi-add", "dropped": "gi-del", "changed": "gi-chg"}[t["state"]]
            same = sum(1 for n in t["after"] if n not in marks)
            tail = f'<li class="gi-why" style="padding:0">{same} unchanged columns</li>' if fold else ""
            out.append(f'<div class="gi-table"><h3>{E(t["table"])}<span class="gi-badge {badge}">{t["state"]}</span></h3>'
                       f'<div class="gi-cols"><div><h4>Before</h4><ul>{"".join(li(n, "before") for n in t["before"]) or ("" if t["before"] else "<li>(none)</li>")}{tail}</ul></div>'
                       f'<div><h4>After</h4><ul>{"".join(li(n, "after") for n in t["after"]) or ("" if t["after"] else "<li>(dropped)</li>")}{tail}</ul></div></div>')
            for k in t["checks"] + t["uniques"]:
                out.append(f'<div class="gi-why">{k["state"]} constraint: <code>{E(k["expr"])}</code></div>')
            out.append("</div>")
        out.append("</div>")
    for e in d["entities"]:
        rows = "".join(f'<li class="gi-{ {"added": "add", "removed": "del", "changed": "chg"}[f["state"]] }">'
                       f'{E(f["name"])}: {E(f["type"])} <span class="gi-why">{E("; ".join(f["what"]) or "column " + f["column"])}</span></li>'
                       for f in e["fields"])
        out.append(f'<details open><summary>Entity <code>{E(e["class"])}</code> ({e["state"]}, table <code>{E(e["table"])}</code>)</summary>'
                   f'<ul class="gi-cols" style="display:block">{rows or "<li>no field change</li>"}</ul></details>')
        for w in e["warnings"]:
            out.append(f'<div class="gi-alert bad">{E(e["class"])}: {E(w)}</div>')

    out.append("<h2>Impact on the rest of the project</h2>")
    if mods:
        flow = impact_flow(d)
        out.append('<p class="lead">Every place outside the migrations that names a changed table, entity or removed field. '
                   'Files this change did not touch are the ones to double check.</p>')
        if flow:
            out.append(f'<pre class="mermaid">\n{E(flow)}\n</pre>')
        top = max(len(m["files"]) for m in mods.values())
        out.append("<table><tr><th>Module</th><th>Files</th><th>Layers</th><th>Not touched by this change</th><th>Uses</th></tr>")
        for name, m in mods.items():
            layers = ", ".join(f"{k} {v}" for k, v in sorted(m["layers"].items(), key=lambda kv: -kv[1]))
            files = "".join(f'<li><code>{E(f["path"])}</code> <span class="gi-why">{E(f["layer"])}{" · changed here" if f["changed"] else ""}</span></li>' for f in m["files"])
            out.append(f'<tr><td><b>{E(name)}</b><details><summary>files</summary><ul>{files}</ul></details></td>'
                       f'<td><span class="gi-bar" style="width:{max(6, 80 * len(m["files"]) // top)}px"></span>{len(m["files"])}</td>'
                       f'<td>{E(layers)}</td><td class="{"gi-chg" if m["untouched"] else ""}">{m["untouched"]}</td>'
                       f'<td>{E(", ".join(m["terms"]))}</td></tr>')
        out.append("</table>")
    else:
        out.append("<p>Nothing outside this change refers to what changed.</p>")
    if d["endpoints"]:
        out.append("<h3>Endpoints</h3><table><tr><th></th><th>Verb</th><th>Mapping</th><th>File</th></tr>")
        for p in d["endpoints"]:
            cls = "gi-add" if p["change"] == "added" else "gi-del"
            out.append(f'<tr><td class="{cls}">{p["change"]}</td><td>{p["verb"]}</td><td><code>{E(p["args"])}</code></td><td><code>{E(p["file"])}</code></td></tr>')
        out.append("</table>")

    out.append("<h2>Business rule changes</h2>")
    if explained:
        out.append("<table><tr><th>Rule</th><th>Before</th><th>After</th><th>Where</th><th>Why</th></tr>")
        for r in explained:
            out.append(f'<tr><td><b>{E(r.get("rule", ""))}</b></td><td class="gi-del" style="text-decoration:none">{E(r.get("before", ""))}</td>'
                       f'<td class="gi-add">{E(r.get("after", ""))}</td><td><code>{E(r.get("where", ""))}</code></td><td>{E(r.get("why", ""))}</td></tr>')
        out.append("</table>")
    if note:
        out.append(f'<p>{E(note)}</p>')
    if unexplained:
        out.append(f'<div class="gi-alert bad">{unexplained} possible rule changes are not explained yet. '
                   "The adventurer must say in plain words what each one means for the business (a rules file).</div>")
    if d["schema_rules"]:
        out.append("<h3>Rules the database now enforces</h3><table><tr><th>Where</th><th>Change</th></tr>"
                   + "".join(f'<tr><td><code>{E(r["where"])}</code></td><td>{E(r["what"])}</td></tr>' for r in d["schema_rules"]) + "</table>")
    if d["rule_candidates"]:
        out.append(f'<details{" open" if unexplained else ""}><summary>{len(d["rule_candidates"])} code changes that touch validation, conditions or errors</summary>'
                   "<table><tr><th>Where</th><th>Before</th><th>After</th></tr>")
        for h in d["rule_candidates"]:
            b = "\n".join(E(x) for x in h["before"]) or "(nothing)"
            a = "\n".join(E(x) for x in h["after"]) or "(removed)"
            out.append(f'<tr><td><code>{E(h["file"])}:{h["line"]}</code></td><td><pre class="gi-code gi-del">{b}</pre></td>'
                       f'<td><pre class="gi-code gi-add">{a}</pre></td></tr>')
        out.append("</table></details>")
    if not (explained or d["schema_rules"] or d["rule_candidates"]):
        out.append("<p>No business rule change found.</p>")
    out.append("</section>")
    return "\n".join(out)


def _col_li(name, change, side, fold=False):
    if not change:
        return "" if fold else f"<li>{E(name)}</li>"
    st = change["state"]
    if st == "added" and side == "before" or st == "removed" and side == "after":
        return ""
    cls = {"added": "gi-add", "removed": "gi-del", "changed": "gi-chg"}[st]
    mark = {"added": "+ ", "removed": "- ", "changed": "~ "}[st]
    why = f'<span class="gi-why">{E("; ".join(change["what"]))}</span>' if change["what"] and side == "after" else ""
    return f'<li class="{cls}">{mark}{E(name)} <span class="gi-why" style="display:inline;padding:0">{E(change["props"]["type"])}</span>{why}</li>'


def load_rules(path):
    if not path:
        return {}
    data = json.load(open(path))
    return data if isinstance(data, dict) else {"rules": data}


def main():
    args = sys.argv[1:]
    rules_path = out_path = None
    if "--rules" in args:
        i = args.index("--rules"); rules_path = args[i + 1]; del args[i:i + 2]
    if "--out" in args:
        i = args.index("--out"); out_path = args[i + 1]; del args[i:i + 2]
    if not args:
        raise SystemExit(__doc__)
    cmd = args[0]
    if cmd == "into":
        page, repo, base = args[1], args[2], args[3]
        section = render(collect(repo, base), load_rules(rules_path))
        text = open(page).read()
        text = re.sub(r'<section class="guild-impact".*?</section>', "", text, flags=re.S)   # a rerun replaces it
        if "<!--GUILD-IMPACT-->" in text:
            text = text.replace("<!--GUILD-IMPACT-->", "<!--GUILD-IMPACT-->\n" + section, 1)
        elif "</body>" in text:
            text = text.replace("</body>", section + "\n</body>", 1)
        else:
            text += section
        if "mermaid.min.js" not in text:
            text = text.replace("</body>", '<script src="/vendor/mermaid.min.js"></script>\n<script>if(window.mermaid){mermaid.initialize({startOnLoad:true,theme:matchMedia("(prefers-color-scheme: dark)").matches?"dark":"neutral",securityLevel:"strict"})}</script>\n</body>', 1)
        open(page, "w").write(text)
        print(f"impact section written into {page}")
        return
    repo, base = args[1], args[2]
    d = collect(repo, base)
    if cmd == "json":
        print(json.dumps(d, indent=1, default=list))
    elif cmd == "detect":
        flags = []
        if d["schema"] or d["entities"]:
            flags.append("model")
        if d["rule_candidates"] or d["schema_rules"]:
            flags.append("rules")
        print(" ".join(flags))
        sys.exit(0 if flags else 1)
    elif cmd == "build":
        section = render(d, load_rules(rules_path))
        if out_path:
            open(out_path, "w").write(section)
            print(out_path)
        else:
            print(section)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
