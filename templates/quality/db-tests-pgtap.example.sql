-- AGENTIZED:QUALITY — example pgTAP DB test for connected projects.
-- Place under db/tests/ or tests/db/ (or pgtap/). Run with pg_prove when DB layer is present.
-- Rules: assert observable schema/data behavior; cover changed migrations; no mirrored app formulas.

BEGIN;
SELECT plan(3);

SELECT has_table('accounts');
SELECT has_column('accounts', 'id');
SELECT col_type_is('accounts', 'id', 'uuid');

SELECT * FROM finish();
ROLLBACK;
