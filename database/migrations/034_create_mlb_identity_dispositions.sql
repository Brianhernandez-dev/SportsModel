-- MLB event disposition is NOT an effective Odds identity correction (033).
CREATE TABLE game_identity_dispositions (
    disposition_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain TEXT NOT NULL CHECK (domain = 'MLB'),
    subject_game_id INTEGER NOT NULL UNIQUE REFERENCES games(game_id) ON DELETE RESTRICT,
    survivor_game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE RESTRICT,
    disposition_type TEXT NOT NULL CHECK (disposition_type = 'STALE_MARKET_ONLY_DUPLICATE'),
    policy_version TEXT NOT NULL CHECK (policy_version = '1.0.0'),
    reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
    evidence_reference TEXT NOT NULL CHECK (length(btrim(evidence_reference)) > 0),
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    operator_identity TEXT NOT NULL CHECK (length(btrim(operator_identity)) > 0),
    tool_identity TEXT NOT NULL CHECK (length(btrim(tool_identity)) > 0),
    implementation_commit TEXT NOT NULL CHECK (implementation_commit ~ '^[0-9a-f]{40}$'),
    implementation_sha256 TEXT NOT NULL CHECK (implementation_sha256 ~ '^[0-9a-f]{64}$'),
    initial_manifest_sha256 TEXT NOT NULL UNIQUE CHECK (initial_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    CHECK (subject_game_id > 0 AND survivor_game_id > 0 AND subject_game_id <> survivor_game_id)
);
CREATE TABLE game_identity_disposition_events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    disposition_id BIGINT NOT NULL REFERENCES game_identity_dispositions(disposition_id) ON DELETE RESTRICT,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    previous_event_id BIGINT UNIQUE,
    action TEXT NOT NULL CHECK (action IN ('ACTIVATE', 'REVOKE')),
    reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
    evidence_reference TEXT NOT NULL CHECK (length(btrim(evidence_reference)) > 0),
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    operator_identity TEXT NOT NULL CHECK (length(btrim(operator_identity)) > 0),
    tool_identity TEXT NOT NULL CHECK (length(btrim(tool_identity)) > 0),
    implementation_commit TEXT NOT NULL CHECK (implementation_commit ~ '^[0-9a-f]{40}$'),
    implementation_sha256 TEXT NOT NULL CHECK (implementation_sha256 ~ '^[0-9a-f]{64}$'),
    approved_manifest_sha256 TEXT NOT NULL UNIQUE CHECK (approved_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    pre_state_sha256 TEXT NOT NULL CHECK (pre_state_sha256 ~ '^[0-9a-f]{64}$'),
    post_state_sha256 TEXT NOT NULL CHECK (post_state_sha256 ~ '^[0-9a-f]{64}$'),
    receipt JSONB NOT NULL CHECK (jsonb_typeof(receipt) = 'object'),
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (disposition_id, sequence),
    UNIQUE (disposition_id, event_id),
    FOREIGN KEY (disposition_id, previous_event_id)
        REFERENCES game_identity_disposition_events(disposition_id, event_id) ON DELETE RESTRICT,
    CHECK ((sequence = 1 AND previous_event_id IS NULL AND action = 'ACTIVATE')
        OR (sequence > 1 AND previous_event_id IS NOT NULL))
);
CREATE INDEX game_identity_disposition_survivor_idx ON game_identity_dispositions(survivor_game_id);
CREATE TABLE mlb_game_identity_write_fences (
    game_id INTEGER PRIMARY KEY REFERENCES games(game_id) ON DELETE RESTRICT,
    epoch BIGINT NOT NULL CHECK (epoch > 0)
);
CREATE VIEW mlb_active_stale_identity_dispositions AS
SELECT d.*, e.event_id, e.sequence, e.created_at AS state_recorded_at,
       e.approved_manifest_sha256
FROM game_identity_dispositions d JOIN LATERAL (
    SELECT * FROM game_identity_disposition_events ev
    WHERE ev.disposition_id = d.disposition_id ORDER BY sequence DESC LIMIT 1
) e ON TRUE WHERE e.action = 'ACTIVATE';

-- Two-key, transaction-scoped gate. Statement ingress on shared tables necessarily
-- couples unrelated writes too, but their row semantics/fences remain unchanged.
CREATE FUNCTION mlb_identity_gate(exclusive_mode BOOLEAN DEFAULT FALSE) RETURNS VOID
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE held TEXT;
BEGIN
    IF (SELECT setting::bigint FROM pg_settings WHERE name='lock_timeout') = 0
       OR (SELECT setting::bigint FROM pg_settings WHERE name='lock_timeout') > 5000 THEN
        PERFORM set_config('lock_timeout', '5s', true);
    END IF;
    IF (SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout') = 0
       OR (SELECT setting::bigint FROM pg_settings WHERE name='statement_timeout') > 30000 THEN
        PERFORM set_config('statement_timeout', '30s', true);
    END IF;
    SELECT mode INTO held FROM pg_locks
      WHERE pid = pg_backend_pid() AND locktype = 'advisory' AND granted
        AND classid = 1397574724 AND objid = 34 AND objsubid = 2
      ORDER BY mode LIMIT 1;
    IF held = 'ExclusiveLock' THEN RETURN; END IF;
    IF exclusive_mode THEN
        IF held IS NOT NULL THEN RAISE EXCEPTION 'MLB identity gate promotion prohibited'; END IF;
        PERFORM pg_advisory_xact_lock(1397574724, 34);
    ELSIF held IS NULL THEN
        PERFORM pg_advisory_xact_lock_shared(1397574724, 34);
    END IF;
END $$;

CREATE FUNCTION mlb_identity_ingress() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    PERFORM public.mlb_identity_gate(TG_ARGV[0] = 'exclusive');
    RETURN NULL;
END $$;

-- SECURITY DEFINER is needed for restricted writers; no caller SQL/search-path.
CREATE FUNCTION mlb_identity_touch_fence(gid INTEGER) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE value BIGINT;
BEGIN
    IF gid IS NULL OR gid <= 0 THEN RAISE EXCEPTION 'Invalid fence identity'; END IF;
    PERFORM public.mlb_identity_gate(false);
    INSERT INTO public.mlb_game_identity_write_fences(game_id, epoch) VALUES(gid, 1)
    ON CONFLICT(game_id) DO UPDATE SET epoch = mlb_game_identity_write_fences.epoch + 1
      WHERE mlb_game_identity_write_fences.epoch < 9223372036854775807
    RETURNING epoch INTO value;
    IF value IS NULL THEN RAISE EXCEPTION 'MLB identity fence overflow'; END IF;
    RETURN value;
END $$;

CREATE FUNCTION mlb_identity_fence_integrity() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN RAISE EXCEPTION 'Fence removal prohibited'; END IF;
    IF TG_OP = 'UPDATE' AND (NEW.game_id <> OLD.game_id OR NEW.epoch <> OLD.epoch + 1) THEN
        RAISE EXCEPTION 'Fence reset or non-monotonic write prohibited';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_fence_row BEFORE UPDATE OR DELETE ON mlb_game_identity_write_fences
FOR EACH ROW EXECUTE FUNCTION mlb_identity_fence_integrity();
CREATE TRIGGER mlb_fence_truncate BEFORE TRUNCATE ON mlb_game_identity_write_fences
FOR EACH STATEMENT EXECUTE FUNCTION mlb_identity_fence_integrity();

CREATE FUNCTION mlb_identity_is_stale(gid INTEGER) RETURNS BOOLEAN
LANGUAGE sql VOLATILE SET search_path = pg_catalog, public AS $$
    SELECT EXISTS(SELECT 1 FROM public.mlb_active_stale_identity_dispositions WHERE subject_game_id = gid)
$$;
CREATE FUNCTION mlb_identity_assert_active(gid INTEGER) RETURNS BOOLEAN
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $$
BEGIN
    IF public.mlb_identity_is_stale(gid) THEN RAISE EXCEPTION 'Active stale MLB identity is ineligible'; END IF;
    RETURN TRUE;
END $$;

CREATE FUNCTION mlb_identity_ledger_fingerprint() RETURNS TEXT
LANGUAGE sql STABLE SET search_path = pg_catalog, public AS $$
    SELECT encode(sha256(jsonb_build_object(
      'cases', (SELECT coalesce(jsonb_agg(to_jsonb(d) ORDER BY subject_game_id), '[]'::jsonb)
                  FROM public.game_identity_dispositions d),
      'events', (SELECT coalesce(jsonb_agg(to_jsonb(e)-'receipt' ORDER BY disposition_id, sequence), '[]'::jsonb)
                   FROM public.game_identity_disposition_events e))::text::bytea), 'hex')
$$;
CREATE FUNCTION mlb_identity_history_guard() RETURNS BOOLEAN
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $$
DECLARE proof JSONB; subject INTEGER;
BEGIN
    -- Append-only empty ledger proves no disposition knowledge was ever applied.
    IF NOT EXISTS(SELECT 1 FROM public.game_identity_dispositions) THEN RETURN TRUE; END IF;
    proof := nullif(current_setting('sportsmodel.identity_knowledge', true), '')::jsonb;
    IF proof IS NULL OR proof->>'version' <> '1'
      OR proof->>'available_at' IS NULL OR proof->>'cutoff_time' IS NULL
      OR proof->>'ledger_fingerprint' IS DISTINCT FROM public.mlb_identity_ledger_fingerprint()
      OR (proof->>'available_at')::timestamptz > (proof->>'cutoff_time')::timestamptz
      OR (proof->>'cutoff_time')::timestamptz > clock_timestamp() THEN
        RAISE EXCEPTION 'Missing/unavailable/changed committed MLB identity knowledge';
    END IF;
    FOR subject IN SELECT subject_game_id FROM public.mlb_active_stale_identity_dispositions LOOP
        IF public.mlb_identity_forbidden_dependencies(subject) <> '{}'::jsonb THEN
            RAISE EXCEPTION 'Active stale history/decision invariant violated';
        END IF;
    END LOOP;
    RETURN TRUE;
END $$;

-- Both catalog references and semantic references are checked. Market rows are
-- permitted provenance; indirect decisions using those rows are NOT permitted.
CREATE FUNCTION mlb_identity_forbidden_dependencies(gid INTEGER) RETURNS JSONB
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE r RECORD; n BIGINT; answer JSONB := '{}'::jsonb;
BEGIN
    FOR r IN SELECT DISTINCT c.table_name FROM information_schema.columns c
      WHERE c.table_schema = 'public' AND c.column_name = 'game_id'
        AND c.table_name NOT IN ('games', 'game_sources', 'odds_market_snapshots',
          'odds_market_snapshots_effective', 'odds_snapshots', 'mlb_game_identity_write_fences')
        AND c.table_name NOT LIKE 'nfl_%'
    LOOP
        EXECUTE format('SELECT count(*) FROM public.%I WHERE game_id=$1', r.table_name) INTO n USING gid;
        IF n > 0 THEN answer := answer || jsonb_build_object(r.table_name, n); END IF;
    END LOOP;
    SELECT count(*) INTO n FROM public.game_sources WHERE game_id = gid AND source_name <> 'odds_api';
    IF n > 0 THEN answer := answer || jsonb_build_object('non_odds_sources', n); END IF;
    SELECT count(*) INTO n FROM public.odds_provider_event_canonical_corrections
      WHERE original_game_id = gid OR corrected_game_id = gid;
    IF n > 0 THEN answer := answer || jsonb_build_object('033_corrections', n); END IF;
    SELECT count(*) INTO n FROM public.market_analysis m JOIN public.odds_market_snapshots s
      USING(odds_market_snapshot_id) WHERE s.game_id = gid;
    IF n > 0 THEN answer := answer || jsonb_build_object('market_analysis', n); END IF;
    SELECT count(*) INTO n FROM public.moneyline_prediction_market_evaluations e
      JOIN public.odds_market_snapshots s USING(odds_market_snapshot_id)
      JOIN public.moneyline_game_predictions p USING(moneyline_game_prediction_id)
      WHERE s.game_id = gid OR p.game_id = gid;
    IF n > 0 THEN answer := answer || jsonb_build_object('market_evaluations', n); END IF;
    RETURN answer;
END $$;

CREATE FUNCTION mlb_identity_pair_fingerprint(subject INTEGER, survivor INTEGER) RETURNS TEXT
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $$
DECLARE state JSONB;
BEGIN
    state := jsonb_build_object(
      'games', (SELECT coalesce(jsonb_agg(to_jsonb(g) ORDER BY game_id),'[]'::jsonb)
                   FROM public.games g WHERE game_id IN(subject,survivor)),
      'sources', (SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY game_source_id),'[]'::jsonb)
                   FROM public.game_sources s WHERE game_id IN(subject,survivor)),
      'snapshots', (SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY odds_market_snapshot_id),'[]'::jsonb)
                   FROM public.odds_market_snapshots s WHERE game_id IN(subject,survivor)),
      'observations', (SELECT coalesce(jsonb_agg(to_jsonb(o) ORDER BY odds_provider_event_observation_id),'[]'::jsonb)
                   FROM public.odds_provider_event_observations o WHERE EXISTS(
                    SELECT 1 FROM public.game_sources s WHERE s.game_id IN(subject,survivor)
                     AND s.source_name=o.source_name AND s.external_game_id=o.external_event_id)),
      'fences', (SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY game_id),'[]'::jsonb)
                   FROM public.mlb_game_identity_write_fences f WHERE game_id IN(subject,survivor)),
      'subject_dependencies', public.mlb_identity_forbidden_dependencies(subject),
      'survivor_dependencies', public.mlb_identity_forbidden_dependencies(survivor),
      'foreign_keys', (SELECT coalesce(jsonb_agg(jsonb_build_array(conname,conrelid::regclass::text,
                           pg_get_constraintdef(oid)) ORDER BY conrelid::regclass::text,conname),'[]'::jsonb)
                   FROM pg_constraint WHERE contype='f' AND confrelid='public.games'::regclass));
    state := state || jsonb_build_object(
      'teams', (SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY team_id),'[]'::jsonb) FROM public.teams t
                 WHERE team_id IN(SELECT home_team_id FROM public.games WHERE game_id IN(subject,survivor))
                    OR team_id IN(SELECT away_team_id FROM public.games WHERE game_id IN(subject,survivor))),
      'team_sources', (SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY baseball_team_source_id),'[]'::jsonb)
                 FROM public.baseball_team_sources t WHERE team_id IN(
                   SELECT home_team_id FROM public.games WHERE game_id IN(subject,survivor)
                   UNION SELECT away_team_id FROM public.games WHERE game_id IN(subject,survivor))),
      'runs', (SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY odds_ingestion_run_id),'[]'::jsonb)
                 FROM public.odds_ingestion_runs r WHERE odds_ingestion_run_id IN(
                   SELECT odds_ingestion_run_id FROM public.odds_market_snapshots WHERE game_id IN(subject,survivor))),
      'books', (SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY sportsbook_id),'[]'::jsonb)
                 FROM public.sportsbooks b WHERE sportsbook_id IN(
                   SELECT sportsbook_id FROM public.odds_market_snapshots WHERE game_id IN(subject,survivor))),
      'book_sources', (SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY sportsbook_provider_identity_id),'[]'::jsonb)
                 FROM public.sportsbook_provider_identities b WHERE sportsbook_provider_identity_id IN(
                   SELECT sportsbook_provider_identity_id FROM public.odds_market_snapshots WHERE game_id IN(subject,survivor))));
    RETURN encode(sha256(state::text::bytea),'hex');
