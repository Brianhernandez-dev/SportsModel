-- Additive successor. No 034 function/view/constraint is replaced.
CREATE TABLE mlb_identity_topology_fence (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton), epoch BIGINT NOT NULL CHECK(epoch > 0)
);
INSERT INTO mlb_identity_topology_fence VALUES(TRUE,1);
CREATE TABLE mlb_legacy_identity_retirements (
    retirement_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain TEXT NOT NULL CHECK(domain='MLB'),
    subject_game_id INTEGER NOT NULL UNIQUE REFERENCES games(game_id) ON DELETE RESTRICT,
    survivor_game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE RESTRICT,
    game_pk INTEGER NOT NULL CHECK(game_pk>0),
    category TEXT NOT NULL CHECK(category IN('LEGACY_MARKET_DUPLICATE_WITHOUT_OBSERVATION_PROVENANCE','IDENTITY_ONLY_DUPLICATE')),
    policy_version TEXT NOT NULL CHECK(policy_version='1.0.0'),
    proof JSONB NOT NULL CHECK(jsonb_typeof(proof)='object'),
    evidence_reference TEXT NOT NULL CHECK(length(btrim(evidence_reference)) BETWEEN 1 AND 1000),
    evidence_sha256 TEXT NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
    approved_preview_sha256 TEXT NOT NULL UNIQUE CHECK(approved_preview_sha256 ~ '^[0-9a-f]{64}$'),
    operator_identity TEXT NOT NULL CHECK(length(btrim(operator_identity)) BETWEEN 1 AND 1000),
    tool_identity TEXT NOT NULL CHECK(length(btrim(tool_identity)) BETWEEN 1 AND 1000),
    implementation_commit TEXT NOT NULL CHECK(implementation_commit ~ '^[0-9a-f]{40}$'),
    implementation_sha256 TEXT NOT NULL CHECK(implementation_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL,
    CHECK(subject_game_id>0 AND survivor_game_id>0 AND subject_game_id<>survivor_game_id)
);
CREATE TABLE mlb_legacy_identity_retirement_events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    retirement_id BIGINT NOT NULL UNIQUE REFERENCES mlb_legacy_identity_retirements(retirement_id) ON DELETE RESTRICT,
    action TEXT NOT NULL CHECK(action='ACTIVATE'), sequence INTEGER NOT NULL CHECK(sequence=1),
    approved_preview_sha256 TEXT NOT NULL UNIQUE CHECK(approved_preview_sha256 ~ '^[0-9a-f]{64}$'),
    pre_state_sha256 TEXT NOT NULL CHECK(pre_state_sha256 ~ '^[0-9a-f]{64}$'),
    post_state_sha256 TEXT NOT NULL CHECK(post_state_sha256 ~ '^[0-9a-f]{64}$'),
    receipt JSONB NOT NULL CHECK(jsonb_typeof(receipt)='object'), created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX mlb_legacy_survivor_idx ON mlb_legacy_identity_retirements(survivor_game_id);
CREATE VIEW mlb_active_retired_identities AS
SELECT '034'::text AS origin, disposition_id AS case_id,subject_game_id,survivor_game_id,
       disposition_type AS category,event_id,sequence,state_recorded_at
FROM mlb_active_stale_identity_dispositions
UNION ALL
SELECT '035'::text, r.retirement_id,r.subject_game_id,r.survivor_game_id,r.category,
       e.event_id,e.sequence,e.created_at
FROM mlb_legacy_identity_retirements r JOIN mlb_legacy_identity_retirement_events e USING(retirement_id);
CREATE VIEW mlb_eligible_active_market_snapshots AS
-- Do not expose a bare game_id: frozen034's conservative dependency scanner
-- treats unknown relations with that column as authoritative/decision state.
SELECT m.odds_market_snapshot_id,m.game_id AS physical_game_id,m.sportsbook_id,
 m.market_type,m.selection_name,m.line_value,m.price,m.snapshot_time,m.source_name,
 m.created_at,m.odds_ingestion_run_id,m.odds_provider_event_observation_id,
 m.sportsbook_provider_identity_id,m.bookmaker_title_at_observation,
 m.bookmaker_updated_at,m.market_updated_at,m.observed_at
FROM odds_market_snapshots m WHERE NOT EXISTS(
    SELECT 1 FROM mlb_active_retired_identities r WHERE r.subject_game_id=m.game_id);

CREATE FUNCTION mlb_retirement_topology_integrity() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN
    IF TG_OP<>'UPDATE' OR NEW.singleton IS DISTINCT FROM OLD.singleton
      OR NEW.epoch<>OLD.epoch+1 THEN RAISE EXCEPTION 'Topology reset/removal prohibited'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_topology_row BEFORE INSERT OR UPDATE OR DELETE ON mlb_identity_topology_fence
FOR EACH ROW EXECUTE FUNCTION mlb_retirement_topology_integrity();
CREATE TRIGGER mlb_topology_truncate BEFORE TRUNCATE ON mlb_identity_topology_fence
FOR EACH STATEMENT EXECUTE FUNCTION mlb_retirement_topology_integrity();
CREATE FUNCTION mlb_retirement_topology_fresh() RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$ DECLARE value BIGINT; BEGIN
    PERFORM public.mlb_identity_gate(false);
    SELECT epoch INTO STRICT value FROM public.mlb_identity_topology_fence WHERE singleton FOR SHARE;
    RETURN value;
END $$;
CREATE FUNCTION mlb_retirement_ledger_ingress() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$ BEGIN
    PERFORM public.mlb_identity_gate(true);
    UPDATE public.mlb_identity_topology_fence SET epoch=epoch+1
      WHERE singleton AND epoch<9223372036854775807;
    IF NOT FOUND THEN RAISE EXCEPTION 'Missing/overflow topology fence'; END IF;
    IF EXISTS(SELECT 1 FROM pg_catalog.pg_constraint k JOIN pg_catalog.pg_class c ON c.oid=k.conrelid
      WHERE k.contype='f' AND c.relnamespace='public'::regnamespace AND k.confrelid IN(
        'public.games'::regclass,'public.odds_market_snapshots'::regclass,
        'public.moneyline_prediction_runs'::regclass,'public.moneyline_game_predictions'::regclass,
        'public.moneyline_prediction_market_evaluations'::regclass)
      AND left(c.relname,4)<>'nfl_' AND c.relname NOT IN(
        'games','game_sources','historical_games','game_results','teams','baseball_team_sources','sportsbooks','sportsbook_provider_identities',
        'odds_ingestion_runs','team_game_statistics','player_game_pitching_statistics','model_predictions','moneyline_game_predictions',
        'moneyline_prediction_market_evaluations','moneyline_paper_candidate_settlements','market_analysis','odds_snapshots',
        'odds_market_snapshots','odds_provider_event_observations','odds_provider_event_canonical_corrections',
        'game_identity_dispositions','mlb_legacy_identity_retirements','mlb_game_identity_write_fences','moneyline_daily_workflow_runs')) THEN
      RAISE EXCEPTION 'Unknown semantic foreign-key dependency'; END IF;
    IF EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
      WHERE c.relnamespace='public'::regnamespace AND c.relkind IN('r','p')
      AND a.attnum>0 AND NOT a.attisdropped
      AND a.attname IN('game_id','original_game_id','corrected_game_id',
        'odds_market_snapshot_id','moneyline_game_prediction_id','moneyline_prediction_market_evaluation_id')
      AND left(c.relname,4)<>'nfl_' AND c.relname NOT IN(
        'games','game_sources','historical_games','game_results','teams','baseball_team_sources','sportsbooks','sportsbook_provider_identities',
        'odds_ingestion_runs','team_game_statistics','player_game_pitching_statistics','model_predictions','moneyline_game_predictions',
        'moneyline_prediction_market_evaluations','moneyline_paper_candidate_settlements','market_analysis','odds_snapshots',
        'odds_market_snapshots','odds_provider_event_observations','odds_provider_event_canonical_corrections',
        'game_identity_dispositions','mlb_legacy_identity_retirements','mlb_game_identity_write_fences','moneyline_daily_workflow_runs')) THEN
      RAISE EXCEPTION 'Unknown semantic column dependency'; END IF;
    RETURN NULL;
