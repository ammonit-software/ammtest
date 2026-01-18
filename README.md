# ammtest

Python test framework for testing critical software systems via ammio.

## Installation

```bash
pip install pynng
pip install -e .
```

## Usage

```python
from ammtest import AmmioClient

client = AmmioClient()
client.force("sensor_temperature", 85.5)
value = client.read("motor_speed")
client.close()
```

Requires [ammio](https://github.com/ammonit-software/ammio) to be running.

## License

MIT
