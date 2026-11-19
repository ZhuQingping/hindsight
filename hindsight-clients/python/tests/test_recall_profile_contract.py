"""Generated profile wire contract, without service or model calls."""

import pytest

from contextbase_client_api.models.recall_request import RecallRequest
from contextbase_client_api.models.recall_response import RecallResponse


def test_default_sdk_request_does_not_send_new_profile_field():
    assert "recall_profile" not in RecallRequest(query="art").to_dict()
    assert "recall_profile" not in RecallRequest.from_dict({"query": "art"}).to_dict()
    assert RecallRequest(query="art", recall_profile="locomo").to_dict()["recall_profile"] == "locomo"
    with pytest.raises(ValueError):
        RecallRequest(query="art", recall_profile="typo")


def test_old_and_profile_responses_are_both_readable():
    assert RecallResponse.from_dict({"results": []}).recall_context is None
    raw = {
        "results": [],
        "recall_context": {
            "profile": "locomo",
            "version": "message_windows_v1",
            "format": "locomo-packed-json-v1",
            "tokenizer": "o200k_base",
            "text": '{"facts":[],"chunks":[]}',
            "tokens": 9,
            "fact_tokens": 0,
            "chunk_tokens": 0,
            "included_fact_ids": [],
            "included_chunk_ids": [],
            "omitted": [],
        },
    }
    response = RecallResponse.from_dict(raw)
    assert response.recall_context.text == raw["recall_context"]["text"]
    assert response.to_dict()["recall_context"]["version"] == "message_windows_v1"
