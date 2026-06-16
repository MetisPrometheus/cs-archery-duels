-- players_clean — the view every dashboard analytics query reads from.
--
-- The daemon writes to `players`; the dashboard reads `players_clean`. This
-- keeps "which rows count as real players" in one place. Mirrors
-- cs-ocean-quest: only successfully-fetched rows, and a sanity guard on
-- playtime to drop any save with an absurd accumulated total (e.g. a
-- startTime=0 bug inflating a duration into a unix-timestamp-sized number).
--
-- Re-run after schema changes:  psql -d archery_duels -f players_clean_view.sql

CREATE OR REPLACE VIEW players_clean AS
SELECT *
FROM players
WHERE status = 'ok'
  AND COALESCE(playtime_seconds, 0) < 864000000;   -- < 10000 days

-- The view is created by the postgres superuser, so the project roles need
-- explicit SELECT (default-privilege grants only cover the creating role).
-- Re-applying this file re-grants — safe and idempotent.
GRANT SELECT ON players_clean TO archery_duels_rw;
GRANT SELECT ON players_clean TO archery_duels_ro;
