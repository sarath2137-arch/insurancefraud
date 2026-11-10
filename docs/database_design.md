# Database design

`users`, `claims`, `fraud_predictions`, `blockchain_transactions`, and `claim_audit_logs` are modelled with foreign keys. The production migration should also add `roles` and `claim_documents` tables before document upload is enabled.
