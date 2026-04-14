import pandas as pd
import os
from django.conf import settings
from django.db import connection
from pathlib import Path
import re
from urllib.parse import unquote

def analyze_file(file_path):
    """Analyze uploaded file and determine its type based on columns"""
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.xls'):
            df = pd.read_excel(file_path, engine='xlrd', header=1)
        else:
            df = pd.read_excel(file_path, engine='openpyxl', header=1)
        
        columns = [str(col).strip().lower() for col in df.columns]
        
        if any('impressions' in c for c in columns) and any('datum' in c or 'date' in c for c in columns):
            return 'content'
        if any('link veröffentlichen' in c or 'post url' in c or 'post link' in c for c in columns):
            return 'posts'
        if any('follower' in c for c in columns):
            return 'followers'
        if any('company' in c or 'unternehmen' in c for c in columns) and any('job title' in c or 'position' in c for c in columns):
            return 'visitors'
        if any('competitor' in c or 'wettbewerber' in c for c in columns):
            return 'competitors'
        
        return None
    except Exception as e:
        print(f"Error analyzing file {file_path}: {e}")
        return None


def extract_post_id(url):
    """Extract post_id from LinkedIn URL"""
    if not url or pd.isna(url):
        return None
    s = unquote(str(url)).strip().rstrip("/")
    m = re.search(r"urn:li:(?:activity|share|ugcpost):(\d+)", s, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(?:activity|share|ugcpost)[:%3A]+(\d+)", s, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(\d{10,})", s)
    return m.group(1) if m else None


def import_to_db(file_path, file_type):
    """Import file to database based on type"""
    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.xls'):
            df = pd.read_excel(file_path, engine='xlrd', header=1)
        else:
            df = pd.read_excel(file_path, engine='openpyxl', header=1)
        
        print(f"Processing {file_type} file: {len(df)} rows")
        
        if file_type == 'content':
            return import_content(df)
        elif file_type == 'posts':
            return import_posts(df)
        
        print(f"{file_type} import not yet implemented")
        return False
        
    except Exception as e:
        print(f"Error importing file {file_path}: {e}")
        return False


def import_content(df):
    """Import content data to linkedin_posts table"""
    # Normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Map columns (German/English)
    col_map = {
        'post_url': ['link veröffentlichen', 'post link', 'post url', 'url'],
        'created_at': ['datum', 'date', 'erstellt am', 'created'],
        'post_title_raw': ['beitragstitel', 'post title', 'titel', 'title'],
        'post_distribution': ['verteilung', 'distribution'],
        'content_type': ['inhaltstyp', 'content type', 'typ', 'type'],
        'campaign_name': ['kampagnenname', 'campaign name', 'kampagne', 'campaign'],
        'published_by': ['veröffentlicht von', 'published by', 'autor', 'author'],
    }
    
    def find_col(names):
        for n in names:
            for c in df.columns:
                if n in c:
                    return c
        return None
    
    mapped = {k: find_col(v) for k, v in col_map.items()}
    
    inserted = 0
    updated = 0
    skipped = 0
    
    with connection.cursor() as cur:
        for _, row in df.iterrows():
            post_url = row.get(mapped['post_url']) if mapped['post_url'] else None
            post_id = extract_post_id(post_url)
            
            if not post_id:
                skipped += 1
                continue
            
            # Parse date
            created_at = None
            if mapped['created_at'] and pd.notna(row.get(mapped['created_at'])):
                try:
                    created_at = pd.to_datetime(row[mapped['created_at']]).strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass
            
            # Clean title
            title_raw = str(row.get(mapped['post_title_raw'], '') or '') if mapped['post_title_raw'] else ''
            title = re.sub(r'\s+', ' ', title_raw).strip()[:500] if title_raw else ''
            
            # Other fields
            distribution = str(row.get(mapped['post_distribution'], '') or '')[:100] if mapped['post_distribution'] else ''
            content_type = str(row.get(mapped['content_type'], '') or '')[:100] if mapped['content_type'] else ''
            campaign = str(row.get(mapped['campaign_name'], '') or '')[:255] if mapped['campaign_name'] else ''
            published_by = str(row.get(mapped['published_by'], '') or '')[:255] if mapped['published_by'] else ''
            
            try:
                cur.execute("""
                    INSERT INTO linkedin_posts 
                        (post_id, post_url, created_at, post_title_raw, post_title, 
                         post_distribution, content_type, campaign_name, published_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        post_url = VALUES(post_url),
                        created_at = COALESCE(VALUES(created_at), created_at),
                        post_title_raw = COALESCE(VALUES(post_title_raw), post_title_raw),
                        post_title = COALESCE(VALUES(post_title), post_title),
                        post_distribution = COALESCE(VALUES(post_distribution), post_distribution),
                        content_type = COALESCE(VALUES(content_type), content_type),
                        campaign_name = COALESCE(VALUES(campaign_name), campaign_name),
                        published_by = COALESCE(VALUES(published_by), published_by)
                """, [post_id, post_url, created_at, title_raw, title, 
                      distribution, content_type, campaign, published_by])
                
                if cur.rowcount == 1:
                    inserted += 1
                elif cur.rowcount == 2:
                    updated += 1
            except Exception as e:
                print(f"Error inserting post_id {post_id}: {e}")
                skipped += 1
    
    print(f"Content import: {inserted} inserted, {updated} updated, {skipped} skipped")
    return True


def import_posts(df):
    """Import posts (mit post_date) to linkedin_posts_posted table"""
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Find URL column
    url_col = None
    for c in df.columns:
        if any(x in c for x in ['link veröffentlichen', 'post link', 'post url', 'url']):
            url_col = c
            break
    
    if not url_col:
        print("No URL column found")
        return False
    
    inserted = 0
    skipped = 0
    
    with connection.cursor() as cur:
        for _, row in df.iterrows():
            post_url = row.get(url_col)
            post_id = extract_post_id(post_url)
            
            if not post_id:
                skipped += 1
                continue
            
            try:
                cur.execute("""
                    INSERT IGNORE INTO linkedin_posts (post_id, post_url)
                    VALUES (%s, %s)
                """, [post_id, post_url])
                
                if cur.rowcount > 0:
                    inserted += 1
            except Exception as e:
                print(f"Error: {e}")
                skipped += 1
    
    print(f"Posts import: {inserted} inserted, {skipped} skipped")
    return True