END $$;
-- BEFORE STATEMENT precedes every BEFORE ROW trigger. Alphabetical name also
-- puts this ingress before unchanged 034 statement triggers of the same kind.
DO $$ DECLARE name TEXT; BEGIN
    FOREACH name IN ARRAY ARRAY['game_identity_dispositions','game_identity_disposition_events',
      'mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events'] LOOP
      EXECUTE format('CREATE TRIGGER mlb_035_topology_ingress BEFORE INSERT ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.mlb_retirement_ledger_ingress()',name);
    END LOOP;
END $$;
CREATE FUNCTION mlb_identity_is_retired(gid INTEGER) RETURNS BOOLEAN
LANGUAGE sql VOLATILE SET search_path=pg_catalog,public AS $$
    SELECT EXISTS(SELECT 1 FROM public.mlb_active_retired_identities WHERE subject_game_id=gid)
$$;
CREATE FUNCTION mlb_retirement_assert_active(gid INTEGER) RETURNS BOOLEAN
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$ BEGIN
    IF gid IS NULL OR gid<=0 THEN RAISE EXCEPTION 'Positive physical identity required'; END IF;
    IF public.mlb_identity_is_retired(gid) THEN RAISE EXCEPTION 'Retired MLB identity ineligible'; END IF;
    RETURN TRUE;
END $$;
-- Preserve the frozen033 projection/correction meaning; eligibility is additive
-- and checks BOTH physical acquisition and effective decision identities.
CREATE FUNCTION mlb_retirement_effective_markets() RETURNS SETOF public.odds_market_snapshots_effective
LANGUAGE sql VOLATILE SET search_path=pg_catalog,public AS $$
 SELECT e.* FROM public.odds_market_snapshots_effective e WHERE NOT EXISTS(
   SELECT 1 FROM public.mlb_active_retired_identities r
   WHERE r.subject_game_id IN(e.raw_acquisition_game_id,e.effective_game_id))
$$;
CREATE FUNCTION mlb_retirement_legacy_fingerprint() RETURNS TEXT
LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT encode(sha256(jsonb_build_object(
   'cases',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY subject_game_id),'[]'::jsonb) FROM public.mlb_legacy_identity_retirements r),
   'events',(SELECT coalesce(jsonb_agg(to_jsonb(e)-ARRAY['receipt','post_state_sha256'] ORDER BY retirement_id),'[]'::jsonb) FROM public.mlb_legacy_identity_retirement_events e)
 )::text::bytea),'hex')
$$;
CREATE FUNCTION mlb_retirement_fingerprint(profile TEXT) RETURNS TEXT
LANGUAGE sql STABLE SET search_path=pg_catalog,public AS $$
 SELECT encode(sha256(jsonb_build_object('domain','MLB_RETIREMENT_KNOWLEDGE_V2','version',2,
   'profile',profile,'ledger034',public.mlb_identity_ledger_fingerprint(),
   'ledger035',public.mlb_retirement_legacy_fingerprint(),
   'topology',(SELECT epoch FROM public.mlb_identity_topology_fence WHERE singleton))::text::bytea),'hex')
