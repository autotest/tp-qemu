from functools import partial

from virttest import guest_agent, utils_misc

from provider import backup_utils, blockdev_base


class BlockdevIncbkFSFreezeTest(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncbkFSFreezeTest, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
        self.inc_backup_tags = []
        self.rebase_funcs = []
        self.bitmaps = []
        self.src_img_tags = params.objects("source_images")
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self.source_images.append("drive_%s" % tag)
        self.full_backups.append("drive_%s" % image_chain[0])
        self.inc_backups.append("drive_%s" % image_chain[1])
        self.inc_backup_tags.append(image_chain[1])
        self.bitmaps.append("bitmap_%s" % tag)

        # rebase 'inc' image onto 'base' image, so inc's backing is base
        inc_img_params = self.params.object_params(image_chain[1])
        inc_img_params["image_chain"] = image_params["image_backup_chain"]
        inc_img = self.source_disk_define_by_params(inc_img_params, image_chain[1])
        self.rebase_funcs.append(partial(inc_img.rebase, params=inc_img_params))

    def do_full_backup(self):
        extra_options = {"sync": "full", "auto_disable_bitmap": False}
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.full_backups,
            self.bitmaps,
            **extra_options,
        )

    def generate_inc_files(self):
        return list(map(self.generate_data_file, self.src_img_tags))

    def do_incremental_backup(self):
        extra_options = {"sync": "incremental", "auto_disable_bitmap": False}
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.inc_backups,
            self.bitmaps,
            **extra_options,
        )

    def restart_vm_with_inc(self):
        images = self.params["images"]
        self.params["images"] = " ".join([images.split()[0]] + self.inc_backup_tags)
        self.prepare_main_vm()
        self.clone_vm = self.main_vm
        self.params["images"] = images

    def prepare_test(self):
        super(BlockdevIncbkFSFreezeTest, self).prepare_test()
        params = self.params.object_params(self.params["agent_name"])
        params["monitor_filename"] = self.main_vm.get_serial_console_filename(
            self.params["agent_name"]
        )
        self.guest_agent = guest_agent.QemuAgent(
            self.main_vm,
            self.params["agent_name"],
            self.params["agent_serial_type"],
            params,
        )

        # bz1747960, enable virt_qemu_ga_read_nonsecurity_files before freeze,
        # if the fix is not backported yet, put SELinux in permissive mode
        # no need to restore the setting for a VM reboot can restore it
        s = self.main_vm.wait_for_login()
        try:
            if s.cmd_status(self.params["enable_nonsecurity_files_cmd"]) != 0:
                s.cmd_status(self.params["enable_permissive_cmd"])
        finally:
            s.close()

    def rebase_inc_onto_base(self):
        return utils_misc.parallel(self.rebase_funcs)

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.guest_agent.fsfreeze()
        self.do_incremental_backup()
        self.guest_agent.fsthaw()
        self.main_vm.destroy()
        self.rebase_inc_onto_base()
        self.restart_vm_with_inc()
        self.verify_data_files()


def run(test, params, env):
    """
    Do incremental backup with guest-fs-freeze

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add non-persistent bitmap
        5. create another file
        6. guest-fsfreeze-freeze
        7. do inc bakcup(sync: incremental)
        8. guest-fsfreeze-thaw
        9. shutdown VM, rebase inc onto base
       10. start VM with inc images, check files' md5

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkFSFreezeTest(test, params, env)
    inc_test.run_test()
