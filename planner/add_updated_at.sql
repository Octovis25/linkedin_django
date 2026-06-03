-- Migration: neue Spalten zu planner_posts hinzufügen
-- Einmalig in DB Verwaltung ausführen

ALTER TABLE planner_posts
  ADD COLUMN IF NOT EXISTS updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  ADD COLUMN IF NOT EXISTS link VARCHAR(512) DEFAULT NULL;