$$;
CREATE FUNCTION mlb_retirement_cross_pair(subject INTEGER,survivor INTEGER,pk INTEGER,origin TEXT) RETURNS VOID
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN
    IF subject IS NULL OR survivor IS NULL OR subject<=0 OR survivor<=0 OR subject=survivor
      OR pk IS NULL OR pk<=0 THEN RAISE EXCEPTION 'Distinct fixed MLB pair required'; END IF;
    IF EXISTS(SELECT 1 FROM public.game_identity_dispositions WHERE
       survivor_game_id=subject OR subject_game_id=survivor OR (origin='035' AND subject_game_id=subject))
      OR EXISTS(SELECT 1 FROM public.mlb_legacy_identity_retirements WHERE
       survivor_game_id=subject OR subject_game_id=survivor OR (origin='034' AND subject_game_id=subject)) THEN
      RAISE EXCEPTION 'Cross-ledger lifetime role/case conflict'; END IF;
    IF EXISTS(SELECT 1 FROM public.mlb_active_retired_identities r JOIN public.game_sources s ON s.game_id=r.survivor_game_id
      WHERE s.source_name='mlb_stats' AND s.external_game_id=pk::text AND r.survivor_game_id<>survivor) THEN
      RAISE EXCEPTION 'Conflicting canonical survivor'; END IF;
END $$;
CREATE FUNCTION mlb_retirement_034_cross_guard() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ DECLARE d public.game_identity_dispositions%ROWTYPE; pk INTEGER; BEGIN
    IF TG_TABLE_NAME='game_identity_dispositions' THEN d:=NEW;
    ELSE SELECT * INTO STRICT d FROM public.game_identity_dispositions WHERE disposition_id=NEW.disposition_id; END IF;
    SELECT external_game_id::integer INTO STRICT pk FROM public.game_sources WHERE game_id=d.survivor_game_id AND source_name='mlb_stats';
    PERFORM public.mlb_retirement_cross_pair(d.subject_game_id,d.survivor_game_id,pk,'034');
    IF TG_TABLE_NAME='game_identity_disposition_events' THEN
      IF NEW.action='REVOKE' AND EXISTS(SELECT 1 FROM public.mlb_legacy_identity_retirements
          WHERE survivor_game_id=d.survivor_game_id) THEN
        RAISE EXCEPTION 'Legacy dependent survivor prevents reversal'; END IF;
      -- Runs after frozen mlb_event_insert. Keep its component receipt intact;
      -- new successor receipts additionally bind the other ledger and topology.
      NEW.receipt:=NEW.receipt||jsonb_build_object('retirement_profile',NEW.implementation_sha256,
        'retirement_fingerprint',encode(sha256(jsonb_build_object(
          'domain','MLB_RETIREMENT_KNOWLEDGE_V2','version',2,'profile',NEW.implementation_sha256,
          'ledger034',NEW.receipt->>'ledger_fingerprint','ledger035',public.mlb_retirement_legacy_fingerprint(),
          'topology',(SELECT epoch FROM public.mlb_identity_topology_fence WHERE singleton))::text::bytea),'hex'));
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_z035_cross_guard BEFORE INSERT ON game_identity_dispositions
FOR EACH ROW EXECUTE FUNCTION mlb_retirement_034_cross_guard();
CREATE TRIGGER mlb_z035_cross_guard BEFORE INSERT ON game_identity_disposition_events
FOR EACH ROW EXECUTE FUNCTION mlb_retirement_034_cross_guard();

CREATE FUNCTION mlb_retirement_legacy_snapshot_count(gid INTEGER) RETURNS INTEGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ DECLARE n INTEGER; invalid INTEGER; BEGIN
    IF to_regclass('public.odds_snapshots') IS NULL THEN RETURN 0; END IF;
    EXECUTE 'SELECT count(*),count(*) FILTER(WHERE market_type<>''h2h'' OR snapshot_time IS NULL) FROM public.odds_snapshots WHERE game_id=$1' INTO n,invalid USING gid;
    IF invalid<>0 THEN RAISE EXCEPTION 'Unknown legacy snapshot shape'; END IF;
    RETURN n;
END $$;
CREATE FUNCTION mlb_retirement_legacy_snapshot_rows(ids INTEGER[]) RETURNS JSONB
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ DECLARE rows JSONB; BEGIN
    IF to_regclass('public.odds_snapshots') IS NULL THEN RETURN '[]'::jsonb; END IF;
    EXECUTE 'SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY snapshot_id),''[]''::jsonb) FROM public.odds_snapshots s WHERE game_id=ANY($1)' INTO rows USING ids;
    RETURN rows;
END $$;
CREATE FUNCTION mlb_retirement_pair_fingerprint(subject INTEGER,survivor INTEGER) RETURNS TEXT
LANGUAGE sql VOLATILE SET search_path=pg_catalog,public AS $$
 SELECT encode(sha256(jsonb_build_object('pair034',public.mlb_identity_pair_fingerprint(subject,survivor),
   'history',(SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY historical_game_id),'[]'::jsonb) FROM public.historical_games h WHERE game_id IN(subject,survivor)),
   'teams',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY team_game_statistics_id),'[]'::jsonb) FROM public.team_game_statistics t WHERE game_id IN(subject,survivor)),
   'pitching',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY player_game_pitching_statistics_id),'[]'::jsonb) FROM public.player_game_pitching_statistics p WHERE game_id IN(subject,survivor)),
   'legacy_raw',public.mlb_retirement_legacy_snapshot_rows(ARRAY[subject,survivor]))::text::bytea),'hex')
$$;
CREATE FUNCTION mlb_retirement_validate(r public.mlb_legacy_identity_retirements,lock_rows BOOLEAN DEFAULT TRUE) RETURNS VOID
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE s public.games%ROWTYPE; c public.games%ROWTYPE; h public.historical_games%ROWTYPE;
        proof JSONB:=r.proof; n INTEGER; home_name TEXT; away_name TEXT; linked INTEGER; legacy_count INTEGER; metric TEXT; pitcher_metric TEXT;
