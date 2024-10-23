import logging
import socket

import six
from virttest import qemu_storage, utils_disk

from provider import backup_utils, blockdev_base, job_utils
from provider.nbd_image_export import InternalNBDExportImage
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevIncBackupPullModeTest(blockdev_base.BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncBackupPullModeTest, self).__init__(test, params, env)
        self.source_images = []
        self.full_backups = []
        self.inc_backups = []
        self.full_backup_bitmaps = []
        self.inc_backup_bitmaps = []
        self.disabled_bitmaps = []
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
        bk_tags = image_params.objects("backup_images")
        self.source_images.append("drive_%s" % tag)

        # fleecing image used for full backup, to be exported by nbd
        self.full_backups.append("drive_%s" % bk_tags[0])
        self.full_backup_bitmaps.append("full_bitmap_%s" % tag)

        # fleecing image used for inc backup, to be exported by nbd
        self.inc_backups.append("drive_%s" % bk_tags[1])
        self.inc_backup_bitmaps.append("inc_bitmap_%s" % tag)

        # nbd export image used full backup
        nbd_image = self.params["nbd_image_%s" % bk_tags[0]]
        disk = qemu_storage.QemuImg(
            self.params.object_params(nbd_image), None, nbd_image
        )
        self.full_backup_nbd_images.append(disk)

        # nbd export image used for inc backup
        nbd_image = self.params["nbd_image_%s" % bk_tags[1]]
        disk = qemu_storage.QemuImg(
            self.params.object_params(nbd_image), None, nbd_image
        )
        self.inc_backup_nbd_images.append(disk)

        # local image used for copying data from nbd export image(full backup)
        client_image = self.params["client_image_%s" % bk_tags[0]]
        disk = self.source_disk_define_by_params(
            self.params.object_params(client_image), client_image
        )
        disk.create(self.params)
        self.trash.append(disk)
        self.full_backup_client_images.append(disk)

        # local image used for copying data from nbd export images(inc backup)
        client_image = self.params["client_image_%s" % bk_tags[1]]
        disk = self.source_disk_define_by_params(
            self.params.object_params(client_image), client_image
        )
        disk.create(self.params)
        self.trash.append(disk)
        self.inc_backup_client_images.append(disk)

        # disable bitmap created in full backup when doing inc backup
        self.disabled_bitmaps.append("full_bitmap_%s" % tag)

    def init_nbd_exports(self):
        def _init_nbd_exports(tag):
            bk_tags = self.params.object_params(tag).objects("backup_images")

            self.full_backup_nbd_objs.append(
                InternalNBDExportImage(self.main_vm, self.params, bk_tags[0])
            )

            self.params["nbd_export_bitmaps_%s" % bk_tags[1]] = "full_bitmap_%s" % tag
            self.inc_backup_nbd_objs.append(
                InternalNBDExportImage(self.main_vm, self.params, bk_tags[1])
            )

        list(map(_init_nbd_exports, self.src_img_tags))

    def full_copyif(self):
        for i, nbd_obj in enumerate(self.full_backup_nbd_images):
            backup_utils.copyif(
                self.params, nbd_obj.tag, self.full_backup_client_images[i].tag
            )

    def inc_copyif(self):
        for i, nbd_obj in enumerate(self.inc_backup_nbd_images):
            backup_utils.copyif(
                self.params,
                nbd_obj.tag,
                self.inc_backup_client_images[i].tag,
                self.full_backup_bitmaps[i],
            )

    def export_full_backups(self):
        for i, obj in enumerate(self.full_backup_nbd_objs):
            obj.start_nbd_server()
            obj.add_nbd_image(self.full_backups[i])

    def stop_export_full_backups(self):
        for obj in self.full_backup_nbd_objs:
            obj.stop_export()

    def export_inc_backups(self):
        for i, obj in enumerate(self.inc_backup_nbd_objs):
            obj.start_nbd_server()
            obj.add_nbd_image(self.inc_backups[i])

    def stop_export_inc_backups(self):
        for obj in self.inc_backup_nbd_objs:
            obj.stop_export()

    def cancel_backup_jobs(self):
        for job_id in self.backup_jobs:
            arguments = {"id": job_id}
            self.main_vm.monitor.cmd("job-cancel", arguments)

    def do_full_backup(self):
        extra_options = {"sync": "none", "wait_job_complete": False}
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.full_backups,
            self.full_backup_bitmaps,
            **extra_options,
        )
        self.backup_jobs = [job["id"] for job in job_utils.query_jobs(self.main_vm)]

    def generate_inc_files(self):
        return list(map(self.generate_data_file, self.src_img_tags))

    def add_target_data_disks(self, bktype="full"):
        """Hot add target disk to VM with qmp monitor"""
        for tag in self.params.objects("source_images"):
            image_params = self.params.object_params(tag)
            img = (
                image_params["full_backup_image"]
                if bktype == "full"
                else image_params["inc_backup_image"]
            )
            disk = self.target_disk_define_by_params(self.params, img)
            disk.hotplug(self.main_vm)
            self.trash.append(disk)

    def do_incremental_backup(self):
        extra_options = {
            "sync": "none",
            "disabled_bitmaps": self.disabled_bitmaps,
            "wait_job_complete": False,
        }
        backup_utils.blockdev_batch_backup(
            self.main_vm,
            self.source_images,
            self.inc_backups,
            self.inc_backup_bitmaps,
            **extra_options,
        )
        self.backup_jobs = [job["id"] for job in job_utils.query_jobs(self.main_vm)]

    def restart_vm_with_backup_images(self):
        """restart vm with back2 as its data disk"""
        self.main_vm.destroy()
        images = self.params["images"].split()[0]
        for obj in self.inc_backup_client_images:
            images += " %s" % obj.tag
        self.params["images"] = images
        self.prepare_main_vm()
        self.clone_vm = self.main_vm

    def clean_images(self):
        for img in self.trash:
            try:
                if hasattr(img, "remove"):
                    img.remove()
                else:
                    sp_admin.remove_volume(img)
            except Exception as e:
                LOG_JOB.warning(str(e))

    def rebase_backup_image(self):
        """rebase image back2 onto back1"""
        for i, img_obj in enumerate(self.inc_backup_client_images):
            target_img_obj = self.full_backup_client_images[i]
            img_obj.base_image_filename = target_img_obj.image_filename
            img_obj.base_format = target_img_obj.image_format
            img_obj.base_tag = target_img_obj.tag
            img_obj.rebase(img_obj.params)

    def verify_data_files(self):
        non_existed_files = {}
        disks_info = {}

        # The last file should not exist on back2
        for i, data_img in enumerate(self.src_img_tags):
            non_existed_files[data_img] = self.files_info[data_img].pop()
            disks_info[data_img] = self.disks_info[data_img]

        # Check md5sum for the first two files
        super(BlockdevIncBackupPullModeTest, self).verify_data_files()

        # Check the files should not exist on back2
        session = self.clone_vm.wait_for_login()
        try:
            for tag, info in six.iteritems(disks_info):
                utils_disk.mount(info[0], info[1], session=session)
                file_path = "%s/%s" % (info[1], non_existed_files[tag])
                cat_cmd = "cat %s" % file_path

                LOG_JOB.info("Check %s should not exist", file_path)
                s, o = session.cmd_status_output(cat_cmd)
                if s == 0:
                    self.test.fail("File (%s) exists" % non_existed_files[tag])
                elif "No such file" not in o.strip():
                    self.test.fail("Unknown error: %s" % o)
        finally:
            if session:
                session.close()

    def do_test(self):
        self.init_nbd_exports()
        self.do_full_backup()
        self.export_full_backups()
        self.generate_inc_files()
        self.full_copyif()
        self.cancel_backup_jobs()
        self.stop_export_full_backups()
        self.add_target_data_disks("inc")
        self.do_incremental_backup()
        self.export_inc_backups()
        self.generate_inc_files()
        self.inc_copyif()
        self.cancel_backup_jobs()
        self.stop_export_inc_backups()
        self.rebase_backup_image()
        self.restart_vm_with_backup_images()
        self.verify_data_files()


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
           into an image, e.g. back1
        9. cancel full backup job and stop nbd server
        10. add aother fleecing disk for inc backup to VM via qmp commands
        11. do inc backup(sync=none) with another new bitmap
            as well as disable the first bitmap
        12. export the inc backup image by internal nbd server
        13. create the 3rd file and save its md5sum on data disk
        14. copy data from nbd image exported in step 12 with
            the disabled bitmap into an image, e.g. back2
        15. cancel inc backup job and stop nbd server
        16. rebase back2 onto back1
        17. restart vm with back2 as its data image
        18. check md5sum for the first two files on back2, and make sure
            the 3rd file doesn't exist

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncBackupPullModeTest(test, params, env)
    inc_test.run_test()
