import logging
import os
from autotest.client.shared import error
from virttest import utils_test, data_dir, remote_build


@error.context_aware
def run(test, params, env):
    """
    Verify if guests using kvm-clock as the time source have a sane clock
    resolution.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    address = vm.get_address(0)
    source_dir = data_dir.get_deps_dir("clock_getres")
    build_dir = params.get("build_dir", None)

    builder = remote_build.Builder(params, address, source_dir,
                                   build_dir=build_dir)

    getres_cmd = os.path.join(builder.build(), "clock_getres")

    if not session.cmd_status(getres_cmd) == 0:
        raise Exception("clock_getres failed")
    logging.info("PASS: Guest reported appropriate clock resolution")
    sub_test = params.get("sub_test")
    if sub_test:
        error.context("Run sub test '%s' after checking"
                      " clock resolution" % sub_test, logging.info)
        utils_test.run_virt_sub_test(test, params, env, sub_test)
