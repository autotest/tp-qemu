from avocado.utils import process
from virttest import data_dir, utils_misc
from virttest.env_process import preprocess_vm
from virttest.iscsi import Iscsi
from virttest.lvm import LVM
from virttest.tests import unattended_install


def run(test, params, env):
    """
    Test to install the guest OS on the lvm device which is created
    on an iSCSI target.
    Steps:
        1) Setup iSCSI initiator on local host.
        2) Discovery and login the above iSCSI target.
        3) Create a partition on the iSCSI target.
        4) Create a lvm on the partition.
        5) Install a guest from ISO with the logical volume.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    params["image_size"] = params["emulated_image_size"]
    post_commands = []
    try:
        iscsi = Iscsi.create_iSCSI(params, data_dir.get_data_dir())
        post_commands.extend(
            (params["post_commands_iscsi"] % (iscsi.emulated_image, iscsi.id)).split(
                ","
            )
        )
        lvm = LVM(params)
        iscsi.login()
        dev_name = utils_misc.wait_for(lambda: iscsi.get_device_name(), 60)
        if not dev_name:
            test.error("Can not get the iSCSI device.")
        process.run(params["cmd_fdisk"] % dev_name, 600, shell=True)
        params["pv_name"] = (
            process.system_output(
                params["cmd_get_partition"].format(dev_name), 60, shell=True
            )
            .decode()
            .strip()
        )
        post_commands.extend(
            (params["post_commands_lvm"] % params["pv_name"]).split(",")
        )
        lvm.setup()
        preprocess_vm(test, params, env, params["main_vm"])
        unattended_install.run(test, params, env)
    finally:
        params["post_command"] = " ; ".join(post_commands[::-1])
