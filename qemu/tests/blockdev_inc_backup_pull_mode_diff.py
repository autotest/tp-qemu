import socket
from functools import partial

import six
from virttest import utils_disk, utils_misc

from provider import backup_utils, block_dirty_bitmap, blockdev_base, job_utils
from provider.nbd_image_export import InternalNBDExportImage


class BlockdevIncBackupPullModeDiff(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncBackupPullModeDiff, self).__init__(test, params, env)
        self.source_images = []
        self.fleecing_full_backups = []
        self.fleecing_inc_backups = []
        self.full_backup_tags = []
        self.inc_backup_tags = []
        self.full_backup_bitmaps = []  # added along with full backup
        self.before_2nd_inc_bitmaps = []  # added before 2nd inc files
        self.merged_bitmaps = []  # merge above two into this one
        self.inc_backup_bitmaps = []  # added along with inc backup
        self.backup_jobs = []
        self.full_backup_nbd_objs = []
        self.inc_backup_nbd_objs = []
        self.full_backup_client_images = []
        self.inc_backup_client_images = []
        self.full_backup_nbd_images = []
        self.inc_backup_nbd_images = []
        self.src_img_tags = params.objects("source_images")
        localhost = socket.gethostname()
        self.params["nbd_server"] = localhost if localhost else "localhost"
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        self.source_images.append("drive_%s" % tag)

        # fleecing images
        bk_tags = image_params.objects("image_backup_chain")
        self.fleecing_full_backups.append("drive_%s" % bk_tags[0])
        self.fleecing_inc_backups.append("drive_%s" % bk_tags[1])

        # bitmaps
        self.full_backup_bitmaps.append("full_bitmap_%s" % tag)
        self.before_2nd_inc_bitmaps.append("before_2nd_inc_bitmap_%s" % tag)
        self.merged_bitmaps.append("merged_bitmap_%s" % tag)
        self.inc_backup_bitmaps.append("inc_bitmap_%s" % tag)
        self.params["nbd_export_bitmaps_%s" % bk_tags[1]] = self.merged_bitmaps[-1]

        # nbd images
        nbd_image = self.params["nbd_image_%s" % bk_tags[0]]
        self.full_backup_nbd_images.append(
            self.source_disk_define_by_params(self.params, nbd_image)
        )
        nbd_image = self.params["nbd_image_%s" % bk_tags[1]]
        self.inc_backup_nbd_images.append(
            self.source_disk_define_by_params(self.params, nbd_image)
        )

        # target 'fullbk' image, copy data from exported full bk image to it
        fullbk = self.params["client_image_%s" % bk_tags[0]]
        disk = self.source_disk_define_by_params(self.params, fullbk)
        disk.create(disk.params)
        self.trash.append(disk)
        self.full_backup_client_images.append(disk)

        # target 'incbk' image, copy data from exported inc bk image to it
        incbk = self.params["client_image_%s" % bk_tags[1]]
        disk = self.source_disk_define_by_params(self.params, incbk)
        disk.create(disk.params)
        self.trash.append(disk)
        self.inc_backup_client_images.append(disk)

        # Only hotplug fleecing images for full backup before full-backup
        self.params["image_backup_chain_%s" % tag] = bk_tags[0]

        self.full_backup_tags.append(bk_tags[0])
        self.inc_backup_tags.append(bk_tags[1])

    def init_nbd_exports(self):
        # nbd export objects, used for exporting local images
        for i, tag in enumerate(self.src_img_tags):
            self.full_backup_nbd_objs.append(
                InternalNBDExportImage(
                    self.main_vm, self.params, self.full_backup_tags[i]
                )
            )
            self.inc_backup_nbd_objs.append(
                InternalNBDExportImage(
                    self.main_vm, self.params, self.inc_backup_tags[i]
                )
            )

    def _copy_data_from_export(self, nbd_imgs, target_imgs, bitmaps=None):
        for i, nbd_obj in enumerate(nbd_imgs):
            if bitmaps is None:
                backup_utils.copyif(self.params, nbd_obj.tag, target_imgs[i].tag)
            else:
                backup_utils.copyif(
                    self.params, nbd_obj.tag, target_imgs[i].tag, bitmaps[i]
                )

    def copy_full_data_from_export(self):
        self._copy_data_from_export(
            self.full_backup_nbd_images, self.full_backup_client_images
        )

    def copy_inc_data_from_export(self):
        self._copy_data_from_export(
            self.inc_backup_nbd_images,
            self.inc_backup_client_images,
            self.merged_bitmaps,
        )

    def _export_fleecing_images(self, nbd_objs, nodes):
        for i, obj in enumerate(nbd_objs):
            obj.start_nbd_server()
            obj.add_nbd_image(nodes[i])

    def _stop_export_fleecing_images(self, nbd_objs):
        for obj in nbd_objs:
            obj.stop_export()

    def export_full_bk_fleecing_imgs(self):
        self._export_fleecing_images(
            self.full_backup_nbd_objs, self.fleecing_full_backups
        )

    def stop_export_full_bk_fleecing_imgs(self):
        self._stop_export_fleecing_images(self.full_backup_nbd_objs)

    def export_inc_bk_fleecing_imgs(self):
        self._export_fleecing_images(
            self.inc_backup_nbd_objs, self.fleecing_inc_backups
        )

    def stop_export_inc_bk_fleecing_imgs(self):
        self._stop_export_fleecing_images(self.inc_backup_nbd_objs)

    def cancel_backup_jobs(self):
        for job_id in self.backup_jobs:
            arguments = {"id": job_id}
            self.main_vm.monitor.cmd("job-cancel", arguments)

    def generate_inc_files(self):
        return list(map(self.generate_data_file, self.src_img_tags))

    def hotplug_inc_backup_images(self):
        for idx, tag in enumerate(self.src_img_tags):
            self.params["image_backup_chain_%s" % tag] = self.inc_backup_tags[idx]
        self.add_target_data_disks()

    def _do_backup(self, backup_nodes, bitmaps):
        extra_options = {"sync": "none", "wait_job_complete": False}
        backup_utils.blockdev_batch_backup(
            self.main_vm, self.source_images, backup_nodes, bitmaps, **extra_options
        )
        self.backup_jobs = [job["id"] for job in job_utils.query_jobs(self.main_vm)]

    def do_full_backup(self):
        self._do_backup(self.fleecing_full_backups, self.full_backup_bitmaps)

    def do_incremental_backup(self):
        self._do_backup(self.fleecing_inc_backups, self.inc_backup_bitmaps)

    def restart_vm_with_incbk_images(self):
        """restart vm with incbk as its data disk"""
        self.main_vm.destroy()
        images = self.params["images"]
        self.params["images"] = " ".join(
            [images.split()[0]] + [o.tag for o in self.inc_backup_client_images]
        )
        self.prepare_main_vm()
        self.clone_vm = self.main_vm
        self.params["images"] = images

    def rebase_inc_onto_full(self):
        # rebase target 'incbk' onto target 'fullbk'
        rebase_funcs = []
        for i, tag in enumerate(self.inc_backup_tags):
            incbk = self.params["client_image_%s" % tag]
            fullbk = self.params["client_image_%s" % self.full_backup_tags[i]]
            image_params = self.params.object_params(incbk)
            image_params["image_chain"] = "%s %s" % (fullbk, incbk)
            disk = self.source_disk_define_by_params(image_params, incbk)
            rebase_funcs.append(partial(disk.rebase, params=image_params))
        utils_misc.parallel(rebase_funcs)

    def check_data_files(self):
        non_existed_files = {}
        disks_info = {}

        # The last file should not exist
        for i, data_img in enumerate(self.src_img_tags):
            non_existed_files[data_img] = self.files_info[data_img].pop()
            disks_info[data_img] = self.disks_info[data_img]

        # Check md5sum for the first three files
        super(BlockdevIncBackupPullModeDiff, self).verify_data_files()

        # Check the files should not exist
        try:
            session = self.clone_vm.wait_for_login()
            for tag, info in six.iteritems(disks_info):
                utils_disk.mount(info[0], info[1], session=session)
                file_path = "%s/%s" % (info[1], non_existed_files[tag])
                cat_cmd = "cat %s" % file_path

                s, o = session.cmd_status_output(cat_cmd)
                if s == 0:
                    self.test.fail("File (%s) exists" % non_existed_files[tag])
                elif "No such file" not in o.strip():
                    self.test.fail("Unknown error: %s" % o)
        finally:
            session.close()

    def _handle_bitmaps(self, disabled_list, new_list, **extra):
        for idx, bitmap in enumerate(disabled_list):
            block_dirty_bitmap.block_dirty_bitmap_disable(
                self.main_vm, self.source_images[idx], bitmap
            )

        for idx, bitmap in enumerate(new_list):
            bitmap_params = {}
            bitmap_params["bitmap_name"] = bitmap
            bitmap_params["target_device"] = self.source_images[idx]
            bitmap_params["disabled"] = extra.pop("disabled", "off")
            block_dirty_bitmap.block_dirty_bitmap_add(self.main_vm, bitmap_params)

        merged_list = extra.pop("merged_list", [])
        for idx, target in enumerate(merged_list):
            src_list = [v[idx] for v in extra.values()]
            block_dirty_bitmap.block_dirty_bitmap_merge(
                self.main_vm, self.source_images[idx], src_list, target
            )

    def add_bitmaps_transaction(self):
        for i, bitmap in enumerate(self.full_backup_bitmaps):
            disabled_params = {
                "bitmap_device_node": self.source_images[i],
                "bitmap_name": bitmap,
            }
            added_params = {
                "bitmap_device_node": self.source_images[i],
                "bitmap_name": self.before_2nd_inc_bitmaps[i],
            }
            block_dirty_bitmap.handle_block_dirty_bitmap_transaction(
                self.main_vm, disabled_params, added_params
            )

    def merge_bitmaps_transaction(self):
        for i, bitmap in enumerate(self.before_2nd_inc_bitmaps):
            disabled_params = {
                "bitmap_device_node": self.source_images[i],
                "bitmap_name": bitmap,
            }
            added_params = {
                "bitmap_device_node": self.source_images[i],
                "bitmap_name": self.merged_bitmaps[i],
                "bitmap_disabled": "on",
            }
            merged_params = {
                "bitmap_device_node": self.source_images[i],
                "bitmap_target": self.merged_bitmaps[i],
                "bitmap_sources": [
                    self.full_backup_bitmaps[i],
                    self.before_2nd_inc_bitmaps[i],
                ],
            }
            block_dirty_bitmap.handle_block_dirty_bitmap_transaction(
                self.main_vm, disabled_params, added_params, merged_params
            )

    def do_test(self):
        self.init_nbd_exports()
        self.do_full_backup()
        self.export_full_bk_fleecing_imgs()
        self.generate_inc_files()
        self.copy_full_data_from_export()
        self.cancel_backup_jobs()
        self.stop_export_full_bk_fleecing_imgs()
        self.add_bitmaps_transaction()
        self.generate_inc_files()
        self.merge_bitmaps_transaction()
        self.hotplug_inc_backup_images()
        self.do_incremental_backup()
        self.export_inc_bk_fleecing_imgs()
        self.generate_inc_files()
        self.copy_inc_data_from_export()
        self.cancel_backup_jobs()
        self.stop_export_inc_bk_fleecing_imgs()
        self.rebase_inc_onto_full()
        self.restart_vm_with_incbk_images()
        self.check_data_files()


def run(test, params, env):
    """
    Blockdev incremental backup test

    test steps:
        1. boot VM with one data disk
        2. make filesystem on data disk
        3. create file and save its md5sum on data disk
        4. add fleecing disk for full backup to VM via qmp commands
        5. do full backup(sync=none) with bitmap
        6. export the full backup image by internal nbd server
        7. create the 2nd file and save its md5sum on data disk
        8. copy data from nbd image exported in step 6
           into an image, e.g. fullbk
        9. cancel full backup job and stop nbd server
        10. add aother fleecing disk for inc backup to VM via qmp commands
        11. do inc backup(sync=none) with another new bitmap
            as well as disable the first bitmap
        12. export the inc backup image by internal nbd server
        13. create the 3rd file and save its md5sum on data disk
        14. copy data from nbd image exported in step 12 with
            the disabled bitmap into an image, e.g. incbk
        15. cancel inc backup job and stop nbd server
        16. rebase incbk onto fullbk
        17. restart vm with incbk as its data image
        18. check md5sum for the first two files on incbk, and make sure
            the 3rd file doesn't exist

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncBackupPullModeDiff(test, params, env)
    inc_test.run_test()
