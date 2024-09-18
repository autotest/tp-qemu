from avocado.utils import process
from virttest import utils_misc

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest
from provider.job_utils import get_event_by_condition


class BlockdevMirrorQemuioReadyjob(BlockdevMirrorNowaitTest):
    """
    Qemuio source image when mirror job reach ready status
    """

    def qemuio_source_image(self):
        tag = self._source_images[0]
        image_params = self.params.object_params(tag)
        image = self.source_disk_define_by_params(image_params, tag)
        filename = image.image_filename
        fmt = image.image_format
        qemu_io = utils_misc.get_qemu_io_binary(self.params)
        qemuio_cmd = self.params.get("qemuio_cmd") % (qemu_io, fmt, filename)
        try:
            process.run(qemuio_cmd, shell=True)
        except process.CmdError as e:
            if self.params["error_msg"] not in e.result.stderr.decode():
                self.test.fail("Write to image that using by another process")
        else:
            self.test.fail("Can qemu-io a using image")

    def wait_till_job_ready(self):
        event = get_event_by_condition(
            self.main_vm,
            "BLOCK_JOB_READY",
            self.params.get_numeric("job_ready_timeout", 120),
            device=self._jobs[0],
        )
        if event is None:
            self.test.fail("Job failed to reach ready state")

    def do_test(self):
        self.blockdev_mirror()
        self.wait_till_job_ready()
        self.qemuio_source_image()


def run(test, params, env):
    """
    Qemuio source image when mirror job reach ready status

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. do blockdev-mirror
        6. wait until block job reach ready status, qemu-io source image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    qemuio_when_ready = BlockdevMirrorQemuioReadyjob(test, params, env)
    qemuio_when_ready.run_test()
