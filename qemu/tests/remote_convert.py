from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage, storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Convert remote image.

    1) Start VM and create a tmp file, record its md5sum, shutdown VM
    2) Convert image
    3) Start VM by the converted image and then check the md5sum
    """

    def _check_file(boot_image, md5_value):
        test.log.debug("Check md5sum.")
        vm = img_utils.boot_vm_with_images(test, params, env, (boot_image,))
        session = vm.wait_for_login()
        guest_temp_file = params["guest_temp_file"]
        md5sum_bin = params.get("md5sum_bin", "md5sum")
        img_utils.check_md5sum(
            guest_temp_file, md5sum_bin, session, md5_value_to_check=md5_value
        )
        session.close()
        vm.destroy()

    vm = img_utils.boot_vm_with_images(test, params, env)
    session = vm.wait_for_login()
    guest_temp_file = params["guest_temp_file"]
    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")

    test.log.info("Create temporary file on guest: %s", guest_temp_file)
    img_utils.save_random_file_to_vm(vm, guest_temp_file, 2048 * 512, sync_bin)

    md5_value = img_utils.check_md5sum(guest_temp_file, md5sum_bin, session)
    test.log.info("Get md5 value of the temporary file: %s", md5_value)

    session.close()
    vm.destroy()

    root_dir = data_dir.get_data_dir()

    # Make a list of all source and target image pairs
    img_pairs = [(params["convert_source"], params["convert_target"])]
    if params.get("convert_target_remote"):
        # local -> remote
        img_pairs.append((params["convert_target"], params["convert_target_remote"]))

    # Convert images
    for source, target in img_pairs:
        params["convert_source"] = source
        params["convert_target"] = target

        source_params = params.object_params(source)
        target_params = params.object_params(target)

        source_image = qemu_storage.QemuImg(source_params, root_dir, source)
        target_image = qemu_storage.QemuImg(target_params, root_dir, target)

        # remove the target
        target_filename = storage.get_image_filename(target_params, root_dir)
        storage.file_remove(target_params, target_filename)

        # skip nbd image creation
        skip_target_creation = target_params.get_boolean("skip_target_creation")

        # Convert source to target
        cache_mode = params.get("cache_mode")
        source_cache_mode = params.get("source_cache_mode")
        test.log.info("Convert %s to %s", source, target)
        fail_on((process.CmdError,))(source_image.convert)(
            params,
            root_dir,
            cache_mode=cache_mode,
            source_cache_mode=source_cache_mode,
            skip_target_creation=skip_target_creation,
        )

        _check_file(target, md5_value)

    # Remove images converted
    for _, target in img_pairs:
        target_params = params.object_params(target)
        target_image = qemu_storage.QemuImg(target_params, root_dir, target)
        target_image.remove()
