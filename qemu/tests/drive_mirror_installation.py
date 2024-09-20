import random
import time

from virttest import utils_misc, utils_test

from qemu.tests import drive_mirror


def run(test, params, env):
    """
    drive_mirror_stress test:
    1). guest installation
    2). start mirror during guest installation
    3). after installation complete, reboot guest verfiy guest reboot correctly.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    args = (test, params, env)
    bg = utils_misc.InterruptedThread(
        utils_test.run_virt_sub_test, args, {"sub_type": "unattended_install"}
    )
    bg.start()
    utils_misc.wait_for(bg.is_alive, timeout=10)
    time.sleep(random.uniform(60, 200))
    tag = params["source_image"]
    mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
    mirror_test.trash_files.append(mirror_test.image_file)
    try:
        mirror_test.start()
        mirror_test.wait_for_steady()
        mirror_test.reopen()
        bg.join()
    finally:
        mirror_test.clean()
