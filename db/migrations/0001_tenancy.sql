-- BillRx multi-tenant schema with row-level security and an append-only audit log.
--
-- One model serves B2C and B2B: a consumer gets a 'personal' organization, an
-- advocate practice or employer gets a shared one. Every tenant row carries
-- org_id, and Postgres row-level security (not application code) decides what
-- each user can see and change.
--
-- The application connects as a role that is a member of billrx_app (never as
-- the table owner) and sets, per transaction:
--     SET LOCAL billrx.user_id = '<users.id>';
-- With no user set, every tenant table reads as empty.
--
-- PHI rules: PHI lives only in clients, documents (in object storage, referenced
-- by key), findings and approvals. The audit log records who changed what and
-- which fields changed, never the values.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS billrx;
SET LOCAL search_path = billrx, public;

CREATE TYPE billrx.org_kind AS ENUM ('personal', 'advocate_practice', 'employer');
CREATE TYPE billrx.member_role AS ENUM ('owner', 'admin', 'advocate', 'viewer');
CREATE TYPE billrx.case_status AS ENUM
    ('draft', 'in_review', 'awaiting_approval', 'sent', 'resolved', 'closed');
CREATE TYPE billrx.document_kind AS ENUM
    ('itemized_bill', 'eob', 'statement', 'correspondence', 'other');
CREATE TYPE billrx.finding_verdict AS ENUM ('pending', 'keep', 'reject');
CREATE TYPE billrx.approval_artifact AS ENUM ('appeal_letter', 'phone_script');

-- ---------------------------------------------------------------- tables

CREATE TABLE billrx.organizations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    kind        billrx.org_kind NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE billrx.users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_subject  text NOT NULL UNIQUE,  -- subject id from the auth provider
    email         text NOT NULL UNIQUE,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE billrx.memberships (
    org_id      uuid NOT NULL REFERENCES billrx.organizations(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES billrx.users(id) ON DELETE CASCADE,
    role        billrx.member_role NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
);
CREATE INDEX memberships_user_idx ON billrx.memberships (user_id);

-- The person whose bills these are. For a personal org this is the user.
CREATE TABLE billrx.clients (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        uuid NOT NULL REFERENCES billrx.organizations(id) ON DELETE CASCADE,
    display_name  text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    external_ref  text,
    created_by    uuid REFERENCES billrx.users(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, org_id)
);
CREATE INDEX clients_org_idx ON billrx.clients (org_id);

-- Composite foreign keys (child.org_id must equal parent.org_id) make
-- cross-tenant references impossible even for code that bypasses RLS.
CREATE TABLE billrx.cases (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL,
    client_id   uuid NOT NULL,
    title       text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),
    status      billrx.case_status NOT NULL DEFAULT 'draft',
    created_by  uuid REFERENCES billrx.users(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, org_id),
    FOREIGN KEY (client_id, org_id) REFERENCES billrx.clients (id, org_id) ON DELETE CASCADE
);
CREATE INDEX cases_org_status_idx ON billrx.cases (org_id, status);

-- File bytes live in encrypted object storage; this row is the reference.
CREATE TABLE billrx.documents (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL,
    case_id      uuid NOT NULL,
    kind         billrx.document_kind NOT NULL,
    storage_key  text NOT NULL UNIQUE,
    sha256       text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_size    integer NOT NULL CHECK (byte_size > 0 AND byte_size <= 15728640),
    mime_type    text NOT NULL CHECK (mime_type IN
                   ('application/pdf', 'image/png', 'image/jpeg', 'image/tiff')),
    uploaded_by  uuid REFERENCES billrx.users(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (case_id, org_id) REFERENCES billrx.cases (id, org_id) ON DELETE CASCADE
);
CREATE INDEX documents_case_idx ON billrx.documents (case_id);

CREATE TABLE billrx.findings (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL,
    case_id          uuid NOT NULL,
    finding_key      text NOT NULL,           -- e.g. F-DUP-80053
    kind             text NOT NULL,
    title            text NOT NULL,
    question         text NOT NULL,
    evidence         jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(evidence) = 'array'),
    amount_at_stake  numeric(12, 2) NOT NULL CHECK (amount_at_stake >= 0),
    verdict          billrx.finding_verdict NOT NULL DEFAULT 'pending',
    reason           text,
    reviewed_by      uuid REFERENCES billrx.users(id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, finding_key),
    FOREIGN KEY (case_id, org_id) REFERENCES billrx.cases (id, org_id) ON DELETE CASCADE
);