END $$;

CREATE FUNCTION mlb_identity_validate_pair(subject INTEGER, survivor INTEGER, revoking BOOLEAN)
RETURNS VOID LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE s public.games%ROWTYPE; c public.games%ROWTYPE; n INTEGER;
BEGIN
    IF subject <= 0 OR survivor <= 0 OR subject = survivor THEN RAISE EXCEPTION 'Distinct positive identities required'; END IF;
    PERFORM game_id FROM public.games WHERE game_id IN (subject, survivor) ORDER BY game_id FOR UPDATE;
    SELECT * INTO STRICT s FROM public.games WHERE game_id = subject;
    SELECT * INTO STRICT c FROM public.games WHERE game_id = survivor;
    IF EXISTS(SELECT 1 FROM public.nfl_games WHERE game_id IN(subject,survivor)) THEN
        RAISE EXCEPTION 'Non-MLB identity cannot be dispositioned';
    END IF;
    IF s.home_team_id <> c.home_team_id OR s.away_team_id <> c.away_team_id
       OR s.home_team_id = s.away_team_id OR s.mlb_game_id IS NOT NULL THEN
        RAISE EXCEPTION 'MLB disposition orientation/legacy identity conflict';
    END IF;
    WITH valid(external_id,canonical_name) AS (VALUES
      ('108','Los Angeles Angels'),('109','Arizona Diamondbacks'),('110','Baltimore Orioles'),
      ('111','Boston Red Sox'),('112','Chicago Cubs'),('113','Cincinnati Reds'),
      ('114','Cleveland Guardians'),('115','Colorado Rockies'),('116','Detroit Tigers'),
      ('117','Houston Astros'),('118','Kansas City Royals'),('119','Los Angeles Dodgers'),
      ('120','Washington Nationals'),('121','New York Mets'),('133','Athletics'),
      ('134','Pittsburgh Pirates'),('135','San Diego Padres'),('136','Seattle Mariners'),
      ('137','San Francisco Giants'),('138','St. Louis Cardinals'),('139','Tampa Bay Rays'),
      ('140','Texas Rangers'),('141','Toronto Blue Jays'),('142','Minnesota Twins'),
      ('143','Philadelphia Phillies'),('144','Atlanta Braves'),('145','Chicago White Sox'),
      ('146','Miami Marlins'),('147','New York Yankees'),('158','Milwaukee Brewers'))
    SELECT count(DISTINCT t.team_id) INTO n FROM public.baseball_team_sources t
      JOIN public.teams club ON club.team_id=t.team_id
      JOIN valid ON valid.external_id=t.external_team_id AND valid.canonical_name=club.team_name
      WHERE t.source_name='mlb_stats' AND t.team_id IN(s.home_team_id,s.away_team_id);
    IF n <> 2 THEN RAISE EXCEPTION 'MLB canonical participants required'; END IF;
    SELECT count(*) INTO n FROM public.game_sources WHERE game_id = survivor AND source_name = 'mlb_stats';
    IF n <> 1 THEN RAISE EXCEPTION 'Survivor requires unique MLB anchor'; END IF;
    IF c.mlb_game_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.game_sources
      WHERE game_id = survivor AND source_name = 'mlb_stats' AND external_game_id = c.mlb_game_id::text) THEN
        RAISE EXCEPTION 'Survivor legacy MLB identity conflict';
    END IF;
    IF public.mlb_identity_forbidden_dependencies(subject) <> '{}'::jsonb THEN
        RAISE EXCEPTION 'Stale subject has prohibited dependencies';
    END IF;
    IF revoking AND (public.mlb_identity_forbidden_dependencies(survivor) - 'non_odds_sources') <> '{}'::jsonb THEN
        RAISE EXCEPTION 'Survivor history/decision state prevents reversal';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM public.game_sources WHERE game_id = subject AND source_name = 'odds_api')
       OR NOT EXISTS(SELECT 1 FROM public.odds_market_snapshots WHERE game_id = subject
                     AND odds_provider_event_observation_id IS NOT NULL) THEN
        RAISE EXCEPTION 'Subject requires retained MLB Odds acquisition provenance';
    END IF;
    IF EXISTS(SELECT 1 FROM public.odds_market_snapshots m
      JOIN public.odds_provider_event_observations o USING(odds_provider_event_observation_id)
      JOIN public.teams h ON h.team_id = s.home_team_id
      JOIN public.teams a ON a.team_id = s.away_team_id
      WHERE m.game_id = subject AND (o.source_name <> 'odds_api' OR o.provider_sport_key <> 'baseball_mlb'
        OR o.provider_home_team_name <> h.team_name OR o.provider_away_team_name <> a.team_name
        OR NOT EXISTS(SELECT 1 FROM public.game_sources gs WHERE gs.game_id=subject
                       AND gs.source_name=o.source_name AND gs.external_game_id=o.external_event_id))) THEN
        RAISE EXCEPTION 'Raw subject provenance orientation/source conflict';
    END IF;
