import aexpect
from avocado.core import exceptions
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    KVM driver load test:
    1) Log into a guest
    2) Read from virtio-rng device
    3) Unload the device driver
    4) Check no crash
    5) Load the device driver

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    driver_unload_cmd = params["driver_unload_cmd"]

    error_context.context("Read virtio-rng device in background", test.log.info)
    read_rng_cmd = params["read_rng_cmd"]
    pid = session.cmd_output(read_rng_cmd)
    pid = pid.split("\n")[1]
    test.log.info("Check if random read process exist")
    status = session.cmd_status("ps -p %s" % pid)
    if status != 0:
        raise exceptions.TestFail("random read is not running background")

    error_context.context("Unload the driver during random read", test.log.info)
    try:
        session.cmd(driver_unload_cmd)
    except aexpect.ShellTimeoutError:
        pass
    error_context.context("Check if there is call trace in guest", test.log.info)
    try:
        vm.verify_kernel_crash()
    finally:
        try:
            session.cmd("kill -9 %s" % pid)
            session.close()
        except Exception:
            pass
