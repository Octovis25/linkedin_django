import pandas as pd
import os
from django.conf import settings
from pathlib import Path
import re

def analyze_file(file_path):
    """
    Analyze uploaded file and determine its type based on columns
    Returns: 'content', 'followers', 'visitors', 'competitors', 'posts', or None
    """
    try:
        # Read Excel or CSV file
        # LinkedIn exports often have description in row 0, real headers in row 1
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.xls'):
            df = pd.read_excel(file_path, engine='xlrd', header=1)
        else:
            df = pd.read_excel(file_path, engine='openpyxl', header=1)
        
        # Get column names (normalize)
        columns = [str(col).strip().lower() for col in df.columns]
        
        # Determine file type based on columns
        # Content files (German or English)
        if any('impressions' in c for c in columns) and any('datum' in c or 'date' in c for c in columns):
            return 'content'
        
        # Posts files
        if any('link veröffentlichen' in c or 'post url' in c or 'post link' in c for c in columns):
            return 'posts'
        
        # Followers files
        if any('follower' in c for c in columns):
            return 'followers'
        
        # Visitors files
        if any('company' in c or 'unternehmen' in c for c in columns) and any('job title' in c or 'position' in c for c in columns):
            return 'visitors'
        
        # Competitors files
        if any('competitor' in c or 'wettbewerber' in c for c in columns):
            return 'competitors'
        
        return None
            
    except Exception as e:
        print(f"Error analyzing file {file_path}: {e}")
        return None

def import_to_db(file_path, file_type):
    """
    Import file to database based on type
    Returns: True if successful, False otherwise
    """
    try:
        # Read file with correct header row
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        elif file_path.endswith('.xls'):
            df = pd.read_excel(file_path, engine='xlrd', header=1)
        else:
            df = pd.read_excel(file_path, engine='openpyxl', header=1)
        
        print(f"Processing {file_type} file: {len(df)} rows")
        
        # TODO: Add actual database import using your existing import scripts
        # For now, we just validate the file can be read
        
        if file_type in ['content', 'posts', 'followers', 'visitors', 'competitors']:
            print(f"{file_type} file validated successfully")
            return True
        
        return False
        
    except Exception as e:
        print(f"Error importing file {file_path}: {e}")
        return False
