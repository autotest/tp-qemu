import json

from avocado import fail_on
from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Rebase a second qcow2 snapshot to a raw base file.

    1. create a qcow2 snapshot base -> sn1
    2. boot the guest from the sn1
    3. create a file in the snapshot disk,  calculate its md5sum
    4. shut the guest down
    5. create a qcow2 snapshot sn1 -> sn2
    6. rebase the sn2 to the base
    7. remove the sn1, optional
    8. boot the guest from the sn2 and check whether the
       file's md5sum stays same

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def get_img_objs(images, params):
        return [
            qemu_storage.QemuImg(params.object_params(tag), root_dir, tag)
            for tag in images
        ]

    @fail_on((AssertionError,))
    def verify_qemu_img_info_backing_chain(output):
        """Verify qemu-img info output for this case."""

        def _get_compat_version():
            """Get compat version from params."""
            return params.get("qcow2_compatible", "1.1")

        test.log.info("Verify snapshot's backing file information.")
        for image, img_info in zip(images, reversed(output)):
            # skip base layer
            if not image.base_tag:
                continue
            base_params = params.object_params(image.base_tag)
            base_image = qemu_storage.get_image_repr(
                image.base_tag, base_params, root_dir
            )
            base_format = image.base_format
            compat = _get_compat_version()
            base_image_info = img_info.get("backing-filename")
            assert base_image == base_image_info, "backing image mismatches"
            if base_image_info and not base_image_info.startswith("json"):
                base_format_info = img_info.get("backing-filename-format")
                assert base_format == base_format_info, "backing format mismatches"
            compat_info = img_info["format-specific"]["data"]["compat"]
            assert compat == compat_info, "compat mode mismatches"

    timeout = int(params.get("timeout", 240))
    images = params["image_chain"].split()
    params["image_name_%s" % images[0]] = params["image_name"]
    params["image_format_%s" % images[0]] = params["image_format"]
    root_dir = data_dir.get_data_dir()
    images = get_img_objs(images, params)
    base, active_layer = images[0], images[-1]

    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")
    for image in images[1:]:
        test.log.debug(
            "Create snapshot %s based on %s",
            image.image_filename,
            image.base_image_filename,
        )
        image.create(image.params)
        info_output = json.loads(image.info(output="json"))
        verify_qemu_img_info_backing_chain(info_output)

    hashes = {}
    rebase_mode = params.get("rebase_mode", "safe")
    for image in images:
        # do not create temp file in intermediate images in unsafe rebase
        if rebase_mode == "safe" or image in (base, active_layer):
            vm = img_utils.boot_vm_with_images(test, params, env, (image.tag,))
            guest_file = params["guest_tmp_filename"] % image.tag
            test.log.debug(
                "Create tmp file %s in image %s", guest_file, image.image_filename
            )
            img_utils.save_random_file_to_vm(vm, guest_file, 2048 * 100, sync_bin)
            session = vm.wait_for_login(timeout=timeout)
            test.log.debug("Get md5 value fo the temporary file")
            hashes[guest_file] = img_utils.check_md5sum(guest_file, md5sum_bin, session)
            session.close()
            vm.destroy()

    # remove intermediate images before unsafe rebase
    if rebase_mode == "unsafe":
        for image in images:
            if image not in (base, active_layer):
                test.log.debug(
                    "Remove the snapshot %s before rebase.", image.image_filename
                )
                image.remove()

    cache_mode = params.get("cache_mode")
    msg = "Rebase the snapshot %s to %s"
    msg += "with cache %s." % cache_mode if cache_mode else "."
    test.log.info(msg)
    active_layer.base_tag = base.tag
    active_layer.rebase(active_layer.params, cache_mode)
    info_output = json.loads(active_layer.info(output="json"))
    verify_qemu_img_info_backing_chain(info_output)

    vm = img_utils.boot_vm_with_images(test, params, env, (active_layer.tag,))
    session = vm.wait_for_login(timeout=timeout)
    for guest_file, hash_val in hashes.items():
        img_utils.check_md5sum(
            guest_file, md5sum_bin, session, md5_value_to_check=hash_val
        )
    session.close()
    vm.destroy()
    for image in images:
        if image is not base:
            image.remove()
