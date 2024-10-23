from avocado.utils import process
from virttest import env_process
from virttest.lvm import LVM


def run(test, params, env):
    """
    Boot guest after disable ept/npt:
    1) Create lvm with read-only permission
    2) Boot up guest with lvm
    3) Unplug the disk
    4) Hotplug blockdev node with auto-read-only

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    params["start_vm"] = "yes"
    params["pv_name"] = process.getoutput(params["get_devname_command"])
    lvm = LVM(params)
    lvm.setup()
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.wait_for_login()
    qmp_port = vm.monitor
    qdev = vm.devices
    device = qdev.get_by_params({"id": "stg0"})[0]
    qdev.simple_unplug(device, qmp_port)
    image_name = params["data_tag"]
    image_params = params.object_params(image_name)
    devs = qdev.images_define_by_params(image_name, image_params, "disk")
    for dev in devs:
        qdev.simple_hotplug(dev, qmp_port)
