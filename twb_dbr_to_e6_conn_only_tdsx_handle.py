#!/usr/bin/env python3
"""
twb_dbr_to_e6_conn_only.py — migrate a Tableau workbook's CONNECTIONS ONLY from
Databricks to e6data (PostgreSQL wire protocol) WITHOUT corrupting the file and
WITHOUT touching any Custom SQL.

One surgical operation on the raw .twb text (never an XML reparse, so the
`user:` namespace / user filters, `_.fcp.*` object model, CDATA, and comments
stay byte-identical):

  CONNECTION SWAP — each <named-connection> whose inner <connection
  class='databricks'> is rebuilt as a clean PostgreSQL <connection>. The
  named-connection `name` id is renamed databricks.* -> postgres.* (and every
  <relation connection=...> reference is repointed to match), so no
  Replace-Data-Source, no field re-mapping, no suffix bug. Temp tables are
  disabled via CAP_* capability flags (e6data has no temp tables).

Usage:
    python twb_dbr_to_e6_conn_only.py --in in.twb[x] --out out.twb[x]
        [--config cfg.json] [--server H --dbname D --username U ...]
        [--allow-temp-tables] [--rename-prefix PREFIX] [--report-only]
"""
import argparse
import json
import os
import re
import sys
import zipfile


DEFAULT_CFG = {
    "match_class": "databricks",
    "class": "postgres",
    "server": "YOUR_E6_PG_HOST",
    "port": "5432",
    "dbname": "YOUR_DATABASE",
    "username": "YOUR_USERNAME",
    "sslmode": "require",
    "authentication": "username-password",
    "caption": None,
    "disable_temp_tables": True,        # e6data has no temp tables -> inject CAP_*='no'
    "rename_prefix": "postgres",        # rename named-connection ids databricks.* -> postgres.*
                                        #   (None keeps original ids)
}

# Capability flags that force Tableau to INLINE instead of using temp tables.
TEMP_TABLE_CAPS = [
    ("CAP_CREATE_TEMP_TABLES", "no"),
    ("CAP_SELECT_INTO", "no"),
    ("CAP_INDEX_TEMP_TABLES", "no"),
]


# ===========================================================================
# CONNECTION SWAP (surgical: rebuild only the <named-connection> body)
# ===========================================================================

NAMED_CONN_RE = re.compile(r"<named-connection\b.*?</named-connection>", re.DOTALL)


def _temp_table_customization(cls):
    caps = "".join("<customization name='%s' value='%s' />" % (n, v) for n, v in TEMP_TABLE_CAPS)
    return ("<connection-customization class='{c}' enabled='true' version='18.1'>"
            "<vendor name='{c}' /><driver name='{c}' />"
            "<customizations>{caps}</customizations>"
            "</connection-customization>").format(c=cls, caps=caps)


def _build_pg_connection(cfg):
    attrs = ("authentication='{auth}' class='{cls}' dbname='{db}' one-time-sql='' "
             "port='{port}' server='{srv}' sslmode='{ssl}' username='{user}'").format(
                auth=cfg["authentication"], cls=cfg["class"], db=cfg["dbname"],
                port=cfg["port"], srv=cfg["server"], ssl=cfg["sslmode"], user=cfg["username"])
    if cfg.get("disable_temp_tables", True):
        return ("<connection %s>\n            %s\n          </connection>"
                % (attrs, _temp_table_customization(cfg["class"])))
    return "<connection %s />" % attrs


def swap_connections(text, cfg, log):
    count = [0]
    token = "class='%s'" % cfg["match_class"]
    caption = cfg.get("caption") or cfg["server"]
    prefix = cfg.get("rename_prefix")
    mapping = {}

    def _sub(m):
        block = m.group(0)
        if token not in block:
            return block
        nm = re.search(r"<named-connection\b[^>]*\bname='([^']*)'", block)
        if not nm:
            return block
        old = nm.group(1)
        new = (prefix + "." + old.split(".", 1)[1]) if (prefix and "." in old) else old
        mapping[old] = new
        count[0] += 1
        return ("<named-connection caption='{cap}' name='{name}'>\n"
                "            {conn}\n"
                "          </named-connection>").format(
                    cap=caption, name=new, conn=_build_pg_connection(cfg))

    new = NAMED_CONN_RE.sub(_sub, text)

    # update every <relation connection='OLD'> reference (incl. _.fcp copies) to the renamed id
    refs = 0
    for old, newn in mapping.items():
        if old != newn:
            refs += new.count("'%s'" % old)
            new = new.replace("'%s'" % old, "'%s'" % newn)

    log.append("Repointed %d named-connection(s) class='%s' -> '%s' (%s)"
               % (count[0], cfg["match_class"], cfg["class"], cfg["server"]))
    if prefix:
        log.append("Renamed connection ids -> '%s.*' and updated %d relation reference(s)" % (prefix, refs))
    if cfg.get("disable_temp_tables", True):
        log.append("Injected CAP_CREATE_TEMP_TABLES='no' (+SELECT_INTO,+INDEX_TEMP_TABLES) — temp tables disabled")
    if count[0] == 0:
        log.append("WARNING: no <named-connection> with class='%s' found" % cfg["match_class"])
    stray = len(re.findall(r"<connection\s[^>]*class='%s'" % cfg["match_class"], new))
    if stray:
        log.append("WARNING: %d stray '%s' <connection>(s) remain outside a named-connection"
                   % (stray, cfg["match_class"]))
    return new


