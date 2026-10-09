"""Keeps Django away from the WordPress database.

The connection "wordpress" is for reading only. Django must never create its
own tables there (migrate) and no model may ever be written to it. The
session is also set to READ ONLY in settings.py, so MySQL itself refuses a
write - this router is the second lock, not the only one.
"""


class WordPressReadOnlyRouter:
    alias = 'wordpress'

    def db_for_read(self, model, **hints):
        return None          # our own models live in "default"

    def db_for_write(self, model, **hints):
        return None          # never "wordpress"

    def allow_relation(self, obj1, obj2, **hints):
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == self.alias:
            return False     # no Django tables in the WordPress database
        return None
