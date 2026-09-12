import os
import requests
from requests.auth import HTTPBasicAuth
from urllib.parse import quote

# Existing/statistics image folder must stay unchanged for the content/statistics workflow.
NC_STATISTICS_IMAGE_FOLDER = "Marketing & Design/LinkedIn/Statistics/data/Post-Bilder"

# Planner media folders for planned posts.
NC_PLANNER_IMAGE_FOLDER = "Marketing & Design/LinkedIn/Planner/Images"
NC_PLANNER_VIDEO_FOLDER = "Marketing & Design/LinkedIn/Planner/Videos"

# Backwards-compatible default name used by older code.
NC_IMAGE_FOLDER = NC_PLANNER_IMAGE_FOLDER


def _get_nc_credentials():
    """(URL, Benutzer, App-Passwort). Erst aus der Datenbank, sonst aus den
    Umgebungsvariablen.

    Die Reihenfolge ist nicht das Heikle - die Bedingung ist es. Vorher fiel
    diese Funktion NUR bei einer Ausnahme auf die Umgebungsvariablen zurueck.
    CollectivesConfig.get_config() wirft aber keine: Es ist ein
    get_or_create(pk=1), und alle Felder haben '' als Vorgabe. Auf einer
    frischen Datenbank legt der erste Aufruf also eine leere Zeile an und
    liefert ('', '', '') - und die Umgebungsvariablen, die daneben korrekt
    gesetzt sind, kommen nie zum Zug. Nextcloud ist dann ueberall tot, ohne
    dass irgendwo ein Fehler auftaucht.

    Darum wird jetzt geprueft, ob wirklich alle drei Felder gefuellt sind.
    Genau so machte es die (ungenutzte) zweite Fassung in core/nc_storage.py -
    die beiden waren sich uneinig, und die schlechtere war die benutzte.
    """
    try:
        from collectives.models import CollectivesConfig
        c = CollectivesConfig.get_config()
        url = (c.nextcloud_url or '').strip()
        user = (c.username or '').strip()
        pw = (c.app_password or '').strip()
        if url and user and pw:
            return url, user, pw
    except Exception:
        pass
    return (os.environ.get("NEXTCLOUD_URL", "").strip(),
            os.environ.get("NEXTCLOUD_USER", "").strip(),
            os.environ.get("NEXTCLOUD_APP_PASSWORD", "").strip())


def _safe_filename(filename):
    return os.path.basename(str(filename or "file")).replace(" ", "_")


def _upload_file_to_nextcloud(file_obj, filename, folder, content_type=None, timeout=120):
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None
    try:
        safe_filename = _safe_filename(filename)
        nc_path = f"{folder}/{safe_filename}"
        upload_url = "{}/remote.php/dav/files/{}/{}".format(
            nc_url.rstrip("/"), username, quote(nc_path, safe="/")
        )
        content = file_obj.read()
        r = requests.put(
            upload_url,
            data=content,
            auth=HTTPBasicAuth(username, password),
            headers={"Content-Type": content_type or getattr(file_obj, "content_type", "application/octet-stream")},
            timeout=timeout,
        )
        if r.status_code in [200, 201, 204]:
            return nc_path
        print("Nextcloud upload failed:", r.status_code, r.text[:300])
        return None
    except Exception as e:
        print("Nextcloud upload error:", e)
        return None


def upload_image_to_nextcloud(image_file, filename):
    """Upload a planner post image to the dedicated Planner/Images folder."""
    return _upload_file_to_nextcloud(
        image_file,
        filename,
        NC_PLANNER_IMAGE_FOLDER,
        content_type=getattr(image_file, "content_type", "image/png"),
        timeout=60,
    )


def upload_video_to_nextcloud(video_file, filename):
    """Upload a planner post video to the dedicated Planner/Videos folder."""
    return _upload_file_to_nextcloud(
        video_file,
        filename,
        NC_PLANNER_VIDEO_FOLDER,
        content_type=getattr(video_file, "content_type", "video/mp4"),
        timeout=180,
    )


def download_image_from_nextcloud(nc_path):
    """Download any file from Nextcloud by stored path. Name kept for backwards compatibility."""
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None, None
    try:
        download_url = "{}/remote.php/dav/files/{}/{}".format(
            nc_url.rstrip("/"), username, quote(nc_path, safe="/")
        )
        r = requests.get(download_url, auth=HTTPBasicAuth(username, password), timeout=60)
        if r.status_code == 200:
            return r.content, r.headers.get("Content-Type", "application/octet-stream")
        print("Nextcloud download failed:", r.status_code, str(nc_path))
        return None, None
    except Exception as e:
        print("Nextcloud download error:", e)
        return None, None


def stream_from_nextcloud(nc_path, range_header=None, timeout=60):
    """Open a file on Nextcloud for streaming. Returns (response, reason).

    The response is a live, unread ``requests`` response - the caller must
    consume and close it. Unlike download_image_from_nextcloud this does NOT
    pull the whole file into memory first, which matters for video: a 50 MB
    clip used to sit in RAM in full before the first byte reached the browser.

    A Range header is passed straight through. Nextcloud answers it with 206
    and a Content-Range, which is what lets a browser seek inside a video.
    """
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None, "Nextcloud is not configured (URL, user or password missing)"
    url = "{}/remote.php/dav/files/{}/{}".format(
        nc_url.rstrip("/"), username, quote(nc_path, safe="/")
    )
    headers = {}
    if range_header:
        headers["Range"] = range_header
    try:
        r = requests.get(url, auth=HTTPBasicAuth(username, password),
                         headers=headers, stream=True, timeout=timeout)
    except Exception as e:
        return None, "Nextcloud could not be reached: {}".format(e)
    if r.status_code not in (200, 206):
        code = r.status_code
        r.close()
        return None, "Nextcloud answered {}".format(code)
    return r, ""


def delete_from_nextcloud_detail(nc_path):
    """Delete a file and say WHY it failed: returns (ok, reason).

    The plain boolean version below throws the reason away, and every caller
    that did so reported success to the user regardless - the tile disappeared
    from the panel and the file was back on the next load. A deletion that
    cannot explain itself is worse than one that fails loudly.

    404 counts as success: the file is gone, which is what was asked for.
    """
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return False, "Nextcloud is not configured (URL, user or password missing)"
    try:
        delete_url = "{}/remote.php/dav/files/{}/{}".format(
            nc_url.rstrip("/"), username, quote(nc_path, safe="/")
        )
        r = requests.delete(delete_url, auth=HTTPBasicAuth(username, password), timeout=30)
    except Exception as e:
        return False, "Nextcloud could not be reached: {}".format(e)

    if r.status_code in (200, 204, 404):
        return True, ""
    if r.status_code in (401, 403):
        return False, "Nextcloud refused the deletion ({}) - check the app password".format(r.status_code)
    if r.status_code == 423:
        return False, "The file is locked in Nextcloud (423) - it may still be open elsewhere"
    return False, "Nextcloud answered {}".format(r.status_code)


def delete_image_from_nextcloud(nc_path):
    """True when the file is gone afterwards. Use delete_from_nextcloud_detail
    wherever the user is told whether it worked."""
    ok, _reason = delete_from_nextcloud_detail(nc_path)
    return ok
