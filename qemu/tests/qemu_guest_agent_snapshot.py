import logging

from autotest.client import utils
from autotest.client.shared import error

from virttest import utils_misc

from qemu.tests.live_snapshot_basic import LiveSnapshot
from qemu.tests.qemu_guest_agent import QemuGuestAgentBasicCheck


class QemuGuestAgentSnapshotTest(QemuGuestAgentBasicCheck):

    @error.context_aware
    def _action_before_fsfreeze(self, *args):
        copy_timeout = int(self.params.get("copy_timeoout", 600))
        file_size = int(self.params.get("file_size", "500"))
        tmp_name = utils_misc.generate_random_string(5)
        self.host_path = self.guest_path = "/tmp/%s" % tmp_name
        if self.params.get("os_type") != "linux":
            self.guest_path = r"c:\%s" % tmp_name

        error.context("Create a file in host.")
        utils.run("dd if=/dev/urandom of=%s bs=1M count=%s" % (self.host_path,
                                                               file_size))
        self.orig_hash = utils.hash_file(self.host_path)
        error.context("Transfer file from %s to %s" % (self.host_path,
                                                       self.guest_path), logging.info)
        self.bg = utils.InterruptedThread(self.vm.copy_files_to,
                                          (self.host_path, self.guest_path),
                                          dict(verbose=True, timeout=copy_timeout))
        self.bg.start()

    @error.context_aware
    def _action_after_fsfreeze(self, *args):
        if self.bg.isAlive():
            image_tag = self.params.get("image_name", "image1")
            image_params = self.params.object_params(image_tag)
            snapshot_test = LiveSnapshot(self.test, self.params,
                                         self.env, image_tag)
            error.context("Creating snapshot", logging.info)
            snapshot_test.create_snapshot()
            error.context("Checking snapshot created successfully",
                          logging.info)
            snapshot_test.check_snapshot()

    @error.context_aware
    def _action_before_fsthaw(self, *args):
        pass

    @error.context_aware
    def _action_after_fsthaw(self, *args):
        if self.bg:
            self.bg.join()
        # Make sure the returned file is identical to the original one
        self.host_path_returned = "%s-returned" % self.host_path
        self.vm.copy_files_from(self.guest_path, self.host_path_returned)
        error.context("comparing hashes", logging.info)
        self.curr_hash = utils.hash_file(self.host_path_returned)
        if self.orig_hash != self.curr_hash:
            raise error.TestFail("Current file hash (%s) differs from "
                                 "original one (%s)" % (self.curr_hash,
                                                        self.orig_hash))

        error.context("Reboot and shutdown guest.")
        self.vm.reboot()
        self.vm.destroy()


def run(test, params, env):
    """
    Freeze guest + create live snapshot + thaw guest

    Test steps:
    1) Create a big file inside on host.
    2) Scp the file from host to guest.
    3) Freeze guest during file transfer.
    4) Create live snapshot.
    5) Thaw guest.
    6) Scp the file from guest to host.
    7) Compare hash of those 2 files.
    8) Reboot and shutdown guest.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    gagent_test = QemuGuestAgentSnapshotTest(test, params, env)
    gagent_test.execute(test, params, env)
