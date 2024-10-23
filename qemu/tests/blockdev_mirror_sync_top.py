from virttest.qemu_devices.qdevices import QBlockdevFormatNode

from provider import backup_utils
from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorSyncTopTest(BlockdevMirrorNowaitTest):
    """
    Block mirror test with sync mode top
    """

    def __init__(self, test, params, env):
        super(BlockdevMirrorSyncTopTest, self).__init__(test, params, env)

        # convert source images to convert images
        self._convert_images = params.objects("convert_images")
        self._convert_nodes = ["drive_%s" % src for src in self._convert_images]

        # mirror snapshot images of source images to target images
        self._snap_images = params.objects("snap_images")
        self._snap_nodes = ["drive_%s" % src for src in self._snap_images]

    def _create_images(self, images):
        for tag in images:
            disk = self.source_disk_define_by_params(self.params, tag)
            disk.create(self.params)
            self.trash.append(disk)

    def create_convert_images(self):
        """create convert images used for converting source images"""
        self._create_images(self._convert_images)

    def create_snapshot_images(self):
        """create snapshot images of data images"""
        self._create_images(self._snap_images)

    def _blockdev_add_images(self, images, is_backing_null=False):
        for tag in images:
            params = self.params.object_params(tag)
            devices = self.main_vm.devices.images_define_by_params(tag, params, "disk")
            devices.pop()
            for dev in devices:
                if self.main_vm.devices.get_by_qid(dev.get_qid()):
                    continue
                if isinstance(dev, QBlockdevFormatNode) and is_backing_null:
                    dev.params["backing"] = None
                ret = self.main_vm.devices.simple_hotplug(dev, self.main_vm.monitor)
                if not ret[1]:
                    self.test.fail("Failed to hotplug '%s': %s." % (dev, ret[0]))

    def add_convert_images(self):
        """blockdev-add convert images: protocol and format nodes only"""
        self._blockdev_add_images(self._convert_images)

    def add_snapshot_images(self):
        """blockdev-add snapshot images: protocol and format nodes only"""
        self._blockdev_add_images(self._snap_images, True)

    def add_mirror_images(self):
        """add mirror images where the snapshot images are mirrored"""
        for tag in self._target_images:
            disk = self.target_disk_define_by_params(
                self.params.object_params(tag), tag
            )

            # overlay must not have a current backing file,
            # achieved by passing "backing": null to blockdev-add
            disk.format.params["backing"] = None

            disk.hotplug(self.main_vm)
            self.trash.append(disk)

    def mirror_data_snapshots_to_mirror_images(self):
        """mirror snapshot images to the mirror images"""
        args = {"sync": "top"}
        for idx, source_node in enumerate(self._snap_nodes):
            self._jobs.append(
                backup_utils.blockdev_mirror_nowait(
                    self.main_vm, source_node, self._target_nodes[idx], **args
                )
            )

    def _blockdev_snapshot(self, nodes, overlays):
        snapshot_options = {}
        for idx, source_node in enumerate(nodes):
            backup_utils.blockdev_snapshot(
                self.main_vm, source_node, overlays[idx], **snapshot_options
            )

    def take_snapshot_on_data_images(self):
        """snapshot, node: data image node, overlay: snapshot nodes"""
        self._blockdev_snapshot(self._source_nodes, self._snap_nodes)

    def take_snapshot_on_convert_images(self):
        """snapshot, node: convert image node, overlay: mirror nodes"""
        self._blockdev_snapshot(self._convert_nodes, self._target_nodes)

    def generate_inc_files(self):
        return list(map(self.generate_data_file, self._source_images))

    def convert_data_images(self):
        """convert data images to the convert images"""
        for idx, tag in enumerate(self._source_images):
            convert_target = self._convert_images[idx]
            convert_params = self.params.object_params(convert_target)
            convert_params["convert_target"] = convert_target
            img_obj = self.source_disk_define_by_params(self.params, tag)
            img_obj.convert(convert_params, img_obj.root_dir)

    def prepare_test(self):
        self.prepare_main_vm()
        self.prepare_data_disks()
        self.create_snapshot_images()
        self.add_snapshot_images()

    def do_test(self):
        self.take_snapshot_on_data_images()
        self.generate_inc_files()
        self.create_convert_images()
        self.add_mirror_images()
        self.mirror_data_snapshots_to_mirror_images()
        self.convert_data_images()
        self.add_convert_images()
        self.take_snapshot_on_convert_images()
        self.wait_mirror_jobs_completed()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()


def run(test, params, env):
    """
    Block mirror test with sync mode top

    images: data1, data1sn, convert1, convert1sn
    operations: <convert>, <snapshot>, <mirror>

                  <snapshot>
         data1       --->    data1sn
           |                    |
       <convert>             <mirror>
           |      <snapshot>     |
        convert1     --->   convert1sn

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it, create a file
        3. add a snapshot image(backing-file: data image),
           whose backing node is null
        4. take snapshot, node: data disk node, overlay: snapshot image node
        5. generate a new file on data disk
        6. create a convert image
        7. hotplug a mirror image(backing-file: convert image),
           whose backing node is null
        8. mirror snapshot image to mirror image
        9. convert data image to convert image
       10. blockdev-add the convert image
       11. take snapshot, node: convert image node, overlay: mirror image node
       12. wait blockdev-mirror done
       13. restart VM with the mirror image
       14. check both files and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorSyncTopTest(test, params, env)
    mirror_test.run_test()
