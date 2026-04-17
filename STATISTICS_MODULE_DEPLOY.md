# Statistics Module Deployment Guide

## What was created?

A fully encapsulated statistics module with:
- ✅ Folder structure with `stat_` prefix on all files
- ✅ Simple overview page with 4 KPI cards
- ✅ Date range filter (ready for future reports)
- ✅ Reusable utility functions
- ✅ Octotrial design integration

---

## Files Created

```
statistics/
├── __init__.py
├── stat_apps.py          ← Django app config
├── stat_urls.py          ← All routes
├── stat_views.py         ← View functions
├── stat_utils.py         ← Shared helpers (date filters, formatting)
│
├── reports/
│   ├── __init__.py
│   └── stat_overview.py  ← Overview KPI logic
│
└── templates/statistics/
    ├── stat_base.html    ← Base template with date filter
    └── stat_overview.html ← KPI cards display
```

---

## Integration Steps

### 1. Add to INSTALLED_APPS

Edit `dashboard/settings.py`:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "posts_posted",
    "collectives",
    "statistics",  # ← ADD THIS
]
```

### 2. Add to URL Configuration

Edit `dashboard/urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('data/posts/', include('posts_posted.urls')),
    path('collectives/', include('collectives.urls')),
    path('statistics/', include('statistics.stat_urls')),  # ← ADD THIS
]
```

### 3. Add to Navigation (Optional)

Edit `core/templates/core/base.html` to add a navigation link:

```html
<nav>
    <a href="/">Dashboard</a>
    <a href="/data/posts/">Data</a>
    <a href="/collectives/">Collectives</a>
    <a href="/statistics/">Statistics</a>  <!-- ADD THIS -->
</nav>
```

### 4. Update Models (Later)

The `stat_overview.py` currently has placeholders. Once you verify the actual model structure from `dashboard` app, update:

```python
# In statistics/reports/stat_overview.py

# Add actual imports:
from dashboard.models import Follower, Visitor, Content

# Then update the logic in get_overview_data()
```

---

## Deploy to Render.com

```bash
# 1. Add files to git
git add statistics/
git add STATISTICS_MODULE_DEPLOY.md

# 2. Commit
git commit -m "Add statistics module - Step 1: Overview"

# 3. Push to GitHub
git push origin main
```

Render.com will automatically detect the changes and redeploy (~2-3 minutes).

---

## Access the Module

After deployment, visit:

```
https://your-app.onrender.com/statistics/
```

You'll see:
- 4 KPI cards (some with placeholders until models are connected)
- Date range filter (functional, ready for future reports)
- Top 3 recent posts
- Octotrial design styling

---

## Next Steps

- ✅ **Step 1 complete:** Overview with KPI cards
- ⏳ **Step 2:** Make posts clickable → detail view
- ⏳ **Step 3:** Add timeline with charts
- ⏳ **Step 4:** Follower growth, competitor analysis

---

## Troubleshooting

**Module not found error?**
→ Make sure `statistics` is in `INSTALLED_APPS`

**Template not found?**
→ Run `python manage.py collectstatic` (or restart server locally)

**No data showing?**
→ Normal! Update `stat_overview.py` with actual model queries once you know the structure

---

**Ready to deploy?** Just push to GitHub and Render will handle the rest!
