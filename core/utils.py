import pandas as pd
import os
from django.conf import settings
from django.db import connection
from pathlib import Path
import re
from urllib.parse import unquote


def read_sheets(file_path):
    """Liest alle Sheets einer Excel-Datei"""
    if file_path.endswith('.csv'):
        return {'sheet1': pd.read_csv(file_path)}, None
    engine = 'xlrd' if file_path.endswith('.xls') else 'openpyxl'
    xl = pd.ExcelFile(file_path, engine=engine)
    sheets = {}
    for name in xl.sheet_names:
        try:
            sheets[name] = pd.read_excel(xl, sheet_name=name, header=1)
        except:
            sheets[name] = pd.read_excel(xl, sheet_name=name, header=0)
    return sheets, xl.sheet_names


def analyze_file(file_path):
    """Erkennt Dateityp anhand der Spalten"""
    try:
        sheets, names = read_sheets(file_path)
        all_cols = []
        for df in sheets.values():
            all_cols += [str(col).strip().lower() for col in df.columns]

        if any('link veröffentlichen' in c or 'post url' in c or 'post link' in c for c in all_cols):
            if any('impressions' in c for c in all_cols):
                return 'content'  # hat beide Sheets
            return 'posts'
        if any('follower' in c for c in all_cols):
            return 'followers'
        if any('company' in c or 'unternehmen' in c for c in all_cols) and any('job title' in c or 'position' in c for c in all_cols):
            return 'visitors'
        if any('competitor' in c or 'wettbewerber' in c for c in all_cols):
            return 'competitors'
        if any('impressions' in c for c in all_cols) and any('datum' in c or 'date' in c for c in all_cols):
            return 'content'
        return None
    except Exception as e:
        print(f"Error analyzing file {file_path}: {e}")
        return None


def extract_post_id(url):
    """Extrahiert post_id aus LinkedIn URL"""
    if not url or pd.isna(url):
        return None
    s = unquote(str(url)).strip().rstrip("/")
    m = re.search(r"urn:li:(?:activity|share|ugcpost):(\d+)", s, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r"(?:activity|share|ugcpost)[:%3A]+(\d+)", s, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r"(\d{10,})", s)
    return m.group(1) if m else None


def import_to_db(file_path, file_type):
    """Import Datei in DB"""
    try:
        sheets, names = read_sheets(file_path)
        print(f"Sheets gefunden: {list(sheets.keys())}")

        if file_type == 'content':
            # Sheet "Alle Beiträge" → linkedin_posts
            posts_sheet = None
            metrics_sheet = None
            for name, df in sheets.items():
                cols = [str(c).strip().lower() for c in df.columns]
                if any('link veröffentlichen' in c or 'post url' in c for c in cols):
                    posts_sheet = df
                elif any('datum' in c or 'date' in c for c in cols) and any('impressions' in c for c in cols):
                    metrics_sheet = df

            stats = []
            r1 = import_posts_from_content(posts_sheet, file_path) if posts_sheet is not None else None
            r2 = import_kennzahlen(metrics_sheet) if metrics_sheet is not None else None
            if r1: stats.append(r1)
            if r2: stats.append(r2)
            from core.nc_storage import upload_excel_to_nextcloud
            upload_excel_to_nextcloud(file_path, file_type)
            return stats if stats else True

        elif file_type == 'posts':
            df = list(sheets.values())[0]
            r = import_posts(df)
            return [r] if r else False

        print(f"{file_type} import not yet implemented")
        return False

    except Exception as e:
        print(f"Error importing {file_path}: {e}")
        import traceback; traceback.print_exc()
        return False


