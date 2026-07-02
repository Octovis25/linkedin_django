NC_ASSETS_ROOT = "Marketing & Design/Octotrial_Assets"

FOLDER_TREE = [
    "Backgrounds", "Backgrounds/Workflows", "Backgrounds/Timelines", "Backgrounds/LinkedIn",
    "Backgrounds/Website", "Backgrounds/Offers", "Backgrounds/Presentations", "Backgrounds/Blank_Templates",
    "Icons", "Icons/Clinical_Data_Management", "Icons/Biostatistics", "Icons/Statistical_Programming",
    "Icons/Data_Management", "Icons/AI", "Icons/Database", "Icons/Validation", "Icons/Quality",
    "Icons/Monitoring", "Icons/CDISC", "Icons/SDTM", "Icons/ADaM", "Icons/Tables", "Icons/Listings",
    "Icons/Figures", "Icons/Risk", "Icons/Security", "Icons/General",
    "Logos", "Logos/Octotrial", "Logos/White", "Logos/Dark", "Logos/Icon_Only",
    "Buttons", "Badges", "Shapes", "Illustrations",
    "Templates", "Templates/LinkedIn", "Templates/Website", "Templates/Offer",
    "Templates/PowerPoint", "Templates/Reports",
    "Flowcharts", "Screenshots", "Archive",
    # Output-Ordner für erstellte Dateien
    "Studio_Output", "Studio_Output/Images", "Studio_Output/Videos",
    "Uploads",  # Bilder die ohne Studio hochgeladen werden
]


def ensure_nc_folders():
    """Create all folders in FOLDER_TREE on Nextcloud via MKCOL."""
    from posts_posted.nc_storage import _get_nc_credentials
    from urllib.parse import quote
    import requests
    from requests.auth import HTTPBasicAuth

    nc_url, username, password = _get_nc_credentials()
    if not all([nc_url, username, password]):
        return False, "NC credentials missing"

    base = f"{nc_url.rstrip('/')}/remote.php/dav/files/{username}"
    created = []
    errors = []

    # First ensure root exists, then all sub-folders
    all_folders = [NC_ASSETS_ROOT] + [f"{NC_ASSETS_ROOT}/{f}" for f in FOLDER_TREE]

    for folder in all_folders:
        url = f"{base}/{quote(folder, safe='/')}"
        try:
            r = requests.request("MKCOL", url, auth=HTTPBasicAuth(username, password), timeout=15)
            if r.status_code in (201, 405):  # 201=created, 405=already exists
                created.append(folder)
            else:
                errors.append(f"{folder}: {r.status_code}")
        except Exception as e:
            errors.append(f"{folder}: {e}")

    return len(errors) == 0, {"created": len(created), "errors": errors}
