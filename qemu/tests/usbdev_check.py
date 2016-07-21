from autotest.client.shared import error
from virttest.utils_test import qemu


@error.context_aware
def run(test, params, env):
    """
    KVM usb device check test:
    1) Log into a guest
    2) Verify usb device in guest and monitor

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    check = qemu.UsbDevTest(test, params, env)
    check.check_usb_dev(params.get("usb_type"))