END $$;

CREATE FUNCTION mlb_identity_case_insert() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.created_at IS NOT NULL THEN RAISE EXCEPTION 'Caller timestamps prohibited'; END IF;
    PERFORM public.mlb_identity_gate(true);
    PERFORM public.mlb_identity_validate_pair(NEW.subject_game_id, NEW.survivor_game_id, false);
    NEW.created_at := clock_timestamp();
    RETURN NEW;
END $$;
CREATE FUNCTION mlb_identity_case_complete() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NOT EXISTS(SELECT 1 FROM public.game_identity_disposition_events e
      WHERE e.disposition_id = NEW.disposition_id AND e.sequence = 1 AND e.action = 'ACTIVATE'
        AND e.approved_manifest_sha256 = NEW.initial_manifest_sha256) THEN
        RAISE EXCEPTION 'Case requires matching initial ACTIVATE at commit';
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER mlb_case_insert BEFORE INSERT ON game_identity_dispositions
FOR EACH ROW EXECUTE FUNCTION mlb_identity_case_insert();
CREATE CONSTRAINT TRIGGER mlb_case_complete AFTER INSERT ON game_identity_dispositions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mlb_identity_case_complete();

CREATE FUNCTION mlb_identity_event_insert() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE d public.game_identity_dispositions%ROWTYPE; prev public.game_identity_disposition_events%ROWTYPE; post_hash TEXT;
BEGIN
    IF NEW.created_at IS NOT NULL THEN RAISE EXCEPTION 'Caller timestamps prohibited'; END IF;
    PERFORM public.mlb_identity_gate(true);
    SELECT * INTO STRICT d FROM public.game_identity_dispositions WHERE disposition_id = NEW.disposition_id;
    PERFORM public.mlb_identity_validate_pair(d.subject_game_id, d.survivor_game_id, NEW.action = 'REVOKE');
    PERFORM disposition_id FROM public.game_identity_dispositions WHERE disposition_id = d.disposition_id FOR UPDATE;
    SELECT * INTO prev FROM public.game_identity_disposition_events WHERE disposition_id = d.disposition_id
      ORDER BY sequence DESC LIMIT 1;
    IF FOUND THEN
        IF NEW.sequence <> prev.sequence + 1 OR NEW.previous_event_id IS DISTINCT FROM prev.event_id
          OR NEW.action = prev.action OR NEW.evidence_sha256 = prev.evidence_sha256 THEN
            RAISE EXCEPTION 'Fresh evidence and alternating latest predecessor required';
        END IF;
    ELSIF NEW.sequence <> 1 OR NEW.previous_event_id IS NOT NULL OR NEW.action <> 'ACTIVATE'
      OR NEW.approved_manifest_sha256 <> d.initial_manifest_sha256 THEN
        RAISE EXCEPTION 'Invalid initial ACTIVATE';
    END IF;
    IF NEW.action = 'ACTIVATE' AND EXISTS(SELECT 1 FROM public.mlb_active_stale_identity_dispositions x
      WHERE x.subject_game_id = d.survivor_game_id OR x.survivor_game_id = d.subject_game_id) THEN
        RAISE EXCEPTION 'Disposition chains/cycles prohibited';
    END IF;
    IF NEW.action = 'REVOKE' AND EXISTS(SELECT 1 FROM public.mlb_active_stale_identity_dispositions x
      WHERE x.survivor_game_id = d.survivor_game_id AND x.disposition_id <> d.disposition_id) THEN
        RAISE EXCEPTION 'Dependent active case prevents reversal';
    END IF;
    PERFORM public.mlb_identity_touch_fence(least(d.subject_game_id, d.survivor_game_id));
    PERFORM public.mlb_identity_touch_fence(greatest(d.subject_game_id, d.survivor_game_id));
    NEW.created_at := clock_timestamp();
    SELECT encode(sha256(jsonb_build_object(
      'cases', (SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY subject_game_id),'[]'::jsonb)
                   FROM public.game_identity_dispositions c),
      'events', (SELECT jsonb_agg(x.row ORDER BY (x.row->>'disposition_id')::bigint,(x.row->>'sequence')::integer)
                   FROM (SELECT to_jsonb(e)-'receipt' AS row FROM public.game_identity_disposition_events e
                         UNION ALL SELECT to_jsonb(NEW)-'receipt') x))::text::bytea),'hex') INTO post_hash;
    NEW.receipt := NEW.receipt || jsonb_build_object('event_id',NEW.event_id,
       'ledger_fingerprint',post_hash,'pair_fingerprint',public.mlb_identity_pair_fingerprint(d.subject_game_id,d.survivor_game_id));
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_event_insert BEFORE INSERT ON game_identity_disposition_events
FOR EACH ROW EXECUTE FUNCTION mlb_identity_event_insert();

