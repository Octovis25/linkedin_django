import os
import requests
from urllib.parse import quote

NC_BASE_PATH = "Marketing & Design/LinkedIn/Statistics/data"

FOLDER_MAP = {
    'content':     'content',
    'followers':   'followers',
    'visitors':    'visitors',
    'competitors': 'competitors',
    'posts':       'content',
}

def _get_nc_credentials():
    try:
        from collectives.models import CollectivesConfig
        config = CollectivesConfig.objects.first()
        if config and config.nextcloud_url and config.username and config.app_password:
            return config.nextcloud_url, config.username, config.app_password
    except Exception:
        pass
    url  = os.environ.get('NEXTCLOUD_URL', '').strip()
    user = os.environ.get('NEXTCLOUD_USER', '').strip()
    pw   = os.environ.get('NEXTCLOUD_APP_PASSWORD', '').strip()
    return url, user, pw

def _ensure_folder(nc_url, username, password, folder_path):
    parts = folder_path.split("/")
    current = ""
    for part in parts:
        current = current + "/" + part if current else part
        folder_url = "{}/remote.php/dav/files/{}/{}/".format(
            nc_url, username, quote(current))
        requests.request('MKCOL', folder_url,
            auth=(username, password), timeout=10)

def upload_excel_to_nextcloud(file_path, file_type):
    """Lädt eine Excel-Datei in den richtigen Nextcloud-Ordner hoch"""
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        print("Nextcloud: keine Zugangsdaten gefunden")
        return False
    try:
        subfolder = FOLDER_MAP.get(file_type, 'content')
        nc_folder = "{}/{}".format(NC_BASE_PATH, subfolder)
        _ensure_folder(nc_url, username, password, nc_folder)

        filename = os.path.basename(file_path)
        nc_path = "{}/{}".format(nc_folder, filename)
        upload_url = "{}/remote.php/dav/files/{}/{}".format(
            nc_url, username, quote(nc_path))

        with open(file_path, 'rb') as f:
            r = requests.put(upload_url, data=f,
                auth=(username, password), timeout=30)

        if r.status_code in (200, 201, 204):
            print(f"Nextcloud Upload OK: {nc_path}")
            return True
        else:
            print(f"Nextcloud Upload Fehler: {r.status_code}")
            return False
    except Exception as e:
        print(f"Nextcloud Upload Exception: {e}")
        return False


def upload_image_to_nextcloud(file_path, filename):
    """Lädt ein Post-Bild in Post-Bilder/image_ready/ hoch"""
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        print("Nextcloud: keine Zugangsdaten")
        return False
    try:
        nc_folder = "Marketing & Design/LinkedIn/Statistics/data/Post-Bilder/image_ready"
        _ensure_folder(nc_url, username, password, nc_folder)
        nc_path = "{}/{}".format(nc_folder, filename)
        upload_url = "{}/remote.php/dav/files/{}/{}".format(
            nc_url, username, quote(nc_path))
        with open(file_path, 'rb') as f:
            r = requests.put(upload_url, data=f,
                auth=(username, password), timeout=30)
        if r.status_code in (200, 201, 204):
            print(f"Nextcloud Bild Upload OK: {nc_path}")
            return True
        print(f"Nextcloud Bild Fehler: {r.status_code}")
        return False
    except Exception as e:
        print(f"Nextcloud Bild Exception: {e}")
        return False
