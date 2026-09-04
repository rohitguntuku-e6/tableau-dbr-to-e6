# tableau-dbr-to-e6

Command-line tools for migrating Tableau content from Databricks to
[e6data](https://www.e6data.com/), which speaks the PostgreSQL wire protocol.

Supported Tableau file formats:

| Extension | Format |
|---|---|
| `.twb` | Tableau Workbook |
| `.twbx` | Tableau Packaged Workbook |
| `.tds` | Tableau Data Source |
| `.tdsx` | Tableau Packaged Data Source |

## Installation

```bash
pip install -r requirements.txt
```

Python 3.8 or later. `twb_dbr_to_e6_conn_only_tdsx_handle.py` uses only the standard
library; `tab_publish.py` requires `requests`.

## `twb_dbr_to_e6_conn_only_tdsx_handle.py`

Rewrites the connection definitions in a `.twb` (Tableau Workbook), `.twbx` (Tableau
Packaged Workbook), `.tds` (Tableau Data Source) or `.tdsx` (Tableau Packaged Data
Source), leaving all Custom SQL unchanged.

The file is edited as raw XML text rather than being reparsed and re-serialised, so the
`user:` namespace and user filters, the `_.fcp.*` object model, CDATA sections and
comments are preserved byte-for-byte.

For each `<named-connection>` containing `<connection class='databricks'>` the script:

- rebuilds the inner connection as PostgreSQL
- renames the connection identifier from `databricks.*` to `postgres.*` and repoints
  every `<relation connection=...>` reference to match, removing the need for Replace
  Data Source or any field re-mapping
- sets connection capability flags so Tableau inlines its queries; pass
  `--allow-temp-tables` to skip this step

### Usage

```bash
python twb_dbr_to_e6_conn_only_tdsx_handle.py \
    --in workbook.twbx \
    --out workbook_migrated.twbx \
    --server my-host.example.com \
    --dbname mydb \
    --username myuser
```

Connection parameters may also be supplied from a JSON file with `--config`. Run with
`--report-only` to analyse the input and print the intended changes without writing
output.

| Option | Description |
|---|---|
| `--in` | Input file (required) |
| `--out` | Output file (required unless `--report-only`) |
| `--config` | JSON file of connection parameters |
| `--server`, `--port`, `--dbname`, `--username`, `--sslmode` | Connection overrides |
| `--rename-prefix` | Prefix for renamed connection identifiers (default `postgres`) |
| `--allow-temp-tables` | Do not set the connection capability flags |
| `--report-only` | Analyse only; write nothing |

## `tab_publish.py`

Publishes a `.tdsx` (Tableau Packaged Data Source) to Tableau Cloud or Tableau Server
through the REST API, optionally embedding the database connection credentials.

Cloud and Server behave identically; only `--host` and `--site` differ. Authentication
uses a Personal Access Token.

### Usage

List the projects available on a site:

```bash
python tab_publish.py \
    --host https://<pod>.online.tableau.com \
    --site mysite \
    --token-name my-token \
    --token-secret 'SECRET' \
    --list-projects
```

Publish with embedded database credentials:

```bash
python tab_publish.py \
    --host https://<pod>.online.tableau.com \
    --site mysite \
    --token-name my-token \
    --token-secret 'SECRET' \
    --file datasource.tdsx \
    --project 'my-project' \
    --name datasource \
    --db-username USER \
    --db-password 'PASS' \
    --overwrite
```

| Option | Description |
|---|---|
| `--host` | Tableau Cloud pod or Tableau Server URL (required) |
| `--site` | Site content URL; omit for the default site |
| `--token-name`, `--token-secret` | Personal Access Token (required) |
| `--file` | File to publish |
| `--project` / `--project-id` | Target project by name or identifier |
| `--name` | Published name (defaults to the file stem) |
| `--db-username`, `--db-password` | Connection credentials to embed |
| `--no-embed` | Store credentials without embedding them |
| `--overwrite` | Replace existing content of the same name |
| `--list-projects` | List projects and exit |

Files larger than 64 MB require Tableau's chunked `/fileUploads` endpoint, which is not
implemented here; the script reports this and exits rather than failing mid-upload.

## Credentials

Neither script stores credentials. All values are supplied per invocation, either as
command-line arguments or through a configuration file. On shared hosts, prefer a
configuration file with restricted permissions, since command-line arguments are visible
to other users through the process list.