CREATE FUNCTION mlb_identity_immutable() RETURNS TRIGGER
LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Identity ledger mutation prohibited'; END $$;
CREATE TRIGGER mlb_case_immutable BEFORE UPDATE OR DELETE ON game_identity_dispositions
FOR EACH ROW EXECUTE FUNCTION mlb_identity_immutable();
CREATE TRIGGER mlb_event_immutable BEFORE UPDATE OR DELETE ON game_identity_disposition_events
FOR EACH ROW EXECUTE FUNCTION mlb_identity_immutable();
CREATE TRIGGER mlb_case_truncate BEFORE TRUNCATE ON game_identity_dispositions
FOR EACH STATEMENT EXECUTE FUNCTION mlb_identity_immutable();
CREATE TRIGGER mlb_event_truncate BEFORE TRUNCATE ON game_identity_disposition_events
FOR EACH STATEMENT EXECUTE FUNCTION mlb_identity_immutable();
CREATE TRIGGER mlb_case_ingress BEFORE INSERT ON game_identity_dispositions
FOR EACH STATEMENT EXECUTE FUNCTION mlb_identity_ingress('exclusive');
CREATE TRIGGER mlb_event_ingress BEFORE INSERT ON game_identity_disposition_events
FOR EACH STATEMENT EXECUTE FUNCTION mlb_identity_ingress('exclusive');

