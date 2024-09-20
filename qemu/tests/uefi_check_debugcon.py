from avocado.utils import process
from virttest import env_process, error_context, utils_misc, utils_package, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Verify the "-debugcon" parameter under the UEFI environment:
    1) Boot up a guest.
       If params["ovmf_log"] is not None,
       append debugcon parameter to qemu command lines.
    2) Remove the existing isa-log device.
    3) Destroy the guest.
    4) Start the trace command on host.
    5) Re-create the guest and verify it is alive.
    6) Destroy the guest.
    7) Check pio_read counts and pio_write counts.
    7.1) If disable debugcon:
            pio_read_counts > 0
            pio_write_counts = 0
    7.2) If enable debugcon:
            pio_read_counts > 0
            pio_write_counts > 0

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def check_trace_process():
        """
        check whether trace process is existing
        """
        if process.system(params["grep_trace_cmd"], ignore_status=True, shell=True):
            return False
        else:
            return True

    def remove_isa_debugcon(vm):
        """
        remove the existing isa-log device
        """
        for device in vm.devices:
            if device.type == "isa-log":
                vm.devices.remove(device)
                break
        env.register_vm(vm.name, vm)

    def trace_kvm_pio():
        """
        trace event kvm_pio
        """
        process.system(trace_record_cmd)

    # install trace-cmd in host
    utils_package.package_install("trace-cmd")
    if params.get("ovmf_log"):
        error_context.context(
            "Append debugcon parameter to " "qemu command lines.", test.log.info
        )
        ovmf_log = utils_misc.get_path(test.debugdir, params["ovmf_log"])
        params["extra_params"] %= ovmf_log
        params["start_vm"] = "yes"
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
    trace_output_file = utils_misc.get_path(test.debugdir, params["trace_output"])
    trace_record_cmd = params["trace_record_cmd"] % trace_output_file
    check_pio_read = params["check_pio_read"] % trace_output_file
    check_pio_write = params["check_pio_write"] % trace_output_file
    stop_trace_record = params["stop_trace_record"]
    timeout = int(params.get("timeout", 120))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    error_context.context("Remove the existing isa-log device.", test.log.info)
    remove_isa_debugcon(vm)
    vm.destroy()
    error_context.context("Run trace record command on host.", test.log.info)
    bg = utils_test.BackgroundTest(trace_kvm_pio, ())
    bg.start()
    if not utils_misc.wait_for(lambda: bg.is_alive, timeout):
        test.fail("Failed to start command: '%s'" % trace_record_cmd)
    try:
        vm.create()
        vm.verify_alive()
        vm.destroy()
        process.system(stop_trace_record, ignore_status=True, shell=True)
        if not utils_misc.wait_for(lambda: not check_trace_process(), timeout, 30, 3):
            test.fail(
                "Failed to stop command: '%s' after %s seconds."
                % (stop_trace_record, timeout)
            )
        pio_read_counts = int(
            process.run(check_pio_read, shell=True).stdout.decode().strip()
        )
        err_str = "pio_read counts should be greater than 0. "
        err_str += "But the actual counts are %s." % pio_read_counts
        test.assertGreater(pio_read_counts, 0, err_str)
        pio_write_counts = int(
            process.run(check_pio_write, shell=True).stdout.decode().strip()
        )
        if params.get("ovmf_log"):
            err_str = "pio_write counts should be greater than 0. "
            err_str += "But the actual counts are %s." % pio_write_counts
            test.assertGreater(pio_write_counts, 0, err_str)
        else:
            err_str = "pio_write counts should be equal to 0. "
            err_str += "But the actual counts are %s." % pio_write_counts
            test.assertEqual(pio_write_counts, 0, err_str)
    finally:
        if check_trace_process():
            process.system(stop_trace_record, ignore_status=True, shell=True)
