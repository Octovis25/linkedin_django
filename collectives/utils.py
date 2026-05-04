import xml.etree.ElementTree as ET
from urllib.parse import unquote, quote

def build_collectives_url(base_url, kollektive_name, folder_parts, title):
    """Build the correct Collectives URL for browser."""
    path_parts = list(folder_parts) + [title]
    encoded_parts = [quote(p) for p in path_parts]
    path_str = '/'.join(encoded_parts)
    return f"{base_url}/apps/collectives/{quote(kollektive_name)}/{path_str}"

def parse_webdav_response(xml_text, username, kollektive_name):
    """Parse WebDAV XML response and extract page information."""
    namespaces = {
        'd': 'DAV:',
        'oc': 'http://owncloud.org/ns',
        'nc': 'http://nextcloud.org/ns'
    }
    
    root = ET.fromstring(xml_text)
    pages = []
    base_path = f"/remote.php/dav/files/{username}/Kollektive/{kollektive_name}/"
    
    for response in root.findall('d:response', namespaces):
        href = response.find('d:href', namespaces)
        if href is None:
            continue
        
        href_text = unquote(href.text)
        
        # Skip directories and non-markdown files
        if href_text.endswith('/') or not href_text.endswith('.md'):
            continue
        
        propstat = response.find('d:propstat', namespaces)
        if propstat is None:
            continue
        
        prop = propstat.find('d:prop', namespaces)
        if prop is None:
            continue
        
        # Extract properties
        displayname = prop.find('d:displayname', namespaces)
        getlastmodified = prop.find('d:getlastmodified', namespaces)
        getcontentlength = prop.find('d:getcontentlength', namespaces)
        owner_display = prop.find('oc:owner-display-name', namespaces)
        
        title = displayname.text if displayname is not None else href_text.split('/')[-1]
        if title.endswith('.md'):
            title = title[:-3]
        
        modified = getlastmodified.text if getlastmodified is not None else ''
        size = int(getcontentlength.text) if getcontentlength is not None and getcontentlength.text else 0
        owner = owner_display.text if owner_display is not None else ''
        
        # Extract folder hierarchy
        clean_path = href_text
        if clean_path.startswith(base_path):
            clean_path = clean_path[len(base_path):]
        
        path_parts = clean_path.split('/')
        folder_parts = path_parts[:-1]
        folder_hierarchy = ' / '.join(folder_parts) if folder_parts else ''
        
        pages.append({
            'title': title,
            'modified': modified,
            'size': size,
            'owner': owner,
            'folder': folder_hierarchy,
            'folder_parts': folder_parts,
            'depth': len(folder_parts),
            'path': href_text
        })
    
    # Replace "Readme" titles with last folder part
    for page in pages:
        if page['title'].lower() == 'readme':
            page['is_readme'] = True
            if page['folder']:
                parts = page['folder'].split(' / ')
                page['title'] = parts[-1] if parts else page['title']
        else:
            page['is_readme'] = False
    
    return pages

