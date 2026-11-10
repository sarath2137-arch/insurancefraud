"""Canonical decision hashing and synchronous Web3 writer/readback for InsuranceClaim."""

import hashlib
import json
import os
from datetime import timezone
from pathlib import Path
from urllib.parse import urlsplit


class BlockchainSetupError(Exception):
    def __init__(self, status, detail, missing=None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.missing = missing or []


def decision_payload(claim_id, provider_id, dnn_result, timestamp):
    """Only this limited, non-medical metadata is committed on chain via its hash."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    return {
        "claim_id": str(claim_id),
        "provider_id": str(provider_id),
        "dnn": {
            "fraud_probability": float(dnn_result["fraud_probability"]),
            "risk_score": float(dnn_result["risk_score"]),
            "prediction": str(dnn_result["prediction"]),
            "threshold": float(dnn_result["threshold"]),
        },
        "timestamp": timestamp.isoformat(),
    }


def decision_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_web3():
    try:
        from web3 import Web3
    except ImportError as exc:
        raise BlockchainSetupError("unavailable_dependency", "Install backend requirements to enable blockchain access.") from exc
    return Web3


def _load_abi(raw):
    try:
        candidate = raw.strip()
        if candidate.startswith("[") or candidate.startswith("{"):
            data = json.loads(candidate)
        else:
            data = json.loads(Path(candidate).expanduser().read_text(encoding="utf-8"))
        abi = data.get("abi") if isinstance(data, dict) else data
        if not isinstance(abi, list):
            raise ValueError
        names = {entry.get("name") for entry in abi if isinstance(entry, dict)}
        if not {"registerClaim", "exists", "claims", "owner"}.issubset(names):
            raise ValueError
        return abi
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise BlockchainSetupError(
            "unavailable_invalid_abi",
            "BLOCKCHAIN_CONTRACT_ABI must be valid ABI JSON or a path to the compiled contract artifact.",
        ) from exc


def _connect(require_signer):
    required = {
        "BLOCKCHAIN_RPC_URL": "RPC URL",
        "BLOCKCHAIN_CONTRACT_ADDRESS": "contract address",
        "BLOCKCHAIN_CONTRACT_ABI": "contract ABI",
    }
    if require_signer:
        required["BLOCKCHAIN_PRIVATE_KEY"] = "wallet private key"
    missing = [label for key, label in required.items() if not os.getenv(key, "").strip()]
    if missing:
        raise BlockchainSetupError("unavailable_not_configured", "Blockchain configuration is incomplete.", missing)

    rpc_url = os.environ["BLOCKCHAIN_RPC_URL"].strip()
    try:
        parsed = urlsplit(rpc_url)
    except ValueError as exc:
        raise BlockchainSetupError("unavailable_invalid_rpc_url", "BLOCKCHAIN_RPC_URL must be a valid HTTP(S) URL.") from exc
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise BlockchainSetupError("unavailable_invalid_rpc_url", "BLOCKCHAIN_RPC_URL must be a valid HTTP(S) URL.")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise BlockchainSetupError("unavailable_invalid_rpc_url", "BLOCKCHAIN_RPC_URL must be a valid HTTP(S) URL.") from exc

    Web3 = _load_web3()
    address = os.environ["BLOCKCHAIN_CONTRACT_ADDRESS"].strip()
    if not Web3.is_address(address):
        raise BlockchainSetupError("unavailable_invalid_contract_address", "BLOCKCHAIN_CONTRACT_ADDRESS is invalid.")
    abi = _load_abi(os.environ["BLOCKCHAIN_CONTRACT_ABI"])
    try:
        timeout = float(os.getenv("BLOCKCHAIN_TIMEOUT_SECONDS", "30"))
        if not 1 <= timeout <= 300:
            raise ValueError
    except ValueError as exc:
        raise BlockchainSetupError("unavailable_invalid_timeout", "BLOCKCHAIN_TIMEOUT_SECONDS must be between 1 and 300.") from exc

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))
        if not w3.is_connected():
            raise BlockchainSetupError("unavailable_rpc", "Could not connect to the configured blockchain RPC.")
    except BlockchainSetupError:
        raise
    except Exception as exc:
        raise BlockchainSetupError("unavailable_rpc", "Could not connect to the configured blockchain RPC.") from exc
    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
    except Exception as exc:
        raise BlockchainSetupError("unavailable_invalid_abi", "The configured ABI is not compatible with the contract interface.") from exc

    account = None
    if require_signer:
        try:
            account = w3.eth.account.from_key(os.environ["BLOCKCHAIN_PRIVATE_KEY"].strip())
        except Exception as exc:
            raise BlockchainSetupError("unavailable_invalid_private_key", "BLOCKCHAIN_PRIVATE_KEY is invalid.") from exc
    return w3, contract, account, timeout


def _record_matches(contract, claim_id, expected_hash, suspicious, risk_score):
    try:
        if not contract.functions.exists(claim_id).call():
            return False, None
        record = contract.functions.claims(claim_id).call()
        # Solidity struct order: dataHash, suspicious, riskScore, verified, timestamp, status.
        stored_hash = record[0].hex().removeprefix("0x").lower()
        expected_hash = expected_hash.removeprefix("0x").lower()
        matches = stored_hash == expected_hash and bool(record[1]) == bool(suspicious) and int(record[2]) == int(risk_score)
        return matches, {"contract_verified": bool(record[3]), "timestamp": int(record[4]), "status": int(record[5])}
    except Exception as exc:
        raise BlockchainSetupError("contract_call_failed", "Could not read the decision record from the contract.") from exc


def _find_submission_event(w3, contract, claim_id):
    try:
        events = contract.events.ClaimSubmitted().get_logs(
            from_block=0, to_block="latest", argument_filters={"claimId": claim_id},
        )
        if not events:
            return None, None, None
        event = events[-1]
        event_tx_hash = event["transactionHash"]
        try:
            receipt = w3.eth.get_transaction_receipt(event_tx_hash)
            receipt_status = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
            receipt_block = receipt.get("blockNumber") if isinstance(receipt, dict) else getattr(receipt, "blockNumber", None)
            block_number = int(receipt_block) if receipt_block is not None else int(event["blockNumber"])
        except Exception:
            receipt_status = None
            block_number = int(event["blockNumber"])
        return w3.to_hex(event_tx_hash), block_number, int(receipt_status) if receipt_status is not None else None
    except Exception:
        # State may still be verifiable even when the node prunes or restricts logs.
        return None, None, None


def _risk_inputs(payload):
    dnn = payload["dnn"]
    suspicious = dnn["prediction"].strip().lower() in {"potential fraud", "suspicious", "1", "true"}
    score = int(round(float(dnn["risk_score"])))
    if not 0 <= score <= 100:
        raise BlockchainSetupError("invalid_decision", "DNN risk score is outside the contract's 0 to 100 range.")
    return suspicious, score


def _configuration_failure(exc):
    return {
        "transaction_hash": None,
        "block_number": None,
        "receipt_status": None,
        "verification_status": exc.status,
        "contract_verified": None,
        "record_matches": False,
        "configuration_missing": exc.missing,
        "verification_detail": exc.detail,
    }


def write_decision(payload, expected_hash):
    """Register the hash with the existing owner-gated contract and verify its state."""
    try:
        w3, contract, account, timeout = _connect(require_signer=True)
    except BlockchainSetupError as exc:
        return _configuration_failure(exc)
    try:
        suspicious, score = _risk_inputs(payload)
        if contract.functions.exists(payload["claim_id"]).call():
            matches, state = _record_matches(contract, payload["claim_id"], expected_hash, suspicious, score)
            tx_hash, block_number, receipt_status = _find_submission_event(w3, contract, payload["claim_id"])
            if matches and receipt_status == 0:
                verification_status = "transaction_failed"
            elif matches and receipt_status is None:
                verification_status = "receipt_unavailable" if tx_hash else "confirmed_on_chain"
            else:
                verification_status = "confirmed_on_chain" if matches else "on_chain_mismatch"
            return {
                "transaction_hash": tx_hash, "block_number": block_number,
                "receipt_status": receipt_status,
                "verification_status": verification_status,
                "contract_verified": state["contract_verified"] if state else None,
                "record_matches": matches, "configuration_missing": [],
                "verification_detail": "Existing on-chain record checked; no duplicate transaction was sent.",
            }
    except BlockchainSetupError as exc:
        return _configuration_failure(exc)
    except Exception:
        return {**_configuration_failure(BlockchainSetupError("contract_call_failed", "Could not check whether this claim is already registered."))}

    try:
        owner = contract.functions.owner().call()
        if owner.lower() != account.address.lower():
            return _configuration_failure(BlockchainSetupError(
                "unavailable_not_contract_owner", "Configured wallet is not the contract owner and cannot register claims.",
            ))
        transaction = contract.functions.registerClaim(
            payload["claim_id"], bytes.fromhex(expected_hash.removeprefix("0x")), suspicious, score,
        ).build_transaction({
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address, "pending"),
            "chainId": w3.eth.chain_id,
        })
    except Exception:
        return _configuration_failure(BlockchainSetupError("contract_call_failed", "Could not prepare the contract registration call."))

    try:
        signed = w3.eth.account.sign_transaction(transaction, private_key=os.environ["BLOCKCHAIN_PRIVATE_KEY"].strip())
        raw_transaction = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    except Exception:
        return _configuration_failure(BlockchainSetupError("transaction_signing_failed", "Could not sign the contract transaction."))
    try:
        sent_hash = w3.eth.send_raw_transaction(raw_transaction)
        tx_hash = w3.to_hex(sent_hash)
    except Exception:
        # A transport failure can happen after the node accepted the raw tx.
        # Without the node's hash, do not report a failure or invent one.
        return _configuration_failure(BlockchainSetupError("transaction_submission_unknown", "RPC did not confirm whether the transaction was submitted."))

    try:
        receipt = w3.eth.wait_for_transaction_receipt(sent_hash, timeout=timeout)
    except Exception as exc:
        status = "receipt_timeout" if "timeout" in type(exc).__name__.lower() or isinstance(exc, TimeoutError) else "receipt_unavailable"
        return {
            "transaction_hash": tx_hash, "block_number": None,
            "receipt_status": None,
            "verification_status": status, "contract_verified": None,
            "record_matches": False, "configuration_missing": [],
            "verification_detail": "Transaction was accepted by RPC, but its receipt could not be retrieved.",
        }
    receipt_status = receipt.get("status") if isinstance(receipt, dict) else getattr(receipt, "status", None)
    receipt_block = receipt.get("blockNumber") if isinstance(receipt, dict) else getattr(receipt, "blockNumber", None)
    if receipt_status != 1:
        return {
            "transaction_hash": tx_hash, "block_number": int(receipt_block) if receipt_block is not None else None,
            "receipt_status": int(receipt_status) if receipt_status is not None else None,
            "verification_status": "transaction_failed", "contract_verified": None,
            "record_matches": False, "configuration_missing": [],
            "verification_detail": "The mined transaction receipt reports failure.",
        }
    try:
        matches, state = _record_matches(contract, payload["claim_id"], expected_hash, suspicious, score)
    except BlockchainSetupError as exc:
        return {
            "transaction_hash": tx_hash, "block_number": int(receipt_block) if receipt_block is not None else None,
            "receipt_status": 1,
            "verification_status": exc.status, "contract_verified": None,
            "record_matches": False, "configuration_missing": [], "verification_detail": exc.detail,
        }
    return {
        "transaction_hash": tx_hash,
        "block_number": int(receipt_block) if receipt_block is not None else None,
        "receipt_status": int(receipt_status),
        "verification_status": "confirmed_on_chain" if matches else "on_chain_mismatch",
        "contract_verified": state["contract_verified"] if state else None,
        "record_matches": matches, "configuration_missing": [],
        "verification_detail": "Mined transaction and stored decision record checked against the canonical hash.",
    }


def verify_decision(claim_id, expected_hash, payload=None):
    """Read contract state and compare it with the locally stored canonical hash/metadata."""
    try:
        w3, contract, _, _ = _connect(require_signer=False)
    except BlockchainSetupError as exc:
        return _configuration_failure(exc)
    try:
        if not contract.functions.exists(claim_id).call():
            return {
                "transaction_hash": None, "block_number": None,
                "receipt_status": None,
                "verification_status": "not_found_on_chain", "contract_verified": None,
                "record_matches": False, "configuration_missing": [],
                "verification_detail": "No contract record exists for this claim ID.",
            }
        record = contract.functions.claims(claim_id).call()
        stored_hash = record[0].hex().removeprefix("0x").lower()
        matches = stored_hash == expected_hash.removeprefix("0x").lower()
        if payload is not None:
            suspicious, score = _risk_inputs(payload)
            matches = matches and bool(record[1]) == suspicious and int(record[2]) == score
        tx_hash, block_number, receipt_status = _find_submission_event(w3, contract, claim_id)
        if matches and receipt_status == 0:
            verification_status = "transaction_failed"
        elif matches and receipt_status is None:
            verification_status = "receipt_unavailable" if tx_hash else "confirmed_on_chain"
        else:
            verification_status = "confirmed_on_chain" if matches else "on_chain_mismatch"
        return {
            "transaction_hash": tx_hash, "block_number": block_number,
            "receipt_status": receipt_status,
            "verification_status": verification_status,
            "contract_verified": bool(record[3]), "record_matches": matches,
            "configuration_missing": [],
            "verification_detail": "On-chain hash and allowed decision metadata compared with the stored decision." if matches else "On-chain record does not match the stored canonical decision.",
        }
    except BlockchainSetupError as exc:
        return _configuration_failure(exc)
    except Exception:
        return _configuration_failure(BlockchainSetupError("contract_call_failed", "Could not read or verify the decision record from the contract."))
