def run(test, params, env):
    """
    Raise TestFail exception (should trigger FAIL in simple harness).
    """
    test.fail("Fail test is failing!")
