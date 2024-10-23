import json

from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Commit with explicit backing file specification.

    1. create snapshot chain as image1->sn1->sn2
    2. commit sn2 to base
    3. check to see that sn2 is not emptied and the temp file in corresponding
    snapshot remains intact.
    """

    def prepare_images_from_params(images, params):
        """Parse params to initialize a QImage list."""
        return [
            qemu_storage.QemuImg(params.object_params(tag), root_dir, tag)
            for tag in images
        ]

    def verify_backing_chain(info):
        """Verify image's backing chain."""
        for image, img_info in zip(images, reversed(info)):
            base_image = None
            if image.base_tag:
                base_params = params.object_params(image.base_tag)
                base_image = qemu_storage.get_image_repr(
                    image.base_tag, base_params, root_dir
                )
            base_image_from_info = img_info.get("full-backing-filename")
            if base_image != base_image_from_info:
                test.fail(
                    (
                        "backing chain check for image %s failed, backing"
                        " file from info is %s, which should be %s."
                    )
                    % (image.image_filename, base_image_from_info, base_image)
                )

    images = params.get("image_chain", "").split()
    if len(images) < 3:
        test.cancel("Snapshot chain must at least contains three images")
    params["image_name_%s" % images[0]] = params["image_name"]
    params["image_format_%s" % images[0]] = params["image_format"]
    root_dir = data_dir.get_data_dir()
    images = prepare_images_from_params(images, params)
    base, active_layer = images[0], images[-1]

    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")
    hashes = {}
    for image in images:
        if image is not base:
            test.log.debug(
                "Create snapshot %s based on %s",
                image.image_filename,
                image.base_image_filename,
            )
            image.create(image.params)
        vm = img_utils.boot_vm_with_images(test, params, env, (image.tag,))
        guest_file = params["guest_tmp_filename"] % image.tag
        test.log.debug(
            "Create tmp file %s in image %s", guest_file, image.image_filename
        )
        img_utils.save_random_file_to_vm(vm, guest_file, 2048 * 100, sync_bin)

        session = vm.wait_for_login()
        test.log.debug("Get md5 value fo the temporary file")
        hashes[guest_file] = img_utils.check_md5sum(guest_file, md5sum_bin, session)
        session.close()
        vm.destroy()

    test.log.debug("Hashes of temporary files:\n%s", hashes)

    test.log.debug("Verify the snapshot chain")
    info = json.loads(active_layer.info(output="json"))
    active_layer_size_before = info[0]["actual-size"]
    verify_backing_chain(info)

    test.log.debug("Commit image")
    active_layer.commit(base=base.tag)

    test.log.debug("Verify the snapshot chain after commit")
    info = json.loads(active_layer.info(output="json"))
    active_layer_size_after = info[0]["actual-size"]
    test.log.debug(
        "%s file size before commit: %s, after commit: %s",
        active_layer.image_filename,
        active_layer_size_before,
        active_layer_size_after,
    )
    if active_layer_size_after < active_layer_size_before:
        test.fail(
            "image %s is emptied after commit with explicit base"
            % active_layer.image_filename
        )
    verify_backing_chain(info)

    test.log.debug("Verify hashes of temporary files")
    vm = img_utils.boot_vm_with_images(test, params, env, (base.tag,))
    session = vm.wait_for_login()
    for tmpfile, hashval in hashes.items():
        img_utils.check_md5sum(tmpfile, md5sum_bin, session, md5_value_to_check=hashval)

    for image in images:
        if image is not base:
            image.remove()
