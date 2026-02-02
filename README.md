# ammtest

Python test framework for testing critical software systems via ammio.

## Installation

```bash
uv add ammtest
```

## Usage

**tests/conftest.py:**
```python
import pytest
from ammtest import AmmioClient

@pytest.fixture(scope="session")
def client():
    c = AmmioClient("config/config.json")
    yield c
    c.close()
```

**tests/test_example.py:**
```python
def test_brake_response(client):
    client.force("brake_request", True)
    assert client.read("brake_status") == 1
```

**Run:**
```bash
pytest
```

Requires [ammio](https://github.com/ammonit-software/ammio) to be running.

## License

MIT
