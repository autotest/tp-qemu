import re
import logging

from avocado.utils import process

from virttest import funcatexit
from virttest import error_context
from virttest import qemu_storage
from virttest import data_dir

from qemu.tests import drive_mirror


def clean_trash_files(trash_files):
    """
    Clean the files created in the test, it will be
    executed after the test finish.
    :param trash_files: the file list need to be clean
    """
    while trash_files:
        clean_cmd = "rm -f %s" % trash_files.pop()
        process.system(clean_cmd, ignore_status=True)


@error_context.context_aware
def run(test, params, env):
    """
    Test block mirroring to different cluster size image.

    1). create target image with different cluster size
    2). boot vm, then mirror $source_image to $target_image
    2). wait for mirroring job go into ready status
    3). pause vm after vm in ready status
    4). reopen $target_image file
    5). compare $source image and $target_image file
    6). resume vm
    7). create target2 with default cluster size
    8). mirror again to target2
    9). Verify the cluster_size of target image correct
    """

    trash_files = []

    def block_mirror(tag):
        """
        A block mirror process, including cluster_size verification.
        It will be execute twice with different source and target.
        :param tag: tag pass to DriveMirror object, source image
        """
        qemu_img = qemu_storage.QemuImg(
            params, data_dir.get_data_dir(), tag)
        mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
        source_image = mirror_test.get_image_file()
        target_image = mirror_test.get_target_image()
        mirror_test.create_files()
        mirror_test.start()
        mirror_test.action_when_steady()
        mirror_test.vm.pause()
        mirror_test.reopen()
        device_id = mirror_test.vm.get_block({"file": target_image})
        if device_id != mirror_test.device:
            test.error("Mirrored image not being used by guest")
            error_context.context("Compare fully mirrored images",
                                  logging.info)
        qemu_img.compare_images(source_image, target_image, force_share=True)
        mirror_test.vm.resume()
        mirror_test.verify_md5s()
        check_cluster_size(params["target_image_%s" % tag])
        while mirror_test.opening_sessions:
            session = mirror_test.opening_sessions.pop()
            if session:
                session.close()
        trash_files.extend(mirror_test.trash_files)

    def check_cluster_size(image):
        """
        Verify the cluster size of the image
        :param image: the image object need to be verified
        """
        image_params = params.object_params(image)
        image_name = image_params["image_name"]
        expected_size = image_params.get("image_cluster_size")
        qemu_img = qemu_storage.QemuImg(
            image_params, data_dir.get_data_dir(), image_name)
        info = qemu_img.info(force_share=True)
        matched = re.search(r"cluster_size: +(.*)", info, re.M)
        actual_size = matched.group(1)
        if expected_size != actual_size:
            msg = "The cluster size of image %s changed from %s to %s" % (
                image_name, expected_size, actual_size)
            test.fail(msg)

    funcatexit.register(env, params.get("type"), clean_trash_files, trash_files)
    source_image = params.get("source_image", "image1")
    block_mirror(source_image)
    # Iterate source and target, and mirror again with updated params
    source_image = params["target_image_%s" % source_image]
    params["source_image"] = source_image
    target_name = "target2"
    params["target_image_%s" % source_image] = target_name
    target_params = params.object_params(source_image)
    params["image_name_%s" % target_name] = "images/%s" % target_name
    params["image_format_%s" % target_name] = target_params["image_format"]
    params["image_cluster_size_%s" % target_name] = "65536"
    block_mirror(source_image)
