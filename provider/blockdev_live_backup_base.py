"""
Module for providing a framwork for live backup test cases.
Note:
1. 'do_test' should be implemented in test cases
2. 'full_backup_options[_tag]' should be defined
   in Json Doc string, e.g.
   '{"sync": "full", "auto-dismiss": "off", "auto_disable_bitmap": "off"}',
   the valid option list:
   2.1 options defined in BackupCommon: auto-finalize, on-target-error...
   2.2 options defined for backup utils:
       timeout: backup timeout
       auto_disable_bitmap: on/off, disable bitmaps or not
       disabled_bitmaps: bitmap name list, in which bitmap will be disabled
       completion_mode: completion-mode in TransactionProperties
       wait_job_complete: on/off, wait job done or not
       granularity: granularity in BlockDirtyInfo
       persistent: persistent in BlockDirtyInfo
"""

import json
from functools import partial

from provider.backup_utils import blockdev_batch_backup
from provider.blockdev_base import BlockdevBaseTest


class BlockdevLiveBackupBaseTest(BlockdevBaseTest):
    """Live backup base test module"""

    def __init__(self, test, params, env):
        super(BlockdevLiveBackupBaseTest, self).__init__(test, params, env)
        self.clone_vm = None
        self._target_images = []
        self._source_images = params.objects("source_images")
        self._source_nodes = ["drive_%s" % src for src in self._source_images]
        self._full_backup_options = self._get_full_backup_options()
        self._full_bk_images = []
        self._full_bk_nodes = []
        self._bitmaps = []
        list(map(self._init_arguments_by_params, self._source_images))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        self._full_bk_images.append(image_chain[0])
        self._full_bk_nodes.append("drive_%s" % image_chain[0])
        self._bitmaps.append("bitmap_%s" % tag)
        self._target_images.append(image_chain[-1])

    def _convert_args(self, backup_options):
        for k, v in backup_options.items():
            if v in ("yes", "true", "True", "on"):
                backup_options[k] = True
            elif v in ("no", "false", "False", "off"):
                backup_options[k] = False

    def _get_full_backup_options(self):
        options = json.loads(self.params["full_backup_options"])
        self._convert_args(options)
        return options

    def _configure_system_disk(self, tag):
        self.disks_info[tag] = ["system", self.params.get("mnt_on_sys_dsk", "/var/tmp")]

    def _configure_data_disk(self, tag):
        self.format_data_disk(tag)

    def remove_files_from_system_image(self, tmo=60):
        """Remove testing files from system image"""
        tag_dir_list = [
            (t, d[1]) for t, d in self.disks_info.items() if d[0] == "system"
        ]
        if tag_dir_list:
            tag, root_dir = tag_dir_list[0]
            files = ["%s/%s" % (root_dir, f) for f in self.files_info[tag]]
            rm_cmd = "rm -f %s" % " ".join(files)

            if self.clone_vm and self.clone_vm.is_alive():
                self.clone_vm.destroy()
            if not self.main_vm.is_alive():
                self.main_vm.create()
                self.main_vm.verify_alive()

            session = self.main_vm.wait_for_login()
            try:
                session.cmd(rm_cmd, timeout=tmo)
            finally:
                session.close()

    def prepare_data_disk(self, tag):
        """Data disk can be a system disk or a non-system disk"""
        if tag == self.params["images"].split()[0]:
            self._configure_system_disk(tag)
        else:
            self._configure_data_disk(tag)
        self.generate_data_file(tag, filename="base")

    def generate_inc_files(self, filename="inc"):
        """Create new files on data disks"""
        f = partial(self.generate_data_file, filename=filename)
        list(map(f, self._source_images))

    def prepare_clone_vm(self):
        """Boot VM with target data disks"""
        if self.main_vm.is_alive():
            self.main_vm.destroy()

        clone_params = self.main_vm.params.copy()
        for s, t in zip(self._source_images, self._target_images):
            clone_params["images"] = clone_params["images"].replace(s, t)

        self.clone_vm = self.main_vm.clone(params=clone_params)
        self.clone_vm.create()
        self.clone_vm.verify_alive()
        self.env.register_vm("%s_clone" % self.clone_vm.name, self.clone_vm)

    def do_full_backup(self):
        blockdev_batch_backup(
            self.main_vm,
            self._source_nodes,
            self._full_bk_nodes,
            self._bitmaps,
            **self._full_backup_options,
        )

    def post_test(self):
        self.remove_files_from_system_image()
        super(BlockdevLiveBackupBaseTest, self).post_test()
