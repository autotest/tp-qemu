import logging

from virttest import error_context, guest_agent

from generic.tests.guest_suspend import GuestSuspendBaseTest
from qemu.tests.qemu_guest_agent import QemuGuestAgentTest

LOG_JOB = logging.getLogger("avocado.test")


class SuspendViaGA(GuestSuspendBaseTest):
    guest_agent = None
    suspend_mode = ""

    @error_context.context_aware
    def start_suspend(self, **args):
        """
        Start suspend via qemu guest agent.
        """
        error_context.context("Suspend guest via guest agent", LOG_JOB.info)
        if self.guest_agent:
            self.guest_agent.suspend(self.suspend_mode)


class QemuGASuspendTest(QemuGuestAgentTest):
    """
    Test qemu guest agent, this case will:
    1) Start VM with virtio serial port.
    2) Install qemu-guest-agent package in guest.
    3) Create QemuAgent object.
    4) Run suspend test with guest agent.
    """

    def run_once(self, test, params, env):
        QemuGuestAgentTest.run_once(self, test, params, env)

        error_context.context("Suspend guest to memory", LOG_JOB.info)
        gs = SuspendViaGA(params, self.vm)
        gs.guest_agent = self.gagent
        gs.suspend_mode = guest_agent.QemuAgent.SUSPEND_MODE_RAM
        gs.guest_suspend_mem(params)

        error_context.context("Suspend guest to disk", LOG_JOB.info)
        gs.suspend_mode = guest_agent.QemuAgent.SUSPEND_MODE_DISK
        gs.guest_suspend_disk(params)

        # Reset guest agent object to None after guest reboot.
        self.gagent = None
        error_context.context("Check if guest agent work again.", LOG_JOB.info)
        session = self._get_session(params, self.vm)
        self.gagent_start(session, self.vm)
        session.close()
        args = [params.get("gagent_serial_type"), params.get("gagent_name")]
        self.gagent_create(params, self.vm, *args)
        self.gagent.verify_responsive()


@error_context.context_aware
def run(test, params, env):
    """
    Test suspend commands in qemu guest agent.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    gagent_test = QemuGASuspendTest(test, params, env)
    gagent_test.execute(test, params, env)
