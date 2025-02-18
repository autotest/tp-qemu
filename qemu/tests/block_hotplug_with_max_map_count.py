from avocado.utils import process
from virttest import env_process


def run(test, params, env):
    """
    Block hotplug with vm.max_map_count test
    1) Boot the VM with a small max_map_count
    2) Login and hotplug 15 block devices
    3) Check the VM status and set max_map_count original value

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    try:
        orig_value = int(
            process.system_output("sysctl -n vm.max_map_count", shell=True)
        )
        max_map_value = params.get_numeric("max_map_value", 3072)
        test.log.info("Setting max_map_count to 3072")
        process.system(f"sysctl vm.max_map_count={max_map_value}", shell=True)

        extra_image_number = params.get_numeric("extra_image_number", 15)
        timeout = params.get_numeric("login_timeout", 240)

        for img_number in range(extra_image_number):
            img = f"stg{img_number}"
            params[f"boot_drive_{img}"] = "no"
            params[f"image_name_{img}"] = f"images/{img}"
            params[f"image_size_{img}"] = "1G"
            params[f"remove_image_{img}"] = "yes"
            params[f"force_create_image_{img}"] = "yes"
            params[f"blk_extra_params_{img}"] = f"serial={img}"
            image_params = params.object_params(img)
            env_process.preprocess_image(test, image_params, img)

        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)

        for img_number in range(extra_image_number):
            img = f"stg{img_number}"
            image_params = params.object_params(img)
            devs = vm.devices.images_define_by_params(img, image_params, "disk")
            for dev in devs:
                vm.devices.simple_hotplug(dev, vm.monitor)
        if "running" not in vm.monitor.get_status():
            test.fail(f"VM is not running!, status: {vm.monitor.get_status()}")
        session.close()

    finally:
        test.log.info("Restoring max_map_count original value")
        process.system(f"sysctl vm.max_map_count={orig_value}", shell=True)
