from source import pipeline
def test_pipeline():
    # [1,2,3,4] -> even [2,4] -> double [4,8]
    assert pipeline([1,2,3,4]) == [4,8]
def test_pipeline2():
    # [2,3] -> even [2] -> double [4]
    assert pipeline([2,3]) == [4]
