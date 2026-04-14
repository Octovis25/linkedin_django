#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User

for user in User.objects.all():
    if not user.first_name or not user.last_name:
        email_prefix = user.email.split('@')[0]
        parts = email_prefix.split('.')
        
        if len(parts) >= 2:
            user.first_name = parts[0].capitalize()
            user.last_name = parts[1].capitalize()
        else:
            user.first_name = email_prefix.capitalize()
            user.last_name = "User"
        
        user.save()
        print(f"✅ {user.username}: {user.get_full_name()}")

print("\n✅ Fertig!")
