from avocado.utils import process
from virttest.data_dir import get_data_dir
from virttest.lvm import EmulatedLVM

from provider import backup_utils, job_utils
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlkdevIncWithIgnore(BlockdevLiveBackupBaseTest):
    """live backup with on-target-error:ignore"""

    def __init__(self, test, params, env):
        super(BlkdevIncWithIgnore, self).__init__(test, params, env)
        # TODO: Workaound lvm setup till VT enhances emulated image creation
        self.lv_size = params["lv_size"]
        params["lv_size"] = params["emulated_image_size"]
        self._lvm = EmulatedLVM(params, get_data_dir())

    def _create_inc_dir(self):
        try:
            self._lvm.setup()
            self._lvm.lvs[-1].resize(self.lv_size)
            process.system(
                self.params["storage_prepare_cmd"], ignore_status=False, shell=True
            )
        except:
            self._clean_inc_dir()
            raise

    def _clean_inc_dir(self):
        process.system(
            self.params["storage_clean_cmd"], ignore_status=False, shell=True
        )
        self._lvm.cleanup()

    def generate_tempfile(self, root_dir, filename, size="10M", timeout=360):
        super(BlkdevIncWithIgnore, self).generate_tempfile(
            root_dir, filename, self.params["tempfile_size"], timeout
        )

    def do_incremental_backup(self):
        extra_options = {
            "sync": self.params["inc_sync_mode"],
            "bitmap": self._bitmaps[0],
            "on-target-error": self.params["on_target_error"],
            "auto_disable_bitmap": False,
        }
        inc_backup = backup_utils.blockdev_backup_qmp_cmd
        cmd, arguments = inc_backup(
            self._source_nodes[0], self.params["inc_node"], **extra_options
        )
        self.main_vm.monitor.cmd(cmd, arguments)
        timeout = self.params.get("job_timeout", 600)
        job_id = arguments.get("job-id", self._source_nodes[0])
        get_event = job_utils.get_event_by_condition
        event = get_event(
            self.main_vm,
            job_utils.BLOCK_JOB_ERROR_EVENT,
            timeout,
            device=job_id,
            action="ignore",
        )
        if not event:
            self.test.fail("Backup job can't reach error after %s seconds" % timeout)
        process.system(self.params["lv_extend_cmd"], ignore_status=False, shell=True)
        job_utils.wait_until_block_job_completed(self.main_vm, job_id, timeout)

    def rebase_backup_images(self):
        """rebase inc to full"""
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        for image_tag in self._source_images:
            image_params = self.params.object_params(image_tag)
            image_chain = image_params.objects("image_backup_chain")
            snapshot_image = self.disk_define_by_params(self.params, image_chain[-1])
            for base_tag in image_chain[-2::-1]:
                base_image = self.disk_define_by_params(self.params, image_chain[-1])
                snapshot_image.base_tag = base_tag
                snapshot_image.base_format = base_image.get_format()
                base_image_filename = base_image.image_filename
                snapshot_image.base_image_filename = base_image_filename
                snapshot_image.rebase(snapshot_image.params)
                snapshot_image = base_image

    def prepare_test(self):
        self._create_inc_dir()
        self.prepare_main_vm()
        self.prepare_data_disks()
        self.add_target_data_disks()

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.do_incremental_backup()
        self.rebase_backup_images()
        self.prepare_clone_vm()
        self.verify_data_files()

    def post_test(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        super(BlkdevIncWithIgnore, self).post_test()
        self._clean_inc_dir()


def run(test, params, env):
    """
    live backup with on-target-error:ignore test

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file, record its md5sum
        4. add target disks full and inc, inc on a small space
        5. do full backup to full and add a bitmap
        6. create a new file, record its md5sum
        7. do incremental backup to inc to trigger block job error
        8. expend space for inc to wait block job completed
        9. shutdown vm, rebase inc to full
       10. start vm with inc, check files' md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    backup_test = BlkdevIncWithIgnore(test, params, env)
    backup_test.run_test()
