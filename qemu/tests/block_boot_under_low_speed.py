"""QEMU Low Speed Booting Test"""

import os
import shutil
import threading
import time

from avocado.utils import process
from virttest import data_dir, env_process, error_context, nfs, storage


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU Low Speed Booting Test

    1) Setup NFS ENV,put image file under the nfs mount folder.
    2) Limit nfs access speed.
    3) Boot vm.
    4) Check vm boot succeed

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _limit_daemon():
        deps_dir = data_dir.get_deps_dir()
        host_file = os.path.join(deps_dir, params["host_script"])
        logger.info("Start speed limit %s", host_file)
        process.system_output(host_file, shell=True)
        logger.info("Finished speed limit.")

    def _setup_env():
        nfs_local.setup()
        org_img = storage.get_image_filename(params, data_dir.DATA_DIR)
        logger.info(org_img)
        file_name = os.path.basename(org_img)
        if not os.path.exists(params["export_dir"] + "/" + file_name):
            logger.info("Copy file %s %s", org_img, params["export_dir"])
            shutil.copy(org_img, params["export_dir"])
        params["image_name"] = (
            params["nfs_mount_dir"] + "/" + os.path.splitext(file_name)[0]
        )

    logger = test.log
    nfs_local = nfs.Nfs(params)
    vm = None
    try:
        _setup_env()
        logger.info("Start limit speed")
        thread = threading.Thread(target=_limit_daemon)
        thread.start()
        time.sleep(2)
        logger.info("Booting vm...%s", params["image_name"])
        params["start_vm"] = "yes"
        vm = env.get_vm(params["main_vm"])
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
        timeout = int(params.get("login_timeout", 360))
        vm.wait_for_login(timeout=timeout)
    finally:
        if vm.is_alive():
            vm.destroy()
        if nfs_local:
            nfs_local.cleanup()