BEGIN
    IF lock_rows THEN
      PERFORM game_id FROM public.games WHERE game_id IN(r.subject_game_id,r.survivor_game_id) ORDER BY game_id FOR UPDATE;
    END IF;
    SELECT * INTO STRICT s FROM public.games WHERE game_id=r.subject_game_id;
    SELECT * INTO STRICT c FROM public.games WHERE game_id=r.survivor_game_id;
    PERFORM public.mlb_retirement_cross_pair(r.subject_game_id,r.survivor_game_id,r.game_pk,'035');
    IF EXISTS(SELECT 1 FROM public.nfl_games WHERE game_id IN(s.game_id,c.game_id))
      OR s.home_team_id IS NULL OR s.away_team_id IS NULL OR s.home_team_id=s.away_team_id
      OR s.home_team_id IS DISTINCT FROM c.home_team_id OR s.away_team_id IS DISTINCT FROM c.away_team_id
      OR s.mlb_game_id IS NOT NULL OR s.odds_api_event_id IS NOT NULL THEN
      RAISE EXCEPTION 'Legacy MLB oriented identity required'; END IF;
    SELECT team_name INTO STRICT home_name FROM public.teams WHERE team_id=c.home_team_id;
    SELECT team_name INTO STRICT away_name FROM public.teams WHERE team_id=c.away_team_id;
    IF (SELECT count(*) FROM jsonb_object_keys(proof))<>20 OR EXISTS(SELECT 1 FROM jsonb_each(proof) WHERE value='null'::jsonb)
      OR jsonb_typeof(proof->'duplicate_proof_approved')<>'boolean' OR jsonb_typeof(proof->'publication_attribution_clear')<>'boolean'
      OR jsonb_typeof(proof->'startTimeTBD')<>'boolean'
      OR NOT proof ?& ARRAY['version','duplicate_proof_approved','publication_attribution_clear','gamePk','officialDate','gameDate','home_mlb_id','away_mlb_id','home_name','away_name','home_score','away_score','gameType','status','doubleHeader','gameNumber','ifNecessary','startTimeTBD','raw_payload_sha256','subject_start']
      OR proof->>'version'<>'1' OR proof->>'duplicate_proof_approved'<>'true' OR proof->>'publication_attribution_clear'<>'true'
      OR (proof->>'gamePk')::integer<>r.game_pk OR proof->>'home_name'<>home_name OR proof->>'away_name'<>away_name
      OR (proof->>'gameDate')::timestamptz<>c.game_date OR (proof->>'subject_start')::timestamptz<>s.game_date
      OR (proof->>'officialDate')::date<>(c.game_date AT TIME ZONE 'America/Los_Angeles')::date
      OR (s.game_date AT TIME ZONE 'America/Los_Angeles')::date<>(proof->>'officialDate')::date
      OR proof->>'gameType' NOT IN('R','F','D','L','W') OR proof->>'status'<>'Final'
      OR proof->>'doubleHeader'<>'N' OR proof->>'gameNumber'<>'1' OR proof->>'ifNecessary'<>'N'
      OR proof->>'startTimeTBD'<>'false' OR proof->>'raw_payload_sha256' !~ '^[0-9a-f]{64}$' THEN
      RAISE EXCEPTION 'Affirmative exact played single-event proof required'; END IF;
    SELECT count(*) INTO n FROM public.baseball_team_sources ts WHERE ts.source_name='mlb_stats' AND
       ((ts.team_id=c.home_team_id AND ts.external_team_id=proof->>'home_mlb_id') OR
        (ts.team_id=c.away_team_id AND ts.external_team_id=proof->>'away_mlb_id'));
    IF n<>2 THEN RAISE EXCEPTION 'Canonical MLB source participants required'; END IF;
    WITH valid(id,name) AS(VALUES
      ('108','Los Angeles Angels'),('109','Arizona Diamondbacks'),('110','Baltimore Orioles'),('111','Boston Red Sox'),
      ('112','Chicago Cubs'),('113','Cincinnati Reds'),('114','Cleveland Guardians'),('115','Colorado Rockies'),('116','Detroit Tigers'),
      ('117','Houston Astros'),('118','Kansas City Royals'),('119','Los Angeles Dodgers'),('120','Washington Nationals'),('121','New York Mets'),
      ('133','Athletics'),('134','Pittsburgh Pirates'),('135','San Diego Padres'),('136','Seattle Mariners'),('137','San Francisco Giants'),
      ('138','St. Louis Cardinals'),('139','Tampa Bay Rays'),('140','Texas Rangers'),('141','Toronto Blue Jays'),('142','Minnesota Twins'),
      ('143','Philadelphia Phillies'),('144','Atlanta Braves'),('145','Chicago White Sox'),('146','Miami Marlins'),('147','New York Yankees'),('158','Milwaukee Brewers'))
    SELECT count(*) INTO n FROM valid WHERE (id=proof->>'home_mlb_id' AND name=home_name) OR(id=proof->>'away_mlb_id' AND name=away_name);
    IF n<>2 THEN RAISE EXCEPTION 'Affirmative canonical MLB clubs required'; END IF;
    SELECT count(*) INTO n FROM public.game_sources WHERE source_name='mlb_stats'
      AND (game_id=c.game_id OR external_game_id=r.game_pk::text);
    IF n<>1 OR NOT EXISTS(SELECT 1 FROM public.game_sources WHERE game_id=c.game_id AND source_name='mlb_stats' AND external_game_id=r.game_pk::text)
      OR (c.mlb_game_id IS NOT NULL AND c.mlb_game_id<>r.game_pk) THEN RAISE EXCEPTION 'Unique fixed survivor anchor required'; END IF;
    SELECT count(*) INTO n FROM public.historical_games WHERE game_id=c.game_id OR mlb_game_id=r.game_pk;
    IF n<>1 THEN RAISE EXCEPTION 'Unique authoritative historical record required'; END IF;
    SELECT * INTO STRICT h FROM public.historical_games WHERE game_id=c.game_id;
    IF h.mlb_game_id IS DISTINCT FROM r.game_pk OR h.game_date<>(proof->>'officialDate')::date
      OR h.home_team<>home_name OR h.away_team<>away_name OR h.home_score<>(proof->>'home_score')::integer
      OR h.away_score<>(proof->>'away_score')::integer OR h.home_win IS DISTINCT FROM(h.home_score>h.away_score) THEN
      RAISE EXCEPTION 'Survivor authoritative result conflicts'; END IF;
    IF public.mlb_identity_forbidden_dependencies(s.game_id)<>'{}'::jsonb THEN RAISE EXCEPTION 'Subject history/decision dependency'; END IF;
    IF EXISTS(SELECT 1 FROM public.games g WHERE g.game_id NOT IN(s.game_id,c.game_id) AND g.home_team_id=c.home_team_id AND g.away_team_id=c.away_team_id
      AND (g.game_date AT TIME ZONE 'America/Los_Angeles')::date=(proof->>'officialDate')::date AND NOT EXISTS(
        SELECT 1 FROM public.mlb_active_retired_identities a WHERE a.subject_game_id=g.game_id AND a.survivor_game_id=c.game_id)) THEN
      RAISE EXCEPTION 'Unreviewed competing real-event identity'; END IF;
    SELECT count(*) INTO n FROM public.team_game_statistics t WHERE t.game_id=c.game_id;
    IF n<>2 OR NOT EXISTS(SELECT 1 FROM public.team_game_statistics WHERE game_id=c.game_id AND team_id=c.home_team_id AND is_home AND runs=h.home_score AND runs_allowed=h.away_score AND source_name='mlb_stats_api')
      OR NOT EXISTS(SELECT 1 FROM public.team_game_statistics WHERE game_id=c.game_id AND team_id=c.away_team_id AND NOT is_home AND runs=h.away_score AND runs_allowed=h.home_score AND source_name='mlb_stats_api') THEN
      RAISE EXCEPTION 'Complete oriented team history required'; END IF;
    IF EXISTS(SELECT 1 FROM public.player_game_pitching_statistics p WHERE p.game_id=c.game_id AND
      (p.team_id NOT IN(c.home_team_id,c.away_team_id) OR p.source_name<>'mlb_stats_api' OR p.created_at>clock_timestamp()
       OR (SELECT count(*) FROM public.baseball_player_sources ps WHERE ps.baseball_player_id=p.baseball_player_id AND ps.source_name='mlb_stats')<>1
       OR NOT EXISTS(SELECT 1 FROM public.baseball_player_sources ps WHERE ps.baseball_player_id=p.baseball_player_id AND ps.source_name='mlb_stats'
           AND ps.external_player_id ~ '^[1-9][0-9]*$')))
      OR (SELECT count(*) FROM public.player_game_pitching_statistics WHERE game_id=c.game_id AND is_starter)<>2
      OR (SELECT count(DISTINCT team_id) FROM public.player_game_pitching_statistics WHERE game_id=c.game_id AND is_starter)<>2
      OR EXISTS(SELECT 1 FROM public.team_game_statistics t WHERE t.game_id=c.game_id AND t.pitching_outs IS DISTINCT FROM
        (SELECT sum(p.pitching_outs) FROM public.player_game_pitching_statistics p WHERE p.game_id=c.game_id AND p.team_id=t.team_id)) THEN
      RAISE EXCEPTION 'Complete canonical pitching history required'; END IF;
    IF EXISTS(SELECT 1 FROM public.team_game_statistics WHERE game_id=c.game_id AND created_at>clock_timestamp()) THEN
      RAISE EXCEPTION 'Future history availability'; END IF;
    IF EXISTS(SELECT 1 FROM public.player_game_pitching_statistics WHERE game_id=c.game_id GROUP BY team_id
       HAVING min(appearance_order)<>1 OR max(appearance_order)<>count(*) OR count(DISTINCT appearance_order)<>count(*)) THEN
      RAISE EXCEPTION 'Incomplete pitching appearance order'; END IF;
    FOREACH metric IN ARRAY ARRAY['pitching_outs','runs_allowed','hits_allowed','home_runs_allowed','walks_allowed','strikeouts_recorded'] LOOP
      pitcher_metric:=CASE WHEN metric='strikeouts_recorded' THEN 'strikeouts' ELSE metric END;
      IF EXISTS(SELECT 1 FROM public.team_game_statistics t WHERE t.game_id=c.game_id AND (to_jsonb(t)->>metric)::integer IS DISTINCT FROM
         (SELECT sum((to_jsonb(p)->>pitcher_metric)::integer) FROM public.player_game_pitching_statistics p WHERE p.game_id=c.game_id AND p.team_id=t.team_id)) THEN
        RAISE EXCEPTION 'Pitching/team metric disagreement'; END IF;
    END LOOP;
    SELECT count(*) INTO n FROM public.game_sources WHERE game_id=s.game_id;
    legacy_count:=public.mlb_retirement_legacy_snapshot_count(s.game_id);
    IF r.category='IDENTITY_ONLY_DUPLICATE' THEN
      IF n<>0 OR EXISTS(SELECT 1 FROM public.odds_market_snapshots WHERE game_id=s.game_id)
        OR legacy_count<>0 THEN RAISE EXCEPTION 'Identity-only subject has provenance'; END IF;
    ELSE
      IF n<>1 OR NOT EXISTS(SELECT 1 FROM public.game_sources WHERE game_id=s.game_id AND source_name='odds_api')
        OR (legacy_count=0 AND NOT EXISTS(SELECT 1 FROM public.odds_market_snapshots WHERE game_id=s.game_id))
        OR EXISTS(SELECT 1 FROM public.odds_market_snapshots WHERE game_id=s.game_id AND
          (odds_provider_event_observation_id IS NOT NULL OR source_name<>'odds_api' OR market_type NOT IN('h2h','spreads','totals')
           OR (market_type IN('h2h','spreads') AND selection_name NOT IN(home_name,away_name))
           OR (market_type='totals' AND selection_name NOT IN('Over','Under'))))
        OR EXISTS(SELECT 1 FROM public.odds_provider_event_observations o JOIN public.game_sources gs ON gs.source_name=o.source_name AND gs.external_game_id=o.external_event_id WHERE gs.game_id=s.game_id) THEN
        RAISE EXCEPTION 'Exact permissible observation-less legacy market required'; END IF;
    END IF;