-- Human approval gate: nothing is sent without one of these rows.
CREATE TABLE billrx.approvals (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          uuid NOT NULL,
    case_id         uuid NOT NULL,
    artifact        billrx.approval_artifact NOT NULL,
    content_sha256  text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    approved_by     uuid NOT NULL REFERENCES billrx.users(id),
    approved_at     timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (case_id, org_id) REFERENCES billrx.cases (id, org_id) ON DELETE CASCADE
);

CREATE TABLE billrx.audit_log (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id          uuid NOT NULL,
    actor_user_id   uuid,
    action          text NOT NULL CHECK (action IN ('insert', 'update', 'delete')),
    entity          text NOT NULL,
    entity_id       uuid,
    changed_fields  text[] NOT NULL DEFAULT '{}',
    at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_org_at_idx ON billrx.audit_log (org_id, at DESC);

-- ---------------------------------------------------------------- session helpers

CREATE FUNCTION billrx.current_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('billrx.user_id', true), '')::uuid
$$;

-- SECURITY DEFINER so policies can consult memberships without recursing
-- through memberships' own policy.
CREATE FUNCTION billrx.has_role(p_org uuid, p_roles billrx.member_role[]) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = billrx, pg_temp AS $$
    SELECT EXISTS (
        SELECT 1 FROM billrx.memberships m
        WHERE m.org_id = p_org
          AND m.user_id = billrx.current_user_id()
          AND m.role = ANY (p_roles))
$$;

