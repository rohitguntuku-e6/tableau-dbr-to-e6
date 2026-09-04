# tableau-dbr-to-e6

Command-line tools for migrating Tableau content from Databricks to
[e6data](https://www.e6data.com/), which speaks the PostgreSQL wire protocol.

## Tableau glossary

| Extension | Format |
|---|---|
| `.twb` | Tableau Workbook |
| `.twbx` | Tableau Packaged Workbook |
| `.tds` | Tableau Data Source |
| `.tdsx` | Tableau Packaged Data Source |

## Installation

### 1. Install Python

Python 3.8 or later is required. Check whether it is already present:

```bash
python3 --version
```

If not, install it:

| Platform | Command |
|---|---|
| macOS | `brew install python` |
| Ubuntu / Debian | `sudo apt update && sudo apt install python3 python3-venv python3-pip` |
| RHEL / Fedora | `sudo dnf install python3 python3-pip` |
| Windows | Download from [python.org](https://www.python.org/downloads/) and select **Add Python to PATH** during setup |

### 2. Create a virtual environment

A virtual environment keeps these dependencies isolated from the system Python.

```bash
git clone https://github.com/rohitguntuku-e6/tableau-dbr-to-e6.git
cd tableau-dbr-to-e6

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

The shell prompt is prefixed with `(.venv)` once the environment is active. Run
`deactivate` to leave it, and re-run the `activate` command in any new shell.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## `twb_dbr_to_e6_conn_only_tdsx_handle.py`

Rewrites the connection definitions in a `.twb` (Tableau Workbook), `.twbx` (Tableau
Packaged Workbook), `.tds` (Tableau Data Source) or `.tdsx` (Tableau Packaged Data
Source), leaving all Custom SQL unchanged.

For each `<named-connection>` containing `<connection class='databricks'>` the script:

- rebuilds the inner connection as PostgreSQL
- renames the connection identifier from `databricks.*` to `postgres.*` and repoints
  every `<relation connection=...>` reference to match, removing the need for Replace
  Data Source or any field re-mapping
- sets connection capability flags so Tableau inlines its queries

### Usage

```bash
python twb_dbr_to_e6_conn_only_tdsx_handle.py \
    --in workbook.twbx \
    --out workbook_migrated.twbx \
    --server my-host.example.com \
    --dbname mydb \
    --username myuser
```

Connection parameters may also be supplied from a JSON file with `--config`.

| Option | Description |
|---|---|
| `--in` | Input file (required) |
| `--out` | Output file (required) |
| `--config` | JSON file of connection parameters |
| `--server`, `--port`, `--dbname`, `--username`, `--sslmode` | e6data connection details |

## `tab_publish.py`

Publishes a `.tdsx` (Tableau Packaged Data Source) to Tableau Cloud or Tableau Server
through the REST API, embedding the database connection credentials.

Authentication uses a Personal Access Token. Only `--host` and `--site` differ between
Cloud and Server:

| Deployment | `--host` |
|---|---|
| Tableau Cloud | `https://<pod>.online.tableau.com` |
| Tableau Server | `https://10.0.0.25` or your server hostname |

### Usage

List the projects available on a site:

```bash
python tab_publish.py \
    --host https://10.0.0.25 \
    --site mysite \
    --token-name my-token \
    --token-secret 'SECRET' \
    --list-projects
```

Publish with embedded database credentials:

```bash
python tab_publish.py \
    --host https://10.0.0.25 \
    --site mysite \
    --token-name my-token \
    --token-secret 'SECRET' \
    --file datasource.tdsx \
    --project 'my-project' \
    --name datasource \
    --db-username 'USER' \
    --db-password 'PASSWORD' \
    --overwrite
```

| Option | Description |
|---|---|
| `--host` | Tableau Cloud or Tableau Server URL (required) |
| `--site` | Site content URL; omit for the default site |
| `--token-name`, `--token-secret` | Personal Access Token (required) |
| `--file` | File to publish |
| `--project` / `--project-id` | Target project by name or identifier |
| `--name` | Published name (defaults to the file stem) |
| `--db-username`, `--db-password` | Connection credentials to embed |
| `--overwrite` | Replace existing content of the same name |
| `--list-projects` | List projects and exit |
