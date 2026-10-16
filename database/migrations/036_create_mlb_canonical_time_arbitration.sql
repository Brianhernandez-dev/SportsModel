-- Additive MLB036. No automatic role/authority provisioning or business mutation.
-- Authority must be explicitly provisioned by an independently approved DBA.
CREATE SCHEMA mlb036_private;
REVOKE ALL ON SCHEMA mlb036_private FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA mlb036_private REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TABLE mlb036_private.authority (
    singleton BOOLEAN PRIMARY KEY CHECK(singleton),
    deployment_id TEXT NOT NULL CHECK(length(deployment_id) BETWEEN 1 AND 128),
    authority_epoch BIGINT NOT NULL CHECK(authority_epoch>0),
    mode TEXT NOT NULL CHECK(mode IN('native','isolated')),
    system_identifier TEXT NOT NULL CHECK(system_identifier ~ '^[1-9][0-9]*$'),
    database_oid OID NOT NULL,
    database_name TEXT NOT NULL,
    server_address TEXT NOT NULL,
    server_port INTEGER NOT NULL,
    postmaster_started_at TIMESTAMPTZ NOT NULL,
    schema_capability_profile TEXT NOT NULL CHECK(schema_capability_profile ~ '^[0-9a-f]{64}$'),
    catalog_sha256 TEXT NOT NULL CHECK(catalog_sha256 ~ '^[0-9a-f]{64}$'),
    correction_policy_version TEXT NOT NULL CHECK(correction_policy_version='1.0.0'),
    policy JSONB NOT NULL,
    reader_role NAME NOT NULL,
    knowledge_role NAME NOT NULL,
    operator_role NAME NOT NULL,
    raw_role NAME NOT NULL,
    observed_high_water TIMESTAMPTZ NOT NULL
);
CREATE TABLE mlb036_private.arbitrations (
    audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_identity TEXT NOT NULL UNIQUE CHECK(case_identity='MLB:584:26:823842:minus60:v1'),
    duplicate_physical_id INTEGER NOT NULL CHECK(duplicate_physical_id=584),
    survivor_physical_id INTEGER NOT NULL CHECK(survivor_physical_id=26),
    authoritative_game_pk BIGINT NOT NULL,
    old_start TIMESTAMPTZ NOT NULL,
    new_start TIMESTAMPTZ NOT NULL,
    signed_delta_seconds INTEGER NOT NULL CHECK(signed_delta_seconds=-60),
    request_sha256 TEXT NOT NULL UNIQUE CHECK(request_sha256 ~ '^[0-9a-f]{64}$'),
    evidence_sha256 TEXT NOT NULL CHECK(evidence_sha256 ~ '^[0-9a-f]{64}$'),
    approval_sha256 TEXT NOT NULL UNIQUE CHECK(approval_sha256 ~ '^[0-9a-f]{64}$'),
    schema_capability_profile TEXT NOT NULL CHECK(schema_capability_profile ~ '^[0-9a-f]{64}$'),
    correction_policy_version TEXT NOT NULL CHECK(correction_policy_version='1.0.0'),
    request_body JSONB NOT NULL,
    retirement_case JSONB NOT NULL,
    pre_business_sha256 TEXT NOT NULL CHECK(pre_business_sha256 ~ '^[0-9a-f]{64}$'),
    post_business_sha256 TEXT NOT NULL CHECK(post_business_sha256 ~ '^[0-9a-f]{64}$'),
    pre_state JSONB NOT NULL,
    post_state JSONB NOT NULL,
    writer_xid8 XID8 NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    CHECK(new_start-old_start=INTERVAL '-60 seconds')
);
CREATE TABLE mlb036_private.arbitration_events (
    event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_reference BIGINT NOT NULL UNIQUE,
    sequence INTEGER NOT NULL CHECK(sequence=1),
    action TEXT NOT NULL CHECK(action='APPLIED'),
    operation_receipt JSONB NOT NULL,
    writer_xid8 XID8 NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE mlb036_private.knowledge_receipts (
    receipt_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    format_version INTEGER NOT NULL CHECK(format_version=1),
    issuer_xid8 XID8 NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    deployment_id TEXT NOT NULL,
    system_identifier TEXT NOT NULL,
    database_oid OID NOT NULL,
    database_name TEXT NOT NULL,
    server_address TEXT NOT NULL,
    server_port INTEGER NOT NULL,
    postmaster_started_at TIMESTAMPTZ NOT NULL,
    authority_epoch BIGINT NOT NULL,
    schema_capability_profile TEXT NOT NULL,
    correction_policy_version TEXT NOT NULL,
    correction_state_fingerprint TEXT NOT NULL CHECK(correction_state_fingerprint ~ '^[0-9a-f]{64}$'),
    identity034_digest TEXT NOT NULL,
    identity035_digest TEXT NOT NULL,
    identity_topology_epoch BIGINT NOT NULL,
    projection_digest TEXT NOT NULL,
    fence_digest TEXT NOT NULL,
    referenced_audit_ids BIGINT[] NOT NULL,
    receipt_body_sha256 TEXT NOT NULL CHECK(receipt_body_sha256 ~ '^[0-9a-f]{64}$')
);
ALTER TABLE public.moneyline_prediction_runs ADD COLUMN canonical_time_knowledge JSONB;

CREATE FUNCTION mlb036_private.frame(tag INTEGER,payload BYTEA) RETURNS BYTEA
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path=pg_catalog AS $$
BEGIN
    IF tag NOT BETWEEN 0 AND 7 OR octet_length(payload)+9>16777216 THEN
        RAISE EXCEPTION '036 codec frame limit/type'; END IF;
    RETURN set_byte('\x00'::bytea,0,tag)||int8send(octet_length(payload)::bigint)||payload;
END $$;
CREATE FUNCTION mlb036_private.codec(value JSONB,depth INTEGER DEFAULT 0) RETURNS BYTEA
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE kind TEXT; output BYTEA; n BIGINT; item RECORD; count_value BIGINT;
BEGIN
    IF value IS NULL OR depth<0 OR depth>32 OR octet_length(value::text)>16777216 THEN
        RAISE EXCEPTION '036 codec bounded JSON required'; END IF;
    kind:=jsonb_typeof(value);
    IF kind='null' THEN RETURN mlb036_private.frame(0,''::bytea);
    ELSIF kind='boolean' THEN RETURN mlb036_private.frame(1,CASE WHEN value='true'::jsonb THEN '\x01'::bytea ELSE '\x00'::bytea END);
    ELSIF kind='number' THEN
        IF value::text !~ '^-?(0|[1-9][0-9]*)$' THEN RAISE EXCEPTION '036 unsupported numeric type'; END IF;
        n:=(value::text)::bigint; RETURN mlb036_private.frame(2,int8send(n));
    ELSIF kind='string' THEN RETURN mlb036_private.frame(3,convert_to(value#>>'{}','UTF8'));
    ELSIF kind='array' THEN
        count_value:=jsonb_array_length(value);
        IF count_value>100000 THEN RAISE EXCEPTION '036 cardinality'; END IF;
        output:=int8send(count_value);
        FOR item IN SELECT element FROM jsonb_array_elements(value) element LOOP
            output:=output||mlb036_private.codec(item.element,depth+1);
            IF octet_length(output)>16777216 THEN RAISE EXCEPTION '036 body limit'; END IF;
        END LOOP; RETURN mlb036_private.frame(5,output);
    ELSIF kind='object' THEN
        SELECT count(*) INTO count_value FROM jsonb_object_keys(value);
        IF count_value>100000 THEN RAISE EXCEPTION '036 cardinality'; END IF;
        output:=int8send(count_value);
        FOR item IN SELECT key,child FROM jsonb_each(value) AS e(key,child) ORDER BY convert_to(key,'UTF8') LOOP
            output:=output||mlb036_private.codec(to_jsonb(item.key),depth+1)||mlb036_private.codec(item.child,depth+1);
            IF octet_length(output)>16777216 THEN RAISE EXCEPTION '036 body limit'; END IF;
        END LOOP; RETURN mlb036_private.frame(6,output);
    END IF;
    RAISE EXCEPTION '036 unsupported codec type';
END $$;
CREATE FUNCTION mlb036_private.unsigned_frame(value XID8) RETURNS BYTEA
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE n NUMERIC:=value::text::numeric; output BYTEA:='\x0000000000000000'::bytea; i INTEGER;
BEGIN
    FOR i IN REVERSE 7..0 LOOP output:=set_byte(output,i,mod(n,256)::integer); n:=div(n,256); END LOOP;
    IF n<>0 THEN RAISE EXCEPTION '036 unsigned overflow'; END IF;
    RETURN mlb036_private.frame(7,output);
END $$;
CREATE FUNCTION mlb036_private.timestamp_frame(value TIMESTAMPTZ) RETURNS BYTEA
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
BEGIN
    IF NOT isfinite(value) THEN RAISE EXCEPTION '036 finite timestamp'; END IF;
    RETURN mlb036_private.frame(2,int8send((extract(epoch FROM value)*1000000)::bigint));
END $$;
CREATE FUNCTION mlb036_private.object_frame(keys TEXT[],encoded_values BYTEA[]) RETURNS BYTEA
LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE result BYTEA; item RECORD; n INTEGER:=cardinality(keys);
BEGIN
    IF n<>cardinality(encoded_values) OR n>100000 OR array_position(keys,NULL) IS NOT NULL
      OR array_position(encoded_values,NULL) IS NOT NULL OR (SELECT count(DISTINCT k) FROM unnest(keys) k)<>n THEN
        RAISE EXCEPTION '036 exact unique object fields'; END IF;
    result:=int8send(n::bigint);
    FOR item IN SELECT keys[i] AS key,encoded_values[i] AS val FROM generate_subscripts(keys,1) i ORDER BY convert_to(keys[i],'UTF8') LOOP
        result:=result||mlb036_private.codec(to_jsonb(item.key))||item.val;
        IF octet_length(result)>16777216 THEN RAISE EXCEPTION '036 body limit'; END IF;
    END LOOP; RETURN mlb036_private.frame(6,result);
END $$;
CREATE FUNCTION mlb036_private.immutable() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION '036 append-only immutable state'; END $$;
CREATE TRIGGER mlb036_audit_immutable BEFORE UPDATE OR DELETE ON mlb036_private.arbitrations FOR EACH ROW EXECUTE FUNCTION mlb036_private.immutable();
CREATE TRIGGER mlb036_audit_truncate BEFORE TRUNCATE ON mlb036_private.arbitrations FOR EACH STATEMENT EXECUTE FUNCTION mlb036_private.immutable();
CREATE TRIGGER mlb036_event_immutable BEFORE UPDATE OR DELETE ON mlb036_private.arbitration_events FOR EACH ROW EXECUTE FUNCTION mlb036_private.immutable();
CREATE TRIGGER mlb036_event_truncate BEFORE TRUNCATE ON mlb036_private.arbitration_events FOR EACH STATEMENT EXECUTE FUNCTION mlb036_private.immutable();
CREATE TRIGGER mlb036_receipt_immutable BEFORE UPDATE OR DELETE ON mlb036_private.knowledge_receipts FOR EACH ROW EXECUTE FUNCTION mlb036_private.immutable();
CREATE TRIGGER mlb036_receipt_truncate BEFORE TRUNCATE ON mlb036_private.knowledge_receipts FOR EACH STATEMENT EXECUTE FUNCTION mlb036_private.immutable();
CREATE FUNCTION mlb036_private.audit_stamp() RETURNS TRIGGER
LANGUAGE plpgsql SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE observed JSONB;
BEGIN
    IF NEW.writer_xid8 IS NOT NULL OR NEW.recorded_at IS NOT NULL THEN RAISE EXCEPTION '036 caller audit time/xid prohibited'; END IF;
    NEW.writer_xid8:=pg_current_xact_id(); NEW.recorded_at:=clock_timestamp();
    IF TG_TABLE_NAME='arbitration_events' THEN
        observed:=mlb036_private.state();
        observed:=jsonb_set(observed,'{events}',(observed->'events')||jsonb_build_array(to_jsonb(NEW)-'operation_receipt'));
        NEW.operation_receipt:=NEW.operation_receipt||jsonb_build_object('post_state_fingerprint',mlb036_private.state_fingerprint(observed));
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlb036_audit_stamp BEFORE INSERT ON mlb036_private.arbitrations FOR EACH ROW EXECUTE FUNCTION mlb036_private.audit_stamp();
CREATE TRIGGER mlb036_event_stamp BEFORE INSERT ON mlb036_private.arbitration_events FOR EACH ROW EXECUTE FUNCTION mlb036_private.audit_stamp();
-- Reuse the reviewed035 exclusive ingress/topology primitive unchanged.
CREATE TRIGGER mlb036_topology_ingress BEFORE INSERT ON mlb036_private.arbitrations FOR EACH STATEMENT EXECUTE FUNCTION public.mlb_retirement_ledger_ingress();

CREATE FUNCTION mlb036_private.identity_projection() RETURNS JSONB
LANGUAGE sql STABLE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
    SELECT jsonb_build_object(
      'games',(SELECT coalesce(jsonb_agg(to_jsonb(g) ORDER BY g.game_id),'[]'::jsonb) FROM public.games g WHERE game_id IN(26,584)),
      'sources',(SELECT coalesce(jsonb_agg(to_jsonb(s)||jsonb_build_object('created_at',s.created_at AT TIME ZONE 'UTC') ORDER BY s.game_source_id),'[]'::jsonb) FROM public.game_sources s WHERE game_id IN(26,584)),
      'candidates',(SELECT coalesce(jsonb_agg(to_jsonb(g) ORDER BY g.game_id),'[]'::jsonb) FROM public.games g
         WHERE (g.home_team_id,g.away_team_id)=(SELECT home_team_id,away_team_id FROM public.games WHERE game_id=26)
         AND (g.game_date AT TIME ZONE 'America/Los_Angeles')::date=DATE '2026-07-12'))
$$;
CREATE FUNCTION mlb036_private.business_snapshot() RETURNS JSONB
LANGUAGE sql STABLE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
    SELECT jsonb_build_object(
      'identity',mlb036_private.identity_projection(),
      'history',(SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY h.historical_game_id),'[]'::jsonb) FROM public.historical_games h WHERE game_id IN(26,584)),
      'teams',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.team_game_statistics_id),'[]'::jsonb) FROM public.team_game_statistics t WHERE game_id IN(26,584)),
      'pitching',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.player_game_pitching_statistics_id),'[]'::jsonb) FROM public.player_game_pitching_statistics p WHERE game_id IN(26,584)),
      -- NUMERIC line_value is an explicitly typed exact decimal string, never
      -- a floating-point JSON number. Legacy timestamps have established UTC
      -- semantics; retain their values and make that timezone explicit.
      'markets',(SELECT coalesce(jsonb_agg(to_jsonb(m)||jsonb_build_object('line_value',m.line_value::text) ORDER BY m.odds_market_snapshot_id),'[]'::jsonb) FROM public.odds_market_snapshots m WHERE game_id IN(26,584)),
      'legacy',(SELECT coalesce(jsonb_agg(to_jsonb(o)||jsonb_build_object('snapshot_time',o.snapshot_time AT TIME ZONE 'UTC') ORDER BY o.snapshot_id),'[]'::jsonb) FROM public.odds_snapshots o WHERE game_id IN(26,584)),
      'observations',(SELECT coalesce(jsonb_agg(to_jsonb(o) ORDER BY o.odds_provider_event_observation_id),'[]'::jsonb) FROM public.odds_provider_event_observations o
        WHERE EXISTS(SELECT 1 FROM public.game_sources s WHERE s.game_id IN(26,584) AND s.source_name=o.source_name AND s.external_game_id=o.external_event_id)),
      'team_sources',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.baseball_team_source_id),'[]'::jsonb) FROM public.baseball_team_sources s
         WHERE team_id IN(SELECT home_team_id FROM public.games WHERE game_id=26 UNION SELECT away_team_id FROM public.games WHERE game_id=26)),
      'player_sources',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.baseball_player_source_id),'[]'::jsonb) FROM public.baseball_player_sources s
        WHERE EXISTS(SELECT 1 FROM public.player_game_pitching_statistics p WHERE p.game_id=26 AND p.baseball_player_id=s.baseball_player_id)),
      'team_identities',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.team_id),'[]'::jsonb) FROM public.teams t
        WHERE t.team_id IN(SELECT home_team_id FROM public.games WHERE game_id IN(26,584) UNION SELECT away_team_id FROM public.games WHERE game_id IN(26,584))),
      'player_identities',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.baseball_player_id),'[]'::jsonb) FROM public.baseball_players p
        WHERE EXISTS(SELECT 1 FROM public.player_game_pitching_statistics s WHERE s.game_id IN(26,584) AND s.baseball_player_id=p.baseball_player_id)),
      'ingestion_runs',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.odds_ingestion_run_id),'[]'::jsonb) FROM public.odds_ingestion_runs r
        WHERE r.odds_ingestion_run_id IN(SELECT odds_ingestion_run_id FROM public.odds_market_snapshots WHERE game_id IN(26,584)
          UNION SELECT o.odds_ingestion_run_id FROM public.odds_provider_event_observations o WHERE EXISTS(
            SELECT 1 FROM public.game_sources s WHERE s.game_id IN(26,584) AND s.source_name=o.source_name AND s.external_game_id=o.external_event_id))),
      'sportsbooks',(SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.sportsbook_id),'[]'::jsonb) FROM public.sportsbooks b
        WHERE b.sportsbook_id IN(SELECT sportsbook_id FROM public.odds_market_snapshots WHERE game_id IN(26,584)
          UNION SELECT sportsbook_id FROM public.odds_snapshots WHERE game_id IN(26,584))),
      'book_sources',(SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.sportsbook_provider_identity_id),'[]'::jsonb) FROM public.sportsbook_provider_identities b
        WHERE b.sportsbook_provider_identity_id IN(SELECT sportsbook_provider_identity_id FROM public.odds_market_snapshots WHERE game_id IN(26,584))),
      'canonical_corrections',(SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY c.odds_provider_event_canonical_correction_id),'[]'::jsonb) FROM public.odds_provider_event_canonical_corrections c
        WHERE c.original_game_id IN(26,584) OR c.corrected_game_id IN(26,584)))
