import os
import time

from virttest import error_context, utils_misc
from virttest.staging import utils_memory


@error_context.context_aware
def run(test, params, env):
    """
    KVM restore from file-test:
    1) Pause VM
    2) Save VM to file
    3) Restore VM from file, and measure the time it takes
    4) Remove VM restoration file
    5) Check VM

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    expect_time = int(params.get("expect_restore_time", 25))
    session = vm.wait_for_login(timeout=timeout)

    save_file = params.get(
        "save_file", os.path.join("/tmp", utils_misc.generate_random_string(8))
    )

    try:
        error_context.context("Pause VM", test.log.info)
        vm.pause()

        error_context.context("Save VM to file", test.log.info)
        vm.save_to_file(save_file)

        error_context.context("Restore VM from file", test.log.info)
        time.sleep(10)
        utils_memory.drop_caches()
        vm.restore_from_file(save_file)
        vm.resume()
        session = vm.wait_for_login(timeout=timeout)
        restore_time = utils_misc.monotonic_time() - vm.start_monotonic_time
        test.write_test_keyval({"result": "%ss" % restore_time})
        test.log.info("Restore time: %ss", restore_time)

    finally:
        try:
            error_context.context("Remove VM restoration file", test.log.info)
            os.remove(save_file)

            error_context.context("Check VM", test.log.info)
            vm.verify_alive()
            vm.wait_for_login(timeout=timeout)
        except Exception:
            test.log.warning("Unable to restore VM, restoring from image")
            params["restore_image_after_testing"] = "yes"

    if restore_time > expect_time:
        test.fail("Guest restoration took too long: %ss" % restore_time)

    session.close()
