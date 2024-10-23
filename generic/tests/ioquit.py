import random
import time

import six
from avocado.utils import process
from virttest import data_dir, error_context, qemu_storage, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Emulate the poweroff under IO workload(dd so far) with signal SIGKILL.

    1) Boot a VM
    2) Add IO workload for guest OS
    3) Sleep for a random time
    4) Kill the VM
    5) Check the image to verify if errors are found except some cluster leaks

    :param test: Kvm test object
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    session2 = vm.wait_for_login(timeout=login_timeout)

    bg_cmd = params.get("background_cmd")
    error_context.context("Add IO workload for guest OS.", test.log.info)
    session.cmd_output(bg_cmd, timeout=60)

    error_context.context("Verify the background process is running")
    check_cmd = params.get("check_cmd")
    session2.cmd(check_cmd, timeout=360)

    error_context.context("Sleep for a random time", test.log.info)
    time.sleep(random.randrange(15, 30))
    session2.cmd(check_cmd, timeout=360)

    error_context.context("Kill the VM", test.log.info)
    utils_misc.kill_process_tree(vm.process.get_pid(), timeout=60)
    time.sleep(3)
    error_context.context("Check img after kill VM", test.log.info)
    base_dir = data_dir.get_data_dir()
    image_name = params.get("image_name")
    image = qemu_storage.QemuImg(params, base_dir, image_name)
    try:
        image.check_image(params, base_dir)
    except Exception as exc:
        if "Leaked clusters" not in six.text_type(exc):
            raise
        error_context.context("Detected cluster leaks, try to repair it", test.log.info)
        restore_cmd = params.get("image_restore_cmd") % image.image_filename
        cmd_status = process.system(restore_cmd, shell=True)
        if cmd_status:
            test.fail("Failed to repair cluster leaks on the image")