$$;
CREATE FUNCTION mlb036_private.codec_raw(value JSON,depth INTEGER DEFAULT 0) RETURNS BYTEA
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE keys TEXT[]; encoded_values BYTEA[]; item RECORD; payload BYTEA;
BEGIN
    IF depth>32 OR octet_length(convert_to(value::text,'UTF8'))>16777216 THEN RAISE EXCEPTION '036 raw codec bound'; END IF;
    IF json_typeof(value)='object' THEN
        IF (SELECT count(*) FROM json_each(value))>100000 OR
          (SELECT count(*)<>count(DISTINCT convert_to(key,'UTF8')) FROM json_each(value)) THEN RAISE EXCEPTION '036 raw duplicate keys/cardinality'; END IF;
        keys:=ARRAY[]::text[]; encoded_values:=ARRAY[]::bytea[];
        FOR item IN SELECT key,val FROM json_each(value) e(key,val) ORDER BY convert_to(key,'UTF8') LOOP
            keys:=array_append(keys,item.key); encoded_values:=array_append(encoded_values,mlb036_private.codec_raw(item.val,depth+1));
        END LOOP;
        RETURN mlb036_private.object_frame(keys,encoded_values);
    ELSIF json_typeof(value)='array' THEN
        IF json_array_length(value)>100000 THEN RAISE EXCEPTION '036 raw list cardinality'; END IF;
        payload:=int8send(json_array_length(value)::bigint);
        FOR item IN SELECT val FROM json_array_elements(value) e(val) LOOP
            payload:=payload||mlb036_private.codec_raw(item.val,depth+1);
            IF octet_length(payload)>16777216 THEN RAISE EXCEPTION '036 raw list bound'; END IF;
        END LOOP;
        RETURN mlb036_private.frame(5,payload);
    ELSIF json_typeof(value)='number' AND value::text !~ '^-?(0|[1-9][0-9]*)$' THEN
        RAISE EXCEPTION '036 raw integer type required';
    END IF;
    RETURN mlb036_private.codec(value::jsonb,depth);
END $$;
CREATE FUNCTION mlb036_private.codec_text(value TEXT) RETURNS BYTEA
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
BEGIN
    IF octet_length(convert_to(value,'UTF8'))>16777216 THEN RAISE EXCEPTION '036 raw text bound'; END IF;
    RETURN mlb036_private.codec_raw(value::json);
END $$;
CREATE FUNCTION mlb036_private.semantic_frame(value JSONB,field_name TEXT DEFAULT '',depth INTEGER DEFAULT 0) RETURNS BYTEA
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE keys TEXT[]; encoded_values BYTEA[]; item RECORD; payload BYTEA; size_value BIGINT;
BEGIN
    IF depth>32 OR octet_length(convert_to(value::text,'UTF8'))>16777216 THEN RAISE EXCEPTION '036 semantic codec bound'; END IF;
    IF value='null'::jsonb THEN RETURN mlb036_private.frame(0,''::bytea); END IF;
    IF field_name IN('old_start','new_start','game_date','gameDate','subject_start','recorded_at','available_at','cutoff_time','postmaster_started_at','created_at','updated_at','snapshot_time',
      'started_at','completed_at','last_synced_at','observed_at','bookmaker_updated_at','market_updated_at','provider_commence_time',
      'request_commence_time_from','request_commence_time_to','request_started_at','response_received_at') THEN
        IF jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-5][0-9])$' THEN RAISE EXCEPTION '036 strict semantic timestamp'; END IF;
        RETURN mlb036_private.timestamp_frame((value#>>'{}')::timestamptz);
    ELSIF field_name IN('officialDate','official_date','active_from','active_through') THEN
        IF jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN RAISE EXCEPTION '036 strict official date'; END IF;
        PERFORM (value#>>'{}')::date;
        RETURN mlb036_private.codec(value,depth);
    ELSIF field_name IN('writer_xid8','issuer_xid8') THEN
        IF value#>>'{}' !~ '^[0-9]+$' THEN RAISE EXCEPTION '036 strict semantic xid8'; END IF;
        RETURN mlb036_private.unsigned_frame((value#>>'{}')::xid8);
    ELSIF field_name IN('profile','schema_capability_profile','ledger034','ledger035','projection_digest','fence_digest',
        'correction_state_fingerprint','identity034_digest','identity035_digest','receipt_body_sha256','artifact_sha256')
        OR field_name LIKE '%\_sha256' ESCAPE '\' THEN
        IF jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION '036 strict semantic digest'; END IF;
        RETURN mlb036_private.frame(4,decode(value#>>'{}','hex'));
    ELSIF field_name='audit_bytes' THEN
        IF jsonb_typeof(value)<>'string' OR value#>>'{}' !~ '^([0-9a-f][0-9a-f])+$' THEN RAISE EXCEPTION '036 strict semantic audit frame'; END IF;
        RETURN mlb036_private.frame(4,decode(value#>>'{}','hex'));
    END IF;
    IF jsonb_typeof(value)='object' THEN
        IF (SELECT count(*) FROM jsonb_object_keys(value))>100000 THEN RAISE EXCEPTION '036 semantic object cardinality'; END IF;
        keys:=ARRAY[]::text[]; encoded_values:=ARRAY[]::bytea[];
        FOR item IN SELECT key,val FROM jsonb_each(value) AS e(key,val) ORDER BY convert_to(key,'UTF8') LOOP
            keys:=array_append(keys,item.key); encoded_values:=array_append(encoded_values,mlb036_private.semantic_frame(item.val,item.key,depth+1));
        END LOOP;
        RETURN mlb036_private.object_frame(keys,encoded_values);
    ELSIF jsonb_typeof(value)='array' THEN
        IF jsonb_array_length(value)>100000 THEN RAISE EXCEPTION '036 semantic list cardinality'; END IF;
        payload:=int8send(jsonb_array_length(value)::bigint);
        FOR item IN SELECT val FROM jsonb_array_elements(value) AS e(val) LOOP
            payload:=payload||mlb036_private.semantic_frame(item.val,CASE WHEN field_name='audits' THEN 'audit_bytes' ELSE '' END,depth+1);
            size_value:=octet_length(payload); IF size_value>16777216 THEN RAISE EXCEPTION '036 semantic list bound'; END IF;
        END LOOP;
        RETURN mlb036_private.frame(5,payload);
    END IF;
    RETURN mlb036_private.codec(value,depth);
END $$;
CREATE FUNCTION mlb036_private.audit_frame(a mlb036_private.arbitrations) RETURNS BYTEA
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
    -- Business rows include non-codec metric numerics and legacy date/timestamp
    -- storage. Bind their independently computed digest, not an opaque JSON string
    -- or a lossy metric coercion. The stored complete pre-snapshot remains immutable.
    SELECT mlb036_private.semantic_frame((to_jsonb(a)-ARRAY['post_state','post_business_sha256','pre_state'])
      ||jsonb_build_object('pre_state',a.pre_state->'state'))
$$;
CREATE FUNCTION mlb036_private.catalog_identity() RETURNS TEXT
LANGUAGE sql STABLE SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
    SELECT encode(sha256(convert_to(jsonb_build_object(
      'schemas',(SELECT jsonb_agg(jsonb_build_array(n.oid,n.nspname,n.nspowner,n.nspacl::text) ORDER BY n.oid) FROM pg_namespace n
           WHERE n.nspname NOT LIKE 'pg_temp_%' AND n.nspname NOT LIKE 'pg_toast%'),
      'functions',(SELECT jsonb_agg(jsonb_build_array(p.oid,p.proname,p.proowner,p.provolatile,p.proparallel,p.prosecdef,p.proconfig,p.prosrc,p.proacl::text,
           pg_get_function_identity_arguments(p.oid),pg_get_function_result(p.oid),pg_get_function_arguments(p.oid),p.prolang,p.proretset,p.proisstrict,p.proleakproof)
           ORDER BY p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
           WHERE n.nspname NOT LIKE 'pg_temp_%' AND n.nspname NOT LIKE 'pg_toast%'),
      'parameter_acls',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY p.oid),'[]'::jsonb) FROM pg_parameter_acl p),
      'migration_rows',(SELECT jsonb_agg(to_jsonb(m) ORDER BY version) FROM public.schema_migrations m),
      'relations',(SELECT jsonb_agg(jsonb_build_array(c.oid,c.relname,c.relowner,c.relkind,c.relacl::text,
           CASE WHEN c.relkind IN('v','m') THEN pg_get_viewdef(c.oid,true) ELSE NULL END) ORDER BY c.oid)
           FROM pg_class c WHERE c.relnamespace IN('public'::regnamespace,'mlb036_private'::regnamespace)),
      'columns',(SELECT jsonb_agg(jsonb_build_array(a.attrelid,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attacl::text,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid)) ORDER BY a.attrelid,a.attnum)
           FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
           WHERE a.attnum>0 AND NOT a.attisdropped AND a.attrelid IN(SELECT oid FROM pg_class WHERE relnamespace IN('public'::regnamespace,'mlb036_private'::regnamespace))),
      'constraints',(SELECT jsonb_agg(jsonb_build_array(k.oid,k.conrelid,k.conname,k.contype,pg_get_constraintdef(k.oid,true)) ORDER BY k.oid) FROM pg_constraint k
           WHERE k.connamespace IN('public'::regnamespace,'mlb036_private'::regnamespace)),
      'triggers',(SELECT jsonb_agg(jsonb_build_array(t.oid,t.tgrelid,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid)) ORDER BY t.oid)
           FROM pg_trigger t WHERE t.tgrelid IN(SELECT oid FROM pg_class WHERE relnamespace IN('public'::regnamespace,'mlb036_private'::regnamespace))),
      'defaults',(SELECT jsonb_agg(to_jsonb(d) ORDER BY d.oid) FROM pg_default_acl d),
      'memberships',(SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.roleid,m.member),'[]'::jsonb) FROM pg_auth_members m),
      'roles',(SELECT jsonb_agg(jsonb_build_array(oid,rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls) ORDER BY oid) FROM pg_roles))::text,'UTF8')),'hex')
$$;
CREATE FUNCTION mlb036_private.context(expected_role TEXT,require_readonly BOOLEAN) RETURNS mlb036_private.authority
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority; role_name NAME; now_value TIMESTAMPTZ;
BEGIN
    IF current_setting('transaction_isolation')<>'read committed' OR
       (require_readonly AND current_setting('transaction_read_only')<>'on') THEN RAISE EXCEPTION '036 certified RC transaction required'; END IF;
    PERFORM public.mlb_identity_gate(false);
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    role_name:=CASE expected_role WHEN 'reader' THEN a.reader_role WHEN 'knowledge' THEN a.knowledge_role ELSE NULL END;
    IF expected_role='reader' AND session_user=a.operator_role THEN role_name:=a.operator_role; END IF;
    IF role_name IS NULL OR session_user<>role_name THEN RAISE EXCEPTION '036 explicit session principal required'; END IF;
    now_value:=clock_timestamp();
    IF pg_is_in_recovery() OR a.database_name<>current_database()
      OR a.database_oid<>(SELECT oid FROM pg_database WHERE datname=current_database())
      OR a.system_identifier<>(SELECT system_identifier::text FROM pg_control_system())
      OR a.server_address IS DISTINCT FROM host(inet_server_addr()) OR a.server_port IS DISTINCT FROM inet_server_port()
      OR a.postmaster_started_at<>pg_postmaster_start_time() OR a.catalog_sha256<>mlb036_private.catalog_identity()
      OR now_value<a.observed_high_water OR now_value<a.postmaster_started_at THEN RAISE EXCEPTION '036 authority/clock/capability drift'; END IF;
    RETURN a;
END $$;
CREATE FUNCTION mlb036_private.state() RETURNS JSONB
LANGUAGE sql STABLE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
    SELECT jsonb_build_object('policy',a.policy,'profile',a.schema_capability_profile,
      'target',to_jsonb(a)-ARRAY['observed_high_water','catalog_sha256','reader_role','knowledge_role','operator_role','raw_role'],
      'ledger034',public.mlb_identity_ledger_fingerprint(),'ledger035',public.mlb_retirement_legacy_fingerprint(),
      'topology',(SELECT epoch FROM public.mlb_identity_topology_fence WHERE singleton),
      'projection_digest',encode(sha256(mlb036_private.semantic_frame(mlb036_private.identity_projection())),'hex'),
      'fences',(SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY game_id),'[]'::jsonb) FROM public.mlb_game_identity_write_fences f WHERE game_id IN(26,584)),
      'audits',(SELECT coalesce(jsonb_agg(encode(mlb036_private.audit_frame(r),'hex') ORDER BY audit_id),'[]'::jsonb) FROM mlb036_private.arbitrations r),
      'events',(SELECT coalesce(jsonb_agg((to_jsonb(e)-'operation_receipt') ORDER BY event_id),'[]'::jsonb) FROM mlb036_private.arbitration_events e),
      'audit_ids',(SELECT coalesce(jsonb_agg(audit_id ORDER BY audit_id),'[]'::jsonb) FROM mlb036_private.arbitrations))
    FROM mlb036_private.authority a WHERE singleton
$$;
CREATE FUNCTION mlb036_private.state_fingerprint(s JSONB) RETURNS TEXT
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
BEGIN
    IF jsonb_typeof(s)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(s))<>11
      OR NOT s ?& ARRAY['policy','profile','target','ledger034','ledger035','topology','projection_digest','fences','audits','events','audit_ids'] THEN
        RAISE EXCEPTION '036 exact correction state fields'; END IF;
    RETURN encode(sha256(mlb036_private.codec(to_jsonb('SPORTSMODEL:MLB036:CORRECTION_STATE:v1'::text))||mlb036_private.semantic_frame(s)),'hex');
