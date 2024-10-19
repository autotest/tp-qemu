from virttest import error_context, utils_net, utils_test
from virttest.utils_windows import virtio_win


@error_context.context_aware
def run(test, params, env):
    """
    The rx/tx offload checksum test for windows
    1) start vm
    2) set the tx/rx offload checksum of the netkvm driver to tcp
    3) restart nic, and run file transfer test
    4) set the tx/rx offload checksum of the nekvm driver to disable
    5) restart nic, and run file transfer test again

    param test: the test object
    param params: the test params
    param env: test environment
    """

    def set_offload_checksum_windows(vm, is_tx, checksum_config):
        """
        Set the tx or rx offload checksum to certain config, for the first nic
        on windows.

        param vm: the target vm
        param is_tx: True for tx setting, False for rx setting
        param checksum_config: config for checksum settings, one of 'tcp' or 'disable'
        """
        param = "Offload.TxChecksum" if is_tx else "Offload.RXCS"
        value = "1" if checksum_config == "tcp" else "0"
        utils_net.set_netkvm_param_value(vm, param, value)

    def start_test(checksum_config="tcp"):
        """
        Start tx/tx offload checksum test. First set tx/rx offload checksum
        value to the driver, the restart the nic and run file transfertest,

        param config: the setting config for checksum, tcp or disable
        """
        error_context.context(
            "Start set tx/rx checksum offload to %s" % checksum_config, test.log.info
        )
        set_offload_checksum_windows(vm, True, checksum_config)
        set_offload_checksum_windows(vm, False, checksum_config)

        error_context.context("Start file transfer test", test.log.info)
        utils_test.run_file_transfer(test, params, env)

    timeout = params.get("timeout", 360)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=timeout)
    error_context.context(
        "Check if the driver is installed and " "verified", test.log.info
    )
    driver_name = params.get("driver_name", "netkvm")
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_name, timeout
    )
    session.close()

    virtio_win.prepare_netkvmco(vm)
    start_test("tcp")
    start_test("disable")
