BEGIN;
SELECT plan(2);
SELECT has_table('accounts');
SELECT has_column('accounts', 'email');
SELECT * FROM finish();
ROLLBACK;