CREATE FUNCTION billrx.is_member(p_org uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT billrx.has_role(p_org, enum_range(NULL::billrx.member_role))
$$;

CREATE FUNCTION billrx.can_write(p_org uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT billrx.has_role(p_org, ARRAY['owner', 'admin', 'advocate']::billrx.member_role[])
$$;

CREATE FUNCTION billrx.can_manage(p_org uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT billrx.has_role(p_org, ARRAY['owner', 'admin']::billrx.member_role[])
$$;

CREATE FUNCTION billrx.shares_org(p_user uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = billrx, pg_temp AS $$
    SELECT EXISTS (
        SELECT 1 FROM billrx.memberships a
        JOIN billrx.memberships b ON a.org_id = b.org_id
        WHERE a.user_id = billrx.current_user_id() AND b.user_id = p_user)
$$;

-- Signup path for both B2C (personal) and B2B: creates the org and makes the
-- current user its owner in one step.
CREATE FUNCTION billrx.create_organization(p_name text, p_kind billrx.org_kind) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = billrx, pg_temp AS $$
DECLARE
    v_user uuid := billrx.current_user_id();
    v_org  uuid;
BEGIN
    IF v_user IS NULL THEN
        RAISE EXCEPTION 'no authenticated user in this session' USING ERRCODE = '42501';
    END IF;
    INSERT INTO billrx.organizations (name, kind) VALUES (p_name, p_kind) RETURNING id INTO v_org;
    INSERT INTO billrx.memberships (org_id, user_id, role) VALUES (v_org, v_user, 'owner');
    RETURN v_org;
END $$;

-- ---------------------------------------------------------------- triggers

CREATE FUNCTION billrx.audit_row() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = billrx, pg_temp AS $$
DECLARE
    v_new jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END;
    v_old jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END;
    v_row jsonb := coalesce(v_new, v_old);
    v_fields text[] := '{}';
BEGIN
    IF TG_OP = 'UPDATE' THEN
        SELECT coalesce(array_agg(k ORDER BY k), '{}') INTO v_fields
        FROM jsonb_object_keys(v_new) k
        WHERE v_new -> k IS DISTINCT FROM v_old -> k;
    END IF;
    INSERT INTO billrx.audit_log (org_id, actor_user_id, action, entity, entity_id, changed_fields)
    VALUES ((v_row ->> 'org_id')::uuid, billrx.current_user_id(), lower(TG_OP), TG_TABLE_NAME,
            CASE WHEN v_row ? 'id' THEN (v_row ->> 'id')::uuid END, v_fields);
    RETURN coalesce(NEW, OLD);
END $$;

CREATE FUNCTION billrx.audit_log_is_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = '42501';
END $$;

CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON billrx.audit_log
    FOR EACH ROW EXECUTE FUNCTION billrx.audit_log_is_append_only();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON billrx.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION billrx.audit_log_is_append_only();

CREATE FUNCTION billrx.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END $$;
CREATE TRIGGER cases_touch BEFORE UPDATE ON billrx.cases
    FOR EACH ROW EXECUTE FUNCTION billrx.touch_updated_at();

-- An organization must always keep at least one owner.
CREATE FUNCTION billrx.keep_an_owner() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = billrx, pg_temp AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM billrx.organizations o WHERE o.id = OLD.org_id)
       AND NOT EXISTS (SELECT 1 FROM billrx.memberships m
                       WHERE m.org_id = OLD.org_id AND m.role = 'owner') THEN
        RAISE EXCEPTION 'an organization must keep at least one owner' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER memberships_keep_owner
    AFTER UPDATE OR DELETE ON billrx.memberships
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION billrx.keep_an_owner();

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['memberships', 'clients', 'cases', 'documents', 'findings', 'approvals'] LOOP
        EXECUTE format('CREATE TRIGGER %I_audit AFTER INSERT OR UPDATE OR DELETE ON billrx.%I '
                       'FOR EACH ROW EXECUTE FUNCTION billrx.audit_row()', t, t);
    END LOOP;
END $$;

-- ---------------------------------------------------------------- row-level security

ALTER TABLE billrx.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE billrx.users         ENABLE ROW LEVEL SECURITY;
ALTER TABLE billrx.memberships   ENABLE ROW LEVEL SECURITY;
ALTER TABLE billrx.clients       ENABLE ROW LEVEL SECURITY;
ALTER TABLE billrx.cases         ENABLE ROW LEVEL SECURITY;
ALTER TABLE billrx.documents     ENABLE ROW LEVEL SECURITY;
ALTER TABLE billrx.findings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE billrx.approvals     ENABLE ROW LEVEL SECURITY;
ALTER TABLE billrx.audit_log     ENABLE ROW LEVEL SECURITY;

CREATE POLICY org_read ON billrx.organizations FOR SELECT USING (billrx.is_member(id));
CREATE POLICY org_rename ON billrx.organizations FOR UPDATE
    USING (billrx.can_manage(id)) WITH CHECK (billrx.can_manage(id));

CREATE POLICY users_read ON billrx.users FOR SELECT
    USING (id = billrx.current_user_id() OR billrx.shares_org(id));

CREATE POLICY members_read ON billrx.memberships FOR SELECT USING (billrx.is_member(org_id));
CREATE POLICY members_add ON billrx.memberships FOR INSERT WITH CHECK (billrx.can_manage(org_id));
CREATE POLICY members_change ON billrx.memberships FOR UPDATE
    USING (billrx.can_manage(org_id)) WITH CHECK (billrx.can_manage(org_id));
CREATE POLICY members_remove ON billrx.memberships FOR DELETE USING (billrx.can_manage(org_id));

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['clients', 'cases', 'documents', 'findings'] LOOP
        EXECUTE format('CREATE POLICY %I_read ON billrx.%I FOR SELECT USING (billrx.is_member(org_id))', t, t);
        EXECUTE format('CREATE POLICY %I_add ON billrx.%I FOR INSERT WITH CHECK (billrx.can_write(org_id))', t, t);
        EXECUTE format('CREATE POLICY %I_change ON billrx.%I FOR UPDATE USING (billrx.can_write(org_id)) '
                       'WITH CHECK (billrx.can_write(org_id))', t, t);
        EXECUTE format('CREATE POLICY %I_remove ON billrx.%I FOR DELETE USING (billrx.can_manage(org_id))', t, t);
    END LOOP;
END $$;

CREATE POLICY approvals_read ON billrx.approvals FOR SELECT USING (billrx.is_member(org_id));
CREATE POLICY approvals_add ON billrx.approvals FOR INSERT
    WITH CHECK (billrx.can_write(org_id) AND approved_by = billrx.current_user_id());

CREATE POLICY audit_read ON billrx.audit_log FOR SELECT USING (billrx.can_manage(org_id));

-- ---------------------------------------------------------------- privileges

DO $$
BEGIN
    CREATE ROLE billrx_app NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA billrx FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA billrx FROM PUBLIC;
GRANT USAGE ON SCHEMA billrx TO billrx_app;
GRANT SELECT, UPDATE ON billrx.organizations TO billrx_app;
GRANT SELECT ON billrx.users TO billrx_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON billrx.memberships TO billrx_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON billrx.clients, billrx.cases, billrx.documents,
    billrx.findings TO billrx_app;
GRANT SELECT, INSERT ON billrx.approvals TO billrx_app;  -- approvals are never edited
GRANT SELECT ON billrx.audit_log TO billrx_app;         -- written only by triggers
GRANT EXECUTE ON FUNCTION billrx.current_user_id(), billrx.has_role(uuid, billrx.member_role[]),
    billrx.is_member(uuid), billrx.can_write(uuid), billrx.can_manage(uuid),
    billrx.shares_org(uuid), billrx.create_organization(text, billrx.org_kind) TO billrx_app;

COMMIT;