END $$;
CREATE FUNCTION mlb_retirement_case_insert() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN
    IF NEW.created_at IS NOT NULL THEN RAISE EXCEPTION 'Caller time prohibited'; END IF;
    PERFORM public.mlb_retirement_validate(NEW);
    PERFORM public.mlb_identity_touch_fence(least(NEW.subject_game_id,NEW.survivor_game_id));
    PERFORM public.mlb_identity_touch_fence(greatest(NEW.subject_game_id,NEW.survivor_game_id));
    NEW.created_at:=clock_timestamp(); RETURN NEW;
END $$;
CREATE TRIGGER mlb_legacy_case_insert BEFORE INSERT ON mlb_legacy_identity_retirements
FOR EACH ROW EXECUTE FUNCTION mlb_retirement_case_insert();
CREATE FUNCTION mlb_retirement_case_complete() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN
    IF NOT EXISTS(SELECT 1 FROM public.mlb_legacy_identity_retirement_events WHERE retirement_id=NEW.retirement_id AND approved_preview_sha256=NEW.approved_preview_sha256) THEN
      RAISE EXCEPTION 'Initial matching ACTIVATE required at commit'; END IF; RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER mlb_legacy_case_complete AFTER INSERT ON mlb_legacy_identity_retirements
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mlb_retirement_case_complete();
CREATE FUNCTION mlb_retirement_event_insert() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ DECLARE r public.mlb_legacy_identity_retirements%ROWTYPE; legacy_hash TEXT; post_hash TEXT; BEGIN
    IF NEW.created_at IS NOT NULL THEN RAISE EXCEPTION 'Caller time prohibited'; END IF;
    SELECT * INTO STRICT r FROM public.mlb_legacy_identity_retirements WHERE retirement_id=NEW.retirement_id FOR UPDATE;
    IF NEW.approved_preview_sha256<>r.approved_preview_sha256 THEN RAISE EXCEPTION 'Approval mismatch'; END IF;
    PERFORM public.mlb_retirement_validate(r);
    NEW.created_at:=clock_timestamp();
    SELECT encode(sha256(jsonb_build_object(
      'cases',(SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY subject_game_id),'[]'::jsonb) FROM public.mlb_legacy_identity_retirements c),
      'events',(SELECT jsonb_agg(x.row ORDER BY (x.row->>'retirement_id')::bigint) FROM(
        SELECT to_jsonb(e)-ARRAY['receipt','post_state_sha256'] AS row FROM public.mlb_legacy_identity_retirement_events e
        UNION ALL SELECT to_jsonb(NEW)-ARRAY['receipt','post_state_sha256']) x))::text::bytea),'hex') INTO legacy_hash;
    SELECT encode(sha256(jsonb_build_object('domain','MLB_RETIREMENT_KNOWLEDGE_V2','version',2,
       'profile',r.implementation_sha256,'ledger034',public.mlb_identity_ledger_fingerprint(),'ledger035',legacy_hash,
       'topology',(SELECT epoch FROM public.mlb_identity_topology_fence WHERE singleton))::text::bytea),'hex') INTO post_hash;
    NEW.post_state_sha256:=post_hash;
    NEW.receipt:=NEW.receipt || jsonb_build_object('retirement_id',r.retirement_id,'event_id',NEW.event_id,'subject_game_id',r.subject_game_id,'survivor_game_id',r.survivor_game_id,'action','ACTIVATE',
       'fingerprint',post_hash,'pair_fingerprint',public.mlb_retirement_pair_fingerprint(r.subject_game_id,r.survivor_game_id));
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_legacy_event_insert BEFORE INSERT ON mlb_legacy_identity_retirement_events
FOR EACH ROW EXECUTE FUNCTION mlb_retirement_event_insert();
DO $$ DECLARE name TEXT; BEGIN
 FOREACH name IN ARRAY ARRAY['mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events'] LOOP
  EXECUTE format('CREATE TRIGGER mlb_legacy_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.mlb_identity_immutable()',name);
  EXECUTE format('CREATE TRIGGER mlb_legacy_truncate BEFORE TRUNCATE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.mlb_identity_immutable()',name);
 END LOOP;