def import_posts_from_content(df, file_path=""):
    """Importiert 'Alle Beiträge' Sheet → linkedin_posts + linkedin_posts_metrics"""
    import datetime as dt

    df.columns = [str(c).strip().lower() for c in df.columns]

    def find_col(names):
        for n in names:
            for c in df.columns:
                if n in c:
                    return c
        return None

    # Export-Datum aus Dateiname extrahieren
    export_date = dt.date.today().isoformat()
    if file_path:
        m = re.search(r'_(\d{10,13})\.', os.path.basename(file_path))
        if m:
            ts = int(m.group(1))
            if ts > 1e12: ts = ts / 1000
            export_date = dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')

    # Spalten mappen
    col_map = {
        'post_url':        ['link veröffentlichen', 'post link', 'post url', 'url'],
        'created_at':      ['erstellt am', 'datum', 'date', 'created'],
        'post_title_raw':  ['titel des beitrags', 'beitragstitel', 'post title', 'titel', 'title'],
        'post_distribution':['verteilung', 'distribution'],
        'content_type':    ['art des beitrags', 'inhaltstyp', 'content type', 'typ', 'type'],
        'campaign_name':   ['name der kampagne', 'kampagnenname', 'campaign name', 'kampagne'],
        'published_by':    ['veröffentlicht von', 'published by', 'autor', 'author'],
        'audience':        ['zielgruppe', 'audience'],
    }
    mapped = {k: find_col(v) for k, v in col_map.items()}

    # Existierende IDs und Metriken vorab laden
    with connection.cursor() as c:
        c.execute("SELECT post_id FROM linkedin_posts")
        existing_post_ids = {r[0] for r in c.fetchall()}
        c.execute("SELECT post_id, metric_date FROM linkedin_posts_metrics")
        existing_metrics = {(r[0], str(r[1])) for r in c.fetchall()}

    inserted = skipped = 0
    metrics_inserted = 0
    metrics_updated = 0
    metrics_updated = 0
    new_rows = []

    def get_str(key, maxlen=None):
        col = mapped.get(key)
        val = str(row.get(col, '') or '') if col else ''
        val = val.strip()
        return val[:maxlen] if maxlen else val

    def get_int(names):
        col = find_col(names)
        if col:
            val = row.get(col)
            if val is not None and str(val).strip() not in ('', 'nan'):
                try: return int(float(val))
                except: pass
        return None

    def get_float(names):
        col = find_col(names)
        if col:
            val = row.get(col)
            if val is not None and str(val).strip() not in ('', 'nan'):
                try: return float(val)
                except: pass
        return None

    with connection.cursor() as cur:
        for _, row in df.iterrows():
            post_url = row.get(mapped['post_url']) if mapped['post_url'] else None
            post_id = extract_post_id(post_url)
            if not post_id:
                skipped += 1
                continue

            created_at = None
            if mapped['created_at'] and pd.notna(row.get(mapped['created_at'])):
                try:
                    created_at = pd.to_datetime(row[mapped['created_at']]).strftime('%Y-%m-%d %H:%M:%S')
                except: pass

            title_raw = get_str('post_title_raw')
            title = re.sub(r'\s+', ' ', title_raw).strip()[:500]

            # 1. Post in linkedin_posts upsert
            try:
                cur.execute("""
                    INSERT INTO linkedin_posts
                        (post_id, post_url, created_at, post_title_raw, post_title,
                         post_distribution, content_type, campaign_name, published_by, audience)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                        post_url=VALUES(post_url),
                        created_at=COALESCE(VALUES(created_at),created_at),
                        post_title_raw=COALESCE(VALUES(post_title_raw),post_title_raw),
                        post_title=COALESCE(VALUES(post_title),post_title),
                        post_distribution=COALESCE(VALUES(post_distribution),post_distribution),
                        content_type=COALESCE(VALUES(content_type),content_type),
                        campaign_name=COALESCE(VALUES(campaign_name),campaign_name),
                        published_by=COALESCE(VALUES(published_by),published_by),
                        audience=COALESCE(VALUES(audience),audience)
                """, [post_id, post_url, created_at, title_raw, title,
                      get_str('post_distribution',100), get_str('content_type',100),
                      get_str('campaign_name',255), get_str('published_by',255), get_str('audience')])
            except Exception as e:
                print(f"Post error {post_id}: {e}")
                skipped += 1
                continue

            # 2. Metriken-Snapshot: nur eintragen wenn fuer dieses Datum noch keiner existiert
            if (post_id, export_date) not in existing_metrics:
                try:
                    cur.execute("""
                        INSERT INTO linkedin_posts_metrics
                            (post_id, metric_date, captured_at,
                             impressions, views, offsite_views,
                             clicks, ctr, likes, comments,
                             direct_shares, followers, engagement_rate)
                        VALUES (%s,%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, [
                        post_id, export_date,
                        get_int(['impressions']),
                        get_int(['aufrufe', 'views']),
                        get_int(['offsite']),
                        get_int(['klicks', 'clicks']),
                        get_float(['klickrate', 'ctr']),
                        get_int(['likes']),
                        get_int(['kommentare', 'comments']),
                        get_int(['direkt geteilte', 'shares']),
                        get_int(['follower']),
                        get_float(['engagement rate', 'engagement_rate']),
                    ])
                    existing_metrics.add((post_id, export_date))
                    metrics_inserted += 1
                except Exception as em:
                    print(f"Metrics error {post_id}: {em}")
            else:
                metrics_updated += 1
            else:
                metrics_updated += 1

            # 3. Zählen
            if post_id not in existing_post_ids:
                inserted += 1
                existing_post_ids.add(post_id)
                new_rows.append({
                    'post_id': post_id,
                    'title': title[:60] + '...' if len(title) > 60 else title,
                    'created_at': created_at,
                    'content_type': get_str('content_type', 100),
                })
            else:
                skipped += 1

    print(f"Posts: {inserted} new, {skipped} unchanged. Metrics: {metrics_inserted} snapshots added for {export_date}")
    return {
        'table': 'linkedin_posts',
        'inserted': inserted,
        'updated': 0,
        'skipped': skipped,
        'new_rows': new_rows,
        'metrics_inserted': metrics_inserted,
        'metrics_updated': metrics_updated,
        'export_date': export_date,
    }


def import_kennzahlen(df):
    """Importiert Kennzahlen Sheet → linkedin_content_metrics"""
    df.columns = [str(c).strip().lower() for c in df.columns]
    print(f"Kennzahlen Spalten: {list(df.columns)[:6]}")

    def find_col(names):
        for n in names:
            for c in df.columns:
                if n in c: return c
        return None

    date_col = find_col(['datum', 'date'])
    if not date_col:
        print("Kein Datum in Kennzahlen gefunden")
        return {'table': 'linkedin_content_metrics', 'inserted': 0, 'updated': 0, 'skipped': 0}

    inserted = skipped = 0
    new_rows = []

    # Existierende metric_dates vorab laden
    with connection.cursor() as _c:
        _c.execute("SELECT metric_date FROM linkedin_content_metrics")
        existing_dates = {str(r[0]) for r in _c.fetchall()}

    with connection.cursor() as cur:
        for _, row in df.iterrows():
            try:
                metric_date = pd.to_datetime(row[date_col]).strftime('%Y-%m-%d') if pd.notna(row.get(date_col)) else None
                if not metric_date:
                    skipped += 1; continue

                def gi(col_names):
                    col = find_col(col_names)
                    if col and pd.notna(row.get(col)):
                        try: return int(float(row[col]))
                        except: pass
                    return None

                def gf(col_names):
                    col = find_col(col_names)
                    if col and pd.notna(row.get(col)):
                        try: return float(row[col])
                        except: pass
                    return None

                cur.execute("""
                    INSERT INTO linkedin_content_metrics
                        (metric_date, captured_at,
                         impressions_organic, impressions_sponsored, impressions_total,
                         unique_impressions_organic,
                         clicks_organic, clicks_sponsored, clicks_total,
                         reactions_organic, reactions_sponsored, reactions_total,
                         comments_organic, comments_sponsored, comments_total,
                         shares_direct_organic, shares_direct_sponsored, shares_direct_total,
                         engagement_rate_organic, engagement_rate_sponsored, engagement_rate_total)
                    VALUES (%s,NOW(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                        impressions_organic=COALESCE(VALUES(impressions_organic),impressions_organic),
                        impressions_sponsored=COALESCE(VALUES(impressions_sponsored),impressions_sponsored),
                        impressions_total=COALESCE(VALUES(impressions_total),impressions_total),
                        unique_impressions_organic=COALESCE(VALUES(unique_impressions_organic),unique_impressions_organic),
                        clicks_organic=COALESCE(VALUES(clicks_organic),clicks_organic),
                        clicks_sponsored=COALESCE(VALUES(clicks_sponsored),clicks_sponsored),
                        clicks_total=COALESCE(VALUES(clicks_total),clicks_total),
                        reactions_organic=COALESCE(VALUES(reactions_organic),reactions_organic),
                        reactions_sponsored=COALESCE(VALUES(reactions_sponsored),reactions_sponsored),
                        reactions_total=COALESCE(VALUES(reactions_total),reactions_total),
                        comments_organic=COALESCE(VALUES(comments_organic),comments_organic),
                        comments_sponsored=COALESCE(VALUES(comments_sponsored),comments_sponsored),
                        comments_total=COALESCE(VALUES(comments_total),comments_total),
                        shares_direct_organic=COALESCE(VALUES(shares_direct_organic),shares_direct_organic),
                        shares_direct_sponsored=COALESCE(VALUES(shares_direct_sponsored),shares_direct_sponsored),
                        shares_direct_total=COALESCE(VALUES(shares_direct_total),shares_direct_total),
                        engagement_rate_organic=COALESCE(VALUES(engagement_rate_organic),engagement_rate_organic),
                        engagement_rate_sponsored=COALESCE(VALUES(engagement_rate_sponsored),engagement_rate_sponsored),
                        engagement_rate_total=COALESCE(VALUES(engagement_rate_total),engagement_rate_total)
                """, [
                    metric_date,
                    gi(['impressions (organische updates)']),
                    gi(['impressions (sponsored updates)']),
                    gi(['impressions (insgesamt)']),
                    gi(['individuelle impressions (organische updates)']),
                    gi(['klicks (organische updates)']),
                    gi(['klicks (sponsored updates)']),
                    gi(['klicks (insgesamt)']),
                    gi(['reaktionen (organisch)']),
                    gi(['reaktionen (gesponsert)']),
                    gi(['reaktionen (insgesamt)']),
                    gi(['kommentare (organisch)']),
                    gi(['kommentare (gesponsert)']),
                    gi(['kommentare (insgesamt)']),
                    gi(['geteilte inhalte (organisch)']),
                    gi(['geteilte inhalte (gesponsert)']),
                    gi(['geteilte inhalte (insgesamt)']),
                    gf(['engagement-rate (organisch)']),
                    gf(['engagement-rate (gesponsert)']),
                    gf(['engagement-rate (insgesamt)']),
                ])
                if metric_date not in existing_dates:
                    inserted += 1
                    existing_dates.add(metric_date)
                    imp = gi(['impressions (insgesamt)'])
                    cli = gi(['klicks (insgesamt)'])
                    rea = gi(['reaktionen (insgesamt)'])
                    new_rows.append({
                        'date': metric_date,
                        'impressions': imp or 0,
                        'clicks': cli or 0,
                        'reactions': rea or 0,
                    })
                else:
                    skipped += 1
            except Exception as e:
                print(f"Kennzahlen error: {e}")
                skipped += 1

    print(f"Kennzahlen Import: {inserted} inserted, {skipped} skipped")
    return {'table': 'linkedin_content_metrics', 'inserted': inserted, 'updated': 0, 'skipped': skipped, 'new_rows': new_rows}


def import_posts(df):
    """Importiert Posts → linkedin_posts_posted"""
    df.columns = [str(c).strip().lower() for c in df.columns]
    url_col = None
    for c in df.columns:
        if any(x in c for x in ['link veröffentlichen', 'post link', 'post url', 'url']):
            url_col = c; break
    if not url_col:
        print("Keine URL-Spalte gefunden"); return False

    inserted = skipped = 0
    new_rows = []

    # Existierende metric_dates vorab laden
    with connection.cursor() as _c:
        _c.execute("SELECT metric_date FROM linkedin_content_metrics")
        existing_dates = {str(r[0]) for r in _c.fetchall()}

    with connection.cursor() as cur:
        for _, row in df.iterrows():
            post_url = row.get(url_col)
            post_id = extract_post_id(post_url)
            if not post_id:
                skipped += 1; continue
            try:
                cur.execute("""
                    INSERT IGNORE INTO linkedin_posts (post_id, post_url)
                    VALUES (%s,%s)
                """, [post_id, post_url])
                if cur.rowcount > 0: inserted += 1
            except Exception as e:
                print(f"Error: {e}"); skipped += 1

    print(f"Posts Import: {inserted} inserted, {skipped} skipped")
    return {'table': 'linkedin_posts_posted', 'inserted': inserted, 'updated': 0, 'skipped': skipped}
