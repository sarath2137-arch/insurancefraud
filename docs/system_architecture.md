# System architecture

React sends authenticated REST requests to FastAPI. FastAPI validates and persists a claim, calls the scoring service, stores its prediction and a SHA-256 verification hash, then attempts a configured Solidity registration. PostgreSQL holds all sensitive information; chain data must remain minimal.
