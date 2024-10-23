import logging

from virttest import env_process, error_context

from qemu.tests import drive_mirror_stress

LOG_JOB = logging.getLogger("avocado.test")


class DriveMirrorPowerdown(drive_mirror_stress.DriveMirrorStress):
    def __init__(self, test, params, env, tag):
        super(DriveMirrorPowerdown, self).__init__(test, params, env, tag)

    @error_context.context_aware
    def powerdown(self):
        """
        power down guest via quit qemu;
        """
        error_context.context("powerdown vm", LOG_JOB.info)
        return self.vm.destroy()

    @error_context.context_aware
    def powerup(self):
        """
        bootup guest with target image;
        """
        params = self.parser_test_args()
        vm_name = params["main_vm"]
        LOG_JOB.info("Target image: %s", self.target_image)
        error_context.context("powerup vm with target image", LOG_JOB.info)
        env_process.preprocess_vm(self.test, params, self.env, vm_name)
        vm = self.env.get_vm(vm_name)
        vm.verify_alive()
        self.vm = vm


def run(test, params, env):
    """
    drive_mirror_powerdown test:
    1). boot guest, do kernel build
    3). mirror boot disk to target image
    4). wait mirroring go into ready status then quit qemu
    5). bootup guest with target image
    6). check guest can response correctly

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    powerdown_test = DriveMirrorPowerdown(test, params, env, tag)
    try:
        powerdown_test.action_before_start()
        powerdown_test.start()
        powerdown_test.action_when_steady()
        powerdown_test.powerup()
        powerdown_test.action_after_reopen()
    finally:
        powerdown_test.clean()
