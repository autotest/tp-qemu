import re

from virttest import env_process, error_context, utils_misc, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    Qemu virtio-rng device test:
    1) boot guest with virtio-rng device
    2) read random data in guest
    3) check the read data rate

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _is_rngd_running():
        """
        Check whether rngd is running
        """
        output = session.cmd_output(check_rngd_service)
        return "running" in output

    timeout = params.get_numeric("login_timeout", 360)
    read_rng_timeout = float(params.get("read_rng_timeout", 3600))
    cmd_timeout = float(params.get("session_cmd_timeout", "360"))
    read_rng_cmd = params["read_rng_cmd"]
    max_bytes = params.get("max-bytes_virtio-rng")
    period = params.get("period_virtio-rng")

    if not max_bytes and not period:
        test.error("Please specify the expected max-bytes and/or period.")
    if not max_bytes or not period:
        error_info = params["expected_error_info"]
        try:
            env_process.process(
                test,
                params,
                env,
                env_process.preprocess_image,
                env_process.preprocess_vm,
            )
        except virt_vm.VMCreateError as e:
            if error_info not in e.output:
                test.fail(
                    "Expected error info '%s' is not reported, "
                    "output: %s" % (error_info, e.output)
                )
        return

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Read virtio-rng device to get random number", test.log.info)
    update_driver = params.get("update_driver")
    if update_driver:
        session.cmd(update_driver, timeout=cmd_timeout)
    check_rngd_service = params.get("check_rngd_service")
    if check_rngd_service:
        if not utils_misc.wait_for(_is_rngd_running, 30, first=5):
            start_rngd_service = params["start_rngd_service"]
            status, output = session.cmd_status_output(start_rngd_service)
            if status:
                test.error(output)

    s, o = session.cmd_status_output(read_rng_cmd, timeout=read_rng_timeout)
    if s:
        test.error(o)
    test.log.info(o)
    data_rate = re.search(r"\s(\d+\.\d+) kB/s", o, re.M)
    expected_data_rate = float(params["expected_data_rate"])
    if float(data_rate.group(1)) > expected_data_rate * 1.1:
        test.error(
            "Read data rate is not as expected. "
            "data rate: %s kB/s, max-bytes: %s, period: %s"
            % (data_rate.group(1), max_bytes, period)
        )

    session.close()