END $$;
CREATE FUNCTION mlb_retirement_assert_decision_links(j JSONB) RETURNS BOOLEAN
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$ DECLARE gid INTEGER; BEGIN
    PERFORM public.mlb_retirement_topology_fresh();
    FOR gid IN SELECT unnest(public.mlb_identity_row_games(j)) ORDER BY 1 LOOP
      PERFORM public.mlb_retirement_assert_active(gid);
    END LOOP; RETURN TRUE;
END $$;
CREATE FUNCTION mlb_retirement_write_guard() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE j JSONB; oldj JSONB; ids INTEGER[]; gid INTEGER; legacy BOOLEAN; linked BOOLEAN; BEGIN
    j:=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    oldj:=CASE WHEN TG_OP='INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;
    ids:=public.mlb_identity_row_games(j)||public.mlb_identity_row_games(oldj);
    IF TG_TABLE_NAME='odds_provider_event_observations' AND (j->>'provider_sport_key'='baseball_mlb' OR oldj->>'provider_sport_key'='baseball_mlb') THEN
      ids:=ids||ARRAY(SELECT game_id FROM public.game_sources WHERE (source_name=j->>'source_name' AND external_game_id=j->>'external_event_id') OR(source_name=oldj->>'source_name' AND external_game_id=oldj->>'external_event_id'));
    END IF;
    IF TG_TABLE_NAME='odds_ingestion_runs' THEN ids:=ids||ARRAY(SELECT game_id FROM public.odds_market_snapshots WHERE odds_ingestion_run_id=(j->>'odds_ingestion_run_id')::bigint); END IF;
    IF TG_TABLE_NAME IN('teams','baseball_team_sources') THEN
      -- Known MLB domain, not new-ledger membership, establishes freshness first.
      IF EXISTS(SELECT 1 FROM public.baseball_team_sources WHERE source_name='mlb_stats' AND team_id IN((j->>'team_id')::integer,(oldj->>'team_id')::integer)) THEN
        PERFORM public.mlb_retirement_topology_fresh();
      END IF;
      ids:=ids||ARRAY(SELECT g.game_id FROM public.games g JOIN public.mlb_legacy_identity_retirements r ON g.game_id IN(r.subject_game_id,r.survivor_game_id)
          WHERE g.home_team_id IN((j->>'team_id')::integer,(oldj->>'team_id')::integer) OR g.away_team_id IN((j->>'team_id')::integer,(oldj->>'team_id')::integer));
    END IF;
    FOR gid IN SELECT DISTINCT unnest(ids) ORDER BY 1 LOOP
      IF EXISTS(SELECT 1 FROM public.games g JOIN public.baseball_team_sources t ON t.team_id=g.home_team_id AND t.source_name='mlb_stats' WHERE g.game_id=gid) THEN
        PERFORM public.mlb_retirement_topology_fresh();
      END IF;
      SELECT EXISTS(SELECT 1 FROM public.mlb_legacy_identity_retirements WHERE subject_game_id=gid),
             EXISTS(SELECT 1 FROM public.mlb_legacy_identity_retirements WHERE subject_game_id=gid OR survivor_game_id=gid) INTO legacy,linked;
      IF NOT linked THEN CONTINUE; END IF;
      PERFORM public.mlb_identity_touch_fence(gid);
      IF TG_TABLE_NAME IN('teams','baseball_team_sources') THEN RAISE EXCEPTION 'Legacy participant identity sealed'; END IF;
      IF TG_TABLE_NAME='games' AND TG_OP<>'INSERT' AND (TG_OP='DELETE' OR
         (j-ARRAY['scheduled_innings','doubleheader_status','game_number']) IS DISTINCT FROM(oldj-ARRAY['scheduled_innings','doubleheader_status','game_number'])) THEN
        RAISE EXCEPTION 'Legacy linked physical identity sealed'; END IF;
      IF TG_TABLE_NAME='game_sources' AND TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Legacy source identity sealed'; END IF;
      IF legacy THEN
        IF TG_TABLE_NAME='odds_ingestion_runs' AND TG_OP='UPDATE' AND
           (j-ARRAY['status','completed_at','games_returned','games_processed','selections_inserted','selections_skipped','error_message']) IS NOT DISTINCT FROM
           (oldj-ARRAY['status','completed_at','games_returned','games_processed','selections_inserted','selections_skipped','error_message']) THEN CONTINUE; END IF;
        RAISE EXCEPTION 'Legacy subject raw/history/decision state sealed';
      END IF;
    END LOOP;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
