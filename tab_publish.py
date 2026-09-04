#!/usr/bin/env python3
"""
tab_publish.py — publish a .tds / .tdsx / .twb / .twbx to Tableau Cloud or
Tableau Server via the REST API, with embedded connection credentials.

Works identically against Cloud and Server: only --host and --site change.
Auth is Personal Access Token (required on Cloud, supported on Server).

Examples
--------
List projects:
    python tab_publish.py --host https://prod-apnortheast-a.online.tableau.com \
        --site mysite --token-name e6-migration --token-secret 'XXX' --list-projects

Publish a datasource with embedded Databricks PAT:
    python tab_publish.py --host ... --site mysite \
        --token-name e6-migration --token-secret 'XXX' \
        --file DBR_test_customer.tds --project 'e6-migration-test' \
        --name customer_dbr \
        --db-username token --db-password 'dapiXXXXXXXX'

Publish the migrated workbook with e6 credentials:
    python tab_publish.py --host ... --site mysite \
        --token-name e6-migration --token-secret 'XXX' \
        --file DBR_test_e6.twb --project 'e6-migration-test' \
        --name DBR_test_e6 \
        --db-username XXXXX --db-password 'XXX' --overwrite
"""
import argparse
import os
import sys
import uuid
import xml.etree.ElementTree as ET

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

NS = {"t": "http://tableau.com/api"}
API = "3.23"          # Matches our Tableau Server ceiling (2024.2.x); also accepted by Tableau Cloud. Override with --api.
CHUNK = 64 * 1024 * 1024   # 64 MB — files above this must use the chunked upload endpoint


def _xml(resp):
    if resp.status_code >= 400:
        sys.exit("HTTP %d\n%s" % (resp.status_code, resp.text[:2000]))
    return ET.fromstring(resp.content)


def signin(host, site, tname, tsecret, api):
    body = ("<tsRequest><credentials personalAccessTokenName='%s' "
            "personalAccessTokenSecret='%s'><site contentUrl='%s' /></credentials></tsRequest>"
            % (tname, tsecret, site))
    r = requests.post("%s/api/%s/auth/signin" % (host, api),
                      data=body.encode("utf-8"),
                      headers={"Content-Type": "application/xml"})
    x = _xml(r)
    c = x.find("t:credentials", NS)
    return c.get("token"), c.find("t:site", NS).get("id")


def signout(host, api, token):
    requests.post("%s/api/%s/auth/signout" % (host, api), headers={"X-Tableau-Auth": token})


def projects(host, api, token, site_id):
    out, page = [], 1
    while True:
        r = requests.get("%s/api/%s/sites/%s/projects?pageSize=100&pageNumber=%d"
                         % (host, api, site_id, page),
                         headers={"X-Tableau-Auth": token})
        x = _xml(r)
        batch = x.findall(".//t:project", NS)
        out += [(p.get("id"), p.get("name")) for p in batch]
        pag = x.find("t:pagination", NS)
        if pag is None or page * 100 >= int(pag.get("totalAvailable", 0)):
            break
        page += 1
    return out


def build_payload(kind, name, project_id, db_user, db_pass, embed):
    cred = ""
    if db_user is not None:
        cred = ("<connectionCredentials name=\"%s\" password=\"%s\" embed=\"%s\" />"
                % (db_user, (db_pass or ""), "true" if embed else "false"))
    return ("<tsRequest><{k} name=\"{n}\">{c}<project id=\"{p}\" /></{k}></tsRequest>"
            .format(k=kind, n=name, c=cred, p=project_id))


def publish(host, api, token, site_id, path, kind, name, project_id,
            db_user, db_pass, embed, overwrite):
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    size = os.path.getsize(path)
    if size > CHUNK:
        sys.exit("File is %.1f MB — over the single-request limit; use the chunked "
                 "upload endpoint (/fileUploads) for this one." % (size / 1e6))

    payload = build_payload(kind, name, project_id, db_user, db_pass, embed)
    boundary = uuid.uuid4().hex

    def part(disp, ctype, data):
        return (("--%s\r\nContent-Disposition: %s\r\nContent-Type: %s\r\n\r\n"
                 % (boundary, disp, ctype)).encode("utf-8") + data + b"\r\n")

    body = part('name="request_payload"', "text/xml", payload.encode("utf-8"))
    body += part('name="tableau_%s"; filename="%s"' % (kind, os.path.basename(path)),
                 "application/octet-stream", open(path, "rb").read())
    body += ("--%s--\r\n" % boundary).encode("utf-8")

    url = ("%s/api/%s/sites/%s/%ss?%sType=%s&overwrite=%s"
           % (host, api, site_id, kind, kind, ext, "true" if overwrite else "false"))
    r = requests.post(url, data=body, headers={
        "X-Tableau-Auth": token,
        "Content-Type": "multipart/mixed; boundary=%s" % boundary,
    })
    x = _xml(r)
    node = x.find(".//t:%s" % kind, NS)
    return node.get("id"), node.get("name")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True, help="https://<pod>.online.tableau.com or your Server URL")
    p.add_argument("--site", default="", help="site contentUrl ('' for Default)")
    p.add_argument("--token-name", required=True)
    p.add_argument("--token-secret", required=True)
    p.add_argument("--api", default=API, help="REST API version (default: %(default)s)")
    p.add_argument("--list-projects", action="store_true")
    p.add_argument("--file")
    p.add_argument("--project", help="project name (or use --project-id)")
    p.add_argument("--project-id")
    p.add_argument("--name", help="published name (default: filename stem)")
    p.add_argument("--db-username")
    p.add_argument("--db-password")
    p.add_argument("--no-embed", action="store_true", help="store creds but do not embed")
    p.add_argument("--overwrite", action="store_true")
    a = p.parse_args()

    token, site_id = signin(a.host, a.site, a.token_name, a.token_secret, a.api)
    print("Signed in. site-id=%s" % site_id)
    try:
        if a.list_projects:
            for pid, pname in projects(a.host, a.api, token, site_id):
                print("  %s  %s" % (pid, pname))
            return

        if not a.file:
            sys.exit("--file required unless --list-projects")

        ext = os.path.splitext(a.file)[1].lower()
        if ext in (".tds", ".tdsx"):
            kind = "datasource"
        elif ext in (".twb", ".twbx"):
            kind = "workbook"
        else:
            sys.exit("Unsupported file type: %s" % ext)

        pid = a.project_id
        if not pid:
            if not a.project:
                sys.exit("--project or --project-id required")
            hits = [i for i, n in projects(a.host, a.api, token, site_id) if n == a.project]
            if not hits:
                sys.exit("Project %r not found (try --list-projects)" % a.project)
            pid = hits[0]

        name = a.name or os.path.splitext(os.path.basename(a.file))[0]
        new_id, new_name = publish(a.host, a.api, token, site_id, a.file, kind, name, pid,
                                   a.db_username, a.db_password, not a.no_embed, a.overwrite)
        print("Published %s: %s (id=%s)" % (kind, new_name, new_id))
    finally:
        signout(a.host, a.api, token)


if __name__ == "__main__":
    main()
