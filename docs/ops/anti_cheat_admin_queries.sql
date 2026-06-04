-- ADR-0026 L2 + L3 owner admin queries — DEFERRED.
--
-- This file is a placeholder for the SQL views + ad-hoc queries used
-- by the owner-side abuse review workflow. L2 (anomaly scoring) and
-- L3 (shadow-ban writes) are not yet implemented; queries below are
-- skeletons of what they will look like once those layers ship.
--
-- See ADR-0026 §"7-gate rollout plan" item 5 for the activation
-- criteria.

-- 1. Per-user 7-day XP total + audit row count.
--    SELECT user_id, sum(xp_delta) AS xp_7d, count(*) AS awards_7d
--      FROM leaderboard_audit
--     WHERE created_at >= now() - interval '7 days'
--     GROUP BY user_id
--     ORDER BY xp_7d DESC
--     LIMIT 50;

-- 2. Region change history per user (for spoofing review).
--    SELECT user_id, old_region, new_region, changed_at
--      FROM profile_region_change_audit
--     ORDER BY changed_at DESC
--     LIMIT 100;

-- 3. Active shadow-bans.
--    SELECT user_id, reason, score, banned_at
--      FROM gamification_shadow_ban
--     WHERE lifted_at IS NULL
--     ORDER BY banned_at DESC;

-- 4. Lift a shadow-ban (manual owner action).
--    UPDATE gamification_shadow_ban
--       SET lifted_at = now()
--     WHERE user_id = '<uuid>' AND lifted_at IS NULL;
