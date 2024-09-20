import json

from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Change the backing file from luks/raw to qcow2.
    1) create snapshot image1 -> sn1
    2) boot from each images in the snapshot chain and create tmp files
    3) create a new base qcow2 image
    4) rebase to the new base qcow2 image
    5) check if the tmp files create in step 2) persist
    """

    def verify_backing_file(image):
        """Verify image backing file."""
        info_output = json.loads(image.info(output="json"))
        backing_params = image.params.object_params(image.base_tag)
        backing_file = qemu_storage.get_image_repr(
            image.base_tag, backing_params, root_dir
        )
        backing_file_info = info_output["backing-filename"]
        if backing_file != backing_file_info:
            err_msg = "backing file mismatch, got %s, expected %s." % (
                backing_file_info,
                backing_file,
            )
            raise ValueError(err_msg)

    timeout = int(params.get("timeout", 360))
    root_dir = data_dir.get_data_dir()
    images = params["image_chain"].split()
    params["image_name_%s" % images[0]] = params["image_name"]
    params["image_format_%s" % images[0]] = params["image_format"]
    images = [
        qemu_storage.QemuImg(params.object_params(tag), root_dir, tag) for tag in images
    ]

    for image in images[1:]:
        test.log.debug(
            "create snapshot %s based on %s",
            image.image_filename,
            image.base_image_filename,
        )
        image.create(image.params)

    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")
    hashes = {}
    for image in images:
        vm = img_utils.boot_vm_with_images(test, params, env, (image.tag,))
        guest_file = params["guest_tmp_filename"] % image.tag
        test.log.debug("save tmp file %s in image %s", guest_file, image.image_filename)
        img_utils.save_random_file_to_vm(vm, guest_file, 2048 * 100, sync_bin)
        session = vm.wait_for_login(timeout=timeout)
        hashes[guest_file] = img_utils.check_md5sum(guest_file, md5sum_bin, session)
        session.close()
        vm.destroy()

    snapshot = images[-1]
    rebase_target = params["rebase_target"]
    # ensure size equals to the base
    params["image_size_%s" % rebase_target] = images[0].size
    rebase_target = qemu_storage.QemuImg(
        params.object_params(rebase_target), root_dir, rebase_target
    )
    rebase_target.create(rebase_target.params)
    test.log.debug("rebase snapshot")
    snapshot.base_tag = rebase_target.tag
    fail_on((process.CmdError,))(snapshot.rebase)(snapshot.params)
    fail_on((ValueError,))(verify_backing_file)(snapshot)

    test.log.debug("boot from snapshot %s", snapshot.image_filename)
    vm = img_utils.boot_vm_with_images(test, params, env, (snapshot.tag,))
    session = vm.wait_for_login(timeout=timeout)
    for guest_file, hashval in hashes.items():
        img_utils.check_md5sum(
            guest_file, md5sum_bin, session, md5_value_to_check=hashval
        )
    session.close()
    vm.destroy()

    # if nothing goes wrong, remove newly created images
    params["remove_image_%s" % snapshot.tag] = "yes"
    params["images"] += " %s" % rebase_target.tag
