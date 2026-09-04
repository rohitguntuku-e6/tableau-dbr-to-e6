# tableau-dbr-to-e6

Two standalone scripts for moving Tableau content from Databricks to
[e6data](https://www.e6data.com/), which speaks the PostgreSQL wire protocol.

Both are dependency-light: `twb_dbr_to_e6_conn_only_tdsx_handle.py` is stdlib only,
`tab_publish.py` needs `requests`.

## `twb_dbr_to_e6_conn_only_tdsx_handle.py`

Rewrites the **connections only** in a `.twb` / `.twbx` / `.tds` / `.tdsx`, leaving
Custom SQL untouched.

It edits the raw XML text rather than reparsing it, so the `user:` namespace and user
filters, the `_.fcp.*` object model, CDATA sections and comments all stay byte-identical
— a reparse-and-serialise round trip tends to corrupt these.

For each `<named-connection>` containing `<connection class='databricks'>` it:

- rebuilds the inner connection as PostgreSQL
- renames the connection id `databricks.*` → `postgres.*` and repoints every
  `<relation connection=...>` reference to match, so no Replace Data Source and no
  field re-mapping is needed
- injects `CAP_CREATE_TEMP_TABLES='no'` (plus `CAP_SELECT_INTO`, `CAP_INDEX_TEMP_TABLES`)
  to force Tableau to inline, since e6data has no temp tables

```bash
# see what would change, write nothing
python twb_dbr_to_e6_conn_only_tdsx_handle.py --in book.twbx --report-only

# migrate
python twb_dbr_to_e6_conn_only_tdsx_handle.py \
    --in book.twbx --out book_e6.twbx \
    --server my-host.e6data.example --dbname mydb --username myuser
```

Connection parameters can also come from a JSON file via `--config`. Defaults are
placeholders (`YOUR_E6_PG_HOST` and friends); the script warns if you leave them.

## `tab_publish.py`

Publishes a `.tds` / `.tdsx` / `.twb` / `.twbx` to Tableau Cloud or Tableau Server
through the REST API, optionally embedding connection credentials. Cloud and Server
behave identically — only `--host` and `--site` differ. Auth is a Personal Access Token.

```bash
# list projects
python tab_publish.py --host https://<pod>.online.tableau.com --site mysite \
    --token-name my-token --token-secret 'SECRET' --list-projects

# publish with embedded database credentials
python tab_publish.py --host https://<pod>.online.tableau.com --site mysite \
    --token-name my-token --token-secret 'SECRET' \
    --file book_e6.twbx --project 'my-project' --name book_e6 \
    --db-username USER --db-password 'PASS' --overwrite
```

Files above 64 MB need Tableau's chunked `/fileUploads` endpoint, which this script
does not implement — it exits with a clear message rather than failing mid-upload.

## Notes

No credentials are stored in either script; everything is passed on the command line or
through a config file you supply. Secrets given as CLI arguments are visible to other
users on the same machine via the process list, so prefer a restricted-permission
config file on shared hosts.