END
$$;
CREATE FUNCTION mlb036_private.receipt_frame(r mlb036_private.knowledge_receipts) RETURNS BYTEA
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
    SELECT mlb036_private.semantic_frame(to_jsonb(r)-'receipt_body_sha256')
$$;
CREATE FUNCTION mlb036_private.receipt_hash(r mlb036_private.knowledge_receipts) RETURNS TEXT
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
    SELECT encode(sha256(mlb036_private.codec(to_jsonb('SPORTSMODEL:MLB036:KNOWLEDGE_RECEIPT:v1'::text))||mlb036_private.receipt_frame(r)),'hex')
$$;
CREATE FUNCTION mlb036_private.issue_knowledge() RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority; s JSONB; fp TEXT; r mlb036_private.knowledge_receipts; own_id XID8; available TIMESTAMPTZ;
BEGIN
    IF current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION '036 explicit issuance write transaction required'; END IF;
    a:=mlb036_private.context('knowledge',false);
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton FOR UPDATE;
    own_id:=pg_current_xact_id();
    IF EXISTS(SELECT 1 FROM mlb036_private.arbitrations WHERE writer_xid8=own_id)
      OR EXISTS(SELECT 1 FROM mlb036_private.arbitration_events WHERE writer_xid8=own_id) THEN RAISE EXCEPTION '036 own uncommitted correction cannot certify'; END IF;
    s:=mlb036_private.state(); fp:=mlb036_private.state_fingerprint(s);
    SELECT * INTO r FROM mlb036_private.knowledge_receipts WHERE correction_state_fingerprint=fp
      AND postmaster_started_at=a.postmaster_started_at AND authority_epoch=a.authority_epoch
      AND issuer_xid8<>own_id ORDER BY receipt_id LIMIT 1;
    IF FOUND THEN
        IF r.receipt_body_sha256<>mlb036_private.receipt_hash(r) THEN RAISE EXCEPTION '036 corrupt receipt'; END IF;
        RETURN to_jsonb(r);
    END IF;
    available:=clock_timestamp();
    IF available<a.observed_high_water OR available<a.postmaster_started_at
      OR EXISTS(SELECT 1 FROM mlb036_private.arbitrations WHERE recorded_at>available) THEN RAISE EXCEPTION '036 observation clock regression'; END IF;
    r.format_version:=1; r.issuer_xid8:=own_id; r.available_at:=available;
    r.deployment_id:=a.deployment_id; r.system_identifier:=a.system_identifier;
    r.database_oid:=a.database_oid; r.database_name:=a.database_name;
    r.server_address:=a.server_address; r.server_port:=a.server_port; r.postmaster_started_at:=a.postmaster_started_at;
    r.authority_epoch:=a.authority_epoch; r.schema_capability_profile:=a.schema_capability_profile;
    r.correction_policy_version:=a.correction_policy_version; r.correction_state_fingerprint:=fp;
    r.identity034_digest:=s->>'ledger034'; r.identity035_digest:=s->>'ledger035';
    r.identity_topology_epoch:=(s->>'topology')::bigint; r.projection_digest:=s->>'projection_digest';
    r.fence_digest:=encode(sha256(mlb036_private.semantic_frame(s->'fences')),'hex');
    SELECT coalesce(array_agg(v::bigint),'{}'::bigint[]) INTO r.referenced_audit_ids FROM jsonb_array_elements_text(s->'audit_ids') v;
    r.receipt_id:=nextval(pg_get_serial_sequence('mlb036_private.knowledge_receipts','receipt_id'));
    r.receipt_body_sha256:=mlb036_private.receipt_hash(r);
    INSERT INTO mlb036_private.knowledge_receipts OVERRIDING SYSTEM VALUE SELECT r.*;
    UPDATE mlb036_private.authority SET observed_high_water=available WHERE singleton;
    RETURN to_jsonb(r);
END $$;
CREATE FUNCTION mlb036_private.canonical_json(value JSONB) RETURNS TEXT
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
    SELECT CASE jsonb_typeof(value)
      WHEN 'object' THEN '{'||coalesce((SELECT string_agg(to_jsonb(key)::text||':'||mlb036_private.canonical_json(val),',' ORDER BY convert_to(key,'UTF8')) FROM jsonb_each(value) e(key,val)),'')||'}'
      WHEN 'array' THEN '['||coalesce((SELECT string_agg(mlb036_private.canonical_json(val),',' ORDER BY ord) FROM jsonb_array_elements(value) WITH ORDINALITY e(val,ord)),'')||']'
      ELSE value::text END
$$;
CREATE FUNCTION mlb036_private.legacy_children(r mlb036_private.knowledge_receipts,cutoff TIMESTAMPTZ) RETURNS JSONB
LANGUAGE plpgsql STABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE body JSONB; child JSONB;
BEGIN
    body:=jsonb_build_object('version',2,'profile',r.schema_capability_profile,
      'fingerprint',public.mlb_retirement_fingerprint(r.schema_capability_profile),
      'ledger034',r.identity034_digest,'ledger035',r.identity035_digest,'topology_epoch',r.identity_topology_epoch,
      'available_at',to_char(r.available_at,'YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00',
      'endpoint',jsonb_build_array(r.server_address,r.server_port,r.database_name));
    child:=jsonb_build_object('version',1,'ledger_fingerprint',r.identity034_digest,'available_at',body->>'available_at','cutoff_time',cutoff);
    RETURN jsonb_build_object('v1',child,'v2',body||jsonb_build_object('cutoff_time',cutoff,
      'artifact_sha256',encode(sha256(convert_to(mlb036_private.canonical_json(body),'UTF8')),'hex')));
END $$;
CREATE FUNCTION mlb036_private.validate_knowledge(receipt_locator BIGINT,cutoff TIMESTAMPTZ,read_only BOOLEAN DEFAULT TRUE) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority; r mlb036_private.knowledge_receipts; s JSONB; fp TEXT; child JSONB; capture RECORD;
BEGIN
    a:=mlb036_private.context('reader',read_only);
    IF receipt_locator IS NULL OR receipt_locator<=0 OR cutoff IS NULL OR NOT isfinite(cutoff) THEN RAISE EXCEPTION '036 exact receipt/cutoff'; END IF;
    -- One query composes the current state and resolves the row in one MVCC snapshot.
    SELECT to_jsonb(rec) AS receipt,mlb036_private.state() AS state INTO capture FROM mlb036_private.knowledge_receipts rec WHERE receipt_id=receipt_locator;
    IF NOT FOUND THEN RAISE EXCEPTION '036 committed receipt required'; END IF;
    r:=jsonb_populate_record(NULL::mlb036_private.knowledge_receipts,capture.receipt); s:=capture.state;
    IF r.issuer_xid8 IS NOT DISTINCT FROM pg_current_xact_id_if_assigned() THEN RAISE EXCEPTION '036 committed other-transaction receipt required'; END IF;
    fp:=mlb036_private.state_fingerprint(s);
    IF r.receipt_body_sha256<>mlb036_private.receipt_hash(r) OR r.correction_state_fingerprint<>fp
      OR r.deployment_id<>a.deployment_id OR r.system_identifier<>a.system_identifier OR r.database_oid<>a.database_oid
      OR r.database_name<>a.database_name OR r.server_address<>a.server_address OR r.server_port<>a.server_port
      OR r.postmaster_started_at<>a.postmaster_started_at OR r.authority_epoch<>a.authority_epoch
      OR r.schema_capability_profile<>a.schema_capability_profile OR r.available_at>cutoff OR cutoff>clock_timestamp() THEN RAISE EXCEPTION '036 unavailable/stale/changed knowledge'; END IF;
    child:=mlb036_private.legacy_children(r,cutoff);
    PERFORM set_config('sportsmodel.identity_knowledge',(child->'v1')::text,true);
    PERFORM set_config('sportsmodel.retirement_knowledge',(child->'v2')::text,true);
    PERFORM public.mlb_retirement_history_guard();
    RETURN jsonb_build_object('receipt',to_jsonb(r),'cutoff_time',cutoff,'state',s);
END $$;
CREATE FUNCTION mlb036_private.register_authority(settings JSONB) RETURNS VOID
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE owner_id OID; read_owner OID; write_owner OID; supplied NAME; previous_epoch BIGINT; p JSONB; role_keys TEXT[]:=ARRAY['reader_role','knowledge_role','operator_role','raw_role']; key TEXT;
BEGIN
    SELECT nspowner INTO STRICT owner_id FROM pg_namespace WHERE nspname='mlb036_private';
    IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname=session_user) AND NOT pg_has_role(session_user,owner_id,'MEMBER') THEN
        RAISE EXCEPTION '036 separately authorized provisioning owner required'; END IF;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE oid=owner_id AND(rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))
      OR EXISTS(SELECT 1 FROM pg_class WHERE relnamespace='mlb036_private'::regnamespace AND relkind IN('r','p','S') AND relowner<>owner_id) THEN
        RAISE EXCEPTION '036 exact restricted schema/table/sequence owner required'; END IF;
    SELECT proowner INTO STRICT read_owner FROM pg_proc WHERE oid='mlb036_private.certified_data(bigint,timestamptz,text,jsonb)'::regprocedure;
    SELECT proowner INTO STRICT write_owner FROM pg_proc WHERE oid='mlb036_private.correct_exact(jsonb,jsonb,text)'::regprocedure;
    IF read_owner=owner_id OR write_owner=owner_id OR read_owner=write_owner OR EXISTS(SELECT 1 FROM pg_roles WHERE oid IN(read_owner,write_owner) AND
      (rolcanlogin OR rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls))
      OR pg_has_role(read_owner,owner_id,'MEMBER') OR pg_has_role(write_owner,owner_id,'MEMBER')
      OR pg_has_role(read_owner,write_owner,'MEMBER')
      OR EXISTS(SELECT 1 FROM pg_proc WHERE pronamespace='mlb036_private'::regnamespace
      AND proname IN('context','validate_knowledge','post_correction_preview','inspect_knowledge','raw_case_snapshot') AND proowner<>read_owner)
      OR EXISTS(SELECT 1 FROM pg_class WHERE relnamespace='mlb036_private'::regnamespace AND relkind IN('r','p')
        AND (has_table_privilege(read_owner,oid,'INSERT') OR has_table_privilege(read_owner,oid,'UPDATE')
          OR has_table_privilege(read_owner,oid,'DELETE') OR has_table_privilege(read_owner,oid,'TRUNCATE'))) THEN
        RAISE EXCEPTION '036 distinct restricted non-login read/write owners required'; END IF;
    IF EXISTS(SELECT 1 FROM pg_proc WHERE pronamespace='mlb036_private'::regnamespace
      AND proname IN('issue_knowledge','reserve_run','finish_run','insert_prediction','run_guard','prediction_guard','lock_exact','operator_state','describe_target','acquire_exact_gate')
      AND proowner<>write_owner) THEN RAISE EXCEPTION '036 exact write-owner responsibility boundary'; END IF;
    IF settings IS NULL OR jsonb_typeof(settings)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(settings))<>8
      OR NOT settings ?& ARRAY['deployment_id','authority_epoch','mode','profile','reader_role','knowledge_role','operator_role','raw_role']
      OR settings->>'profile' !~ '^[0-9a-f]{64}$' OR settings->>'mode' NOT IN('native','isolated')
      OR length(settings->>'deployment_id') NOT BETWEEN 1 AND 128 THEN RAISE EXCEPTION '036 exact authority settings'; END IF;
    IF (SELECT array_agg(version ORDER BY version) FROM public.schema_migrations)<>ARRAY(SELECT generate_series(1,36)) THEN RAISE EXCEPTION '036 exact migration boundary'; END IF;
    IF (SELECT count(DISTINCT settings->>k) FROM unnest(role_keys) k)<>4 THEN RAISE EXCEPTION '036 distinct principals required'; END IF;
    IF EXISTS(SELECT 1 FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.prosecdef
      AND p.proname NOT IN('mlb_identity_touch_fence','mlb_identity_write_guard','mlb_retirement_topology_fresh',
        'mlb_retirement_ledger_ingress','mlb_retirement_write_guard','mlb_retirement_activate')) THEN
        RAISE EXCEPTION '036 unknown public privileged callable'; END IF;
    IF EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.prosecdef
      AND NOT (n.nspname='public' OR (n.nspname='mlb036_private' AND p.proname IN(
        'context','issue_knowledge','validate_knowledge','register_authority','operator_state','game_seal','correction_complete',
        'audit_complete','correct_exact','describe_target','lock_exact','certified_data','source_seal','acquire_exact_gate',
        'inspect_knowledge','raw_case_snapshot','post_correction_preview','run_guard','reserve_run','finish_run','prediction_guard','insert_prediction'))))
      OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='pg_catalog' AND p.oid>=16384) THEN
        RAISE EXCEPTION '036 unknown auxiliary/system privileged callable'; END IF;
    FOREACH key IN ARRAY role_keys LOOP
        supplied:=(settings->>key)::name;
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=supplied AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
             AND NOT rolreplication AND NOT rolbypassrls) OR pg_has_role(supplied,owner_id,'MEMBER') OR pg_has_role(supplied,read_owner,'MEMBER') OR pg_has_role(supplied,write_owner,'MEMBER')
             OR has_database_privilege(supplied,current_database(),'CREATE')
             OR has_database_privilege(supplied,current_database(),'TEMP')
             OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_toast%'
               AND has_schema_privilege(supplied,n.oid,'CREATE'))
             OR EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname NOT IN('pg_catalog','information_schema','mlb036_private')
               AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%'
               AND has_schema_privilege(supplied,n.oid,'USAGE'))
             OR EXISTS(SELECT 1 FROM pg_roles r WHERE r.rolname<>supplied AND pg_has_role(supplied,r.oid,'MEMBER'))
             OR has_parameter_privilege(supplied,'session_replication_role','SET')
             OR EXISTS(SELECT 1 FROM pg_parameter_acl p WHERE has_parameter_privilege(supplied,p.parname,'ALTER SYSTEM'))
             OR EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
               WHERE n.nspname='pg_catalog' AND has_function_privilege(supplied,p.oid,'EXECUTE')
                 AND NOT EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) acl
                    WHERE acl.grantee=0 AND acl.privilege_type='EXECUTE'))
             OR has_any_column_privilege(supplied,'public.games','UPDATE')
             OR EXISTS(SELECT 1 FROM pg_roles r WHERE pg_has_role(supplied,r.oid,'MEMBER') AND
               (r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls
                OR r.rolname IN('pg_read_all_data','pg_write_all_data','pg_execute_server_program','pg_read_server_files','pg_write_server_files','pg_signal_backend','pg_checkpoint')))
             OR EXISTS(SELECT 1 FROM pg_class c WHERE c.relnamespace='mlb036_private'::regnamespace
                AND CASE WHEN c.relkind IN('r','p','v','m','f') THEN
                  (has_table_privilege(supplied,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
                   OR has_any_column_privilege(supplied,c.oid,'SELECT,INSERT,UPDATE')) ELSE false END)
             OR EXISTS(SELECT 1 FROM pg_class c WHERE c.relnamespace='mlb036_private'::regnamespace
                AND CASE WHEN c.relkind='S' THEN has_sequence_privilege(supplied,c.oid,'USAGE,SELECT,UPDATE') ELSE false END) THEN
            RAISE EXCEPTION '036 unsafe runtime principal'; END IF;
    END LOOP;
    FOREACH key IN ARRAY ARRAY['operator_role','raw_role'] LOOP
        IF pg_has_role((settings->>'reader_role')::name,(settings->>key)::name,'MEMBER') THEN RAISE EXCEPTION '036 reader role inheritance bypass'; END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_class c WHERE c.relnamespace='public'::regnamespace AND c.relkind IN('r','p','v','m')
      AND (has_table_privilege((settings->>'reader_role')::name,c.oid,'SELECT') OR has_any_column_privilege((settings->>'reader_role')::name,c.oid,'SELECT'))) THEN
        RAISE EXCEPTION '036 reader must have no raw public relation grant'; END IF;
    -- PostgreSQL has no per-role DENY overriding PUBLIC. Do not silently revoke
    -- shared/NFL privileges here. Require independently provisioned namespace
    -- isolation, or block registration. Frozen034/035 bodies/ACLs remain unchanged.
    FOREACH key IN ARRAY role_keys LOOP
        IF has_schema_privilege((settings->>key)::name,'public','USAGE') THEN
            RAISE EXCEPTION '036 bounded client inherits raw public namespace; separate provisioning required'; END IF;
    END LOOP;
    SELECT authority_epoch INTO previous_epoch FROM mlb036_private.authority WHERE singleton;
    IF (settings->>'authority_epoch')::bigint<=coalesce(previous_epoch,0) THEN RAISE EXCEPTION '036 monotonic authority epoch'; END IF;
    IF settings->>'mode'='isolated' THEN
        IF current_database() !~ '^sportsmodel_test_arbitration210_[0-9]+$' OR pg_is_in_recovery() THEN RAISE EXCEPTION '036 isolated policy target required'; END IF;
        p:=jsonb_build_object('subject',584,'survivor',26,'game_pk',900584,
          'home',(SELECT team_id FROM public.teams WHERE team_name='Miami Marlins'),
          'away',(SELECT team_id FROM public.teams WHERE team_name='Cleveland Guardians'),
          'old_start','2026-07-12T17:41:00Z','new_start','2026-07-12T17:40:00Z','mlb_source',571,'odds_source',12,'odds_event','synthetic-arbitration-26');
        IF p->'home'='null'::jsonb OR p->'away'='null'::jsonb THEN RAISE EXCEPTION '036 isolated canonical participant fixture missing'; END IF;
    ELSE
        IF current_database()<>'sportsmodel' OR host(inet_server_addr())<>'127.0.0.1' OR inet_server_port()<>5432 OR pg_is_in_recovery() THEN
            RAISE EXCEPTION '036 fixed native policy target required'; END IF;
        p:=jsonb_build_object('subject',584,'survivor',26,'game_pk',823842,'home',14,'away',76,
          'old_start','2026-07-12T17:41:00Z','new_start','2026-07-12T17:40:00Z','mlb_source',571,'odds_source',12,'odds_event','fe2a389f5cf40c61156a794804ec0fff');
    END IF;
    p:=p||jsonb_build_object('case_identity','MLB:584:26:823842:minus60:v1','codec_version',1,'capability_version',1,
      'home_mlb_id',146,'away_mlb_id',114,'officialDate','2026-07-12','subject_start','2026-07-12T17:40:00Z','signed_delta_seconds',-60);
    PERFORM public.mlb_identity_gate(true);
    FOREACH key IN ARRAY role_keys LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA mlb036_private TO %I',settings->>key);
    END LOOP;
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.issue_knowledge() TO %I',settings->>'knowledge_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.inspect_knowledge() TO %I',settings->>'knowledge_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.raw_case_snapshot() TO %I',settings->>'raw_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.validate_knowledge(bigint,timestamptz,boolean) TO %I',settings->>'reader_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.certified_data(bigint,timestamptz,text,jsonb) TO %I',settings->>'reader_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.reserve_run(bigint,timestamptz,jsonb),mlb036_private.finish_run(bigint,timestamptz,text,bigint,text,jsonb,text),mlb036_private.insert_prediction(bigint,timestamptz,jsonb) TO %I',settings->>'reader_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.operator_state(),mlb036_private.correct_exact(jsonb,jsonb,text) TO %I',settings->>'operator_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.lock_exact(),mlb036_private.describe_target() TO %I',settings->>'operator_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.acquire_exact_gate() TO %I',settings->>'operator_role');
    EXECUTE format('GRANT EXECUTE ON FUNCTION mlb036_private.post_correction_preview(bigint,timestamptz,jsonb) TO %I',settings->>'operator_role');
    FOREACH key IN ARRAY role_keys LOOP
        IF has_schema_privilege((settings->>key)::name,'public','USAGE')
          OR NOT has_schema_privilege((settings->>key)::name,'mlb036_private','USAGE') THEN
            RAISE EXCEPTION '036 explicit schema grants unavailable'; END IF;
    END LOOP;
    INSERT INTO mlb036_private.authority VALUES(true,settings->>'deployment_id',(settings->>'authority_epoch')::bigint,settings->>'mode',
      (SELECT system_identifier::text FROM pg_control_system()),(SELECT oid FROM pg_database WHERE datname=current_database()),current_database(),
      host(inet_server_addr()),inet_server_port(),pg_postmaster_start_time(),settings->>'profile',repeat('0',64),'1.0.0',p,
      (settings->>'reader_role')::name,(settings->>'knowledge_role')::name,(settings->>'operator_role')::name,(settings->>'raw_role')::name,clock_timestamp())
    ON CONFLICT(singleton) DO UPDATE SET deployment_id=EXCLUDED.deployment_id,authority_epoch=EXCLUDED.authority_epoch,
      mode=EXCLUDED.mode,system_identifier=EXCLUDED.system_identifier,database_oid=EXCLUDED.database_oid,database_name=EXCLUDED.database_name,
      server_address=EXCLUDED.server_address,server_port=EXCLUDED.server_port,postmaster_started_at=EXCLUDED.postmaster_started_at,
      schema_capability_profile=EXCLUDED.schema_capability_profile,policy=EXCLUDED.policy,reader_role=EXCLUDED.reader_role,
      knowledge_role=EXCLUDED.knowledge_role,operator_role=EXCLUDED.operator_role,raw_role=EXCLUDED.raw_role,
      observed_high_water=greatest(mlb036_private.authority.observed_high_water,EXCLUDED.observed_high_water);
    UPDATE mlb036_private.authority SET catalog_sha256=mlb036_private.catalog_identity() WHERE singleton;
