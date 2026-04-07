from virttest import data_dir, qemu_storage

from provider import backup_utils, job_utils
from provider.blockdev_mirror_base import BlockdevMirrorBaseTest
from provider.storage_benchmark import generate_instance


class BlockdevMirrorPauseAndCompareTest(BlockdevMirrorBaseTest):
    """Pause VM immediately after starting block-mirror with background fio test"""

    def fio_run_bg(self):
        fio_options = self.params.get("fio_options")
        if fio_options:
            if "refill_buffers" not in fio_options:
                fio_options += " --refill_buffers"
            self.test.log.info("Start to run fio")
            self.fio = generate_instance(self.params, self.main_vm, "fio")
            fio_run_timeout = self.params.get_numeric("fio_timeout", 2400)
            self.fio.run(fio_options, fio_run_timeout)

    def do_test(self):
        self.fio_run_bg()

        try:
            job_ids = []
            for idx, source_node in enumerate(self._source_nodes):
                job_id = backup_utils.blockdev_mirror_nowait(
                    self.main_vm,
                    source_node,
                    self._target_nodes[idx],
                    **self._backup_options[idx],
                )
                job_ids.append(job_id)

            # Immediately pause the VM
            self.test.log.info(
                "Pause the VM immediately after starting the mirror jobs"
            )
            self.main_vm.pause()

            for job_id in job_ids:
                job_utils.wait_until_block_job_completed(
                    self.main_vm, job_id, timeout=900
                )

            # When the mirror job has completed, compare the source and target image.
            self.test.log.info("Compare the source and target images")
            for src_tag, tgt_tag in zip(self._source_images, self._target_images):
                src_img_obj = qemu_storage.QemuImg(
                    self.params.object_params(src_tag), data_dir.get_data_dir(), src_tag
                )
                tgt_img_obj = qemu_storage.QemuImg(
                    self.params.object_params(tgt_tag), data_dir.get_data_dir(), tgt_tag
                )

                src_path = src_img_obj.image_filename
                tgt_path = tgt_img_obj.image_filename

                self.test.log.info("Comparing %s with %s", src_path, tgt_path)
                src_img_obj.compare_images(src_path, tgt_path, force_share=True)

        finally:
            if self.main_vm.is_paused():
                self.main_vm.resume()
            if hasattr(self, "fio"):
                self.fio.clean(force=True)


def run(test, params, env):
    """
    Basic block mirror test with fio and pausing immediately

    test steps:
        1. Start a write stress test in the guest
        2. Start a mirror job
        3. Immediately pause the VM
        4. Wait until the mirror job is ready and complete it
        5. Compare the source and target image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorPauseAndCompareTest(test, params, env)
    mirror_test.run_test()