-- Resolve direct AND indirect decision links before checking stale eligibility.
CREATE FUNCTION mlb_identity_row_games(j JSONB) RETURNS INTEGER[]
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $$
DECLARE ids INTEGER[] := ARRAY[]::integer[]; value INTEGER; snapshot BIGINT; prediction BIGINT; evaluation BIGINT;
BEGIN
    IF j ? 'game_id' AND j->>'game_id' IS NOT NULL THEN ids := ids || (j->>'game_id')::integer; END IF;
    IF j ? 'original_game_id' AND j->>'original_game_id' IS NOT NULL THEN ids := ids || (j->>'original_game_id')::integer; END IF;
    IF j ? 'corrected_game_id' AND j->>'corrected_game_id' IS NOT NULL THEN ids := ids || (j->>'corrected_game_id')::integer; END IF;
    evaluation := (j->>'moneyline_prediction_market_evaluation_id')::bigint;
    prediction := (j->>'moneyline_game_prediction_id')::bigint;
    snapshot := (j->>'odds_market_snapshot_id')::bigint;
    IF evaluation IS NOT NULL AND NOT (j ? 'moneyline_game_prediction_id' OR j ? 'odds_market_snapshot_id') THEN
        SELECT moneyline_game_prediction_id, odds_market_snapshot_id INTO prediction, snapshot
          FROM public.moneyline_prediction_market_evaluations WHERE moneyline_prediction_market_evaluation_id = evaluation;
    END IF;
    IF prediction IS NOT NULL THEN
        SELECT game_id INTO value FROM public.moneyline_game_predictions WHERE moneyline_game_prediction_id = prediction;
        IF value IS NOT NULL THEN ids := ids || value; END IF;
    END IF;
    IF snapshot IS NOT NULL THEN
        SELECT game_id INTO value FROM public.odds_market_snapshots WHERE odds_market_snapshot_id = snapshot;
        IF value IS NOT NULL THEN ids := ids || value; END IF;
    END IF;
    RETURN ARRAY(SELECT DISTINCT unnest(ids) ORDER BY 1);
