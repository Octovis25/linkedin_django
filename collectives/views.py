from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from .models import CollectivesConfig, PageStatus
from .utils import fetch_collective_pages, test_nextcloud_connection
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.worksheet.table import Table, TableStyleInfo
from datetime import datetime
import tempfile

@login_required
def collectives_dashboard(request):
    """Main Collectives dashboard view"""
    return render(request, 'collectives/dashboard.html')

@login_required
@require_http_methods(["GET", "POST"])
def api_config(request):
    """Get or update Nextcloud config"""
    config, created = CollectivesConfig.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
        
        config.nextcloud_url = data.get('nextcloud_url', '').rstrip('/')
        config.kollektive_name = data.get('kollektive_name', '')
        config.username = data.get('username', '')
        
        if data.get('app_password'):
            config.app_password = data.get('app_password')
        
        config.save()
        
        return JsonResponse({
            'success': True,
            'config': {
                'nextcloud_url': config.nextcloud_url,
                'kollektive_name': config.kollektive_name,
                'username': config.username,
                'connected': bool(config.nextcloud_url and config.username and config.app_password)
            }
        })
    
    return JsonResponse({
        'nextcloud_url': config.nextcloud_url,
        'kollektive_name': config.kollektive_name,
        'username': config.username,
        'app_password': '',  # Never send password to frontend
        'connected': bool(config.nextcloud_url and config.username and config.app_password)
    })

@login_required
@require_http_methods(["POST"])
def api_test_connection(request):
    """Test Nextcloud connection"""
    config = CollectivesConfig.objects.filter(user=request.user).first()
    
    if not config or not config.nextcloud_url or not config.username or not config.app_password:
        return JsonResponse({
            'success': False,
            'message': 'Please fill in all fields'
        })
    
    success = test_nextcloud_connection(
        config.nextcloud_url,
        config.username,
        config.app_password
    )
    
    if success:
        return JsonResponse({
            'success': True,
            'message': f'Connection to {config.nextcloud_url} successful!'
        })
    else:
        return JsonResponse({
            'success': False,
            'message': 'Connection failed. Check credentials.'
        })

@login_required
def api_pages(request):
    """Fetch pages from Nextcloud Collectives"""
    config = CollectivesConfig.objects.filter(user=request.user).first()
    
    if not config or not config.nextcloud_url or not config.app_password:
        return JsonResponse({
            'success': False,
            'message': 'Not connected'
        })
    
    try:
        pages = fetch_collective_pages(config)
        
        # Add status and typ from database
        for page in pages:
            status_obj = PageStatus.objects.filter(
                user=request.user,
                path=page['path']
            ).first()
            
            if status_obj:
                page['status'] = status_obj.status
                page['typ'] = status_obj.typ
            else:
                page['status'] = ''
                page['typ'] = ''
        
        return JsonResponse({
            'success': True,
            'pages': pages
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

@login_required
@require_http_methods(["POST"])
def api_status(request):
    """Update page status or typ"""
    import json
    data = json.loads(request.body)
    
    path = data.get('path')
    if not path:
        return JsonResponse({'success': False, 'message': 'No path provided'})
    
    status_obj, created = PageStatus.objects.get_or_create(
        user=request.user,
        path=path
    )
    
    if 'status' in data:
        status_obj.status = data['status']
    
    if 'typ' in data:
        status_obj.typ = data['typ']
    
    status_obj.save()
    
    return JsonResponse({'success': True})

@login_required
def api_export_excel(request):
    """Export pages to Excel"""
    config = CollectivesConfig.objects.filter(user=request.user).first()
    
    if not config or not config.nextcloud_url or not config.app_password:
        return JsonResponse({'success': False, 'message': 'Not connected'})
    
    try:
        pages = fetch_collective_pages(config)
        
        # Add status
        for page in pages:
            status_obj = PageStatus.objects.filter(
                user=request.user,
                path=page['path']
            ).first()
            
            if status_obj:
                page['status'] = status_obj.status
                page['typ'] = status_obj.typ
            else:
                page['status'] = ''
                page['typ'] = ''
        
        # Create Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Collective Pages"
        
        headers = ['Title', 'Folder / Hierarchy', 'Typ', 'Status', 'Last Modified', 'Size (KB)', 'Owner', 'Path']
        ws.append(headers)
        
        # Header styling
        header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        header_font = Font(bold=True, color='FFFFFF')
        
        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
        
        # Status colors
        status_fills = {
            '📝 In Bearbeitung': PatternFill(start_color='FFF9C4', end_color='FFF9C4', fill_type='solid'),
            '🚀 Bereit zum Posten': PatternFill(start_color='C8E6C9', end_color='C8E6C9', fill_type='solid'),
            '📤 Gepostet': PatternFill(start_color='BBDEFB', end_color='BBDEFB', fill_type='solid'),
            '❌ Verworfen': PatternFill(start_color='FFCDD2', end_color='FFCDD2', fill_type='solid'),
        }
        
        # Add data rows
        for row_num, page in enumerate(pages, 2):
            modified_date = ''
            if page.get('modified'):
                try:
                    dt = datetime.strptime(page['modified'], '%a, %d %b %Y %H:%M:%S %Z')
                    modified_date = dt.strftime('%d.%m.%Y %H:%M')
                except:
                    modified_date = page['modified']
            
            size_kb = round(page.get('size', 0) / 1024, 2) if page.get('size') else 0
            status = page.get('status', '')
            typ = page.get('typ', '')
            
            ws.append([
                page.get('title', ''),
                page.get('folder', ''),
                typ,
                status,
                modified_date,
                size_kb,
                page.get('owner', ''),
                page.get('path', '')
            ])
            
            # Apply status color
            if status and status in status_fills:
                for col in range(1, len(headers) + 1):
                    ws.cell(row=row_num, column=col).fill = status_fills[status]
        
        # Column widths
        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 40
        ws.column_dimensions['C'].width = 12
        ws.column_dimensions['D'].width = 22
        ws.column_dimensions['E'].width = 20
        ws.column_dimensions['F'].width = 12
        ws.column_dimensions['G'].width = 25
        ws.column_dimensions['H'].width = 50
        
        # Add table
        tab_ref = f"A1:H{len(pages) + 1}"
        tab = Table(displayName="CollectivePages", ref=tab_ref)
        tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
        ws.add_table(tab)
        
        # Save to temp file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
        wb.save(tmp.name)
        tmp.close()
        
        koll_name = config.kollektive_name.replace(' ', '_').replace('&', 'and')
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"Collective_Export_{koll_name}_{timestamp}.xlsx"
        
        with open(tmp.name, 'rb') as f:
            response = HttpResponse(
                f.read(),
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
    
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})
