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
    avocadoinstalltype = params.get("avocadoinstalltype", "pip")
    avocadotestrepo = params.get(
        "avocadotestrepo",
        "https://github.com/avocado-framework-tests/avocado-misc-tests.git",
    )
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
        installtype=avocadoinstalltype,
        reinstall=False,
        add_args=avocadotestargs,
        ignore_result=False,
    )
    avocado_obj.run_avocado()
