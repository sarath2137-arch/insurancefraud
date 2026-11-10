# AI and Blockchain-Based Medical Insurance Fraud Detection

An educational full-stack capstone system that accepts medical insurance claims, scores risk with a configurable ML decision-support workflow, stores sensitive data off-chain, and records only a tamper-evident claim hash and decision metadata on a Solidity contract.

## Run locally

1. Backend: from `backend`, create/activate a virtual environment, install `requirements.txt`, apply `python -m alembic -c alembic.ini upgrade head`, then run `uvicorn app.main:app --reload`. SQLite is used locally unless `DATABASE_URL` is set to PostgreSQL. Blockchain settings are read from process environment variables; no private key is stored in source or database.
2. Frontend: `cd frontend`; `npm install`; `npm run dev`.
3. Public registration always creates a `claim_officer`. To bootstrap a local administrator, explicitly set `SEED_DEVELOPMENT_ADMIN=true`, `SEED_ADMIN_EMAIL`, and a unique `SEED_ADMIN_PASSWORD` of at least 16 characters before the first backend start. Seeding is disabled by default. Keep these values private and remove/disable the seed configuration after the administrator is created.
4. Local blockchain: from `blockchain`, run `npm install` and `npm run compile`; then run `npm run node`. In a second terminal run `npm run deploy` (targets only `http://127.0.0.1:8545`). Configure the backend process with the actual deployment output and the local deployer account's key. Never use a public network or a fabricated key.

## Run with Docker Compose

From the repository root, start PostgreSQL, apply its schema migration, then start the FastAPI backend:

```powershell
docker compose build backend
docker compose up -d postgres
docker compose run --rm --no-deps backend python -m alembic -c alembic.ini upgrade head
docker compose up -d backend
docker compose ps
docker compose logs --tail=100 backend
```

Wait until both services report `healthy`, then check the API:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

The backend image uses Python 3.12 and installs the pinned dependencies in `backend/requirements.txt`. Compose builds from the repository root using `backend/Dockerfile`, connects to the `postgres` service using the configured PostgreSQL `DATABASE_URL`, and runs without performing schema changes at startup. The image contains the DNN model, fitted preprocessor, and minimized provider-level feature artifact; raw provider CSVs are excluded from the image.

To stop the services while preserving the PostgreSQL data volume:

```powershell
docker compose down
```

Hardhat is not started by Compose. If you separately start a local Hardhat node on Windows and want the containerized backend to reach it, configure the backend with the actual deployment details and `BLOCKCHAIN_RPC_URL=http://host.docker.internal:8545`. Supply `BLOCKCHAIN_PRIVATE_KEY` through your shell environment or an untracked `.env` file; never commit it. The contract address and ABI must also come from the actual deployment. For example, set values in PowerShell before starting Compose:

```powershell
$env:BLOCKCHAIN_RPC_URL = 'http://host.docker.internal:8545'
$env:BLOCKCHAIN_CONTRACT_ADDRESS = '<actual deployed address>'
$env:BLOCKCHAIN_CONTRACT_ABI = '<actual contract ABI JSON>'
$env:BLOCKCHAIN_PRIVATE_KEY = '<actual contract owner key>'
docker compose up -d backend
```

For the Docker backend, supply the ABI JSON directly (a host artifact path is not visible inside the container). Leaving these variables unset keeps blockchain operations unconfigured. Starting Compose does not start Hardhat or send a transaction.

## API

`POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`; `POST/GET /api/claims`; `GET /api/claims/{id}`; `PUT /api/claims/{id}/status`; `GET /api/fraud/{id}`; `POST /api/blockchain/register?claim_id={id}` (admin); `GET /api/blockchain/{id}`, `GET /api/blockchain/verify/{id}`, and `GET /api/blockchain/hash/{decision_hash}`; `GET /api/reports/summary`.

## Provider-level ML training

The DNN training pipeline uses the real Kaggle Medical Provider Fraud Detection training tables. Place these files in `ml/data/raw/`:

```text
Train-1542865627584.csv
Train_Beneficiarydata-1542865627584.csv
Train_Inpatientdata-1542865627584.csv
Train_Outpatientdata-1542865627584.csv
```

