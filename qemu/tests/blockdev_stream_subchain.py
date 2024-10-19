import json
import logging

from virttest import data_dir, qemu_storage
from virttest.qemu_capabilities import Flags

from provider import backup_utils
from provider.blockdev_stream_base import BlockDevStreamTest
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevStreamSubChainTest(BlockDevStreamTest):
    """Do block-stream based on an existed snapshot in snapshot chain"""

    def __init__(self, test, params, env):
        super(BlockdevStreamSubChainTest, self).__init__(test, params, env)
        self._snapshot_images = self.params.objects("snapshot_images")
        self._base_node_tag = self.params["base_node_tag"]
        self._trash = []

    def snapshot_test(self):
        """create one snapshot, create one new file"""
        self.generate_tempfile(
            self.disks_info[self.base_tag][1],
            filename="base",
            size=self.params["tempfile_size"],
        )

        # data->sn1->sn2->sn3
        chain = [self.base_tag] + self._snapshot_images
        for idx in range(1, len(chain)):
            backup_utils.blockdev_snapshot(
                self.main_vm, "drive_%s" % chain[idx - 1], "drive_%s" % chain[idx]
            )

            self.generate_tempfile(
                self.disks_info[self.base_tag][1],
                filename=chain[idx],
                size=self.params["tempfile_size"],
            )

    def _disk_define_by_params(self, tag):
        params = self.params.copy()
        params.setdefault("target_path", data_dir.get_data_dir())
        return sp_admin.volume_define_by_params(tag, params)

    def prepare_snapshot_file(self):
        """hotplug all snapshot images"""
        for tag in self._snapshot_images:
            disk = self._disk_define_by_params(tag)
            disk.hotplug(self.main_vm)
            self._trash.append(disk)

    def _remove_images(self):
        for img in self._trash:
            sp_admin.remove_volume(img)

    def post_test(self):
        try:
            if self.clone_vm.is_alive():
                self.clone_vm.destroy()
            self._remove_images()
        except Exception as e:
            LOG_JOB.warning(str(e))

    def _is_same_file(self, file_params, file_opts):
        # FIXME: this should be supported in VT
        mapping = {
            "gluster": "path",
            "iscsi": "lun",
            "nbd": "server.port",
            "rbd": "image",
        }
        option = mapping.get(file_opts["driver"], "filename")
        return file_params[option] == file_opts[option]

    def _check_backing(self, backing):
        data_image_opts = qemu_storage.filename_to_file_opts(
            qemu_storage.QemuImg(
                self.params.object_params(self.base_tag),
                data_dir.get_data_dir(),
                self.base_tag,
            ).image_filename
        )
        base_image_opts = qemu_storage.filename_to_file_opts(
            qemu_storage.QemuImg(
                self.params.object_params(self._base_node_tag),
                data_dir.get_data_dir(),
                self._base_node_tag,
            ).image_filename
        )

        try:
            # datasn1->datasn3: check datasn1 is datasn3's backing file
            if not self._is_same_file(backing["file"], base_image_opts):
                self.test.fail("Failed to get backing file for %s" % self.snapshot_tag)
            # data->datasn1: check data is datasn1's backing file
            backing_mask = self.main_vm.check_capability(
                Flags.BLOCKJOB_BACKING_MASK_PROTOCOL
            )
            raw_format = self.get_image_by_tag(self.base_tag).image_format == "raw"
            backing_opts = (
                backing["backing"]
                if (backing_mask and raw_format)
                else backing["backing"]["file"]
            )
            if not self._is_same_file(backing_opts, data_image_opts):
                self.test.fail(
                    "Failed to get backing file for %s" % self._base_node_tag
                )
        except Exception as e:
            self.test.fail("Failed to get backing chain: %s" % str(e))

    def check_backing_chain(self):
        """after block-stream, the backing chain: data->datasn1->dtasn3"""
        out = self.main_vm.monitor.query("block")
        for item in out:
            if self.base_tag in item["qdev"]:
                backing = item["inserted"].get("backing_file")
                if not backing:
                    self.test.fail(
                        "Failed to get backing_file for qdev %s" % self.base_tag
                    )
                backing_dict = json.loads(backing[5:])
                self._check_backing(backing_dict)
                break
        else:
            self.test.fail("Failed to find %s" % self.base_tag)

    def clone_vm_with_snapshot(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()

        # Add image_chain , then VT can add access secret objects
        # in qemu-kvm command, qemu-kvm can access the backing files
        self.clone_vm.params["image_chain_%s" % self.snapshot_tag] = "%s %s %s" % (
            self.base_tag,
            self._base_node_tag,
            self.snapshot_tag,
        )
        self.clone_vm.create()

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        self.check_backing_chain()
        self.clone_vm_with_snapshot()
        self.mount_data_disks()
        self.verify_data_file()


def run(test, params, env):
    """
    Basic block stream test with stress
    test steps:
        1. boot VM with a data image
        2. add snapshot images
        3. create a file(base) on data image
        4. take snapshots(data->sn1->sn2->sn3),
           take one snapshot, create one new file(snx, x=1,2,3)
        5. do block-stream (base-node:sn1, device: sn3)
        6. check backing chain(data->sn1->sn3)
        7. restart VM with the sn3, all files should exist
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamSubChainTest(test, params, env)
    stream_test.run_test()
