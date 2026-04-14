"""
Nextcloud WebDAV Storage for Post Images.
Uploads images to: Marketing & Design/LinkedIn/Post-Bilder/
Proxies images back through Django (no public Nextcloud link needed).
"""
import os
import requests
from requests.auth import HTTPBasicAuth
from urllib.parse import quote

# Nextcloud folder for post images
NC_IMAGE_FOLDER = "Marketing & Design/LinkedIn/Post-Bilder"


def _get_nc_credentials():
    """Get Nextcloud credentials from collectives config or env."""
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
    """Create the image folder in Nextcloud if it doesn't exist."""
    parts = NC_IMAGE_FOLDER.split("/")
    current = ""
    for part in parts:
        current = f"{current}/{part}" if current else part
        folder_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(current)}/"
        requests.request(
            'MKCOL', folder_url,
            auth=HTTPBasicAuth(username, password),
            timeout=10
        )
        # Ignore errors (folder may already exist)


def upload_image_to_nextcloud(image_file, filename):
    """
    Upload an image file to Nextcloud via WebDAV.
    Returns the Nextcloud path (relative) on success, None on failure.
    """
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None

    try:
        _ensure_folder_exists(nc_url, username, password)

        # Clean filename
        safe_filename = filename.replace(" ", "_")
        nc_path = f"{NC_IMAGE_FOLDER}/{safe_filename}"
        upload_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path)}"

        # Read file content
        content = image_file.read()

        # Upload via PUT
        r = requests.put(
            upload_url,
            data=content,
            auth=HTTPBasicAuth(username, password),
            headers={'Content-Type': image_file.content_type or 'image/png'},
            timeout=30
        )

        if r.status_code in [200, 201, 204]:
            return nc_path
        else:
            print(f"Nextcloud upload failed: HTTP {r.status_code} - {r.text[:200]}")
            return None

    except Exception as e:
        print(f"Nextcloud upload error: {e}")
        return None


def download_image_from_nextcloud(nc_path):
    """
    Download an image from Nextcloud via WebDAV.
    Returns (content_bytes, content_type) or (None, None).
    """
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return None, None

    try:
        download_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path)}"

        r = requests.get(
            download_url,
            auth=HTTPBasicAuth(username, password),
            timeout=30
        )

        if r.status_code == 200:
            content_type = r.headers.get('Content-Type', 'image/png')
            return r.content, content_type
        else:
            return None, None

    except Exception as e:
        print(f"Nextcloud download error: {e}")
        return None, None


def delete_image_from_nextcloud(nc_path):
    """Delete an image from Nextcloud via WebDAV."""
    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return False

    try:
        delete_url = f"{nc_url}/remote.php/dav/files/{username}/{quote(nc_path)}"
        r = requests.delete(
            delete_url,
            auth=HTTPBasicAuth(username, password),
            timeout=10
        )
        return r.status_code in [200, 204]
    except Exception:
        return False
