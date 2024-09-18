from virttest import env_process, utils_disk
from virttest.tests import unattended_install

from provider.block_devices_plug import BlockDevicesPlug
from provider.storage_benchmark import generate_instance


def run(test, params, env):
    """
    Test hot plug and unplug NVMe device.

    Steps:
        1. Install guest with local filesystem.
        2. Hot plug NVMe device to guest.
        3. Check if the NVMe device exists in qemu side.
        4. Check if the NVMe has been successfully added to guest.
        5. Run fio in the hot plugged NVMe device in guest.
        6. Unplug the NVMe device.
        7. Check if the NVMe device still exists.
        8. Check if the NVMe has been successfully removed from guest.
        9. Reboot guest.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    unattended_install.run(test, params, env)

    if params.get("remove_options"):
        for option in params.get("remove_options").split():
            del params[option]
    params["cdroms"] = params.get("default_cdroms")

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    plug = BlockDevicesPlug(vm)
    plug.hotplug_devs_serial()
    target = "/dev/%s" % plug[0]
    os_type = params["os_type"]
    data_img_size = params.get("image_size_%s" % params.get("data_img_tag"))
    if os_type == "windows":
        utils_disk.update_windows_disk_attributes(session, plug[0])
        drive_letter = utils_disk.configure_empty_disk(
            session, plug[0], data_img_size, os_type
        )[0]
        target = r"%s\:\\%s" % (drive_letter, params.get("fio_filename"))
    fio = generate_instance(params, vm, "fio")
    for option in params["fio_options"].split(";"):
        fio.run("--filename=%s %s" % (target, option))
    plug.unplug_devs_serial()
    vm.reboot(session)