END $$;

CREATE FUNCTION mlb_identity_write_guard() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE j JSONB; oldj JSONB; ids INTEGER[]; gid INTEGER; raw_mapping INTEGER;
BEGIN
    j := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    oldj := CASE WHEN TG_OP = 'INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;
    ids := public.mlb_identity_row_games(j) || public.mlb_identity_row_games(oldj);
    IF TG_TABLE_NAME = 'odds_ingestion_runs' THEN
        ids := ids || ARRAY(SELECT DISTINCT game_id FROM public.odds_market_snapshots
            WHERE odds_ingestion_run_id=(j->>'odds_ingestion_run_id')::bigint);
    END IF;
    IF TG_TABLE_NAME IN ('teams','baseball_team_sources') THEN
        ids := ids || ARRAY(SELECT DISTINCT g.game_id FROM public.games g
          JOIN public.game_identity_dispositions d ON g.game_id IN(d.subject_game_id,d.survivor_game_id)
          WHERE (j->>'team_id')::integer IN(g.home_team_id,g.away_team_id)
             OR (oldj->>'team_id')::integer IN(g.home_team_id,g.away_team_id));
    END IF;
    IF TG_TABLE_NAME = 'odds_provider_event_observations' AND j->>'provider_sport_key' = 'baseball_mlb' THEN
        SELECT game_id INTO raw_mapping FROM public.game_sources
          WHERE source_name = j->>'source_name' AND external_game_id = j->>'external_event_id';
        IF raw_mapping IS NOT NULL THEN ids := ids || raw_mapping; END IF;
    END IF;
    FOR gid IN SELECT DISTINCT unnest(ids) ORDER BY 1 LOOP
        -- Restrict fences/semantics to known MLB rows or an explicit MLB ledger.
        IF EXISTS(SELECT 1 FROM public.game_identity_dispositions WHERE subject_game_id=gid OR survivor_game_id=gid)
          OR EXISTS(SELECT 1 FROM public.games g WHERE g.game_id=gid
              AND EXISTS(SELECT 1 FROM public.baseball_team_sources t WHERE t.team_id=g.home_team_id AND t.source_name='mlb_stats')
              AND EXISTS(SELECT 1 FROM public.baseball_team_sources t WHERE t.team_id=g.away_team_id AND t.source_name='mlb_stats')) THEN
            PERFORM public.mlb_identity_touch_fence(gid);
        END IF;
        IF TG_TABLE_NAME = 'games' AND TG_OP <> 'INSERT' AND EXISTS(
          SELECT 1 FROM public.game_identity_dispositions WHERE subject_game_id=gid OR survivor_game_id=gid) THEN
            IF TG_OP = 'DELETE' OR (j - ARRAY['scheduled_innings','doubleheader_status','game_number'])
               IS DISTINCT FROM (oldj - ARRAY['scheduled_innings','doubleheader_status','game_number']) THEN
                RAISE EXCEPTION 'Ledger-linked game identity immutable';
            END IF;
        END IF;
        IF TG_TABLE_NAME = 'game_sources' AND TG_OP <> 'INSERT' AND oldj->>'source_name'='mlb_stats'
          AND EXISTS(SELECT 1 FROM public.mlb_active_stale_identity_dispositions WHERE survivor_game_id=gid) THEN
            RAISE EXCEPTION 'Active survivor MLB anchor immutable';
        END IF;
        IF TG_TABLE_NAME IN ('game_sources','odds_market_snapshots','odds_provider_event_observations')
          AND TG_OP <> 'INSERT' AND EXISTS(SELECT 1 FROM public.game_identity_dispositions
              WHERE subject_game_id=gid OR survivor_game_id=gid) THEN
            RAISE EXCEPTION 'Ledger-linked raw provenance immutable, including after reversal';
        END IF;
        IF TG_TABLE_NAME IN ('teams','baseball_team_sources') AND EXISTS(
          SELECT 1 FROM public.game_identity_dispositions WHERE subject_game_id=gid OR survivor_game_id=gid) THEN
            RAISE EXCEPTION 'Ledger-linked MLB participant identity immutable';
        END IF;
        IF TG_TABLE_NAME = 'odds_ingestion_runs' AND EXISTS(SELECT 1 FROM public.game_identity_dispositions
              WHERE subject_game_id=gid OR survivor_game_id=gid) THEN
            IF TG_OP='UPDATE' AND (j - ARRAY['status','completed_at','games_returned','games_processed','selections_inserted','selections_skipped','error_message'])
               IS NOT DISTINCT FROM (oldj - ARRAY['status','completed_at','games_returned','games_processed','selections_inserted','selections_skipped','error_message']) THEN
                CONTINUE;
            END IF;
            RAISE EXCEPTION 'Ledger-linked acquisition run identity/timestamps immutable';
        END IF;
        IF public.mlb_identity_is_stale(gid) THEN
            IF TG_TABLE_NAME = 'odds_ingestion_runs' AND TG_OP='UPDATE'
              AND (j - ARRAY['status','completed_at','games_returned','games_processed','selections_inserted','selections_skipped','error_message'])
                IS NOT DISTINCT FROM (oldj - ARRAY['status','completed_at','games_returned','games_processed','selections_inserted','selections_skipped','error_message']) THEN
                CONTINUE;
            END IF;
            IF TG_TABLE_NAME = 'odds_provider_event_observations' AND TG_OP='INSERT'
              AND j->>'source_name'='odds_api' AND j->>'provider_sport_key'='baseball_mlb'
              AND EXISTS(SELECT 1 FROM public.games g JOIN public.teams h ON h.team_id=g.home_team_id
                JOIN public.teams a ON a.team_id=g.away_team_id WHERE g.game_id=gid
                AND h.team_name=j->>'provider_home_team_name' AND a.team_name=j->>'provider_away_team_name') THEN
                CONTINUE;
            END IF;
            IF TG_TABLE_NAME = 'odds_market_snapshots' AND TG_OP='INSERT'
              AND j->>'source_name'='odds_api' AND (j->>'game_id')::integer=gid
              AND EXISTS(SELECT 1 FROM public.odds_provider_event_observations o JOIN public.game_sources s
                ON s.source_name=o.source_name AND s.external_game_id=o.external_event_id
                WHERE o.odds_provider_event_observation_id=(j->>'odds_provider_event_observation_id')::bigint
                  AND o.provider_sport_key='baseball_mlb' AND s.game_id=gid) THEN
                CONTINUE;
            END IF;
            RAISE EXCEPTION 'Authoritative/decision write for active stale identity prohibited';
        END IF;
    END LOOP;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION mlb_identity_assert_decision_links(j JSONB) RETURNS BOOLEAN
LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $$
DECLARE gid INTEGER;
BEGIN
    PERFORM public.mlb_identity_gate(false);
    FOR gid IN SELECT unnest(public.mlb_identity_row_games(j)) ORDER BY 1 LOOP
        PERFORM public.mlb_identity_assert_active(gid);
    END LOOP;
    RETURN TRUE;
END $$;

CREATE FUNCTION mlb_identity_provenance_truncate() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    PERFORM public.mlb_identity_gate(false);
    IF EXISTS(SELECT 1 FROM public.game_identity_dispositions) THEN
        RAISE EXCEPTION 'TRUNCATE would destroy ledger-linked raw provenance';
    END IF;
    RETURN NULL;
END $$;
CREATE TRIGGER mlb_source_truncate BEFORE TRUNCATE ON game_sources
FOR EACH STATEMENT EXECUTE FUNCTION mlb_identity_provenance_truncate();
CREATE TRIGGER mlb_snapshot_truncate BEFORE TRUNCATE ON odds_market_snapshots
FOR EACH STATEMENT EXECUTE FUNCTION mlb_identity_provenance_truncate();
CREATE TRIGGER mlb_observation_truncate BEFORE TRUNCATE ON odds_provider_event_observations
FOR EACH STATEMENT EXECUTE FUNCTION mlb_identity_provenance_truncate();

