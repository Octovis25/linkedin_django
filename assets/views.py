import json
import os
import mimetypes
import requests
from urllib.parse import quote, unquote
from xml.etree import ElementTree

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import render
from django.db import connection
from requests.auth import HTTPBasicAuth

from .nc_folders import NC_ASSETS_ROOT, FOLDER_TREE, ensure_nc_folders


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe(cur, sql, params=None):
    try:
        cur.execute(sql, params or [])
        return cur.fetchall()
    except Exception as e:
        print("Assets SQL:", e)
        return []


def _nc_creds():
    from posts_posted.nc_storage import _get_nc_credentials
    return _get_nc_credentials()


def _nc_base():
    nc_url, username, password = _nc_creds()
    if not all([nc_url, username, password]):
        return None, None, None
    base = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}"
    return base, username, password


# ── DB setup ─────────────────────────────────────────────────────────────────

def _ensure_asset_tables():
    with connection.cursor() as c:
        try:
            c.execute("""
                CREATE TABLE IF NOT EXISTS asset_metadata (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    nc_path VARCHAR(500) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    category VARCHAR(100) DEFAULT '',
                    description TEXT,
                    file_type VARCHAR(20) DEFAULT '',
                    file_size INT DEFAULT 0,
                    is_favorite BOOLEAN DEFAULT FALSE,
                    last_used_at DATETIME DEFAULT NULL,
                    created_at DATETIME DEFAULT NOW(),
                    updated_at DATETIME DEFAULT NOW(),
                    created_by VARCHAR(100) DEFAULT '',
                    UNIQUE KEY uq_nc_path (nc_path)
                )
            """)
        except Exception:
            pass
        try:
            c.execute("""
                CREATE TABLE IF NOT EXISTS asset_tags (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    asset_id INT NOT NULL,
                    tag VARCHAR(100) NOT NULL,
                    UNIQUE KEY uq_asset_tag (asset_id, tag)
                )
            """)
        except Exception:
            pass


# ── NC WebDAV helpers ────────────────────────────────────────────────────────

def _nc_list_folder(folder_path):
    """PROPFIND on NC_ASSETS_ROOT/folder_path. Returns list of file dicts."""
    base, username, password = _nc_base()
    if not base:
        return []

    rel = f"{NC_ASSETS_ROOT}/{folder_path}".rstrip("/") if folder_path else NC_ASSETS_ROOT
    url = f"{base}/{quote(rel, safe='/')}"

    try:
        r = requests.request(
            "PROPFIND", url,
            auth=HTTPBasicAuth(username, password),
            headers={"Depth": "1", "Content-Type": "application/xml"},
            timeout=20,
        )
        if r.status_code not in (207, 200):
            return []
    except Exception:
        return []

    ns = {"d": "DAV:"}
    tree = ElementTree.fromstring(r.content)
    items = []
    base_href = f"/remote.php/dav/files/{username}/{quote(rel, safe='/')}"

    for resp in tree.findall("d:response", ns):
        href = resp.findtext("d:href", "", ns)
        # Skip the folder itself
        if href.rstrip("/") == base_href.rstrip("/"):
            continue

        props = resp.find("d:propstat/d:prop", ns)
        if props is None:
            continue

        is_dir = props.find("d:resourcetype/d:collection", ns) is not None
        ct = props.findtext("d:getcontenttype", "", ns)
        size_text = props.findtext("d:getcontentlength", "0", ns)
        try:
            size = int(size_text)
        except (ValueError, TypeError):
            size = 0

        # Decode the href to get the name
        name = unquote(href.rstrip("/").split("/")[-1])
        nc_path = f"{rel}/{name}"

        items.append({
            "name": name,
            "nc_path": nc_path,
            "is_dir": is_dir,
            "content_type": ct,
            "size": size,
        })

    return items


def _nc_upload_file(file_obj, nc_path):
    """PUT file to Nextcloud. Returns True/False."""
    base, username, password = _nc_base()
    if not base:
        return False
    url = f"{base}/{quote(nc_path, safe='/')}"
    try:
        content = file_obj.read()
        r = requests.put(url, data=content, auth=HTTPBasicAuth(username, password), timeout=60)
        return r.status_code in (200, 201, 204)
    except Exception:
        return False


