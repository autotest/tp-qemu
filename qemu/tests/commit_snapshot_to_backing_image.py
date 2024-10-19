import json

from avocado.utils import process
from virttest import data_dir, error_context, qemu_storage

from provider import qemu_img_utils as img_utils


@error_context.context_aware
def run(test, params, env):
    """
    qemu-img commit test.
    1. create images image1->sn
    2. boot from sn and create temporary files.
    3. calculate MD5 value of the temp file.
    4. commit sn.
    5. check snapshot is emptied.
    6. boot from image1 and check the existence of the temp file and its md5
    value.
    """
    # add missing params for image1
    images = params["images"].split()
    params["image_name_%s" % images[0]] = params["image_name"]
    params["image_format_%s" % images[0]] = params["image_format"]

    root_dir = data_dir.get_data_dir()
    image_chain = params["image_chain"].split()
    base, sn = (
        qemu_storage.QemuImg(params.object_params(tag), root_dir, tag)
        for tag in image_chain
    )

    error_context.context("create snapshot %s" % sn.tag, test.log.info)
    sn.create(sn.params)

    error_context.context("boot vm from snapshot %s" % sn.tag, test.log.info)
    vm = img_utils.boot_vm_with_images(test, params, env, (sn.tag,))

    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")
    guest_file = params["guest_tmp_filename"]
    dd_blkcnt = int(params["dd_blkcnt"])
    error_context.context("save random file %s" % guest_file, test.log.info)
    img_utils.save_random_file_to_vm(vm, guest_file, dd_blkcnt, sync_bin)
    session = vm.wait_for_login()
    md5val = img_utils.check_md5sum(guest_file, md5sum_bin, session)
    test.log.debug("random file %s md5sum value: %s", guest_file, md5val)
    session.close()
    vm.destroy()

    error_context.context("commit snapshot %s" % sn.tag, test.log.info)
    size_before_commit = json.loads(sn.info(output="json"))["actual-size"]
    test.log.debug("%s size before commit: %s", sn.tag, size_before_commit)
    cache_mode = params.get("cache_mode")
    sn.commit(cache_mode=cache_mode)
    test.log.debug("sync host cache after commit")
    process.system("sync")

    error_context.context("verify snapshot is emptied after commit", test.log.info)
    size_after_commit = json.loads(sn.info(output="json"))["actual-size"]
    test.log.debug("%s size after commit: %s", sn.tag, size_after_commit)
    guest_file_size = dd_blkcnt * 512  # tmp file size in bytes
    if size_before_commit - size_after_commit >= guest_file_size:
        test.log.debug("the snapshot file was emptied.")
    else:
        test.fail("snapshot was not emptied")

    error_context.context("boot vm from base %s" % base.tag, test.log.info)
    vm = img_utils.boot_vm_with_images(test, params, env, (base.tag,))
    session = vm.wait_for_login()
    img_utils.check_md5sum(guest_file, md5sum_bin, session, md5_value_to_check=md5val)
    vm.destroy()
    # remove snapshot
    params["remove_image_%s" % sn.tag] = "yes"
