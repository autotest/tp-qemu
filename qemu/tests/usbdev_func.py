from virttest.utils_test import qemu


def run(test, params, env):
    """
    KVM usb device check test:
    1) Log into a guest
    2) Verify the function of usb device

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def io_without_fs(disklist, session):
        for devname in disklist:
            dev.usb_disk_io('no', devname, session)

    def io_with_fs(disklist, session):
        for devname in disklist:
            dev.format_usb_disk(devname, session)
            dev.usb_disk_io('yes', devname, session)

    vm = env.get_vm(params["main_vm"])
    dev = qemu.UsbStorageTest(test, params, env)
    dev.add_udisk()
    timeout = float(params.get("login_timeout", 600))
    session = vm.wait_for_login(timeout=timeout)
    disklist = dev.get_usb_disk_list(session)
    function = params.get("function")
    if function and hasattr(function, '__call__'):
        eval(function)(disklist, session)
