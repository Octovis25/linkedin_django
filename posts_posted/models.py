from django.db import models
from django.core.exceptions import ValidationError

class LinkedinPostPosted(models.Model):
    post_id = models.CharField(max_length=30, unique=True, verbose_name="Post-ID")
    post_date = models.DateField(verbose_name="Tatsaechlich gepostet am")
    post_image = models.ImageField(upload_to="post_images/", blank=True, null=True, verbose_name="Post-Bild")

    class Meta:
        db_table = "linkedin_posts_posted"
        managed = False
        ordering = ["-post_date"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute("UPDATE linkedin_posts SET post_date=%s WHERE post_id=%s AND (post_date IS NULL OR post_date!=%s)",
                [self.post_date, self.post_id, self.post_date])
