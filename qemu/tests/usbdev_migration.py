from autotest.client.shared import error
from virttest.utils_test import qemu


@error.context_aware
def run(test, params, env):
    """
    KVM usb device check test:
    1) Log into a guest
    2) Verify if the vm with usb device can be migrated

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    usb = qemu.UsbDevTest(test, params, env)
    usb.local_migration_usbdev(params.get("usb_type"),
                               params.get("mig_protocol"))
