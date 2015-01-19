import logging
import time
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest import qemu_storage, data_dir
from qemu.tests import drive_mirror


@error.context_aware
def run(test, params, env):
    """
    1) Synchronize disk and then do continuous backup

    "qemu-img compare" is used to verify disk is mirrored successfully.
    """
    tag = params.get("source_images", "image1")
    qemu_img = qemu_storage.QemuImg(params, data_dir.get_data_dir(), tag)
    mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
    tmp_dir = params.get("tmp_dir", "c:\\")
    clean_cmd = params.get("clean_cmd", "del /f /s /q tmp*.file")
    dd_cmd = "dd if=/dev/zero bs=1024 count=1024 of=tmp%s.file"
    dd_cmd = params.get("dd_cmd", dd_cmd)
    try:
        source_image = mirror_test.get_image_file()
        target_image = mirror_test.get_target_image()
        error.context("start mirror block device", logging.info)
        mirror_test.start()
        error.context("Wait mirror job in steady status", logging.info)
        mirror_test.wait_for_steady()
        error.context("Testing continuous backup", logging.info)
        session = mirror_test.get_session()
        error.context("Continuous create file in guest", logging.info)
        session.cmd("cd %s" % tmp_dir)
        for fn in range(0, 128):
            session.cmd(dd_cmd % fn)
        error.context("pause vm and sync host cache", logging.info)
        time.sleep(3)
        mirror_test.vm.pause()
        utils.system("sync")
        time.sleep(3)
        error.context("Compare original and backup images", logging.info)
        qemu_img.compare_images(source_image, target_image)
        mirror_test.vm.resume()
        session = mirror_test.get_session()
        session.cmd("cd %s" % tmp_dir)
        session.cmd(clean_cmd)
        mirror_test.vm.destroy()
    finally:
        mirror_test.clean()