CREATE FUNCTION mlb_retirement_truncate() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ BEGIN
    PERFORM public.mlb_retirement_topology_fresh();
    IF EXISTS(SELECT 1 FROM public.mlb_legacy_identity_retirements) THEN RAISE EXCEPTION 'Legacy raw TRUNCATE prohibited'; END IF;
    RETURN NULL;
END $$;
DO $$ DECLARE name TEXT; BEGIN
 FOREACH name IN ARRAY ARRAY['games','game_sources','historical_games','game_results','teams','baseball_team_sources','odds_ingestion_runs',
  'team_game_statistics','player_game_pitching_statistics','model_predictions','moneyline_game_predictions','moneyline_prediction_market_evaluations',
  'moneyline_paper_candidate_settlements','market_analysis','odds_snapshots','odds_market_snapshots','odds_provider_event_observations','odds_provider_event_canonical_corrections'] LOOP
  IF to_regclass('public.'||name) IS NOT NULL THEN
    EXECUTE format('CREATE TRIGGER mlb_035_write_guard BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.mlb_retirement_write_guard()',name);
  END IF;
 END LOOP;
 FOREACH name IN ARRAY ARRAY['game_sources','odds_snapshots','odds_market_snapshots','odds_provider_event_observations'] LOOP
  IF to_regclass('public.'||name) IS NOT NULL THEN
    EXECUTE format('CREATE TRIGGER mlb_035_provenance_truncate BEFORE TRUNCATE ON public.%I FOR EACH STATEMENT EXECUTE FUNCTION public.mlb_retirement_truncate()',name);
  END IF;
 END LOOP;
END $$;
CREATE FUNCTION mlb_retirement_history_guard() RETURNS BOOLEAN
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$ DECLARE p JSONB; gid INTEGER; BEGIN
    p:=nullif(current_setting('sportsmodel.retirement_knowledge',true),'')::jsonb;
    IF p IS NULL OR p->>'version'<>'2' OR p->>'profile' !~ '^[0-9a-f]{64}$'
      OR p->>'fingerprint' IS DISTINCT FROM public.mlb_retirement_fingerprint(p->>'profile')
      OR p->>'available_at' IS NULL OR p->>'cutoff_time' IS NULL
      OR (p->>'available_at')::timestamptz>(p->>'cutoff_time')::timestamptz
      OR (p->>'cutoff_time')::timestamptz>clock_timestamp() THEN RAISE EXCEPTION 'Committed v2 knowledge required'; END IF;
    PERFORM public.mlb_identity_history_guard();
    FOR gid IN SELECT subject_game_id FROM public.mlb_active_retired_identities LOOP
      IF public.mlb_identity_forbidden_dependencies(gid)<>'{}'::jsonb THEN RAISE EXCEPTION 'Retired history invariant'; END IF;
    END LOOP; RETURN TRUE;