END $$;
CREATE FUNCTION mlb036_private.normalize_business(value JSONB,old_time TIMESTAMPTZ) RETURNS JSONB
LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
    SELECT jsonb_set(jsonb_set(value,'{identity,games}',
      (SELECT coalesce(jsonb_agg(CASE WHEN (g->>'game_id')::integer=26 THEN jsonb_set(g,'{game_date}',to_jsonb(old_time)) ELSE g END ORDER BY i),'[]'::jsonb)
         FROM jsonb_array_elements(value#>'{identity,games}') WITH ORDINALITY AS rows(g,i))),'{identity,candidates}',
      (SELECT coalesce(jsonb_agg(CASE WHEN (g->>'game_id')::integer=26 THEN jsonb_set(g,'{game_date}',to_jsonb(old_time)) ELSE g END ORDER BY i),'[]'::jsonb)
         FROM jsonb_array_elements(value#>'{identity,candidates}') WITH ORDINALITY AS rows(g,i)))
$$;
CREATE FUNCTION mlb036_private.business_hash(value JSONB) RETURNS TEXT
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE framed_value JSONB;
BEGIN
    IF jsonb_typeof(value)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(value))<>15
      OR NOT value ?& ARRAY['identity','history','teams','pitching','markets','legacy','observations','team_sources','player_sources',
        'team_identities','player_identities','ingestion_runs','sportsbooks','book_sources','canonical_corrections'] THEN
        RAISE EXCEPTION '036 exact business snapshot fields'; END IF;
    -- historical_games.game_date is an official DATE, not a canonical instant.
    -- The audit snapshot keeps its original field; only its framed projection
    -- uses the explicit official_date semantic type.
    framed_value:=jsonb_set(value,'{history}',(SELECT coalesce(jsonb_agg(
      (row_value-'game_date')||jsonb_build_object('official_date',row_value->'game_date') ORDER BY ordinal),'[]'::jsonb)
      FROM jsonb_array_elements(value->'history') WITH ORDINALITY rows(row_value,ordinal)));
    RETURN encode(sha256(mlb036_private.codec(to_jsonb('SPORTSMODEL:MLB036:BUSINESS_STATE:v1'::text))
      ||mlb036_private.semantic_frame(framed_value)),'hex');
END $$;
CREATE FUNCTION mlb036_private.operator_state() RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority; s JSONB;
BEGIN
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.operator_role OR pg_is_in_recovery() OR a.database_name<>current_database()
      OR a.system_identifier<>(SELECT system_identifier::text FROM pg_control_system())
      OR a.server_address IS DISTINCT FROM host(inet_server_addr()) OR a.server_port IS DISTINCT FROM inet_server_port()
      OR a.postmaster_started_at<>pg_postmaster_start_time() OR a.catalog_sha256<>mlb036_private.catalog_identity()
      OR clock_timestamp()<a.observed_high_water THEN RAISE EXCEPTION '036 operator authority/capability drift'; END IF;
    SELECT jsonb_build_object('state',mlb036_private.state(),'business',mlb036_private.business_snapshot(),
      'subject_dependencies',public.mlb_identity_forbidden_dependencies(584),
      'operation',(SELECT jsonb_build_object('request_sha256',r.request_sha256,'approval_sha256',r.approval_sha256,
        'audit_id',r.audit_id,'receipt',e.operation_receipt,'post_state_current',
        e.operation_receipt->>'post_state_fingerprint'=mlb036_private.state_fingerprint(mlb036_private.state()))
        FROM mlb036_private.arbitrations r JOIN mlb036_private.arbitration_events e ON e.audit_reference=r.audit_id),
      'label','RAW_FORENSIC','historically_certified',false) INTO s;
    RETURN s;
END $$;
CREATE FUNCTION mlb036_private.game_seal() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE own_id OID; configured mlb036_private.authority;
BEGIN
    IF OLD.game_id NOT IN(26,584) THEN IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW; END IF;
    IF EXISTS(SELECT 1 FROM mlb036_private.arbitrations) THEN
        IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['scheduled_innings','doubleheader_status','game_number'])
            IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['scheduled_innings','doubleheader_status','game_number']) THEN
            RAISE EXCEPTION '036 audit-linked physical identity sealed'; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    IF NEW.game_date IS DISTINCT FROM OLD.game_date AND OLD.game_id=26 THEN
        SELECT * INTO STRICT configured FROM mlb036_private.authority WHERE singleton;
        SELECT nspowner INTO own_id FROM pg_namespace WHERE nspname='mlb036_private';
        IF session_user<>configured.operator_role OR current_setting('transaction_isolation')<>'serializable'
          OR OLD.game_date<>(configured.policy->>'old_start')::timestamptz OR NEW.game_date<>(configured.policy->>'new_start')::timestamptz
          OR (to_jsonb(NEW)-'game_date') IS DISTINCT FROM(to_jsonb(OLD)-'game_date') THEN RAISE EXCEPTION '036 bounded correction only'; END IF;
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_036_game_seal BEFORE UPDATE OR DELETE ON public.games FOR EACH ROW EXECUTE FUNCTION mlb036_private.game_seal();
CREATE FUNCTION mlb036_private.correction_complete() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
BEGIN
    IF OLD.game_id=26 AND NEW.game_date IS DISTINCT FROM OLD.game_date THEN
        IF (SELECT count(*) FROM mlb036_private.arbitrations WHERE survivor_physical_id=26 AND old_start=OLD.game_date
            AND new_start=NEW.game_date AND writer_xid8=pg_current_xact_id())<>1 THEN RAISE EXCEPTION '036 matching same-transaction correction audit required'; END IF;
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER mlb036_correction_complete AFTER UPDATE ON public.games DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mlb036_private.correction_complete();
CREATE FUNCTION mlb036_private.audit_complete() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE case_value public.mlb_legacy_identity_retirements;
BEGIN
    IF (SELECT count(*) FROM mlb036_private.arbitration_events WHERE audit_reference=NEW.audit_id AND writer_xid8=NEW.writer_xid8)<>1
      OR NOT EXISTS(SELECT 1 FROM public.games WHERE game_id=26 AND game_date=NEW.new_start)
      OR NEW.writer_xid8<>pg_current_xact_id() THEN RAISE EXCEPTION '036 atomic audit/event/time completeness'; END IF;
    IF (SELECT operation_receipt->>'post_state_fingerprint' FROM mlb036_private.arbitration_events WHERE audit_reference=NEW.audit_id)
      IS DISTINCT FROM mlb036_private.state_fingerprint(mlb036_private.state()) THEN RAISE EXCEPTION '036 independent operation post-state completeness'; END IF;
    IF NEW.pre_business_sha256 IS DISTINCT FROM mlb036_private.business_hash(NEW.pre_state->'business')
      OR NEW.post_business_sha256 IS DISTINCT FROM mlb036_private.business_hash(mlb036_private.business_snapshot())
      OR mlb036_private.normalize_business(NEW.pre_state->'business',NEW.old_start) IS DISTINCT FROM
         mlb036_private.normalize_business(mlb036_private.business_snapshot(),NEW.old_start) THEN
        RAISE EXCEPTION '036 independent framed business preservation'; END IF;
    case_value:=jsonb_populate_record(NULL::public.mlb_legacy_identity_retirements,NEW.retirement_case);
    PERFORM public.mlb_retirement_validate(case_value,false);
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER mlb036_audit_complete AFTER INSERT ON mlb036_private.arbitrations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mlb036_private.audit_complete();
CREATE FUNCTION mlb036_private.correct_exact(request_body JSONB,expected_state JSONB,approved_preview_sha256 TEXT) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority; before_state JSONB; after_state JSONB; business_before JSONB; business_after JSONB;
        audit_row mlb036_private.arbitrations; case_value public.mlb_legacy_identity_retirements; result JSONB; gid INTEGER;
        origin JSONB; metadata JSONB;
BEGIN
    IF current_setting('transaction_isolation')<>'serializable' OR current_setting('transaction_read_only')<>'off' THEN
        RAISE EXCEPTION '036 SERIALIZABLE explicit correction transaction'; END IF;
    PERFORM public.mlb_identity_gate(true);
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.operator_role THEN RAISE EXCEPTION '036 correction principal'; END IF;
    PERFORM epoch FROM public.mlb_identity_topology_fence WHERE singleton FOR UPDATE;
    PERFORM game_id FROM public.games WHERE game_id IN(26,584) ORDER BY game_id FOR UPDATE;
    PERFORM game_id FROM public.mlb_game_identity_write_fences WHERE game_id IN(26,584) ORDER BY game_id FOR UPDATE;
    IF EXISTS(SELECT 1 FROM mlb036_private.arbitrations) THEN RAISE EXCEPTION 'ALREADY_APPLIED_REFUSAL'; END IF;
    before_state:=mlb036_private.operator_state();
    IF before_state IS DISTINCT FROM expected_state OR request_body IS NULL OR jsonb_typeof(request_body)<>'object'
      OR NOT request_body ?& ARRAY['request_sha256','evidence_sha256','retirement_case','profile','old_start','new_start','subject','survivor','game_pk','origin_provenance']
      OR EXISTS(SELECT 1 FROM jsonb_each(request_body) WHERE value='null'::jsonb)
      OR (SELECT count(*) FROM jsonb_object_keys(request_body))<>10
      OR EXISTS(SELECT 1 FROM jsonb_each(request_body) WHERE key IN('request_sha256','evidence_sha256','profile','old_start','new_start') AND jsonb_typeof(value)<>'string')
      OR EXISTS(SELECT 1 FROM jsonb_each(request_body) WHERE key IN('subject','survivor','game_pk') AND (jsonb_typeof(value)<>'number' OR value::text !~ '^[1-9][0-9]*$'))
      OR request_body->>'old_start' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'
      OR request_body->>'new_start' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'
      OR request_body->>'request_sha256' !~ '^[0-9a-f]{64}$' OR request_body->>'evidence_sha256' !~ '^[0-9a-f]{64}$'
      OR approved_preview_sha256 !~ '^[0-9a-f]{64}$' OR request_body->>'profile'<>a.schema_capability_profile
      OR (request_body->>'subject')::integer<>584 OR (request_body->>'survivor')::integer<>26
      OR (request_body->>'game_pk')::bigint<>(a.policy->>'game_pk')::bigint
      OR (request_body->>'old_start')::timestamptz<>(a.policy->>'old_start')::timestamptz
      OR (request_body->>'new_start')::timestamptz<>(a.policy->>'new_start')::timestamptz THEN
        RAISE EXCEPTION '036 exact request/approval/state differs'; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.games WHERE game_id=26 AND game_date=(a.policy->>'old_start')::timestamptz AND home_team_id=(a.policy->>'home')::integer AND away_team_id=(a.policy->>'away')::integer)
      OR NOT EXISTS(SELECT 1 FROM public.games WHERE game_id=584 AND game_date=(a.policy->>'new_start')::timestamptz AND home_team_id=(a.policy->>'home')::integer AND away_team_id=(a.policy->>'away')::integer)
      OR NOT EXISTS(SELECT 1 FROM public.game_sources WHERE game_source_id=571 AND game_id=26 AND source_name='mlb_stats' AND external_game_id=a.policy->>'game_pk')
      OR NOT EXISTS(SELECT 1 FROM public.game_sources WHERE game_source_id=12 AND game_id=26 AND source_name='odds_api' AND external_game_id=a.policy->>'odds_event')
      OR EXISTS(SELECT 1 FROM public.games g WHERE g.game_id IN(26,584) AND
        ((g.doubleheader_status IS NOT NULL AND g.doubleheader_status<>'single') OR
         (g.game_number IS NOT NULL AND g.game_number<>1)))
      OR EXISTS(SELECT 1 FROM public.game_identity_dispositions WHERE subject_game_id IN(26,584) OR survivor_game_id IN(26,584))
      OR EXISTS(SELECT 1 FROM public.mlb_legacy_identity_retirements WHERE subject_game_id IN(26,584) OR survivor_game_id IN(26,584)) THEN
        RAISE EXCEPTION '036 exact fixed source/physical/lifetime case required'; END IF;
    case_value:=jsonb_populate_record(NULL::public.mlb_legacy_identity_retirements,request_body->'retirement_case');
    origin:=request_body->'origin_provenance'; metadata:=origin->'metadata';
    IF jsonb_typeof(origin)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(origin))<>6
      OR NOT origin ?& ARRAY['metadata','metadata_utf8','metadata_raw_sha256','chain_sha256','chain_manifest_sha256','chain_entries']
      OR EXISTS(SELECT 1 FROM jsonb_each(origin) WHERE value='null'::jsonb)
      OR EXISTS(SELECT 1 FROM jsonb_each(origin) WHERE key IN('metadata_raw_sha256','chain_sha256','chain_manifest_sha256') AND jsonb_typeof(value)<>'string')
      OR origin->>'metadata_raw_sha256' !~ '^[0-9a-f]{64}$' OR origin->>'chain_sha256' !~ '^[0-9a-f]{64}$'
      OR origin->>'chain_manifest_sha256' !~ '^[0-9a-f]{64}$' OR jsonb_typeof(origin->'metadata_utf8')<>'string'
      OR octet_length(origin->>'metadata_utf8') NOT BETWEEN 1 AND 8192
      OR encode(sha256(convert_to(origin->>'metadata_utf8','UTF8')),'hex') IS DISTINCT FROM origin->>'metadata_raw_sha256'
      OR (origin->>'metadata_utf8')::jsonb IS DISTINCT FROM metadata
      OR case_value.evidence_reference IS DISTINCT FROM origin->>'metadata_raw_sha256'
      OR jsonb_typeof(origin->'chain_entries')<>'object' OR (SELECT count(*) FROM jsonb_object_keys(origin->'chain_entries'))<>2
      OR NOT (origin->'chain_entries') ?& ARRAY['payload','metadata']
      OR EXISTS(SELECT 1 FROM jsonb_each(origin->'chain_entries') WHERE jsonb_typeof(value)<>'string' OR length(value#>>'{}') NOT BETWEEN 1 AND 1000)
      OR jsonb_typeof(metadata)<>'object' OR NOT metadata ?& ARRAY['url','final_url','http_status','observed_utc','sha256','bytes','requests','anonymous','paid_Odds_API','server_date','content_type']
      OR EXISTS(SELECT 1 FROM jsonb_each(metadata) WHERE value='null'::jsonb)
      OR EXISTS(SELECT 1 FROM jsonb_each(metadata) WHERE key IN('url','final_url','observed_utc','sha256','server_date','content_type') AND jsonb_typeof(value)<>'string')
      OR (SELECT count(*) FROM jsonb_object_keys(metadata))<>(CASE WHEN a.mode='isolated' THEN 12 ELSE 11 END)
      OR (SELECT count(*) FROM json_object_keys((origin->>'metadata_utf8')::json))<>(SELECT count(*) FROM jsonb_object_keys(metadata))
      OR (a.mode='isolated' AND metadata->'synthetic' IS DISTINCT FROM 'true'::jsonb)
      OR metadata->>'url'<>'https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-07-12'
      OR metadata->>'final_url' IS DISTINCT FROM metadata->>'url'
      OR metadata->'http_status' IS DISTINCT FROM '200'::jsonb OR metadata->'requests' IS DISTINCT FROM '1'::jsonb
      OR metadata->'anonymous' IS DISTINCT FROM 'true'::jsonb OR metadata->'paid_Odds_API' IS DISTINCT FROM 'false'::jsonb
      OR jsonb_typeof(metadata->'bytes')<>'number' OR metadata->>'bytes' !~ '^[1-9][0-9]*$'
      OR jsonb_typeof(metadata->'content_type')<>'string' OR length(metadata->>'content_type') NOT BETWEEN 1 AND 128
      OR lower(split_part(metadata->>'content_type',';',1))<>'application/json'
      OR jsonb_typeof(metadata->'server_date')<>'string' OR length(metadata->>'server_date') NOT BETWEEN 1 AND 128
      OR lower(metadata->>'sha256') IS DISTINCT FROM case_value.proof->>'raw_payload_sha256'
      OR metadata->>'observed_utc' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})$'
      OR (metadata->>'observed_utc')::timestamptz<(a.policy->>'new_start')::timestamptz
      OR (metadata->>'observed_utc')::timestamptz>clock_timestamp()
      OR (a.mode='native' AND (origin->>'metadata_raw_sha256'<>'fa628ec01db3189fc79e5a7a7519b1d8f0456780e48458cb3bd15d4ac9b7fe00'
        OR origin->>'chain_sha256'<>'e71cc17ee25dddf4c55a69a073192f0665cb66dbc9e5a67813bf871eba6b02e3'
        OR case_value.proof->>'raw_payload_sha256'<>'f8a664f6cc3a0eaa640b5669cd490502f36edc9a0087c58219d462a8d606b23b')) THEN
        RAISE EXCEPTION '036 exact retained origin/payload/source-chain provenance required'; END IF;
    IF case_value.domain IS DISTINCT FROM 'MLB' OR case_value.policy_version IS DISTINCT FROM '1.0.0'
       OR case_value.subject_game_id<>584 OR case_value.survivor_game_id<>26 OR case_value.game_pk<>(a.policy->>'game_pk')::bigint
       OR case_value.category<>'IDENTITY_ONLY_DUPLICATE' OR case_value.implementation_sha256<>a.schema_capability_profile
       OR case_value.proof->>'gameType'<>'R' OR case_value.proof->>'home_mlb_id'<>'146' OR case_value.proof->>'away_mlb_id'<>'114'
       OR case_value.proof->>'home_name'<>'Miami Marlins' OR case_value.proof->>'away_name'<>'Cleveland Guardians' THEN
       RAISE EXCEPTION '036 exact authority case'; END IF;
    -- Exact A04 fixed-case inventory; unchanged035 still validates every retained
    -- player/source, starter, appearance, metric and availability predicate.
    IF (SELECT count(*) FROM public.player_game_pitching_statistics WHERE game_id=26)<>12 THEN
        RAISE EXCEPTION '036 complete fixed survivor pitching inventory required'; END IF;
    business_before:=before_state->'business';
    UPDATE public.games SET game_date=(a.policy->>'new_start')::timestamptz WHERE game_id=26;
    -- Validate the unchanged035 contract on the corrected projection, without activation.
    PERFORM public.mlb_retirement_validate(case_value,false);
    PERFORM public.mlb_identity_touch_fence(26); PERFORM public.mlb_identity_touch_fence(584);
    business_after:=mlb036_private.business_snapshot();
    IF mlb036_private.normalize_business(business_after,(a.policy->>'old_start')::timestamptz)
       IS DISTINCT FROM mlb036_private.normalize_business(business_before,(a.policy->>'old_start')::timestamptz) THEN
       RAISE EXCEPTION '036 protected business state changed'; END IF;
    INSERT INTO mlb036_private.arbitrations(case_identity,duplicate_physical_id,survivor_physical_id,authoritative_game_pk,old_start,new_start,signed_delta_seconds,
      request_sha256,evidence_sha256,approval_sha256,schema_capability_profile,correction_policy_version,request_body,retirement_case,
      pre_business_sha256,post_business_sha256,pre_state,post_state,writer_xid8,recorded_at)
    VALUES('MLB:584:26:823842:minus60:v1',584,26,(a.policy->>'game_pk')::bigint,(a.policy->>'old_start')::timestamptz,(a.policy->>'new_start')::timestamptz,-60,
      request_body->>'request_sha256',request_body->>'evidence_sha256',approved_preview_sha256,a.schema_capability_profile,'1.0.0',request_body,request_body->'retirement_case',
      mlb036_private.business_hash(business_before),mlb036_private.business_hash(business_after),
      before_state,mlb036_private.state(),NULL,NULL) RETURNING * INTO audit_row;
    result:=jsonb_build_object('status','APPLIED','audit_id',audit_row.audit_id,'old_start',audit_row.old_start,'new_start',audit_row.new_start,
      'writer_xid8',audit_row.writer_xid8,'recorded_at',audit_row.recorded_at,'approval_sha256',approved_preview_sha256,
      'request_sha256',audit_row.request_sha256,'retry_authorized',false);
    INSERT INTO mlb036_private.arbitration_events(audit_reference,sequence,action,operation_receipt,writer_xid8,recorded_at)
      VALUES(audit_row.audit_id,1,'APPLIED',result,NULL,NULL) RETURNING operation_receipt INTO result;
    RETURN result;
END $$;
CREATE FUNCTION mlb036_private.describe_target() RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE a mlb036_private.authority;
BEGIN
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.operator_role THEN RAISE EXCEPTION '036 target-inspection principal'; END IF;
    RETURN jsonb_build_object('database',current_database(),'address',host(inet_server_addr()),'port',inet_server_port(),
      'started',pg_postmaster_start_time(),'backend',pg_backend_pid(),'version',current_setting('server_version_num'),
      'readonly',current_setting('transaction_read_only'),'isolation',current_setting('transaction_isolation'),
      'system_identifier',(SELECT system_identifier::text FROM pg_control_system()),
      'migrations',(SELECT jsonb_agg(jsonb_build_array(version,filename,checksum) ORDER BY version) FROM public.schema_migrations));
END $$;
CREATE FUNCTION mlb036_private.lock_exact() RETURNS VOID
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE a mlb036_private.authority;
BEGIN
    IF current_setting('transaction_isolation')<>'serializable' OR current_setting('transaction_read_only')<>'off' THEN
      RAISE EXCEPTION '036 exact SERIALIZABLE lock transaction'; END IF;
    PERFORM public.mlb_identity_gate(true);
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.operator_role THEN RAISE EXCEPTION '036 lock principal'; END IF;
    PERFORM epoch FROM public.mlb_identity_topology_fence WHERE singleton FOR UPDATE;
    PERFORM game_id FROM public.games WHERE game_id IN(26,584) ORDER BY game_id FOR UPDATE;
    PERFORM game_id FROM public.mlb_game_identity_write_fences WHERE game_id IN(26,584) ORDER BY game_id FOR UPDATE;
END $$;
CREATE FUNCTION mlb036_private.bounded_ids(value JSONB,maximum INTEGER) RETURNS INTEGER[]
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE result INTEGER[];
BEGIN
    IF jsonb_typeof(value)<>'array' OR maximum NOT BETWEEN 1 AND 10000 OR jsonb_array_length(value)>maximum
      OR EXISTS(SELECT 1 FROM jsonb_array_elements(value) v WHERE jsonb_typeof(v)<>'number' OR v::text !~ '^[1-9][0-9]*$') THEN
        RAISE EXCEPTION '036 bounded typed reader IDs'; END IF;
    SELECT coalesce(array_agg(v::integer),'{}'::integer[]) INTO result FROM jsonb_array_elements_text(value) v;
    IF cardinality(result)<>(SELECT count(DISTINCT v) FROM unnest(result) v) THEN RAISE EXCEPTION '036 duplicate reader IDs'; END IF;
    RETURN result;
END $$;
CREATE FUNCTION mlb036_private.data_rows(purpose TEXT,params JSONB,cutoff TIMESTAMPTZ) RETURNS JSONB
LANGUAGE plpgsql STABLE PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE rows JSONB; selected_id INTEGER; ids INTEGER[]; teams_requested INTEGER[]; starters_requested INTEGER[]; n INTEGER; start_value TIMESTAMPTZ; end_value TIMESTAMPTZ; keys TEXT[];
BEGIN
    keys:=CASE purpose WHEN 'game' THEN ARRAY['id'] WHEN 'next_game' THEN ARRAY[]::text[]
      WHEN 'earliest_start' THEN ARRAY['start','end'] WHEN 'slate' THEN ARRAY['start','end']
      WHEN 'h1_team' THEN ARRAY['ids'] WHEN 'h1_starter' THEN ARRAY['ids']
      WHEN 'team_stats' THEN ARRAY['id','limit'] WHEN 'starter_stats' THEN ARRAY['id','limit']
      WHEN 'bullpen_stats' THEN ARRAY['id'] WHEN 'markets' THEN ARRAY['id','include_live']
      WHEN 'recovery_identity' THEN ARRAY['id'] WHEN 'feature_audit' THEN ARRAY['start','end']
      WHEN 'completeness' THEN ARRAY['ids'] WHEN 'game_sources' THEN ARRAY['ids']
      WHEN 'mlb_teams' THEN ARRAY['ids'] WHEN 'mlb_starters' THEN ARRAY['ids'] WHEN 'nonplayed_identity' THEN ARRAY['ids']
      WHEN 'required_game_pks' THEN ARRAY['team_ids','starter_ids']
      WHEN 'feature_audit_summary' THEN ARRAY['start','end']
      WHEN 'prediction_explanation' THEN ARRAY['id'] ELSE NULL END;
    IF keys IS NULL OR params IS NULL OR jsonb_typeof(params)<>'object'
      OR (SELECT count(*) FROM jsonb_object_keys(params))<>cardinality(keys) OR NOT params ?& keys
      OR EXISTS(SELECT 1 FROM jsonb_each(params) WHERE value='null'::jsonb) THEN RAISE EXCEPTION '036 typed reader exact fields'; END IF;
    IF params ? 'id' THEN
        IF params->>'id' !~ '^[1-9][0-9]*$' OR jsonb_typeof(params->'id')<>'number' THEN RAISE EXCEPTION '036 positive typed reader ID'; END IF;
        selected_id:=(params->>'id')::integer;
    END IF;
    IF params ? 'ids' THEN
        ids:=mlb036_private.bounded_ids(params->'ids',CASE WHEN purpose IN('completeness','game_sources') THEN 10000 ELSE 32 END);
    END IF;
    IF purpose='required_game_pks' THEN
        teams_requested:=mlb036_private.bounded_ids(params->'team_ids',32);
        starters_requested:=mlb036_private.bounded_ids(params->'starter_ids',32);
    END IF;
    IF params ? 'limit' THEN
        n:=(params->>'limit')::integer;
        IF jsonb_typeof(params->'limit')<>'number' OR params->>'limit' !~ '^[1-9][0-9]*$'
          OR n>(CASE WHEN purpose='starter_stats' THEN 50 ELSE 200 END) THEN RAISE EXCEPTION '036 fixed feature window limit'; END IF;
    END IF;
    IF params ? 'start' THEN
        IF params->>'start' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' OR params->>'end' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' THEN RAISE EXCEPTION '036 aware date window'; END IF;
        start_value:=(params->>'start')::timestamptz; end_value:=(params->>'end')::timestamptz;
        IF NOT isfinite(start_value) OR NOT isfinite(end_value) OR start_value>=end_value OR end_value-start_value>INTERVAL '2 days' THEN
           RAISE EXCEPTION '036 bounded date window'; END IF;
    END IF;
    IF purpose IN('game','next_game','slate','earliest_start','feature_audit') THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.game_date,q.game_id),'[]'::jsonb) INTO rows FROM (
          SELECT g.game_id,g.game_date,g.home_team_id,g.away_team_id FROM public.games g
          WHERE NOT public.mlb_identity_is_retired(g.game_id) AND NOT EXISTS(SELECT 1 FROM public.nfl_games f WHERE f.game_id=g.game_id)
            AND g.home_team_id IS NOT NULL AND g.away_team_id IS NOT NULL
            AND EXISTS(SELECT 1 FROM public.baseball_team_sources t WHERE t.team_id=g.home_team_id AND t.source_name='mlb_stats')
            AND EXISTS(SELECT 1 FROM public.baseball_team_sources t WHERE t.team_id=g.away_team_id AND t.source_name='mlb_stats')
            AND (purpose<>'earliest_start' OR EXISTS(SELECT 1 FROM public.game_sources s WHERE s.game_id=g.game_id AND s.source_name='mlb_stats'))
            AND CASE WHEN purpose='game' THEN g.game_id=selected_id WHEN purpose='next_game' THEN g.game_date>=cutoff
                ELSE g.game_date>=start_value AND g.game_date<end_value END
          ORDER BY g.game_date,g.game_id LIMIT CASE WHEN purpose='next_game' THEN 1 ELSE 1001 END) q;
        IF jsonb_array_length(rows)>1000 THEN RAISE EXCEPTION '036 slate cardinality'; END IF;
    ELSIF purpose='h1_team' THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.team_id,q.rank),'[]'::jsonb) INTO rows FROM (
          SELECT * FROM (SELECT requested.team_id,g.game_id,g.game_date,g.home_team_id,g.away_team_id,
            row_number() OVER(PARTITION BY requested.team_id ORDER BY g.game_date DESC,g.game_id DESC) AS rank
          FROM unnest(ids) requested(team_id) JOIN public.games g ON g.home_team_id=requested.team_id OR g.away_team_id=requested.team_id
          WHERE g.game_date<cutoff AND NOT public.mlb_identity_is_retired(g.game_id)
            AND NOT EXISTS(SELECT 1 FROM public.nfl_games f WHERE f.game_id=g.game_id)) ranked WHERE rank<=200) q;
    ELSIF purpose='h1_starter' THEN
        IF EXISTS(SELECT 1 FROM public.player_game_pitching_statistics p JOIN public.games g USING(game_id)
          WHERE p.baseball_player_id=ANY(ids) AND p.is_starter AND g.game_date<cutoff AND p.created_at<=cutoff
            AND (public.mlb_identity_is_retired(g.game_id) OR g.home_team_id=g.away_team_id OR g.home_team_id IS NULL
              OR g.away_team_id IS NULL OR p.team_id NOT IN(g.home_team_id,g.away_team_id))) THEN RAISE EXCEPTION '036 malformed retained starter'; END IF;
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.baseball_player_id,q.rank),'[]'::jsonb) INTO rows FROM (
          SELECT * FROM (SELECT p.baseball_player_id,g.game_id,g.game_date,p.team_id,g.home_team_id,g.away_team_id,p.created_at,
            row_number() OVER(PARTITION BY p.baseball_player_id ORDER BY g.game_date DESC,g.game_id DESC) AS rank
          FROM public.player_game_pitching_statistics p JOIN public.games g USING(game_id)
          WHERE p.baseball_player_id=ANY(ids) AND p.is_starter AND g.game_date<cutoff AND p.created_at<=cutoff
            AND NOT public.mlb_identity_is_retired(g.game_id) AND NOT EXISTS(SELECT 1 FROM public.nfl_games f WHERE f.game_id=g.game_id)) ranked WHERE rank<=50) q;
    ELSIF purpose='team_stats' THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.game_date DESC,q.game_id DESC),'[]'::jsonb) INTO rows FROM (
          SELECT g.game_id,g.game_date,t.team_id,CASE WHEN g.home_team_id=t.team_id THEN g.away_team_id ELSE g.home_team_id END AS opponent_team_id,
            t.is_home,to_jsonb(t) AS statistics FROM public.team_game_statistics t JOIN public.games g USING(game_id)
          WHERE t.team_id=selected_id AND g.game_date<cutoff AND t.created_at<=cutoff AND NOT public.mlb_identity_is_retired(g.game_id)
            AND t.team_id IN(g.home_team_id,g.away_team_id) AND g.home_team_id IS NOT NULL AND g.away_team_id IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM public.nfl_games f WHERE f.game_id=g.game_id)
          ORDER BY g.game_date DESC,g.game_id DESC LIMIT n) q;
    ELSIF purpose IN('starter_stats','bullpen_stats') THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.game_date DESC,q.game_id DESC,q.appearance_order,q.baseball_player_id),'[]'::jsonb) INTO rows FROM (
          SELECT g.game_id,g.game_date,p.team_id,CASE WHEN g.home_team_id=p.team_id THEN g.away_team_id ELSE g.home_team_id END AS opponent_team_id,
            (g.home_team_id=p.team_id) AS is_home,p.appearance_order,p.baseball_player_id,to_jsonb(p) AS statistics
          FROM public.player_game_pitching_statistics p JOIN public.games g USING(game_id)
          WHERE g.game_date<cutoff AND p.created_at<=cutoff AND NOT public.mlb_identity_is_retired(g.game_id)
            AND p.team_id IN(g.home_team_id,g.away_team_id) AND g.home_team_id IS NOT NULL AND g.away_team_id IS NOT NULL
            AND NOT EXISTS(SELECT 1 FROM public.nfl_games f WHERE f.game_id=g.game_id)
            AND CASE WHEN purpose='starter_stats' THEN p.is_starter AND p.baseball_player_id=selected_id
              ELSE NOT p.is_starter AND p.team_id=selected_id AND extract(year FROM g.game_date)=extract(year FROM cutoff) END
          ORDER BY g.game_date DESC,g.game_id DESC,p.appearance_order,p.baseball_player_id LIMIT CASE WHEN purpose='starter_stats' THEN n ELSE 10001 END) q;
        IF jsonb_array_length(rows)>10000 THEN RAISE EXCEPTION '036 bullpen cardinality'; END IF;
    ELSIF purpose='markets' THEN
        IF jsonb_typeof(params->'include_live')<>'boolean' THEN RAISE EXCEPTION '036 typed live flag'; END IF;
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.snapshot_time,q.odds_market_snapshot_id),'[]'::jsonb) INTO rows FROM (
          SELECT m.*,m.line_value::text AS exact_line_value FROM public.odds_market_snapshots_effective m JOIN public.games g ON g.game_id=m.effective_game_id
          WHERE m.effective_game_id=selected_id AND m.snapshot_time<=cutoff AND m.created_at<=cutoff
            AND (m.observed_at IS NULL OR m.observed_at<=cutoff)
            AND NOT EXISTS(SELECT 1 FROM public.mlb_active_retired_identities a WHERE a.subject_game_id IN(m.raw_acquisition_game_id,m.effective_game_id))
            AND ((params->>'include_live')::boolean OR m.snapshot_time<g.game_date)
            AND NOT EXISTS(SELECT 1 FROM public.nfl_games f WHERE f.game_id=g.game_id)
          ORDER BY m.snapshot_time,m.odds_market_snapshot_id LIMIT 10001) q;
        IF jsonb_array_length(rows)>10000 THEN RAISE EXCEPTION '036 market cardinality'; END IF;
        SELECT coalesce(jsonb_agg((item-'exact_line_value')||jsonb_build_object('line_value',item->'exact_line_value') ORDER BY ord),'[]'::jsonb)
          INTO rows FROM jsonb_array_elements(rows) WITH ORDINALITY q(item,ord);
    ELSIF purpose='feature_audit_summary' THEN
        WITH bounded AS (
          SELECT g.* FROM public.games g WHERE g.game_date>=start_value AND g.game_date<end_value
            AND NOT public.mlb_identity_is_retired(g.game_id) AND NOT EXISTS(SELECT 1 FROM public.nfl_games n WHERE n.game_id=g.game_id)
            AND EXISTS(SELECT 1 FROM public.baseball_team_sources s WHERE s.team_id=g.home_team_id AND s.source_name='mlb_stats')
            AND EXISTS(SELECT 1 FROM public.baseball_team_sources s WHERE s.team_id=g.away_team_id AND s.source_name='mlb_stats')
          ORDER BY g.game_date,g.game_id LIMIT 1001),
        audit_rows AS (
          SELECT 1 AS ord,'Historical game results' AS name,NOT EXISTS(
            SELECT 1 FROM bounded g WHERE g.game_date<cutoff AND NOT EXISTS(SELECT 1 FROM public.historical_games h WHERE h.game_id=g.game_id
              AND h.home_score>=0 AND h.away_score>=0 AND EXISTS(SELECT 1 FROM public.game_sources s WHERE s.game_id=g.game_id AND s.source_name='mlb_stats' AND s.external_game_id=h.mlb_game_id::text))) AS available,
            'Scoped canonical identity/result presence only; not boxscore or training completeness'::text AS detail,
            (SELECT count(*) FROM public.historical_games h JOIN bounded g USING(game_id) WHERE g.game_date<cutoff) AS row_count
          UNION ALL SELECT 2,'Canonical game timestamps',NOT EXISTS(SELECT 1 FROM bounded WHERE NOT isfinite(game_date)),
            'Receipt-certified bounded current timestamps; no historical as-of reconstruction',(SELECT count(*) FROM bounded)
          UNION ALL SELECT 3,'Canonical team linkage',NOT EXISTS(SELECT 1 FROM bounded g WHERE g.home_team_id=g.away_team_id
            OR (SELECT count(*) FROM public.baseball_team_sources s WHERE s.team_id=g.home_team_id AND s.source_name='mlb_stats')<>1
            OR (SELECT count(*) FROM public.baseball_team_sources s WHERE s.team_id=g.away_team_id AND s.source_name='mlb_stats')<>1),
            'Unique scoped MLB provider mappings; full franchise validation remains separate',(SELECT count(*) FROM bounded)
          UNION ALL SELECT 4,'Pregame market snapshots',true,
            'Count of available active pregame quotes only; no guarantee of complete market coverage',
            (SELECT count(*) FROM public.odds_market_snapshots_effective m JOIN bounded g ON g.game_id=m.effective_game_id
              WHERE m.snapshot_time<g.game_date AND m.snapshot_time<=cutoff AND m.created_at<=cutoff
                AND (m.observed_at IS NULL OR m.observed_at<=cutoff)
                AND NOT EXISTS(SELECT 1 FROM public.mlb_active_retired_identities a WHERE a.subject_game_id IN(m.raw_acquisition_game_id,m.effective_game_id))))
        SELECT CASE WHEN (SELECT count(*) FROM bounded)>1000 THEN NULL ELSE
          jsonb_agg(jsonb_build_object('name',name,'available',available,'detail',detail,'row_count',row_count) ORDER BY ord) END INTO rows FROM audit_rows;
        IF rows IS NULL THEN RAISE EXCEPTION '036 bounded audit cardinality'; END IF;
    ELSIF purpose='game_sources' THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.game_id,q.game_source_id),'[]'::jsonb) INTO rows FROM
          (SELECT game_id,game_source_id,external_game_id FROM public.game_sources WHERE source_name='mlb_stats' AND game_id=ANY(ids)) q;
    ELSIF purpose='mlb_teams' THEN
        IF EXISTS(SELECT 1 FROM public.baseball_team_sources WHERE source_name='mlb_stats' AND team_id=ANY(ids) AND external_team_id !~ '^[1-9][0-9]*$') THEN
            RAISE EXCEPTION '036 invalid MLB team source'; END IF;
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.team_id,q.source_row_id),'[]'::jsonb) INTO rows FROM (
          SELECT t.team_id,t.team_name AS name,s.external_team_id::integer AS mlb_team_id,s.baseball_team_source_id AS source_row_id
          FROM public.teams t JOIN public.baseball_team_sources s USING(team_id) WHERE t.team_id=ANY(ids) AND s.source_name='mlb_stats') q;
    ELSIF purpose='mlb_starters' THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.baseball_player_id,q.baseball_player_source_id),'[]'::jsonb) INTO rows FROM (
          SELECT baseball_player_id,baseball_player_source_id,external_player_id FROM public.baseball_player_sources
          WHERE baseball_player_id=ANY(ids) AND source_name='mlb_stats') q;
    ELSIF purpose='nonplayed_identity' THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.external_game_id,q.game_id),'[]'::jsonb) INTO rows FROM (
          SELECT s.external_game_id,g.game_id,h.team_name AS home_team_name,a.team_name AS away_team_name,
            (EXISTS(SELECT 1 FROM public.historical_games r WHERE r.game_id=g.game_id)
              OR EXISTS(SELECT 1 FROM public.team_game_statistics t WHERE t.game_id=g.game_id)
              OR EXISTS(SELECT 1 FROM public.player_game_pitching_statistics p WHERE p.game_id=g.game_id)) AS played_history,
            (SELECT count(*) FROM public.game_sources x WHERE x.game_id=g.game_id AND x.source_name='mlb_stats') AS source_count
          FROM public.game_sources s LEFT JOIN public.games g USING(game_id) LEFT JOIN public.teams h ON h.team_id=g.home_team_id
            LEFT JOIN public.teams a ON a.team_id=g.away_team_id WHERE s.source_name='mlb_stats' AND s.external_game_id=ANY(ARRAY(SELECT v::text FROM unnest(ids) v))) q;
    ELSIF purpose='required_game_pks' THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q) ORDER BY q.external_game_id),'[]'::jsonb) INTO rows FROM (
          WITH ranked_teams AS (
            SELECT g.game_id,row_number() OVER(PARTITION BY requested.team_id ORDER BY g.game_date DESC,g.game_id DESC) AS rank
            FROM unnest(teams_requested) requested(team_id) JOIN public.games g ON requested.team_id IN(g.home_team_id,g.away_team_id)
            WHERE g.game_date<cutoff AND NOT public.mlb_identity_is_retired(g.game_id)
              AND EXISTS(SELECT 1 FROM public.game_sources s WHERE s.game_id=g.game_id AND s.source_name='mlb_stats')
              AND NOT EXISTS(SELECT 1 FROM public.nfl_games f WHERE f.game_id=g.game_id)),
          ranked_starters AS (
            SELECT g.game_id,row_number() OVER(PARTITION BY p.baseball_player_id ORDER BY g.game_date DESC,g.game_id DESC) AS rank
            FROM public.player_game_pitching_statistics p JOIN public.games g USING(game_id)
            WHERE p.baseball_player_id=ANY(starters_requested) AND p.is_starter AND g.game_date<cutoff AND p.created_at<=cutoff
              AND NOT public.mlb_identity_is_retired(g.game_id) AND EXISTS(SELECT 1 FROM public.game_sources s WHERE s.game_id=g.game_id AND s.source_name='mlb_stats')
              AND NOT EXISTS(SELECT 1 FROM public.nfl_games f WHERE f.game_id=g.game_id)),
          retained AS (SELECT game_id FROM ranked_teams WHERE rank<=200 UNION SELECT game_id FROM ranked_starters WHERE rank<=50)
          SELECT s.external_game_id FROM retained r JOIN public.game_sources s USING(game_id) WHERE s.source_name='mlb_stats') q;
    ELSIF purpose='completeness' THEN
        IF EXISTS(SELECT 1 FROM public.game_sources s WHERE s.source_name='mlb_stats' AND s.external_game_id=ANY(ARRAY(SELECT v::text FROM unnest(ids) v))
          AND public.mlb_identity_is_retired(s.game_id)) THEN RAISE EXCEPTION '036 retired completeness identity'; END IF;
        SELECT coalesce(jsonb_agg(jsonb_build_object('game_pk',requested.pk,
          'mapping_game_ids',(SELECT coalesce(jsonb_agg(s.game_id ORDER BY s.game_source_id),'[]'::jsonb) FROM public.game_sources s WHERE s.source_name='mlb_stats' AND s.external_game_id=requested.pk::text),
          'home_team_id',(SELECT g.home_team_id FROM public.games g WHERE g.game_id=mapped.ids[1]),
          'away_team_id',(SELECT g.away_team_id FROM public.games g WHERE g.game_id=mapped.ids[1]),
          'canonical_mlb_game_pks',(SELECT coalesce(jsonb_agg(s.external_game_id::bigint ORDER BY s.game_source_id),'[]'::jsonb) FROM public.game_sources s WHERE s.source_name='mlb_stats' AND s.game_id=ANY(mapped.ids)),
          'results',(SELECT coalesce(jsonb_agg(jsonb_build_object('game_id',h.game_id,'mlb_game_id',h.mlb_game_id,'home_score',h.home_score,'away_score',h.away_score) ORDER BY h.historical_game_id),'[]'::jsonb)
            FROM public.historical_games h WHERE h.game_id=ANY(mapped.ids) OR h.mlb_game_id=requested.pk),
          'team_statistics',(SELECT coalesce(jsonb_agg(jsonb_build_object('team_id',t.team_id,'is_home',t.is_home,'runs',t.runs,'pitching_outs',t.pitching_outs,'runs_allowed',t.runs_allowed,
            'earned_runs_allowed',t.earned_runs_allowed,'hits_allowed',t.hits_allowed,'home_runs_allowed',t.home_runs_allowed,'walks_allowed',t.walks_allowed,'strikeouts_recorded',t.strikeouts_recorded,'created_at',t.created_at) ORDER BY t.team_game_statistics_id),'[]'::jsonb)
            FROM public.team_game_statistics t WHERE t.game_id=ANY(mapped.ids) AND t.created_at<=cutoff),
          'pitching_statistics',(SELECT coalesce(jsonb_agg(jsonb_build_object('team_id',p.team_id,'appearance_order',p.appearance_order,'is_starter',p.is_starter,'pitching_outs',p.pitching_outs,'hits_allowed',p.hits_allowed,
            'runs_allowed',p.runs_allowed,'earned_runs_allowed',p.earned_runs_allowed,'home_runs_allowed',p.home_runs_allowed,'walks_allowed',p.walks_allowed,'strikeouts',p.strikeouts,'created_at',p.created_at) ORDER BY p.player_game_pitching_statistics_id),'[]'::jsonb)
            FROM public.player_game_pitching_statistics p WHERE p.game_id=ANY(mapped.ids) AND p.created_at<=cutoff)) ORDER BY requested.ord),'[]'::jsonb) INTO rows
          FROM unnest(ids) WITH ORDINALITY requested(pk,ord) CROSS JOIN LATERAL
            (SELECT coalesce(array_agg(s.game_id ORDER BY s.game_source_id),'{}'::integer[]) AS ids FROM public.game_sources s WHERE s.source_name='mlb_stats' AND s.external_game_id=requested.pk::text) mapped;
    ELSIF purpose='recovery_identity' THEN
        SELECT coalesce(jsonb_agg(to_jsonb(q)),'[]'::jsonb) INTO rows FROM (
          SELECT g.game_id,g.game_date,g.home_team_id,g.away_team_id,s.game_source_id,s.external_game_id
          FROM public.game_sources s JOIN public.games g USING(game_id)
          WHERE s.source_name='mlb_stats' AND s.external_game_id=selected_id::text
            AND NOT public.mlb_identity_is_retired(g.game_id)) q;
        IF jsonb_array_length(rows)<>1 THEN RAISE EXCEPTION '036 unique active recovery source required'; END IF;
    ELSE
        RAISE EXCEPTION '036 reader not implemented';
    END IF;
    RETURN rows;
