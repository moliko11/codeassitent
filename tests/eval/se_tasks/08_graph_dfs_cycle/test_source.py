from source import dfs
def test_simple():
    assert dfs({1:[2,3], 2:[], 3:[]}, 1) == {1,2,3}
def test_cycle():
    g = {1:[2], 2:[3], 3:[1]}
    assert dfs(g, 1) == {1,2,3}
def test_disconnected():
    assert dfs({1:[2], 2:[], 3:[]}, 1) == {1,2}
