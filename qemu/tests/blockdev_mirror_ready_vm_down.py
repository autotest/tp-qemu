import time

from virttest import utils_misc, utils_qemu
from virttest.utils_version import VersionInterval

from provider import job_utils
from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorReadyVMDownTest(BlockdevMirrorNowaitTest):
    """
    VM poweroff when mirror job is ready
    """

    def poweroff_vm(self):
        self.main_vm.monitor.system_powerdown()

    def wait_mirror_jobs_ready(self):
        def _wait_mirror_job_ready(jobid):
            tmo = self.params.get_numeric("job_ready_timeout", 600)
            job_utils.wait_until_job_status_match(self.main_vm, "ready", jobid, tmo)

        list(map(_wait_mirror_job_ready, self._jobs))

    def wait_mirror_jobs_auto_completed(self):
        """job completed automatically after vm poweroff"""

        def _wait_mirror_job_completed(jobid):
            tmo = self.params.get_numeric("job_completed_timeout", 200)
            for i in range(tmo):
                events = self.main_vm.monitor.get_events()
                completed_events = [
                    e
                    for e in events
                    if e.get("event") == job_utils.BLOCK_JOB_COMPLETED_EVENT
                ]
                job_events = [
                    e
                    for e in completed_events
                    if e.get("data")
                    and jobid in (e["data"].get("id"), e["data"].get("device"))
                ]
                if job_events:
                    break
                time.sleep(1)
            else:
                self.test.fail("job complete event never received in %s" % tmo)

        list(map(_wait_mirror_job_completed, self._jobs))

    def wait_mirror_jobs_cancelled(self):
        """job cancelled after vm poweroff since qemu6.2"""

        def _wait_mirror_job_cancelled(jobid):
            tmo = self.params.get_numeric("job_cancelled_timeout", 200)
            for i in range(tmo):
                events = self.main_vm.monitor.get_events()
                cancelled_events = [
                    e
                    for e in events
                    if e.get("event") == job_utils.BLOCK_JOB_CANCELLED_EVENT
                ]
                job_events = [
                    e
                    for e in cancelled_events
                    if e.get("data")
                    and jobid in (e["data"].get("id"), e["data"].get("device"))
                ]
                if job_events:
                    break
                time.sleep(1)
            else:
                self.test.fail("job cancelled event not received in %s" % tmo)

        list(map(_wait_mirror_job_cancelled, self._jobs))

    def wait_mirror_jobs_done(self):
        qemu_binary = utils_misc.get_qemu_binary(self.params)
        qemu_version = utils_qemu.get_qemu_version(qemu_binary)[0]
        required_qemu_version = self.params["required_qemu_version"]
        if qemu_version in VersionInterval(required_qemu_version):
            self.wait_mirror_jobs_cancelled()
        else:
            self.wait_mirror_jobs_auto_completed()

    def do_test(self):
        self.blockdev_mirror()
        self.wait_mirror_jobs_ready()
        self.poweroff_vm()
        self.wait_mirror_jobs_done()


def run(test, params, env):
    """
    VM poweroff when mirror job is ready

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. do blockdev-mirror
        6. wait till mirror job is ready
        7. poweroff vm
        8. check mirror job completed/cancelled since qemu6.2

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorReadyVMDownTest(test, params, env)
    mirror_test.run_test()
