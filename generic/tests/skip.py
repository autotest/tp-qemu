def run(test, params, env):
    """
    Cancel test (should trigger SKIP in simple harness)
    """
    test.cancel("Skip test is canceling a test!")
