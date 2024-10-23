from avocado.utils import process
from virttest import data_dir, env_process, utils_misc
from virttest.iscsi import Iscsi
from virttest.utils_disk import get_linux_disks


def run(test, params, env):
    """
    Test to install the guest OS on the lvm device which is created
    on an iSCSI target.
    Steps:
        1) Setup iSCSI initiator on local host.
        2) Discovery and login the above iSCSI target.
        3) Send sg_inq to get information on the host.
        4) Boot guest with this lun as a block device as the second
           disk, with scsi=on,format=raw,werror=stop,rerror=stop.
        5) In the guest, sg_inq should show similar information in
           step 3.
        6) Logout iscsi server.
        7) Check the disk info with sg_inq inside guest, should show
           fail information.
        8) Run dd on this disk, the guest should stop.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def fetch_sg_info(device, session=None):
        cmd = params["cmd_sg_inq"] % device
        if session:
            return session.cmd_output(cmd)
        return process.getoutput(cmd, 60, ignore_status=False)

    iscsi = Iscsi.create_iSCSI(params, data_dir.get_data_dir())
    try:
        iscsi.login()
        if not utils_misc.wait_for(lambda: iscsi.get_device_name(), 60):
            test.error("Can not get the iSCSI device.")

        cmd_get_disk_path = params["cmd_get_disk_path"]
        disk_path = process.system_output(cmd_get_disk_path, 60, shell=True).decode()

        host_sg_info = fetch_sg_info(disk_path)
        test.log.info("The scsi generic info from host: %s", host_sg_info)

        image_data_tag = params["image_data_tag"]
        params["image_name_%s" % image_data_tag] = disk_path
        params["image_size"] = params["emulated_image_size"]
        image_params = params.object_params(image_data_tag)
        env_process.preprocess_image(test, image_params, image_data_tag)

        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login()

        data_disk = "/dev/" + list(get_linux_disks(session).keys()).pop()
        guest_sg_info = fetch_sg_info(data_disk, session)
        test.log.info("The scsi generic info from guest: %s", guest_sg_info)

        for info in guest_sg_info.split():
            if info not in host_sg_info:
                test.fail("The guest scsi generic info is not similar to host.")

        iscsi.logout()
        if params["sg_fail_info"] not in fetch_sg_info(data_disk, session):
            test.fail("No found the fail information after logout iscsi server.")

        session.cmd_output(params["cmd_dd"] % data_disk)
        vm_status_paused = params["vm_status_paused"]
        if not utils_misc.wait_for(
            lambda: vm.monitor.verify_status(vm_status_paused), 120, step=3
        ):
            test.fail("The vm status is not %s." % vm_status_paused)
    finally:
        iscsi.delete_target()
