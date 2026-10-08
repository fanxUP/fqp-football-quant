-- Reverting application code is safe while retaining these encrypted credentials.
-- Do not drop credential columns: dropping would destroy newly established logins.
SELECT 1;