END $$;
CREATE FUNCTION mlb036_private.certified_data(receipt_locator BIGINT,cutoff TIMESTAMPTZ,purpose TEXT,params JSONB) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE validated JSONB; materialized RECORD;
BEGIN
    validated:=mlb036_private.validate_knowledge(receipt_locator,cutoff,true);
    -- Stable inner routines share this one fresh post-gate query snapshot.
    SELECT mlb036_private.state() AS state,mlb036_private.data_rows(purpose,params,cutoff) AS rows INTO materialized;
    IF mlb036_private.state_fingerprint(materialized.state)<>validated#>>'{receipt,correction_state_fingerprint}' THEN
        RAISE EXCEPTION '036 state changed while materializing certified data'; END IF;
    RETURN jsonb_build_object('receipt_id',receipt_locator,'cutoff_time',cutoff,'state_fingerprint',validated#>>'{receipt,correction_state_fingerprint}',
      'receipt_body_sha256',validated#>>'{receipt,receipt_body_sha256}',
      'rows',materialized.rows,'certification','MLB036_CERTIFIED');
END $$;
CREATE FUNCTION mlb036_private.source_seal() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
BEGIN
    IF EXISTS(SELECT 1 FROM mlb036_private.arbitrations) THEN
        IF TG_OP='INSERT' AND NEW.game_id=584 THEN RAISE EXCEPTION '036 subject identity sealed'; END IF;
        IF TG_OP IN('UPDATE','DELETE') AND OLD.game_source_id IN(12,571) THEN
            IF TG_OP='DELETE' OR to_jsonb(OLD) IS DISTINCT FROM to_jsonb(NEW) THEN RAISE EXCEPTION '036 original source anchor sealed'; END IF;
        END IF;
        IF TG_OP='UPDATE' AND NEW.game_id=584 THEN RAISE EXCEPTION '036 subject identity sealed'; END IF;
    END IF;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_036_source_seal BEFORE INSERT OR UPDATE OR DELETE ON public.game_sources FOR EACH ROW EXECUTE FUNCTION mlb036_private.source_seal();
