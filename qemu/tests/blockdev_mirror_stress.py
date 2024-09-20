import random
import time

import six

from provider.blockdev_mirror_wait import BlockdevMirrorWaitTest
from provider.storage_benchmark import generate_instance


class BlockdevMirrorStressTest(BlockdevMirrorWaitTest):
    """Do block-mirror with fio test as background test"""

    def fio_run_bg(self):
        fio_options = self.params.get("fio_options")
        if fio_options:
            self.test.log.info("Start to run fio")
            self.fio = generate_instance(self.params, self.main_vm, "fio")
            fio_run_timeout = self.params.get_numeric("fio_timeout", 2400)
            self.fio.run(fio_options, fio_run_timeout)

    def remove_files_from_system_image(self, tmo=60):
        """Remove testing files from system image"""
        tag_dir_list = [
            (t, d[1]) for t, d in six.iteritems(self.disks_info) if d[0] == "system"
        ]
        if tag_dir_list:
            tag, root_dir = tag_dir_list[0]
            files = ["%s/%s" % (root_dir, f) for f in self.files_info[tag]]
            files.append(
                "%s/%s" % (self.params["mnt_on_sys_dsk"], self.params["file_fio"])
            )
            rm_cmd = "rm -f %s" % " ".join(files)

            # restart main vm for the original system image is offlined
            # and the mirror image is attached after block-mirror
            self.prepare_main_vm()
            session = self.main_vm.wait_for_login()
            try:
                session.cmd(rm_cmd, timeout=tmo)
            finally:
                session.close()

    def do_test(self):
        self.fio_run_bg()
        self.test.log.info("sleep random time before mirror during fio")
        mint = self.params.get_numeric("sleep_min")
        maxt = self.params.get_numeric("sleep_max")
        time.sleep(random.randint(mint, maxt))
        try:
            self.blockdev_mirror()
        finally:
            self.fio.clean(force=True)
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()
        self.remove_files_from_system_image()


def run(test, params, env):
    """
    Basic block mirror test with fio -- only system disk

    test steps:
        1. boot VM
        2. create a file on system disk
        3. add a target disk for mirror to VM via qmp commands
        4. start fio test on system disk
        5. do block-mirror for system disk
        6. check the mirrored disk is attached
        7. restart VM with the mirrored disk, check the file and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorStressTest(test, params, env)
    mirror_test.run_test()
