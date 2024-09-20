import random
import time

from virttest import utils_misc, utils_test

from qemu.tests import blk_stream


def run(test, params, env):
    """
    block_stream_installation test:
    1). guest installation
    2). live snapshot during guest installation
    3). block stream afterwards
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
    stream_test = blk_stream.BlockStream(test, params, env, tag)
    stream_test.trash_files.append(stream_test.image_file)
    try:
        stream_test.create_snapshots()
        stream_test.start()
        stream_test.wait_for_finished()
        bg.join()
    finally:
        stream_test.clean()