def _nc_mkdir(nc_path):
    """MKCOL — create folder on Nextcloud. Returns True/False."""
    base, username, password = _nc_base()
    if not base:
        return False
    url = f"{base}/{quote(nc_path, safe='/')}"
    try:
        r = requests.request("MKCOL", url, auth=HTTPBasicAuth(username, password), timeout=15)
        return r.status_code in (201, 405)  # 405 = already exists
    except Exception:
        return False


def _nc_delete(nc_path):
    """DELETE file/folder from Nextcloud."""
    base, username, password = _nc_base()
    if not base:
        return False
    url = f"{base}/{quote(nc_path, safe='/')}"
    try:
        r = requests.delete(url, auth=HTTPBasicAuth(username, password), timeout=15)
        return r.status_code in (200, 204, 404)
    except Exception:
        return False


def _nc_move(src_path, dest_path):
    """MOVE file on Nextcloud."""
    base, username, password = _nc_base()
    if not base:
        return False
    src_url = f"{base}/{quote(src_path, safe='/')}"
    dest_url = f"{base}/{quote(dest_path, safe='/')}"
    try:
        r = requests.request(
            "MOVE", src_url,
            auth=HTTPBasicAuth(username, password),
            headers={"Destination": dest_url, "Overwrite": "F"},
            timeout=15,
        )
        return r.status_code in (200, 201, 204)
    except Exception:
        return False


def _get_or_create_meta(nc_path, name='', file_type='', file_size=0, created_by=''):
    """INSERT IGNORE + SELECT for asset_metadata. Returns dict or None."""
    _ensure_asset_tables()
    with connection.cursor() as c:
        c.execute(
            "INSERT IGNORE INTO asset_metadata (nc_path, name, file_type, file_size, created_by) "
            "VALUES (%s, %s, %s, %s, %s)",
            [nc_path, name, file_type, file_size, created_by],
        )
        rows = _safe(c,
            "SELECT id, nc_path, name, category, description, file_type, file_size, "
            "is_favorite, last_used_at, created_at, updated_at, created_by "
            "FROM asset_metadata WHERE nc_path=%s", [nc_path])
    if not rows:
        return None
    r = rows[0]
    return {
        "id": r[0], "nc_path": r[1], "name": r[2], "category": r[3],
        "description": r[4] or "", "file_type": r[5], "file_size": r[6],
        "is_favorite": bool(r[7]), "last_used_at": str(r[8]) if r[8] else None,
        "created_at": str(r[9]), "updated_at": str(r[10]), "created_by": r[11] or "",
    }


def _get_tags(asset_id):
    with connection.cursor() as c:
        rows = _safe(c, "SELECT tag FROM asset_tags WHERE asset_id=%s ORDER BY tag", [asset_id])
    return [r[0] for r in (rows or [])]


def _set_tags(asset_id, tags_list):
    with connection.cursor() as c:
        c.execute("DELETE FROM asset_tags WHERE asset_id=%s", [asset_id])
        for t in tags_list:
            t = t.strip()
            if t:
                try:
                    c.execute("INSERT IGNORE INTO asset_tags (asset_id, tag) VALUES (%s, %s)", [asset_id, t])
                except Exception:
                    pass


# ── Views ────────────────────────────────────────────────────────────────────

@login_required
def assets_view(request):
    _ensure_asset_tables()
    # Kategorien LIVE aus Nextcloud lesen (nicht mehr aus der festen FOLDER_TREE),
    # damit die Anzeige immer der echten NC-Struktur entspricht.
    items = _nc_list_folder("")
    top_level = sorted(
        [i["name"] for i in items
         if i.get("is_dir") and not i["name"].startswith(".") and i["name"] != "_data"],
        key=str.lower,
    )
    return render(request, "assets/library.html", {"categories": top_level})


