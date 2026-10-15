-- INSERT OR REPLACE can bypass immutable DELETE guards with recursive triggers disabled.
-- Reject any existing outcome mapping before SQLite reaches its conflict-replacement phase.
CREATE TRIGGER immutable_outcome_owners_insert_conflict
BEFORE INSERT ON outcome_owners
WHEN EXISTS (
    SELECT 1 FROM outcome_owners WHERE outcome_id = NEW.outcome_id
)
BEGIN
    SELECT RAISE(ABORT, 'outcome ownership is immutable');
END;