CREATE FUNCTION mlb036_private.acquire_exact_gate() RETURNS VOID
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET lock_timeout='1500ms' AS $$
DECLARE a mlb036_private.authority;
BEGIN
    IF current_setting('transaction_isolation')<>'serializable' OR current_setting('transaction_read_only')<>'off' THEN
        RAISE EXCEPTION '036 exact operator SERIALIZABLE transaction'; END IF;
    PERFORM public.mlb_identity_gate(true);
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.operator_role THEN RAISE EXCEPTION '036 exact operator principal'; END IF;
END $$;
CREATE FUNCTION mlb036_private.inspect_knowledge() RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority; capture RECORD; r mlb036_private.knowledge_receipts;
BEGIN
    a:=mlb036_private.context('knowledge',true);
    SELECT to_jsonb(rec) AS receipt,mlb036_private.state() AS state INTO capture FROM mlb036_private.knowledge_receipts rec
      WHERE rec.correction_state_fingerprint=mlb036_private.state_fingerprint(mlb036_private.state()) ORDER BY receipt_id LIMIT 1;
    IF NOT FOUND THEN RETURN jsonb_build_object('status','INDETERMINATE_NO_CURRENT_COMMITTED_RECEIPT','retry_authorized',false,'rollback_proven',false); END IF;
    r:=jsonb_populate_record(NULL::mlb036_private.knowledge_receipts,capture.receipt);
    IF r.issuer_xid8 IS NOT DISTINCT FROM pg_current_xact_id_if_assigned() OR r.receipt_body_sha256<>mlb036_private.receipt_hash(r)
      OR r.available_at>clock_timestamp() THEN RAISE EXCEPTION '036 invalid committed inspection receipt'; END IF;
    RETURN jsonb_build_object('status','CURRENT_COMMITTED_RECEIPT','receipt',capture.receipt,'retry_authorized',false);