@login_required
def assets_api_list(request):
    _ensure_asset_tables()
    folder = request.GET.get("folder", "").strip()
    q = request.GET.get("q", "").strip()
    tag = request.GET.get("tag", "").strip()
    fav_only = request.GET.get("favorites_only", "") == "1"

    # List from NC
    items_raw = _nc_list_folder(folder)
    files = []
    folders = []

    nc_paths_seen = set()

    for item in items_raw:
        if item["is_dir"]:
            folders.append(item)
        else:
            nc_paths_seen.add(item["nc_path"])
            # Enrich with metadata
            ext = os.path.splitext(item["name"])[1].lstrip(".").lower()
            meta = _get_or_create_meta(item["nc_path"], name=item["name"], file_type=ext, file_size=item["size"])
            if meta:
                meta["tags"] = _get_tags(meta["id"])
            else:
                meta = {"nc_path": item["nc_path"], "name": item["name"], "file_type": ext,
                        "file_size": item["size"], "tags": [], "is_favorite": False, "description": ""}

            # Apply filters
            if fav_only and not meta.get("is_favorite"):
                continue
            if tag and tag not in meta.get("tags", []):
                continue
            if q and q.lower() not in item["name"].lower() and q.lower() not in (meta.get("description") or "").lower():
                # Also check tags
                if not any(q.lower() in t.lower() for t in meta.get("tags", [])):
                    continue

            meta["content_type"] = item["content_type"]
            files.append(meta)

    # Lazy cleanup: DB-Einträge löschen deren Dateien auf NC nicht mehr existieren
    if folder is not None:
        rel = f"{NC_ASSETS_ROOT}/{folder}".rstrip("/") if folder else NC_ASSETS_ROOT
        try:
            with connection.cursor() as c:
                c.execute("SELECT id, nc_path FROM asset_metadata WHERE nc_path LIKE %s",
                          [f"{rel}/%"])
                for row in c.fetchall():
                    if row[1] not in nc_paths_seen:
                        c.execute("DELETE FROM asset_tags WHERE asset_id=%s", [row[0]])
                        c.execute("DELETE FROM asset_metadata WHERE id=%s", [row[0]])
        except Exception:
            pass

    return JsonResponse({"items": files, "folders": folders, "path": folder})


