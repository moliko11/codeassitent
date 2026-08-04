import pytest
from source import Door
def test_open_close():
    d = Door()
    d.open(); assert d.state == "open"
    d.close(); assert d.state == "closed"
def test_double_open_raises():
    d = Door(); d.open()
    with pytest.raises(ValueError):
        d.open()
