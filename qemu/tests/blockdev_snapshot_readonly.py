import re

from aexpect import ShellCmdError
from virttest import utils_disk

from provider import backup_utils
from provider.blockdev_snapshot_base import BlockDevSnapshotTest


class BlockdevSnapshotReadonly(BlockDevSnapshotTest):
    def configure_data_disk(self):
        self.params["os_type"]
        disk_params = self.params.object_params(self.base_tag)
        disk_size = disk_params["image_size"]
        session = self.main_vm.wait_for_login()
        disk_id = self.get_linux_disk_path(session, disk_size)
        assert disk_id, "Disk not found in guest!"
        try:
            utils_disk.configure_empty_linux_disk(session, disk_id, disk_size)[0]
        except ShellCmdError as e:
            disk_tag = r"/dev/%s" % disk_id
            error_msg = self.params["error_msg"] % disk_tag
            if not re.search(error_msg, str(e)):
                self.test.fail("Unexpected disk format error: %s" % str(e))
            self.disks_info[self.base_tag] = [disk_tag, "/mnt"]
        else:
            self.test.fail("Read-only disk is formated")
        finally:
            session.close()

    def mount_data_disks(self):
        session = self.clone_vm.wait_for_login()
        backup_utils.refresh_mounts(self.disks_info, self.params, session)
        for info in self.disks_info.values():
            disk_path = info[0]
            mount_point = info[1]
            if utils_disk.mount(disk_path, mount_point, session=session):
                self.test.fail("Read-only disk is mounted with rw")
        session.close()

    def verify_snapshot(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        self.snapshot_image.base_tag = self.base_tag
        self.snapshot_image.base_format = self.base_image.get_format()
        base_image_filename = self.base_image.image_filename
        self.snapshot_image.base_image_filename = base_image_filename
        self.snapshot_image.rebase(self.snapshot_image.params)
        self.clone_vm.create()
        self.clone_vm.verify_alive()
        self.mount_data_disks()

    def snapshot_test(self):
        self.create_snapshot()
        self.verify_snapshot()


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with data disk and read-only
    2) check if error prompted when configure read-only data disk
    3) do snapshot to target disk
    4) quit vm, clone vm, then start vm with snapshot disk
    5) check if snapshot disk can be mounted, if yes, fail.
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    snapshot_readonly = BlockdevSnapshotReadonly(test, params, env)
    snapshot_readonly.run_test()
