import re

from provider import backup_utils
from provider import block_dirty_bitmap
from provider import blockdev_backup_nbd


class BlockdevBackupNbdTest(blockdev_backup_nbd.BlockdevBackupNbdBaseTest):

    def __init__(self, test, params, env):
        super(BlockdevBackupNbdTest, self).__init__(test, params, env)
        self.bitmaps_base = []
        self.bitmaps_inc = []
        self.full_backups = []
        self.inc_backups = []
        self.source_images = []
        self.name_prefix = "drive"
        self.bitmap_prefix = "bitmap"
        self.src_img_tag = params.objects("source_images")
        self.inc_img_tag = []
        self.full_img_tag = []
        self.dst_img_tag = []
        list(map(self._init_by_params, self.src_img_tag))

    def _init_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_chain")
        self.source_images.append("%s_%s" % (self.name_prefix, tag))
        self.full_backups.append("%s_%s" % (self.name_prefix, image_chain[0]))
        self.full_img_tag.append(image_chain[0])
        self.inc_backups.append("%s_%s" % (self.name_prefix, image_chain[1]))
        self.inc_img_tag.append(image_chain[1])
        self.bitmaps_base.append("%s_base_%s" % (self.bitmap_prefix, tag))
        self.bitmaps_inc.append("%s_inc_%s" % (self.bitmap_prefix, tag))
        self.dst_img_tag.append(image_params.objects("backup_chain"))

    def _do_backup(self, source_images, backup_images, bitmaps):
        """
        Start blockdev backup process and ignore job timeout
        """
        extra_options = {"sync": "none", "timeout": "1"}
        try:
            backup_utils.blockdev_batch_backup(
                self.main_vm,
                source_images,
                backup_images,
                bitmaps,
                **extra_options)
        except AssertionError as e:
            jobs_id = re.findall(r'job \((.*)\) complete', str(e), re.M)
            if not jobs_id:
                raise e
            return jobs_id

    def do_full_backup(self):
        jobs_id = self._do_backup(
            self.source_images,
            self.full_backups,
            self.bitmaps_base)
        for idx, name in enumerate(self.full_img_tag):
            src_tag = self.src_img_tag[idx]
            dst_tag = self.dst_img_tag[idx][0]
            self.backup_blockdev_via_nbd(name, src_tag, dst_tag)
        list(map(self.main_vm.cancel_block_job, jobs_id))
        for idx, bitmap in enumerate(self.bitmaps_base):
            node = self.source_images[idx]
            block_dirty_bitmap.block_dirty_bitmap_disable(
                self.main_vm, node, bitmap)

    def do_inc_backup(self):
        jobs_id = self._do_backup(
            self.source_images,
            self.inc_backups,
            self.bitmaps_inc)
        list(map(self.generate_data_file, self.src_img_tag))
        for idx, name in enumerate(self.inc_img_tag):
            src_tag = self.src_img_tag[idx]
            dst_tag = self.dst_img_tag[idx][1]
            self.backup_blockdev_via_nbd(name, src_tag, dst_tag, self.bitmaps_base[idx])
            self.main_vm.monitor.cancel_block_job(jobs_id[0])
            self.main_vm.monitor.blockdev_del("%s_%s" % (self.name_prefix, name))
            disk = self.target_disk_define_by_params(self.params, name)
            disk.remove()

    def backup_blockdev_via_nbd(self, name, src_tag, dst_tag, bitmap=None):
        """
        Backup a blockdev image via nbd to local

        :param name: img tag want to expose
        :param src_tag: source image tag
        :param dst_tag: img tag in backup chain
        :param bitmap: bitmap name
        """
        src_params = self.params.object_params(src_tag)
        dst_params = self.params.object_params(dst_tag)
        dst_img = self.disk_define_by_params(dst_params, dst_tag)
        dst_img.create(params=dst_params)
        dst_file = dst_img.image_filename
        self.trash.append(dst_img)
        node_name = "%s_%s" % (self.name_prefix, name)
        self.expose_blockdev(node_name, bitmap)
        self.pull_backup_data(node_name, dst_file, bitmap)
        self.unexpose_blockdev(node_name)

    def rebase_expose_disk(self):
        for tag in self.src_img_tag:
            img_params = self.params.object_params(tag)
            backup_chain = img_params["backup_chain"]
            top_img_tag = img_params.objects("backup_chain")[-1]
            top_img_params = self.params.object_params(top_img_tag)
            top_img_params["image_chain"] = backup_chain
            top_img = self.disk_define_by_params(top_img_params, top_img_tag)
            top_img.rebase(params=top_img_params)

    def prepare_clone_vm(self):
        self.main_vm.destroy()
        vm_params = self.main_vm.params.copy()
        images = self.params.objects("images")
        for tag in self.src_img_tag:
            params = self.params.object_params(tag)
            top = params.objects("backup_chain")[-1]
            images[images.index(tag)] = top
        vm_params["images"] = " ".join(images)
        clone_vm = self.main_vm.clone(params=vm_params)
        self.clone_vm = clone_vm
        clone_vm.create()

    def verify_data_files(self):
        self.main_vm.destroy()
        self.prepare_clone_vm()
        try:
            super(BlockdevBackupNbdTest, self).verify_data_files()
        finally:
            self.clone_vm.destroy()

    def do_test(self):
        self.do_full_backup()
        self.do_inc_backup()
        self.rebase_expose_disk()
        self.verify_data_files()


def run(test, params, env):
    """
    Blockdev increamental backup test

    test steps:
        1. boot VM with one or two data disks
        2. make filesystem in data disks
        3. create file and save it md5sum in data disks
        4. add target disks for backup to VM via qmp commands
        5. do full backup and expose backup via nbd server
        6. create new files and save it md5sum in data disks
        7. do increamental backup and expose backup via nbd server
        8. destroy VM and rebase increamental backup image
        9. start VM with image in step8
        10. verify files in data disks not change

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevBackupNbdTest(test, params, env)
    inc_test.run_test()