The provider table supplies one label per `Provider`; `PotentialFraud` is encoded as `No=0`, `Yes=1`. Claim and beneficiary tables are joined by their source IDs and aggregated to exactly one numeric feature row per provider. The features include provider claim counts, reimbursement/deductible and duration summaries, beneficiary counts and aggregated demographics, coverage and chronic-condition summaries, code diversity summaries, and counts of distinct physicians by role. Provider, beneficiary, claim, and raw physician IDs and the target are excluded from model inputs. `DOD` is excluded to avoid using a post-claim outcome.

Training first splits unique providers into stratified train, validation, and held-out test partitions (70/15/15). Missing-value imputation and scaling are fitted on the training partition only. Dynamic balanced class weights are computed from training labels. The network uses Dense(128)-BatchNormalization-Dropout(0.30), Dense(64)-BatchNormalization-Dropout(0.25), Dense(32)-Dropout(0.20), and a sigmoid output. It uses Adam at 0.001, binary cross-entropy, accuracy, precision, recall, and AUC, with early stopping on validation AUC.

Install the ML dependencies and train explicitly:

```powershell
pip install -r ml\requirements.txt
python ml\models\train.py
```

The script reports class distributions and provider counts for all splits, then held-out test accuracy, precision, recall, F1-score, ROC-AUC, and confusion matrix. It saves `ml/models/medical_fraud_dnn.keras` and the reusable fitted preprocessing artifact with feature order at `ml/models/medical_fraud_dnn_preprocessor.joblib`. No performance figures are claimed before a real training run.

Claim submissions require the canonical source `provider_id`. The backend validates it against the minimized provider-level feature table generated by the existing feature engineering pipeline, then applies the saved preprocessor and DNN. For local setup or regeneration, run `python ml\preprocessing\export_provider_features.py` from the repository root after placing the four source CSVs in `ml/data/raw/`. The claim-level heuristic remains active and is returned separately from the provider-level DNN score. Provider lookup uses the source training population, so its score is not an independent held-out evaluation; scoring new providers requires an equivalent trusted provider-history source. Neither score establishes fraud; both are decision-support signals for human review.

## Privacy and configuration

Medical documents, patient data, diagnosis, hospital, and claim amounts are excluded from the canonical decision payload and contract call. The local SHA-256 payload covers claim ID, provider ID, DNN probability/risk/prediction/threshold, and timestamp. The existing contract receives the claim ID, payload hash, DNN suspicious flag, and integer risk score. The backend signs `registerClaim(string,bytes32,bool,uint8)`, waits for the real receipt, and compares `exists(id)` and `claims(id)` with the expected hash and metadata. `confirmed_on_chain` means the transaction succeeded and the stored record matched. The separate Solidity `verified` flag is returned from contract state and remains false until the owner separately calls `verifyClaim(string)`; the backend does not label a locally generated hash as verified.

Set these process environment variables to enable chain reads/writes: `BLOCKCHAIN_RPC_URL`, `BLOCKCHAIN_CONTRACT_ADDRESS`, `BLOCKCHAIN_PRIVATE_KEY`, and `BLOCKCHAIN_CONTRACT_ABI`. The ABI variable accepts the compiled Hardhat artifact JSON path or ABI JSON. `BLOCKCHAIN_TIMEOUT_SECONDS` is optional (default 30, allowed range 1–300). Missing credentials leave chain status `unavailable_not_configured`. Invalid RPC/address/key/ABI, failed transactions, unavailable receipts, and failed contract reads return distinct non-success statuses without exposing credentials or inventing transaction data. The private key must belong to the Solidity contract owner because its writer methods are `onlyOwner`.

Example local configuration from PowerShell, after deploying to a local Hardhat node and using the actual deployment output and owner key:

```powershell
$env:BLOCKCHAIN_RPC_URL = 'http://127.0.0.1:8545'
$env:BLOCKCHAIN_CONTRACT_ADDRESS = '<actual address printed by local deploy>'
$env:BLOCKCHAIN_PRIVATE_KEY = '<actual local deployer key>'
$env:BLOCKCHAIN_CONTRACT_ABI = '..\blockchain\artifacts\contracts\InsuranceClaim.sol\InsuranceClaim.json'
```

Do not commit or log these values. Keep the RPC on localhost for this project setup.

## Run tests

From the repository root, install backend dependencies and run the relevant tests:

```powershell
cd backend
python -m pip install -r requirements.txt
cd ..
python -m pytest tests/test_claims.py tests/test_fraud_detection.py tests/test_blockchain.py tests/test_provider_ml.py
```
