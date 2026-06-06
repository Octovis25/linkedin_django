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
    try:
        from collectives.models import CollectivesConfig
        c = CollectivesConfig.get_config()
        return c.nextcloud_url, c.username, c.app_password
    except Exception:
        url = os.environ.get("NEXTCLOUD_URL", "").strip()
        user = os.environ.get("NEXTCLOUD_USER", "").strip()
        pw = os.environ.get("NEXTCLOUD_APP_PASSWORD", "").strip()
        return url, user, pw


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


def delete_image_from_nextcloud(nc_path):
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return False
    try:
        delete_url = "{}/remote.php/dav/files/{}/{}".format(
            nc_url.rstrip("/"), username, quote(nc_path, safe="/")
        )
        r = requests.delete(delete_url, auth=HTTPBasicAuth(username, password), timeout=30)
        return r.status_code in [200, 204]
    except Exception:
        return False
