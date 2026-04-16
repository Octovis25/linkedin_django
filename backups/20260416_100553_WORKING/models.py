import re
from urllib.parse import unquote
from django.db import models
from django.core.exceptions import ValidationError

def extract_post_id(url):
    if not url: return None
    s = unquote(str(url)).strip().rstrip("/")
    m = re.search(r"urn:li:(?:activity|share|ugcpost):(\d+)", s, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r"(?:activity|share|ugcpost)[:%3A]+(\d+)", s, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r"(\d{10,})", s)
    return m.group(1) if m else None

class LinkedinPostPosted(models.Model):
    id = models.AutoField(primary_key=True)
    post_url = models.CharField(max_length=512, unique=True, verbose_name="Post-URL")
    post_id = models.CharField(max_length=30, unique=True, blank=True, null=True, verbose_name="Post-ID")
    created_at = models.DateTimeField(blank=True, null=True, verbose_name="Erstellt am")
    post_date = models.DateField(blank=True, null=True, verbose_name="Tatsaechlich gepostet am")
    post_image = models.CharField(max_length=512, blank=True, null=True, verbose_name="Post-Bild")

    class Meta:
        db_table = "linkedin_posts_posted"
        managed = False
        ordering = ["-post_date"]

    def clean(self):
        extracted = extract_post_id(self.post_url)
        if not extracted:
            raise ValidationError({"post_url": "Keine post_id im Link gefunden."})
        self.post_id = extracted
        qs = LinkedinPostPosted.objects.filter(post_id=self.post_id)
        if self.pk: qs = qs.exclude(pk=self.pk)
        if qs.exists():
            raise ValidationError({"post_url": "Post mit ID {} existiert bereits!".format(self.post_id)})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("UPDATE linkedin_posts SET post_date=%s WHERE post_id=%s AND (post_date IS NULL OR post_date!=%s)",
                [self.post_date, self.post_id, self.post_date])
