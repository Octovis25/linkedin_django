"""
Nextcloud WebDAV Storage for Post Images.
Uploads images to: Marketing & Design/LinkedIn/Post-Bilder/
Proxies images back through Django (no public Nextcloud link needed).
"""
import os
import requests
from requests.auth import HTTPBasicAuth
from urllib.parse import quote

NC_IMAGE_FOLDER = "Marketing & Design/LinkedIn/Post-Bilder"

def _get_nc_credentials():
    try:
        from collectives.views import get_config_with_env
        config = get_config_with_env()
        return config.nextcloud_url, config.username, config.app_password
    except Exception:
        url = os.environ.get('NEXTCLOUD_URL', '').strip()
        user = os.environ.get('NEXTCLOUD_USER', '').strip()
        pw = os.environ.get('NEXTCLOUD_APP_PASSWORD', '').strip()
        return url, user, pw

def _ensure_folder_exists(nc_url, username, password):
    parts = NC_IMAGE_FOLDER.split("/")
    current = ""
    for part in parts:
        current = "{}/{}".format(current, part) if current else part
        folder_url = "{}/remote.php/dav/files/{}/{}/".format(nc_url, username, quote(current))
        requests.request('MKCOL', folder_url, auth=HTTPBasicAuth(username, password), timeout=10)

def upload_image_to_nextcloud(image_file, filename):
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None
    try:
        _ensure_folder_exists(nc_url, username, password)
        safe_filename = filename.replace(" ", "_")
        nc_path = "{}/{}".format(NC_IMAGE_FOLDER, safe_filename)
        upload_url = "{}/remote.php/dav/files/{}/{}".format(nc_url, username, quote(nc_path))
        content = image_file.read()
        r = requests.put(upload_url, data=content, auth=HTTPBasicAuth(username, password),
            headers={'Content-Type': getattr(image_file, 'content_type', 'image/png')}, timeout=30)
        if r.status_code in [200, 201, 204]:
            return nc_path
        return None
    except Exception as e:
        print("Nextcloud upload error: {}".format(e))
        return None

def download_image_from_nextcloud(nc_path):
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None, None
    try:
        download_url = "{}/remote.php/dav/files/{}/{}".format(nc_url, username, quote(nc_path))
        r = requests.get(download_url, auth=HTTPBasicAuth(username, password), timeout=30)
        if r.status_code == 200:
            return r.content, r.headers.get('Content-Type', 'image/png')
        return None, None
    except Exception:
        return None, None

def delete_image_from_nextcloud(nc_path):
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return False
    try:
        delete_url = "{}/remote.php/dav/files/{}/{}".format(nc_url, username, quote(nc_path))
        r = requests.delete(delete_url, auth=HTTPBasicAuth(username, password), timeout=10)
        return r.status_code in [200, 204]
    except Exception:
        return False