END $$;
CREATE FUNCTION mlb036_private.raw_case_snapshot() RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority;
BEGIN
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.raw_role OR current_setting('transaction_read_only')<>'on' THEN RAISE EXCEPTION '036 separate raw read-only principal'; END IF;
    RETURN jsonb_build_object('label','RAW_FORENSIC','historically_certified',false,'case_identity',a.policy->>'case_identity',
      'business',mlb036_private.business_snapshot());
END $$;
CREATE FUNCTION mlb036_private.post_correction_preview(receipt_locator BIGINT,cutoff TIMESTAMPTZ,retirement_case JSONB) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp AS $$
DECLARE a mlb036_private.authority; r public.mlb_legacy_identity_retirements; proof JSONB;
BEGIN
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.operator_role THEN RAISE EXCEPTION '036 separate retirement-preview principal'; END IF;
    proof:=mlb036_private.validate_knowledge(receipt_locator,cutoff,true);
    r:=jsonb_populate_record(NULL::public.mlb_legacy_identity_retirements,retirement_case);
    IF r.domain IS DISTINCT FROM 'MLB' OR r.category IS DISTINCT FROM 'IDENTITY_ONLY_DUPLICATE'
      OR r.subject_game_id IS DISTINCT FROM 584 OR r.survivor_game_id IS DISTINCT FROM 26
      OR r.game_pk IS DISTINCT FROM (a.policy->>'game_pk')::bigint THEN RAISE EXCEPTION '036 fixed post-correction preview only'; END IF;
    PERFORM public.mlb_retirement_validate(r,false);
    RETURN jsonb_build_object('status','ELIGIBLE','retirement_activated',false,'knowledge_receipt_id',receipt_locator,
       'retirement_case',retirement_case,'cutoff_time',cutoff);
END $$;
CREATE FUNCTION mlb036_private.run_companion(r mlb036_private.knowledge_receipts,cutoff TIMESTAMPTZ,target_date DATE,admitted_run_id BIGINT DEFAULT 0) RETURNS JSONB
LANGUAGE sql STABLE STRICT SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
    SELECT jsonb_build_object('version',1,'receipt_id',r.receipt_id,'receipt_body_sha256',r.receipt_body_sha256,
      'correction_state_fingerprint',r.correction_state_fingerprint,'identity034_digest',r.identity034_digest,
      'identity035_digest',r.identity035_digest,'identity_topology_epoch',r.identity_topology_epoch,
      'available_at',r.available_at,'cutoff_time',cutoff,'deployment_id',r.deployment_id,'authority_epoch',r.authority_epoch,
      'system_identifier',r.system_identifier,'database_oid',r.database_oid,'database_name',r.database_name,
      'server_address',r.server_address,'server_port',r.server_port,'postmaster_started_at',r.postmaster_started_at,
      'schema_capability_profile',r.schema_capability_profile,'correction_policy_version',r.correction_policy_version,
      'target_date',target_date,'target_state',(SELECT coalesce(jsonb_agg(jsonb_build_object(
        'game',to_jsonb(g),'mlb_sources',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY game_source_id),'[]'::jsonb)
          FROM public.game_sources s WHERE s.game_id=g.game_id AND s.source_name='mlb_stats'),
        'team_sources',(SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY baseball_team_source_id),'[]'::jsonb)
          FROM public.baseball_team_sources t WHERE t.team_id IN(g.home_team_id,g.away_team_id) AND t.source_name='mlb_stats'),
        -- Frozen034 advances the fence once per admitted prediction INSERT.
        -- Subtract ONLY this run's persisted inserts; every other advance invalidates admission.
        'fence_epoch',f.epoch-(SELECT count(*) FROM public.moneyline_game_predictions p
          WHERE p.moneyline_prediction_run_id=admitted_run_id AND p.game_id=g.game_id)) ORDER BY g.game_id),'[]'::jsonb)
        FROM public.games g LEFT JOIN public.mlb_game_identity_write_fences f USING(game_id)
        WHERE (g.game_date AT TIME ZONE 'America/Los_Angeles')::date=target_date
          AND NOT public.mlb_identity_is_retired(g.game_id) AND NOT EXISTS(SELECT 1 FROM public.nfl_games n WHERE n.game_id=g.game_id)
          AND EXISTS(SELECT 1 FROM public.baseball_team_sources t WHERE t.team_id=g.home_team_id AND t.source_name='mlb_stats')
          AND EXISTS(SELECT 1 FROM public.baseball_team_sources t WHERE t.team_id=g.away_team_id AND t.source_name='mlb_stats')))
