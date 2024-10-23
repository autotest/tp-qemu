from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    qemu-img create a snapshot on a running base image.

    1. boot a guest up from a base image
    2. create a file on the base image disk, calculate its md5sum
    3. create a snapshot on the running base image
    4. shut the guest down and boot a guest from the snapshot
    5. check whether the file's md5sum stays same

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def generate_images_from_image_chain(image_chain):
        root_dir = data_dir.get_data_dir()
        return [
            qemu_storage.QemuImg(params.object_params(image), root_dir, image)
            for image in image_chain.split()
        ]

    params["image_name_image1"] = params["image_name"]
    params["image_format_image1"] = params["image_format"]

    images = generate_images_from_image_chain(params["image_chain"])
    base, snapshot = images[0], images[1]
    guest_temp_file = params["guest_temp_file"]
    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")

    test.log.info(
        "Boot a guest up from base image: %s, and create a" " file %s on the disk.",
        base.tag,
        guest_temp_file,
    )
    vm = img_utils.boot_vm_with_images(test, params, env)
    session = vm.wait_for_login()
    img_utils.save_random_file_to_vm(vm, guest_temp_file, 1024 * 512, sync_bin)
    md5_value = img_utils.check_md5sum(guest_temp_file, md5sum_bin, session)
    session.close()

    test.log.info("Create a snapshot %s on the running base image.", snapshot.tag)
    snapshot.create(snapshot.params)

    vm.destroy()
    test.log.info(
        "Boot the guest up from snapshot image: %s, and verify the"
        " file %s's md5 on the disk.",
        snapshot.tag,
        guest_temp_file,
    )
    vm = img_utils.boot_vm_with_images(test, params, env, images=(snapshot.tag,))
    session = vm.wait_for_login()
    img_utils.check_md5sum(
        guest_temp_file, md5sum_bin, session, md5_value_to_check=md5_value
    )
    session.close()
    vm.destroy()
