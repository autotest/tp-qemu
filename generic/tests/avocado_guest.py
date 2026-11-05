from virttest import utils_test


def run(test, params, env):
    """
    Run an avocado test inside a guest.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("test_timeout", 3600))
    testlist = []
    avocadoinstalltype = params.get("avocadoinstalltype", "git")
    avocadotestrepo = params.get(
        "avocadotestrepo",
        "https://github.com/avocado-framework-tests/avocado-misc-tests.git",
    )
    avocadotestbranch = params.get("avocadotestbranch", "master")
    avocadotest = params.get("avocadotest", "cpu/ebizzy.py")
    avocadomux = params.get("avocadomux", "")
    avocadotestargs = params.get("avocadotestargs", "")
    for index, item in enumerate(avocadotest.split(",")):
        try:
            mux = ""
            mux = avocadomux.split(",")[index]
        except IndexError:
            pass
        testlist.append((item, mux))
    avocado_obj = utils_test.AvocadoGuest(
        vm,
        params,
        test,
        testlist,
        timeout=timeout,
        testrepo=avocadotestrepo,
        testbranch=avocadotestbranch,
        installtype=avocadoinstalltype,
        reinstall=False,
        add_args=avocadotestargs,
        ignore_result=True,
    )
    result = avocado_obj.run_avocado()
    if not result:
        test.fail("Avocado test failed. Please look into debug.log")
