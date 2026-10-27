# ContextBase Python SDK

Install the downloaded wheel (Python 3.10+):

```sh
python -m pip install ./contextbase_client-1.0.0-py3-none-any.whl
```

Set `CONTEXTBASE_API_URL`, `CONTEXTBASE_API_TOKEN` and `CONTEXTBASE_BANK_ID` to the values supplied by your service provider, then use:

```python
import os
from contextbase_client import ContextBase

with ContextBase(
    base_url=os.environ["CONTEXTBASE_API_URL"],
    api_key=os.environ["CONTEXTBASE_API_TOKEN"],
) as client:
    bank = os.environ["CONTEXTBASE_BANK_ID"]
    client.retain(bank_id=bank, content="The project uses PostgreSQL 16.")
    result = client.recall(bank_id=bank, query="Which database does the project use?")
    print(result)
```

Inside an async application, use `await client.aretain(...)`, `await client.arecall(...)`, `await client.areflect(...)` and finally `await client.aclose()`. The synchronous methods are intended for scripts outside a running event loop.

`contextbase_client_api` exposes the generated models and low-level async APIs. Both modules are included in the same distribution. The SDK connects to your configured service; it does not install a server or create your Bank automatically.