-- Catalog-known optional legacy tables are guarded if present. NFL tables are
-- deliberately not selected; shared table statement ingress has documented coupling.
DO $$ DECLARE name TEXT; BEGIN
    FOREACH name IN ARRAY ARRAY['games','game_sources','historical_games','game_results',
       'teams','baseball_team_sources','sportsbooks','sportsbook_provider_identities','odds_ingestion_runs',
       'team_game_statistics','player_game_pitching_statistics','model_predictions',
       'moneyline_game_predictions','moneyline_prediction_market_evaluations',
       'moneyline_paper_candidate_settlements','market_analysis','odds_snapshots',
       'odds_market_snapshots','odds_provider_event_observations',
       'odds_provider_event_canonical_corrections'] LOOP
        IF to_regclass('public.' || name) IS NOT NULL THEN
            EXECUTE format('CREATE TRIGGER mlb_identity_ingress BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.mlb_identity_ingress(''shared'')', name);
            EXECUTE format('CREATE TRIGGER mlb_identity_write_guard BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.mlb_identity_write_guard()', name);
        END IF;
    END LOOP;
END $$;

REVOKE ALL ON game_identity_dispositions, game_identity_disposition_events,
    mlb_game_identity_write_fences FROM PUBLIC;
COMMENT ON TABLE game_identity_dispositions IS 'Immutable MLB event retirement association; no raw/effective market identity transfer';
COMMENT ON FUNCTION mlb_identity_gate(BOOLEAN) IS 'Transaction gate (1397574724,34); shared-table statement coupling bounded by lock_timeout';

-- NULL preserves the meaning of every pre-034 run; never backfill old knowledge.
ALTER TABLE moneyline_prediction_runs ADD COLUMN identity_disposition_knowledge JSONB;
ALTER TABLE moneyline_prediction_runs ADD CONSTRAINT chk_moneyline_identity_knowledge
CHECK (identity_disposition_knowledge IS NULL OR (
    jsonb_typeof(identity_disposition_knowledge)='object'
    AND identity_disposition_knowledge ?& ARRAY['version','ledger_fingerprint','artifact_sha256','available_at']
    AND identity_disposition_knowledge->>'version'='1'
    AND identity_disposition_knowledge->>'ledger_fingerprint' ~ '^[0-9a-f]{64}$'
    AND identity_disposition_knowledge->>'artifact_sha256' ~ '^[0-9a-f]{64}$'
    AND identity_disposition_knowledge->>'available_at' IS NOT NULL));
