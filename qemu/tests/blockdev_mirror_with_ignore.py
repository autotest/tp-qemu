from avocado.utils import process

from provider import job_utils
from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorWithIgnore(BlockdevMirrorNowaitTest):
    """Block mirror with error ignore on target"""

    def blockdev_mirror(self):
        super(BlockdevMirrorWithIgnore, self).blockdev_mirror()
        timeout = self.params.get("job_timeout", 600)
        for job_id in self._jobs:
            get_event = job_utils.get_event_by_condition
            event = get_event(
                self.main_vm,
                job_utils.BLOCK_JOB_ERROR_EVENT,
                timeout,
                device=job_id,
                action="ignore",
            )
            if not event:
                self.test.fail(
                    "Mirror job can't reach error after %s seconds" % timeout
                )
        process.system(self.params["lv_extend_cmd"], ignore_status=False, shell=True)
        self.wait_mirror_jobs_completed()


def run(test, params, env):
    """
    Block mirror with '"on-target-error": "ignore"'

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. hotplug a target disk(actual size < 2G) for mirror
        5. do block-mirror with sync mode full
        6. check the mirror job report error
        7. extend the target actual disk
        8. wait until mirror job finished
        9. destroy vm, start vm with mirror image, check files md5

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorWithIgnore(test, params, env)
    mirror_test.run_test()
