import json

from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Rebase a qcow2 snapshot onto no backing file.

    1. create an external qcow2v2/qcow2v3 snapshot
       based on a raw image
    2. boot the guest from the base
    3. create a file in the base disk, calculate its md5sum
    4. shut the guest down
    5. rebase the snapshot onto no backing file
    6. check the snapshot
    7. boot the guest from the snapshot and check whether the
    file's md5sum stays same

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def _verify_image_backing_file(info_output, base):
        """Verify backing image filename and format."""
        backing_filename = info_output["backing-filename"]
        backing_format = info_output.get("backing-filename-format")
        backing_filename_desired = qemu_storage.get_image_repr(
            base.tag, params, root_dir
        )
        if backing_filename != backing_filename_desired:
            test.fail(
                "backing image name mismatch, got %s, expect %s"
                % (backing_filename, backing_filename_desired)
            )
        if backing_format:
            backing_format_desired = base.image_format
            if backing_format != backing_format_desired:
                test.fail(
                    "backing image format mismatch, got %s, expect %s"
                    % (backing_format, backing_format_desired)
                )

    def _verify_qcow2_compatible(info_output, image):
        """Verify qcow2 compat version."""
        compat = info_output["format-specific"]["data"]["compat"]
        compat_desired = image.params.get("qcow2_compatible", "1.1")
        if compat != compat_desired:
            test.fail(
                "%s image compat version mismatch, got %s, expect %s"
                % (image.tag, compat, compat_desired)
            )

    def _verify_no_backing_file(info_output):
        """Verify snapshot has no backing file for this case."""
        test.log.info("Verify snapshot has no backing file after rebase.")
        for key in info_output:
            if "backing" in key:
                test.fail("the snapshot has backing file after rebase.")

    images = params["image_chain"].split()
    params["image_name_%s" % images[0]] = params["image_name"]
    params["image_format_%s" % images[0]] = params["image_format"]
    root_dir = data_dir.get_data_dir()
    base, sn = (
        qemu_storage.QemuImg(params.object_params(tag), root_dir, tag) for tag in images
    )

    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")

    test.log.info("boot guest from base image %s", base.image_filename)
    vm = img_utils.boot_vm_with_images(test, params, env, (base.tag,))

    guest_file = params["guest_tmp_filename"]
    test.log.info("save tmp file %s in guest", guest_file)
    img_utils.save_random_file_to_vm(vm, guest_file, 2048 * 100, sync_bin)

    test.log.info("get md5 value of tmp file %s", guest_file)
    session = vm.wait_for_login()
    hashval = img_utils.check_md5sum(guest_file, md5sum_bin, session)
    test.log.info("tmp file %s md5: %s", guest_file, hashval)
    session.close()
    vm.destroy()

    test.log.info("create a snapshot %s based on %s", sn.tag, base.tag)
    sn.create(sn.params)

    test.log.info("verify backing chain")
    info_output = json.loads(sn.info(output="json"))
    _verify_image_backing_file(info_output, base)

    test.log.info("verify snapshot %s qcow2 compat version", sn.tag)
    _verify_qcow2_compatible(info_output, sn)

    test.log.info("rebase snapshot %s to none", sn.tag)
    sn.base_tag = "null"
    fail_on((process.CmdError,))(sn.rebase)(sn.params)

    test.log.info("verify backing chain after rebase")
    info_output = json.loads(sn.info(output="json"))
    _verify_no_backing_file(info_output)

    test.log.info("check image %s after rebase", sn.tag)
    sn.check_image(sn.params, root_dir)

    test.log.info("boot guest from snapshot %s", sn.tag)
    vm = img_utils.boot_vm_with_images(test, params, env, (sn.tag,))

    test.log.info("check the md5 value of tmp file %s after rebase", guest_file)
    session = vm.wait_for_login()
    img_utils.check_md5sum(guest_file, md5sum_bin, session, md5_value_to_check=hashval)
    session.close()
    vm.destroy()

    # if nothing goes wrong, remove snapshot
    params["remove_image_%s" % sn.tag] = "yes"