# ===========================================================================
# DRIVER
# ===========================================================================

def transform(text, cfg, log):
    # CONNECTION SWAP ONLY — Custom SQL is intentionally left untouched.
    return swap_connections(text, cfg, log)


def process(in_path, out_path, cfg, report_only=False):
    log = []
    ZIP_EXT = (".twbx", ".tdsx")
    DOC_EXT = (".twb", ".tds")

    in_is_zip = in_path.lower().endswith(ZIP_EXT)
    out_is_zip = bool(out_path) and out_path.lower().endswith(ZIP_EXT)

    zin_entries, twb_name = None, None
    if in_is_zip:
        with zipfile.ZipFile(in_path) as zin:
            twbs = [n for n in zin.namelist() if n.lower().endswith(DOC_EXT)]
            if len(twbs) != 1:
                raise SystemExit("Expected exactly one .twb/.tds inside %s, found: %s"
                                 % (os.path.basename(in_path), twbs))
            twb_name = twbs[0]
            text = zin.read(twb_name).decode("utf-8")
            zin_entries = {it.filename: (it, zin.read(it.filename)) for it in zin.infolist()}
    else:
        text = open(in_path, encoding="utf-8").read()

    new = transform(text, cfg, log)
    if report_only:
        return log

    if out_is_zip:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
            if in_is_zip:
                for fname, (it, data) in zin_entries.items():
                    zout.writestr(it, new.encode("utf-8") if fname == twb_name else data)
            else:
                inner = (os.path.splitext(os.path.basename(out_path))[0]
                         + (".tds" if out_path.lower().endswith(".tdsx") else ".twb"))
                zout.writestr(inner, new.encode("utf-8"))
    else:
        if in_is_zip and any(not f.lower().endswith(DOC_EXT) for f in zin_entries):
            log.append("WARNING: input archive had packaged resources; a flat output drops them")
        open(out_path, "w", encoding="utf-8").write(new)
    return log


def load_cfg(args):
    cfg = dict(DEFAULT_CFG)
    if args.config:
        with open(args.config) as f:
            cfg.update(json.load(f))
    for k in ("server", "port", "dbname", "username", "sslmode", "authentication",
              "caption", "match_class"):
        v = getattr(args, k, None)
        if v is not None:
            cfg[k] = v
    if args.allow_temp_tables:
        cfg["disable_temp_tables"] = False
    if args.rename_prefix is not None:
        cfg["rename_prefix"] = args.rename_prefix or None
    return cfg


def main():
    ap = argparse.ArgumentParser(
        description="Migrate a Tableau workbook's CONNECTIONS ONLY from Databricks to e6data (PostgreSQL). Custom SQL is left unchanged.")
    ap.add_argument("--in", dest="in_path", required=True, help="input .twb/.twbx/.tds/.tdsx")
    ap.add_argument("--out", dest="out_path", help="output .twb/.twbx/.tds/.tdsx")
    ap.add_argument("--config", help="JSON connection-param file")
    for k in ("server", "port", "dbname", "username", "sslmode", "authentication",
              "caption", "match_class"):
        ap.add_argument("--%s" % k.replace("_", "-"), dest=k, default=None, help="override %s" % k)
    ap.add_argument("--allow-temp-tables", action="store_true",
                    help="do NOT inject the temp-table-disabling capability (e6data has no temp tables, so default is to disable)")
    ap.add_argument("--rename-prefix", dest="rename_prefix", default=None,
                    help="prefix for renamed connection ids (default postgres; pass '' to keep databricks.* ids)")
    ap.add_argument("--report-only", action="store_true", help="analyze only; write nothing")
    args = ap.parse_args()

    if not os.path.exists(args.in_path):
        raise SystemExit("Input not found: %s" % args.in_path)
    if not args.report_only and not args.out_path:
        raise SystemExit("--out is required unless --report-only")

    cfg = load_cfg(args)
    log = process(args.in_path, args.out_path, cfg, report_only=args.report_only)

    print("=" * 72)
    print("CHANGES (connection swap only — Custom SQL untouched):")
    for c in log:
        print("  - " + c)
    if cfg["server"] == DEFAULT_CFG["server"]:
        print("\nNOTE: connection params are placeholders — set --server/--dbname/etc or --config.")
    if not args.report_only:
        print("\nWrote: %s" % args.out_path)
    print("=" * 72)


if __name__ == "__main__":
    main()