@login_required
def assets_api_upload(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    _ensure_asset_tables()
    folder = request.POST.get("folder", "").strip()
    uploaded = []

    for f in request.FILES.getlist("files"):
        rel = f"{NC_ASSETS_ROOT}/{folder}/{f.name}".replace("//", "/") if folder else f"{NC_ASSETS_ROOT}/{f.name}"
        ok = _nc_upload_file(f, rel)
        if ok:
            ext = os.path.splitext(f.name)[1].lstrip(".").lower()
            meta = _get_or_create_meta(rel, name=f.name, file_type=ext, file_size=f.size,
                                       created_by=request.user.username)
            uploaded.append(meta)

    return JsonResponse({"ok": True, "uploaded": uploaded})


@login_required
def assets_api_delete(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    _ensure_asset_tables()
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST
    nc_path = data.get("nc_path", "").strip()
    if not nc_path:
        return JsonResponse({"error": "nc_path required"}, status=400)

    ok = _nc_delete(nc_path)
    if ok:
        with connection.cursor() as c:
            rows = _safe(c, "SELECT id FROM asset_metadata WHERE nc_path=%s", [nc_path])
            if rows:
                c.execute("DELETE FROM asset_tags WHERE asset_id=%s", [rows[0][0]])
            c.execute("DELETE FROM asset_metadata WHERE nc_path=%s", [nc_path])

    return JsonResponse({"ok": ok})


@login_required
def assets_api_move(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    _ensure_asset_tables()
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST
    nc_path = data.get("nc_path", "").strip()
    dest_folder = data.get("dest_folder", "").strip()
    if not nc_path:
        return JsonResponse({"error": "nc_path required"}, status=400)

    name = nc_path.rstrip("/").split("/")[-1]
    dest_path = f"{NC_ASSETS_ROOT}/{dest_folder}/{name}".replace("//", "/") if dest_folder else f"{NC_ASSETS_ROOT}/{name}"

    ok = _nc_move(nc_path, dest_path)
    if ok:
        with connection.cursor() as c:
            c.execute("UPDATE asset_metadata SET nc_path=%s, updated_at=NOW() WHERE nc_path=%s", [dest_path, nc_path])

    return JsonResponse({"ok": ok, "new_path": dest_path})


@login_required
def assets_api_rename(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    _ensure_asset_tables()
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST
    nc_path = data.get("nc_path", "").strip()
    new_name = data.get("new_name", "").strip()
    if not nc_path or not new_name:
        return JsonResponse({"error": "nc_path and new_name required"}, status=400)

    parts = nc_path.rstrip("/").rsplit("/", 1)
    folder_part = parts[0] if len(parts) > 1 else ""
    dest_path = f"{folder_part}/{new_name}" if folder_part else new_name

    ok = _nc_move(nc_path, dest_path)
    if ok:
        ext = os.path.splitext(new_name)[1].lstrip(".").lower()
        with connection.cursor() as c:
            c.execute("UPDATE asset_metadata SET nc_path=%s, name=%s, file_type=%s, updated_at=NOW() WHERE nc_path=%s",
                      [dest_path, new_name, ext, nc_path])

    return JsonResponse({"ok": ok, "new_path": dest_path, "new_name": new_name})


@login_required
def assets_api_update_meta(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    _ensure_asset_tables()
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST
    nc_path = data.get("nc_path", "").strip()
    if not nc_path:
        return JsonResponse({"error": "nc_path required"}, status=400)

    with connection.cursor() as c:
        rows = _safe(c, "SELECT id FROM asset_metadata WHERE nc_path=%s", [nc_path])
        if not rows:
            return JsonResponse({"error": "asset not found"}, status=404)
        asset_id = rows[0][0]

        updates = []
        params = []
        if "description" in data:
            updates.append("description=%s")
            params.append(data["description"])
        if "category" in data:
            updates.append("category=%s")
            params.append(data["category"])
        if updates:
            updates.append("updated_at=NOW()")
            params.append(nc_path)
            c.execute(f"UPDATE asset_metadata SET {', '.join(updates)} WHERE nc_path=%s", params)

        if "tags" in data:
            tags_str = data["tags"]
            tags_list = [t.strip() for t in tags_str.split(",") if t.strip()] if isinstance(tags_str, str) else tags_str
            _set_tags(asset_id, tags_list)

    return JsonResponse({"ok": True})


@login_required
def assets_api_toggle_favorite(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    _ensure_asset_tables()
    data = json.loads(request.body) if request.content_type == "application/json" else request.POST
    nc_path = data.get("nc_path", "").strip()
    if not nc_path:
        return JsonResponse({"error": "nc_path required"}, status=400)

    with connection.cursor() as c:
        rows = _safe(c, "SELECT id, is_favorite FROM asset_metadata WHERE nc_path=%s", [nc_path])
        if not rows:
            return JsonResponse({"error": "asset not found"}, status=404)
        new_val = not bool(rows[0][1])
        c.execute("UPDATE asset_metadata SET is_favorite=%s, updated_at=NOW() WHERE nc_path=%s", [new_val, nc_path])

    return JsonResponse({"ok": True, "is_favorite": new_val})


@login_required
def assets_api_tags(request):
    _ensure_asset_tables()
    with connection.cursor() as c:
        rows = _safe(c, "SELECT DISTINCT tag FROM asset_tags ORDER BY tag")
    return JsonResponse({"tags": [r[0] for r in (rows or [])]})


@login_required
def assets_api_create_folder(request):
    """Create a new subfolder on Nextcloud."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST
    parent = data.get("parent", "").strip("/")
    name = data.get("name", "").strip()
    if not name:
        return JsonResponse({"error": "Name required"}, status=400)
    # Sanitize: replace spaces with underscores, remove dangerous chars
    import re
    safe_name = re.sub(r'[^\w\-.]', '_', name)
    if parent:
        nc_path = f"{NC_ASSETS_ROOT}/{parent}/{safe_name}"
    else:
        nc_path = f"{NC_ASSETS_ROOT}/{safe_name}"
    ok = _nc_mkdir(nc_path)
    return JsonResponse({"ok": ok, "nc_path": nc_path, "name": safe_name})


@login_required
def assets_api_setup(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)
    if not request.user.is_superuser:
        return JsonResponse({"error": "Superuser required"}, status=403)

    ok, result = ensure_nc_folders()
    return JsonResponse({"ok": ok, "result": result})


@login_required
def assets_image_proxy(request):
    """Proxy Nextcloud files through Django (same-origin, no CORS)."""
    nc_path = request.GET.get("path", "")
    if not nc_path:
        raise Http404

    base, username, password = _nc_base()
    if not base:
        raise Http404

    url = f"{base}/{quote(nc_path, safe='/')}"
    try:
        r = requests.get(url, auth=HTTPBasicAuth(username, password), timeout=30)
        if r.status_code != 200:
            raise Http404
    except Exception:
        raise Http404

    ct = r.headers.get("Content-Type", "application/octet-stream")
    resp = HttpResponse(r.content, content_type=ct)
    resp["Cache-Control"] = "public, max-age=3600"
    # For download support
    if request.GET.get("dl") == "1":
        name = nc_path.rstrip("/").split("/")[-1]
        resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp
