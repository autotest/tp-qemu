import time

from avocado.utils import process
from virttest.data_dir import get_data_dir
from virttest.lvm import EmulatedLVM

from provider import job_utils
from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest


class BlockdevStreamOnErrorIgnoreTest(BlockdevStreamNowaitTest):
    """Do block-stream with on-error:ignore"""

    def __init__(self, test, params, env):
        super(BlockdevStreamOnErrorIgnoreTest, self).__init__(test, params, env)
        # TODO: Workaound lvm setup till VT enhances emulated image creation
        self.lv_size = params["lv_size"]
        params["lv_size"] = params["emulated_image_size"]
        self._lvm = EmulatedLVM(params, get_data_dir())

    def _create_snapshot_dir(self):
        self._lvm.setup()
        self._lvm.lvs[-1].resize(self.lv_size)
        process.system(
            self.params["storage_prepare_cmd"], ignore_status=False, shell=True
        )

    def _clean_snapshot_dir(self):
        process.system(
            self.params["storage_clean_cmd"], ignore_status=False, shell=True
        )
        self._lvm.cleanup()

    def generate_tempfile(self, root_dir, filename, size="10M", timeout=360):
        super(BlockdevStreamOnErrorIgnoreTest, self).generate_tempfile(
            root_dir, filename, self.params["tempfile_size"], timeout
        )

    def pre_test(self):
        try:
            self._create_snapshot_dir()
        except Exception:
            self._clean_snapshot_dir()
            self.test.error("Failed to setup lvm env")
        super(BlockdevStreamOnErrorIgnoreTest, self).pre_test()

    def post_test(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        self.snapshot_image.remove()
        self._clean_snapshot_dir()

    def check_job_error_event(self):
        """
        Check if BLOCK_JOB_ERROR can be received, then clear all
        """
        tmo = self.params.get_numeric("job_error_timeout", 120)
        event = job_utils.get_event_by_condition(
            self.main_vm,
            job_utils.BLOCK_JOB_ERROR_EVENT,
            tmo,
            device=self._job,
            action="ignore",
        )

        if not event:
            self.test.fail(
                "Failed to get BLOCK_JOB_ERROR event for %s in %s" % (self._job, tmo)
            )
        self.main_vm.monitor.clear_event(job_utils.BLOCK_JOB_ERROR_EVENT)

    def extend_lv_size(self):
        process.system(self.params["lv_extend_cmd"], ignore_status=False, shell=True)
        time.sleep(5)

    def wait_until_job_complete_with_error(self):
        try:
            job_utils.wait_until_block_job_completed(self.main_vm, self._job)
        except AssertionError as e:
            if self.params["error_msg"] not in str(e):
                self.test.fail(str(e))
        else:
            self.test.fail("stream completed without error 'No space left'")

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        self.check_job_error_event()
        self.extend_lv_size()
        self.wait_until_job_complete_with_error()


def run(test, params, env):
    """
    Do block stream test with on-error:ignore

    test steps:
        1. boot VM
        2. create an image by dd, then control it by lvm, create a fs
           whose size < size of system image
        3. add a snapshot image under fs created in step 2
        4. take snapshot for system image
        5. do block-stream with on-error:ignore
        6. check BLOCK_JOB_ERROR is always received
        7. extend lv
        8. check BLOCK_JOB_COMPLETE with No space left on device

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamOnErrorIgnoreTest(test, params, env)
    stream_test.run_test()
