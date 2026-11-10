from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from app.services import blockchain_service as chain


@pytest.fixture
def decision():
    return chain.decision_payload(
        "CLM-123", "Provider-42",
        {"fraud_probability": 0.75, "risk_score": 75.0, "prediction": "Potential Fraud", "threshold": 0.5},
        datetime(2026, 10, 7, 8, 0, tzinfo=timezone.utc),
    )


def test_canonical_hash_and_privacy_limited_payload(decision):
    assert chain.decision_hash(decision) == chain.decision_hash(dict(reversed(list(decision.items()))))
    assert len(chain.decision_hash(decision)) == 64
    assert set(decision) == {"claim_id", "provider_id", "dnn", "timestamp"}
    for forbidden in ("patient", "diagnosis", "hospital", "claim_amount", "medical"):
        assert forbidden not in str(decision).lower()


def test_missing_chain_configuration_is_not_configured(decision, monkeypatch):
    for key in ("BLOCKCHAIN_RPC_URL", "BLOCKCHAIN_CONTRACT_ADDRESS", "BLOCKCHAIN_CONTRACT_ABI", "BLOCKCHAIN_PRIVATE_KEY"):
        monkeypatch.delenv(key, raising=False)
    result = chain.write_decision(decision, chain.decision_hash(decision))
    assert result["transaction_hash"] is None
    assert result["block_number"] is None
    assert result["verification_status"] == "unavailable_not_configured"
    assert set(result["configuration_missing"]) == {"RPC URL", "contract address", "contract ABI", "wallet private key"}


def test_missing_private_key_is_explicitly_reported(monkeypatch):
    monkeypatch.setenv("BLOCKCHAIN_RPC_URL", "http://127.0.0.1:8545")
    monkeypatch.setenv("BLOCKCHAIN_CONTRACT_ADDRESS", "0x" + "12" * 20)
    monkeypatch.setenv("BLOCKCHAIN_CONTRACT_ABI", "[]")
    monkeypatch.delenv("BLOCKCHAIN_PRIVATE_KEY", raising=False)
    with pytest.raises(chain.BlockchainSetupError) as error:
        chain._connect(require_signer=True)
    assert error.value.status == "unavailable_not_configured"
    assert error.value.missing == ["wallet private key"]


def test_invalid_rpc_and_contract_address_are_reported_without_network(monkeypatch):
    class FakeWeb3:
        @staticmethod
        def is_address(_): return False
    monkeypatch.setattr(chain, "_load_web3", lambda: FakeWeb3)
    monkeypatch.setenv("BLOCKCHAIN_RPC_URL", "not-a-url")
    monkeypatch.setenv("BLOCKCHAIN_CONTRACT_ADDRESS", "invalid")
    monkeypatch.setenv("BLOCKCHAIN_CONTRACT_ABI", "[]")
    with pytest.raises(chain.BlockchainSetupError) as error:
        chain._connect(require_signer=False)
    assert error.value.status == "unavailable_invalid_rpc_url"
    monkeypatch.setenv("BLOCKCHAIN_RPC_URL", "http://127.0.0.1:8545")
    with pytest.raises(chain.BlockchainSetupError) as error:
        chain._connect(require_signer=False)
    assert error.value.status == "unavailable_invalid_contract_address"


def test_invalid_abi_is_rejected():
    with pytest.raises(chain.BlockchainSetupError) as error:
        chain._load_abi('{"not_abi": []}')
    assert error.value.status == "unavailable_invalid_abi"


class FakeCall:
    def __init__(self, value): self.value = value
    def call(self): return self.value


class FakeSigned:
    raw_transaction = b"signed-test-transaction"


class FakeAccount:
    address = "0xOwner"


class FakeTransactionFunction:
    def build_transaction(self, tx): return tx


class FakeFunctions:
    def __init__(self, receipt_status=1): self.exists_calls=0; self.receipt_status=receipt_status
    def owner(self): return FakeCall("0xOwner")
    def exists(self, _):
        self.exists_calls += 1
        return FakeCall(self.exists_calls > 1)
    def claims(self, _): return FakeCall((bytes.fromhex("11" * 32), True, 75, False, 1_791_360_000, 0))
    def registerClaim(self, *_): return FakeTransactionFunction()


class FakeContract:
    def __init__(self, receipt_status=1): self.functions=FakeFunctions(receipt_status)


