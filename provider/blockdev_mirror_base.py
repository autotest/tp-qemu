"""
Module for providing a framwork for block-mirror test cases.

The test strategy for block-mirror test cases:
  1. prepare data disks to create files, take md5sum
  2. hotplug the target disks for block-mirror
  3. do block-mirror
  4. check the target disks are attached
  5. restart vm with the target disks
  6. check the files and md5sum
  7. remove files created on system disk

Note:
  1. blockdev_mirror must be implemented for different mirror test scenarios.
  2. There are three specific modules derived from this module, which cover
     almost all test cases:

     blockdev_mirror_wait: do block-mirror and wait job completed, note that
                           this module is used for mirroring a single disk
                           in our testing scenarios.
     blockdev_mirror_nowait: do block-mirror for disks one by one, and never
                             wait job completed.
     blockdev_mirror_parallel: do block-mirror for several disks, as well as
                               other tests in parallel, for block jobs, wait
                               till all jobs completed.

"""

import six

from provider import blockdev_base


class BlockdevMirrorBaseTest(blockdev_base.BlockdevBaseTest):
    """
    block-mirror basic test class
    """

    def __init__(self, test, params, env):
        super(BlockdevMirrorBaseTest, self).__init__(test, params, env)
        self.clone_vm = None
        self._source_images = params.objects("source_images")
        self._target_images = params.objects("target_images")
        self._source_nodes = ["drive_%s" % src for src in self._source_images]
        self._target_nodes = ["drive_%s" % tgt for tgt in self._target_images]
        self._backup_options = list(map(self._get_backup_options, self._source_images))

    def _get_backup_options(self, source_image):
        params = self.params.object_params(source_image)
        opts = params.objects("backup_options")
        backup_options = params.copy_from_keys(opts)

        for k, v in six.iteritems(backup_options):
            if v in ("yes", "true", "on"):
                backup_options[k] = True
            elif v in ("no", "false", "off"):
                backup_options[k] = False

        return backup_options

    def _configure_system_disk(self, tag):
        self.disks_info[tag] = ["system", self.params.get("mnt_on_sys_dsk", "/var/tmp")]

    def _configure_data_disk(self, tag):
        self.format_data_disk(tag)

    def remove_files_from_system_image(self, tmo=60):
        """Remove testing files from system image"""
        tag_dir_list = [
            (t, d[1]) for t, d in six.iteritems(self.disks_info) if d[0] == "system"
        ]
        if tag_dir_list:
            tag, root_dir = tag_dir_list[0]
            files = ["%s/%s" % (root_dir, f) for f in self.files_info[tag]]
            rm_cmd = "rm -f %s" % " ".join(files)

            # restart main vm for the original system image is offlined
            # and the mirror image is attached after block-mirror
            self.prepare_main_vm()
            session = self.main_vm.wait_for_login()
            try:
                session.cmd(rm_cmd, timeout=tmo)
            finally:
                session.close()

    def prepare_data_disk(self, tag):
        """
        data disk can be a system disk or a non-system disk
        """
        if tag == self.params["images"].split()[0]:
            self._configure_system_disk(tag)
        else:
            self._configure_data_disk(tag)
        self.generate_data_file(tag)

    def clone_vm_with_mirrored_images(self):
        """Boot VM with mirrored data disks"""
        if self.main_vm.is_alive():
            self.main_vm.destroy()

        params = self.main_vm.params.copy()
        system_image = params.objects("images")[0]
        images = (
            [system_image] + self._target_images
            if self._source_images[0] != system_image
            else self._target_images
        )
        params["images"] = " ".join(images)

        self.clone_vm = self.main_vm.clone(params=params)
        self.clone_vm.create()
        self.clone_vm.verify_alive()

        self.env.register_vm("%s_clone" % self.clone_vm.name, self.clone_vm)

    def add_target_data_disks(self):
        """Hot plug target disks to VM with qmp monitor"""
        for tag in self._target_images:
            disk = self.target_disk_define_by_params(
                self.params.object_params(tag), tag
            )
            disk.hotplug(self.main_vm)
            self.trash.append(disk)

    def _check_mirrored_block_node_attached(self, source_qdev, target_node):
        out = self.main_vm.monitor.query("block")
        for item in out:
            if (
                source_qdev in item["qdev"]
                and item["inserted"].get("node-name") == target_node
            ):
                break
        else:
            self.test.fail(
                "Device(%s) is not attached to target node(%s)"
                % (source_qdev, target_node)
            )

    def check_mirrored_block_nodes_attached(self):
        """All source devices attach to the mirrored nodes"""
        for idx, target in enumerate(self._target_nodes):
            self._check_mirrored_block_node_attached(self._source_images[idx], target)

    def blockdev_mirror(self):
        """Need to be implemented in specific test case"""
        raise NotImplementedError

    def do_test(self):
        self.blockdev_mirror()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()
        self.remove_files_from_system_image()
