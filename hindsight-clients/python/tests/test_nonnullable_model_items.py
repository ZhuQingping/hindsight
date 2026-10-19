"""Generated clients preserve the native schema's non-null array elements."""

import pytest
from pydantic import ValidationError

from hindsight_client_api.models.bank_template_config import BankTemplateConfig
from hindsight_client_api.models.memory_unit_list_item import MemoryUnitListItem
from hindsight_client_api.models.mental_model_delta_operations import MentalModelDeltaOperations


@pytest.mark.parametrize(
    "model,payload",
    [
        (MemoryUnitListItem, {"id": "memory", "source_memory_ids": [None]}),
        (BankTemplateConfig, {"observation_scope_limits": [None]}),
        (MentalModelDeltaOperations, {"applied": [None], "skipped": []}),
        (MentalModelDeltaOperations, {"applied": [], "skipped": [None]}),
    ],
)
def test_nonnullable_items_reject_null(model, payload):
    field = next(key for key, value in payload.items() if value == [None])
    model(**{**payload, field: []})  # All other fields form a valid model.
    with pytest.raises(ValidationError) as error:
        model(**payload)
    assert error.value.errors()[0]["loc"] == (field, 0)