class FakeEth:
    chain_id = 31337
    def __init__(self, receipt_status=1): self.account=self; self.receipt_status=receipt_status
    def from_key(self, _): return FakeAccount()
    def get_transaction_count(self, *_): return 0
    def sign_transaction(self, *_args, **_kwargs): return FakeSigned()
    def send_raw_transaction(self, _): return bytes.fromhex("ab" * 32)
    def wait_for_transaction_receipt(self, *_args, **_kwargs): return {"status":self.receipt_status,"blockNumber":42}


class FakeWeb3:
    def __init__(self, receipt_status=1): self.eth=FakeEth(receipt_status)
    @staticmethod
    def to_hex(value): return "0x" + bytes(value).hex()


@pytest.mark.parametrize(("receipt_status", "expected_status"), [(1, "confirmed_on_chain"), (0, "transaction_failed")])
def test_writer_uses_receipt_and_returns_rpc_transaction_hash(decision, monkeypatch, receipt_status, expected_status):
    fake_web3, contract = FakeWeb3(receipt_status), FakeContract(receipt_status)
    monkeypatch.setattr(chain, "_connect", lambda require_signer: (fake_web3, contract, FakeAccount(), 1))
    monkeypatch.setenv("BLOCKCHAIN_PRIVATE_KEY", "mocked-test-key")
    result = chain.write_decision(decision, "11" * 32)
    assert result["transaction_hash"] == "0x" + "ab" * 32
    assert result["block_number"] == 42
    assert result["receipt_status"] == receipt_status
    assert result["verification_status"] == expected_status
    assert result["record_matches"] is (receipt_status == 1)
    assert "mocked-test-key" not in str(result)


def test_receipt_timeout_keeps_real_node_hash_without_claiming_confirmation(decision, monkeypatch):
    class TimeoutEth(FakeEth):
        def wait_for_transaction_receipt(self, *_args, **_kwargs): raise TimeoutError()
    class TimeoutWeb3(FakeWeb3):
        def __init__(self): self.eth=TimeoutEth()
    fake_web3, contract = TimeoutWeb3(), FakeContract()
    monkeypatch.setattr(chain, "_connect", lambda require_signer: (fake_web3, contract, FakeAccount(), 1))
    monkeypatch.setenv("BLOCKCHAIN_PRIVATE_KEY", "mocked-test-key")
    result = chain.write_decision(decision, "11" * 32)
    assert result["transaction_hash"] == "0x" + "ab" * 32
    assert result["block_number"] is None
    assert result["receipt_status"] is None
    assert result["verification_status"] == "receipt_timeout"


def test_contract_read_failure_is_not_reported_as_verified(decision, monkeypatch):
    class BrokenCall:
        def call(self): raise ConnectionError()
    class BrokenFunctions(FakeFunctions):
        def exists(self, _): return BrokenCall()
    class BrokenContract:
        functions=BrokenFunctions()
    monkeypatch.setattr(chain, "_connect", lambda require_signer: (FakeWeb3(), BrokenContract(), None, 1))
    result = chain.verify_decision("CLM-123", chain.decision_hash(decision), decision)
    assert result["verification_status"] == "contract_call_failed"
    assert result["record_matches"] is False


def test_readback_reports_missing_record_as_unconfirmed(decision, monkeypatch):
    fake_web3, contract = FakeWeb3(), FakeContract()
    contract.functions.exists = lambda _claim: FakeCall(False)
    monkeypatch.setattr(chain, "_connect", lambda require_signer: (fake_web3, contract, None, 1))
    result = chain.verify_decision("CLM-123", chain.decision_hash(decision), decision)
    assert result["verification_status"] == "not_found_on_chain"
    assert result["transaction_hash"] is None
    assert result["contract_verified"] is None


def test_readback_distinguishes_contract_verified_flag(decision, monkeypatch):
    fake_web3, contract = FakeWeb3(), FakeContract()
    contract.functions.exists = lambda _claim: FakeCall(True)
    monkeypatch.setattr(chain, "_connect", lambda require_signer: (fake_web3, contract, None, 1))
    result = chain.verify_decision("CLM-123", "11" * 32, decision)
    assert result["verification_status"] == "confirmed_on_chain"
    assert result["record_matches"] is True
    assert result["contract_verified"] is False
