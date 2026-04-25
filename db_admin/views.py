from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.db import connection
from django.views.decorators.csrf import csrf_exempt
import json


def superuser_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise Http404
        return view_func(request, *args, **kwargs)
    return wrapped


def get_all_tables_with_counts():
    """Alle Tabellen mit Zeilenanzahl für die rechte Spalte."""
    tables = []
    with connection.cursor() as c:
        c.execute("SHOW TABLES")
        table_names = [row[0] for row in c.fetchall()]
        for name in table_names:
            try:
                c.execute(f"SELECT COUNT(*) FROM `{name}`")
                row_count = c.fetchone()[0]
            except Exception:
                row_count = "?"
            tables.append({"name": name, "rows": row_count})
    return tables


@superuser_required
def db_index(request):
    tables = get_all_tables_with_counts()
    return render(request, "db_admin/index.html", {"tables": tables})


@superuser_required
def db_table(request, table_name):
    tables = get_all_tables_with_counts()
    all_table_names = [t["name"] for t in tables]

    if table_name not in all_table_names:
        raise Http404

    page     = int(request.GET.get("page", 1))
    per_page = int(request.GET.get("per_page", 50))
    search   = request.GET.get("search", "").strip()
    sort_col = request.GET.get("sort", "")
    sort_dir = request.GET.get("dir", "asc")
    offset   = (page - 1) * per_page

    with connection.cursor() as c:
        c.execute(f"DESCRIBE `{table_name}`")
        columns = [{"name": row[0], "type": row[1], "null": row[2], "key": row[3], "default": row[4]}
                   for row in c.fetchall()]
        col_names = [col["name"] for col in columns]

        if search:
            like_clauses = " OR ".join([f"CAST(`{col}` AS CHAR) LIKE %s" for col in col_names])
            c.execute(f"SELECT COUNT(*) FROM `{table_name}` WHERE {like_clauses}",
                      [f"%{search}%"] * len(col_names))
        else:
            c.execute(f"SELECT COUNT(*) FROM `{table_name}`")
        total_rows = c.fetchone()[0]

        order_clause = ""
        if sort_col and sort_col in col_names:
            direction = "DESC" if sort_dir == "desc" else "ASC"
            order_clause = f"ORDER BY `{sort_col}` {direction}"

        if search:
            like_clauses = " OR ".join([f"CAST(`{col}` AS CHAR) LIKE %s" for col in col_names])
            c.execute(f"SELECT * FROM `{table_name}` WHERE {like_clauses} {order_clause} LIMIT %s OFFSET %s",
                      [f"%{search}%"] * len(col_names) + [per_page, offset])
        else:
            c.execute(f"SELECT * FROM `{table_name}` {order_clause} LIMIT %s OFFSET %s",
                      [per_page, offset])
        rows = c.fetchall()

    total_pages      = max(1, (total_rows + per_page - 1) // per_page)
    page_range_start = max(1, page - 3)
    page_range_end   = min(total_pages, page + 3)
    page_range       = range(page_range_start, page_range_end + 1)

    return render(request, "db_admin/table.html", {
        "tables":      tables,
        "table_name":  table_name,
        "columns":     columns,
        "rows":        rows,
        "search":      search,
        "sort_col":    sort_col,
        "sort_dir":    sort_dir,
        "page":        page,
        "per_page":    per_page,
        "total_rows":  total_rows,
        "total_pages": total_pages,
        "page_range":  page_range,
    })


@superuser_required
def db_sql(request):
    """SQL-Abfrage ausführen und Ergebnis als JSON zurückgeben."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        sql  = data.get("sql", "").strip()
    except Exception:
        return JsonResponse({"error": "Ungültige Anfrage"}, status=400)

    if not sql:
        return JsonResponse({"error": "Kein SQL eingegeben"}, status=400)

    try:
        with connection.cursor() as c:
            c.execute(sql)
            sql_upper = sql.upper().lstrip()
            if sql_upper.startswith("SELECT") or sql_upper.startswith("SHOW") or sql_upper.startswith("DESCRIBE"):
                cols = [desc[0] for desc in c.description] if c.description else []
                rows = c.fetchall()
                rows_serializable = [[str(v) if v is not None else None for v in row] for row in rows]
                return JsonResponse({
                    "type":    "select",
                    "columns": cols,
                    "rows":    rows_serializable,
                    "count":   len(rows),
                })
            else:
                return JsonResponse({
                    "type":         "exec",
                    "rows_affected": c.rowcount,
                })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)
