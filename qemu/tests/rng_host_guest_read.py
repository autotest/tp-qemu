from avocado.utils import process
from virttest import error_context, utils_test

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Qemu virtio-rng device test:
    1) boot guest with virtio-rng device
    2) host read random numbers in the background
    3) guest read random data at the same time during step2
    4) clean host read process after test

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def host_read_start(host_read_cmd):
        """
        Read random numbers on the host side
        :param host_read_cmd: host read random numbers command line
        :return: reture host_read_process
        """
        host_read_process = process.SubProcess(host_read_cmd, shell=True)
        host_read_process.start()
        return host_read_process

    def host_read_clean(host_read_process):
        """
        Clean host read random numbers process
        :param host_read_process: process of the host reading
        """
        if host_read_process.poll() is None:
            host_read_process.kill()

    host_read_cmd = params.get("host_read_cmd")
    guest_rng_test = params.get("guest_rng_test")
    os_type = params["os_type"]
    vm = env.get_vm(params["main_vm"])
    vm.wait_for_login()

    error_context.context("Host read random numbers in the background", test.log.info)
    host_read_process = host_read_start(host_read_cmd)

    try:
        if host_read_process.poll() is None:
            error_context.context("Guest begin to read random numbers", test.log.info)
            utils_test.run_virt_sub_test(test, params, env, guest_rng_test)
        else:
            test.error("Host reading data is not alive!")
    finally:
        error_context.context("Clean host read process", test.log.info)
        host_read_clean(host_read_process)
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if os_type == "windows":
        win_driver_utils.memory_leak_check(vm, test, params)