END $$;
ALTER TABLE moneyline_prediction_runs ADD COLUMN identity_retirement_knowledge JSONB;
ALTER TABLE moneyline_prediction_runs ADD CONSTRAINT chk_moneyline_retirement_knowledge CHECK(
 identity_retirement_knowledge IS NULL OR(jsonb_typeof(identity_retirement_knowledge)='object'
 AND identity_retirement_knowledge ?& ARRAY['version','profile','fingerprint','artifact_sha256','available_at']
 AND identity_retirement_knowledge->>'version'='2' AND identity_retirement_knowledge->>'profile' ~ '^[0-9a-f]{64}$'
 AND identity_retirement_knowledge->>'fingerprint' ~ '^[0-9a-f]{64}$' AND identity_retirement_knowledge->>'artifact_sha256' ~ '^[0-9a-f]{64}$'));
REVOKE ALL ON mlb_legacy_identity_retirements,mlb_legacy_identity_retirement_events,mlb_identity_topology_fence FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION mlb_retirement_ledger_ingress(),mlb_retirement_topology_integrity(),
 mlb_retirement_case_insert(),mlb_retirement_case_complete(),mlb_retirement_event_insert() FROM PUBLIC;
CREATE FUNCTION mlb_retirement_activate(request JSONB) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE r public.mlb_legacy_identity_retirements%ROWTYPE; rid BIGINT; result JSONB; oldr public.mlb_legacy_identity_retirements%ROWTYPE; BEGIN
    IF jsonb_typeof(request)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(request))<>3
      OR NOT request ?& ARRAY['case','expected_pair_sha256','expected_state_sha256']
      OR jsonb_typeof(request->'case')<>'object' OR (SELECT count(*) FROM jsonb_object_keys(request->'case'))<>14
      OR NOT (request->'case') ?& ARRAY['domain','subject_game_id','survivor_game_id','game_pk','category','policy_version','proof','evidence_reference','evidence_sha256','approved_preview_sha256','operator_identity','tool_identity','implementation_commit','implementation_sha256'] THEN
      RAISE EXCEPTION 'Exact bounded activation request required'; END IF;
    r:=jsonb_populate_record(NULL::public.mlb_legacy_identity_retirements,request->'case');
    PERFORM public.mlb_identity_gate(true);
    PERFORM epoch FROM public.mlb_identity_topology_fence WHERE singleton FOR UPDATE;
    SELECT * INTO oldr FROM public.mlb_legacy_identity_retirements WHERE approved_preview_sha256=r.approved_preview_sha256;
    IF FOUND THEN
      IF (to_jsonb(oldr)-ARRAY['retirement_id','created_at']) IS DISTINCT FROM request->'case' THEN RAISE EXCEPTION 'Approval replay differs'; END IF;
      SELECT receipt INTO STRICT result FROM public.mlb_legacy_identity_retirement_events WHERE retirement_id=oldr.retirement_id;
      IF result->>'fingerprint' IS DISTINCT FROM public.mlb_retirement_fingerprint(r.implementation_sha256)
        OR result->>'pair_fingerprint' IS DISTINCT FROM public.mlb_retirement_pair_fingerprint(r.subject_game_id,r.survivor_game_id) THEN
        RAISE EXCEPTION 'Receipt state changed; replay refused'; END IF;
      RETURN result||jsonb_build_object('replay',true);
    END IF;
    PERFORM game_id FROM public.games WHERE game_id IN(r.subject_game_id,r.survivor_game_id) ORDER BY game_id FOR UPDATE;
    PERFORM game_id FROM public.mlb_game_identity_write_fences WHERE game_id IN(r.subject_game_id,r.survivor_game_id) ORDER BY game_id FOR UPDATE;
    IF request->>'expected_pair_sha256' IS DISTINCT FROM public.mlb_retirement_pair_fingerprint(r.subject_game_id,r.survivor_game_id)
      OR request->>'expected_state_sha256' IS DISTINCT FROM public.mlb_retirement_fingerprint(r.implementation_sha256) THEN
      RAISE EXCEPTION 'Preview pair/ledger/topology differs'; END IF;
    INSERT INTO public.mlb_legacy_identity_retirements(domain,subject_game_id,survivor_game_id,game_pk,category,policy_version,proof,
      evidence_reference,evidence_sha256,approved_preview_sha256,operator_identity,tool_identity,implementation_commit,implementation_sha256)
      VALUES(r.domain,r.subject_game_id,r.survivor_game_id,r.game_pk,r.category,r.policy_version,r.proof,r.evidence_reference,r.evidence_sha256,
        r.approved_preview_sha256,r.operator_identity,r.tool_identity,r.implementation_commit,r.implementation_sha256) RETURNING retirement_id INTO rid;
    INSERT INTO public.mlb_legacy_identity_retirement_events(retirement_id,action,sequence,approved_preview_sha256,pre_state_sha256,post_state_sha256,receipt)
      VALUES(rid,'ACTIVATE',1,r.approved_preview_sha256,request->>'expected_state_sha256',repeat('0',64),'{}'::jsonb) RETURNING receipt INTO result;
    RETURN result||jsonb_build_object('replay',false);
END $$;
REVOKE EXECUTE ON FUNCTION mlb_retirement_activate(JSONB) FROM PUBLIC;
CREATE FUNCTION mlb_retirement_run_guard() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$ DECLARE proof JSONB; BEGIN
    IF TG_OP='UPDATE' THEN
      IF NEW.identity_retirement_knowledge IS DISTINCT FROM OLD.identity_retirement_knowledge THEN
        RAISE EXCEPTION 'Run v2 knowledge immutable; no historical backfill'; END IF;
      RETURN NEW;
    END IF;
    PERFORM public.mlb_retirement_history_guard();
    proof:=nullif(current_setting('sportsmodel.retirement_knowledge',true),'')::jsonb;
    IF NEW.identity_retirement_knowledge IS NULL OR NEW.identity_retirement_knowledge IS DISTINCT FROM proof THEN
      RAISE EXCEPTION 'Run requires exact committed v2 knowledge'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_035_run_knowledge BEFORE INSERT OR UPDATE ON moneyline_prediction_runs
FOR EACH ROW EXECUTE FUNCTION mlb_retirement_run_guard();
