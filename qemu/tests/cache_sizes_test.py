from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Cache sizes test for a guest.

    1. Boot a guest up with different cache sizes.
    2. Check writing data to the guest works fine.
    3. Shut the guest down.

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    file = params["guest_file_name"]
    initial_tag = params["images"]
    cache_sizes = params["cache_sizes"].split()

    test.log.info(
        "Boot a guest up from initial image: %s, and create a" " file %s on the disk.",
        initial_tag,
        file,
    )
    for cache_size in cache_sizes:
        params["drv_extra_params_image1"] = "cache-size=%s" % cache_size
        vm = img_utils.boot_vm_with_images(test, params, env)
        session = vm.wait_for_login()
        guest_temp_file = params["guest_file_name"]
        sync_bin = params.get("sync_bin", "sync")

        test.log.debug("Create temporary file on guest: %s", guest_temp_file)
        img_utils.save_random_file_to_vm(vm, guest_temp_file, 2048 * 512, sync_bin)

        session.close()
        vm.destroy()
