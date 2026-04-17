from datetime import datetime, timedelta

def get_date_range(request):
    date_to = datetime.today().date()
    date_from = date_to - timedelta(days=365)
    from_param = request.GET.get('date_from') or request.GET.get('from')
    to_param = request.GET.get('date_to') or request.GET.get('to')
    if from_param:
        try: date_from = datetime.strptime(from_param, '%Y-%m-%d').date()
        except ValueError: pass
    if to_param:
        try: date_to = datetime.strptime(to_param, '%Y-%m-%d').date()
        except ValueError: pass
    return date_from, date_to