$$;
CREATE FUNCTION mlb036_private.run_guard() RETURNS TRIGGER
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority; r mlb036_private.knowledge_receipts; proof JSONB; cutoff TIMESTAMPTZ; children JSONB;
BEGIN
    IF TG_OP='UPDATE' THEN
        IF NEW.canonical_time_knowledge IS DISTINCT FROM OLD.canonical_time_knowledge THEN RAISE EXCEPTION '036 immutable run companion; no backfill'; END IF;
        IF OLD.canonical_time_knowledge IS NULL THEN RETURN NEW; END IF;
        IF (to_jsonb(NEW)-ARRAY['status','completed_at','games_received','predictions_created','games_skipped','error_message'])
          IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','completed_at','games_received','predictions_created','games_skipped','error_message']) THEN
            RAISE EXCEPTION '036 immutable certified run inputs'; END IF;
        IF OLD.status<>'running' THEN RAISE EXCEPTION '036 terminal certified run immutable'; END IF;
    END IF;
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.reader_role OR current_setting('transaction_isolation')<>'read committed'
      OR current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION '036 certified run principal/RC write transaction required'; END IF;
    IF NEW.canonical_time_knowledge IS NULL OR jsonb_typeof(NEW.canonical_time_knowledge)<>'object' THEN RAISE EXCEPTION '036 committed run companion required'; END IF;
    -- A failed/held outcome remains recordable when the original receipt is stale.
    -- It cannot replace proof or turn into a successful publication.
    IF TG_OP='UPDATE' AND NEW.status='failed' THEN RETURN NEW; END IF;
    cutoff:=(NEW.canonical_time_knowledge->>'cutoff_time')::timestamptz;
    proof:=mlb036_private.validate_knowledge((NEW.canonical_time_knowledge->>'receipt_id')::bigint,cutoff,false);
    r:=jsonb_populate_record(NULL::mlb036_private.knowledge_receipts,proof->'receipt');
    -- Lock admitted identities/fences through finalization; ordinary writers cannot
    -- move a checked target between this validation and transaction completion.
    PERFORM g.game_id FROM public.games g WHERE g.game_id IN
      (SELECT (v->'game'->>'game_id')::integer FROM jsonb_array_elements(NEW.canonical_time_knowledge->'target_state') v)
      ORDER BY g.game_id FOR SHARE;
    PERFORM f.game_id FROM public.mlb_game_identity_write_fences f WHERE f.game_id IN
      (SELECT (v->'game'->>'game_id')::integer FROM jsonb_array_elements(NEW.canonical_time_knowledge->'target_state') v)
      ORDER BY f.game_id FOR UPDATE;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.canonical_time_knowledge->'target_state') v
        WHERE v->'fence_epoch'='null'::jsonb OR (v->>'fence_epoch')::bigint<1)
      OR NEW.canonical_time_knowledge IS DISTINCT FROM mlb036_private.run_companion(r,cutoff,NEW.target_date,NEW.moneyline_prediction_run_id) THEN
        RAISE EXCEPTION '036 exact server-derived run companion/target state required; admission drift'; END IF;
    children:=mlb036_private.legacy_children(r,cutoff);
    IF NEW.identity_retirement_knowledge IS DISTINCT FROM children->'v2' THEN RAISE EXCEPTION '036 receipt-derived v2 required'; END IF;
    IF NEW.started_at<r.available_at OR NEW.started_at>clock_timestamp() OR NEW.status NOT IN('running','completed') THEN RAISE EXCEPTION '036 invalid run chronology'; END IF;
    IF NEW.status='completed' AND EXISTS(SELECT 1 FROM public.moneyline_game_predictions p
      WHERE p.moneyline_prediction_run_id=NEW.moneyline_prediction_run_id AND
        (SELECT count(*) FROM jsonb_array_elements(NEW.canonical_time_knowledge->'target_state') v
          WHERE (v->'game'->>'game_id')::integer=p.game_id)<>1) THEN
        RAISE EXCEPTION '036 finalization prediction target outside immutable admitted slate'; END IF;
    RETURN NEW;
END $$;
-- Alphabetical trigger ordering derives/validates children BEFORE the unchanged035 guard.
CREATE TRIGGER mlb_000036_run_knowledge BEFORE INSERT OR UPDATE ON public.moneyline_prediction_runs
FOR EACH ROW EXECUTE FUNCTION mlb036_private.run_guard();
CREATE FUNCTION mlb036_private.reserve_run(receipt_locator BIGINT,cutoff TIMESTAMPTZ,request JSONB) RETURNS BIGINT
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE proof JSONB; r mlb036_private.knowledge_receipts; children JSONB; result BIGINT;
BEGIN
    IF current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION '036 dedicated run reservation write transaction'; END IF;
    proof:=mlb036_private.validate_knowledge(receipt_locator,cutoff,false);
    IF jsonb_typeof(request)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(request))<>6
      OR NOT request ?& ARRAY['target_date','run_type','model_version','feature_schema_version','model_artifact_sha256','model_training_cutoff']
      OR EXISTS(SELECT 1 FROM jsonb_each(request) WHERE key<>'model_training_cutoff' AND jsonb_typeof(value)<>'string')
      OR (request->'model_training_cutoff'<>'null'::jsonb AND jsonb_typeof(request->'model_training_cutoff')<>'string')
      OR request->>'target_date' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
      OR request->>'run_type' NOT IN('official','preview') OR length(request->>'model_version') NOT BETWEEN 1 AND 100
      OR length(request->>'feature_schema_version') NOT BETWEEN 1 AND 50 OR request->>'model_artifact_sha256' !~ '^[0-9a-f]{64}$'
      OR request->'target_date'='null'::jsonb OR request->'model_version'='null'::jsonb
      OR request->'feature_schema_version'='null'::jsonb OR request->'model_artifact_sha256'='null'::jsonb OR request->'run_type'='null'::jsonb THEN
        RAISE EXCEPTION '036 exact bounded run request'; END IF;
    IF request->'model_training_cutoff'<>'null'::jsonb AND
      (request->>'model_training_cutoff' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' OR (request->>'model_training_cutoff')::timestamptz>cutoff) THEN
        RAISE EXCEPTION '036 training cutoff must precede input cutoff'; END IF;
    r:=jsonb_populate_record(NULL::mlb036_private.knowledge_receipts,proof->'receipt'); children:=mlb036_private.legacy_children(r,cutoff);
    INSERT INTO public.moneyline_prediction_runs(target_date,run_type,model_version,feature_schema_version,model_artifact_sha256,
      model_training_cutoff,started_at,status,identity_retirement_knowledge,canonical_time_knowledge)
    VALUES((request->>'target_date')::date,request->>'run_type',request->>'model_version',request->>'feature_schema_version',
      request->>'model_artifact_sha256',(request->>'model_training_cutoff')::timestamptz,clock_timestamp(),'running',
      children->'v2',mlb036_private.run_companion(r,cutoff,(request->>'target_date')::date)) RETURNING moneyline_prediction_run_id INTO result;
    RETURN result;
END $$;
CREATE FUNCTION mlb036_private.finish_run(receipt_locator BIGINT,original_cutoff TIMESTAMPTZ,expected_receipt_body_sha256 TEXT,run_id BIGINT,outcome TEXT,counts JSONB,error_text TEXT DEFAULT NULL) RETURNS VOID
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE a mlb036_private.authority; existing public.moneyline_prediction_runs; cutoff TIMESTAMPTZ; total_predictions INTEGER;
BEGIN
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.reader_role OR current_setting('transaction_isolation')<>'read committed'
      OR current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION '036 explicit run completion principal/transaction'; END IF;
    PERFORM public.mlb_identity_gate(false);
    SELECT * INTO STRICT existing FROM public.moneyline_prediction_runs WHERE moneyline_prediction_run_id=run_id FOR UPDATE;
    IF existing.status<>'running' OR existing.canonical_time_knowledge IS NULL THEN RAISE EXCEPTION '036 running certified run required'; END IF;
    IF receipt_locator IS DISTINCT FROM (existing.canonical_time_knowledge->>'receipt_id')::bigint
      OR original_cutoff IS DISTINCT FROM (existing.canonical_time_knowledge->>'cutoff_time')::timestamptz
      OR expected_receipt_body_sha256 IS DISTINCT FROM existing.canonical_time_knowledge->>'receipt_body_sha256' THEN
        RAISE EXCEPTION '036 original run receipt/cutoff immutable; no swap'; END IF;
    IF outcome NOT IN('completed','failed') OR jsonb_typeof(counts)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(counts))<>3
      OR NOT counts ?& ARRAY['games_received','predictions_created','games_skipped']
      OR EXISTS(SELECT 1 FROM jsonb_each(counts) WHERE jsonb_typeof(value)<>'number' OR value::text !~ '^[0-9]+$') THEN RAISE EXCEPTION '036 exact nonnegative completion counts'; END IF;
    IF (counts->>'predictions_created')::integer+(counts->>'games_skipped')::integer>(counts->>'games_received')::integer THEN RAISE EXCEPTION '036 inconsistent completion counts'; END IF;
    SELECT count(*) INTO total_predictions FROM public.moneyline_game_predictions WHERE moneyline_prediction_run_id=run_id;
    IF total_predictions<>(counts->>'predictions_created')::integer THEN RAISE EXCEPTION '036 persisted prediction count differs'; END IF;
    IF outcome='completed' THEN
        cutoff:=(existing.canonical_time_knowledge->>'cutoff_time')::timestamptz;
        PERFORM mlb036_private.validate_knowledge((existing.canonical_time_knowledge->>'receipt_id')::bigint,cutoff,false);
        IF total_predictions=0 AND EXISTS(SELECT 1 FROM public.games g WHERE (g.game_date AT TIME ZONE 'America/Los_Angeles')::date=existing.target_date
          AND NOT public.mlb_identity_is_retired(g.game_id) AND EXISTS(SELECT 1 FROM public.baseball_team_sources t WHERE t.team_id=g.home_team_id AND t.source_name='mlb_stats')
          AND EXISTS(SELECT 1 FROM public.baseball_team_sources t WHERE t.team_id=g.away_team_id AND t.source_name='mlb_stats')) THEN
            RAISE EXCEPTION '036 retained canonical slate cannot complete with zero predictions'; END IF;
    ELSIF error_text IS NULL OR length(error_text) NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION '036 bounded failure reason required'; END IF;
    UPDATE public.moneyline_prediction_runs SET status=outcome,completed_at=clock_timestamp(),
      games_received=(counts->>'games_received')::integer,predictions_created=(counts->>'predictions_created')::integer,
      games_skipped=(counts->>'games_skipped')::integer,error_message=CASE WHEN outcome='failed' THEN error_text ELSE NULL END
      WHERE moneyline_prediction_run_id=run_id;
END $$;
CREATE FUNCTION mlb036_private.prediction_guard() RETURNS TRIGGER
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE run public.moneyline_prediction_runs; g public.games; cutoff TIMESTAMPTZ; proof JSONB; r mlb036_private.knowledge_receipts;
BEGIN
    PERFORM public.mlb_identity_gate(false);
    SELECT * INTO STRICT run FROM public.moneyline_prediction_runs WHERE moneyline_prediction_run_id=NEW.moneyline_prediction_run_id FOR UPDATE;
    IF run.canonical_time_knowledge IS NULL THEN RETURN NEW; END IF;
    IF TG_OP<>'INSERT' OR run.status<>'running' THEN RAISE EXCEPTION '036 immutable certified prediction'; END IF;
    IF jsonb_typeof(run.canonical_time_knowledge->'target_state') IS DISTINCT FROM 'array'
      OR (SELECT count(*) FROM jsonb_array_elements(run.canonical_time_knowledge->'target_state') v
        WHERE (v->'game'->>'game_id')::integer=NEW.game_id)<>1 THEN
        RAISE EXCEPTION '036 prediction target outside immutable admitted slate'; END IF;
    cutoff:=(run.canonical_time_knowledge->>'cutoff_time')::timestamptz;
    proof:=mlb036_private.validate_knowledge((run.canonical_time_knowledge->>'receipt_id')::bigint,cutoff,false);
    r:=jsonb_populate_record(NULL::mlb036_private.knowledge_receipts,proof->'receipt');
    SELECT * INTO STRICT g FROM public.games WHERE game_id=NEW.game_id FOR SHARE;
    PERFORM game_id FROM public.mlb_game_identity_write_fences WHERE game_id=NEW.game_id FOR UPDATE;
    IF run.canonical_time_knowledge IS DISTINCT FROM mlb036_private.run_companion(r,cutoff,run.target_date,run.moneyline_prediction_run_id) THEN
        RAISE EXCEPTION '036 prediction admission target state drift'; END IF;
    IF NEW.prediction_time IS DISTINCT FROM cutoff OR NEW.game_start_time IS DISTINCT FROM g.game_date
      OR (NEW.home_team_id,NEW.away_team_id) IS DISTINCT FROM (g.home_team_id,g.away_team_id)
      OR public.mlb_identity_is_retired(g.game_id) OR EXISTS(SELECT 1 FROM public.nfl_games WHERE game_id=g.game_id)
      OR (SELECT array_agg(external_game_id::text ORDER BY game_source_id) FROM public.game_sources WHERE game_id=g.game_id AND source_name='mlb_stats')
        IS DISTINCT FROM ARRAY[NEW.mlb_game_id::text] THEN RAISE EXCEPTION '036 exact canonical prediction identity/cutoff required'; END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER mlb_000036_prediction_knowledge BEFORE INSERT OR UPDATE ON public.moneyline_game_predictions
FOR EACH ROW EXECUTE FUNCTION mlb036_private.prediction_guard();
CREATE FUNCTION mlb036_private.insert_prediction(receipt_locator BIGINT,original_cutoff TIMESTAMPTZ,request JSONB) RETURNS BIGINT
LANGUAGE plpgsql VOLATILE SECURITY DEFINER PARALLEL UNSAFE SET search_path=pg_catalog,mlb036_private,public,pg_temp SET timezone='UTC' AS $$
DECLARE p public.moneyline_game_predictions; run public.moneyline_prediction_runs; result BIGINT; a mlb036_private.authority;
BEGIN
    SELECT * INTO STRICT a FROM mlb036_private.authority WHERE singleton;
    IF session_user<>a.reader_role OR current_setting('transaction_isolation')<>'read committed'
      OR current_setting('transaction_read_only')<>'off' THEN RAISE EXCEPTION '036 dedicated certified prediction transaction'; END IF;
    IF request IS NULL OR jsonb_typeof(request)<>'object' OR (SELECT count(*) FROM jsonb_object_keys(request))<>19
      OR NOT request ?& ARRAY['moneyline_prediction_run_id','game_id','mlb_game_id','game_start_time','prediction_time','home_team_id','away_team_id',
        'home_starting_pitcher_id','away_starting_pitcher_id','home_starting_pitcher_mlb_id','away_starting_pitcher_mlb_id',
        'home_starter_features_available','away_starter_features_available','starter_coverage','missing_raw_value_count','home_win_probability',
        'away_win_probability','predicted_team_id','predicted_probability'] THEN RAISE EXCEPTION '036 exact prediction input fields'; END IF;
    p:=jsonb_populate_record(NULL::public.moneyline_game_predictions,request);
    PERFORM public.mlb_identity_gate(false);
    SELECT * INTO STRICT run FROM public.moneyline_prediction_runs WHERE moneyline_prediction_run_id=p.moneyline_prediction_run_id FOR UPDATE;
    IF run.canonical_time_knowledge IS NULL OR run.status<>'running' THEN RAISE EXCEPTION '036 certified running reservation required'; END IF;
    IF receipt_locator IS DISTINCT FROM (run.canonical_time_knowledge->>'receipt_id')::bigint
      OR original_cutoff IS DISTINCT FROM (run.canonical_time_knowledge->>'cutoff_time')::timestamptz THEN
        RAISE EXCEPTION '036 original prediction receipt/cutoff immutable; no swap'; END IF;
    PERFORM mlb036_private.validate_knowledge((run.canonical_time_knowledge->>'receipt_id')::bigint,
      (run.canonical_time_knowledge->>'cutoff_time')::timestamptz,false);
    PERFORM public.mlb_retirement_assert_decision_links(jsonb_build_object('game_id',p.game_id));
    INSERT INTO public.moneyline_game_predictions(moneyline_prediction_run_id,game_id,mlb_game_id,game_start_time,prediction_time,home_team_id,away_team_id,
      home_starting_pitcher_id,away_starting_pitcher_id,home_starting_pitcher_mlb_id,away_starting_pitcher_mlb_id,
      home_starter_features_available,away_starter_features_available,starter_coverage,missing_raw_value_count,home_win_probability,
      away_win_probability,predicted_team_id,predicted_probability)
    VALUES(p.moneyline_prediction_run_id,p.game_id,p.mlb_game_id,p.game_start_time,p.prediction_time,p.home_team_id,p.away_team_id,
      p.home_starting_pitcher_id,p.away_starting_pitcher_id,p.home_starting_pitcher_mlb_id,p.away_starting_pitcher_mlb_id,
      p.home_starter_features_available,p.away_starter_features_available,p.starter_coverage,p.missing_raw_value_count,p.home_win_probability,
      p.away_win_probability,p.predicted_team_id,p.predicted_probability) RETURNING moneyline_game_prediction_id INTO result;
    RETURN result;
END $$;
-- No provisioning, activation, receipt issuance or physical correction is performed.
REVOKE ALL ON ALL TABLES IN SCHEMA mlb036_private FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA mlb036_private FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA mlb036_private FROM PUBLIC;
