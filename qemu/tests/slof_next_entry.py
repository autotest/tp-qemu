from virttest import error_context

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify that next-entry will get unset after reboot.

    Step:
     1) Check if any error info in output of SLOF during booting.
     2) Ensure the guest has at least two kernel versions.
     3) Set a boot next entry and check it.
     4) Reboot guest, check the kernel version and value of next_entry.
     5) Reboot guest again, continue to check the kernel version.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_kernels_info():
        """Get detailed information about each kernel version in the guest."""
        kernels_info = {}
        for kernel in kernel_list:
            grubby_info = session.cmd_output(
                "grubby --info=%s" % kernel, print_func=test.log.info
            )
            entry_dict = dict(
                (
                    item.replace('"', "").split("=", 1)
                    for item in grubby_info.splitlines()
                )
            )
            kernels_info[int(entry_dict.pop("index"))] = entry_dict
        return kernels_info

    def check_kernel_version(k_index):
        """Check whether the kernel version matches the kernel index."""
        current_kernel = session.cmd_output("uname -r").strip()
        if guest_kernels[k_index]["kernel"].split("-", 1)[1] != current_kernel:
            test.log.debug("The current kernel version is: %s", current_kernel)
            test.fail("The current kernel version is different from expected")
        test.log.info("The kernel version matches the kernel index")

    get_kernel_list_cmd = params["get_kernel_list_cmd"]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.base_context("Check the output of SLOF.", test.log.info)
    content = slof.wait_for_loaded(vm, test)[0]
    slof.check_error(test, content)
    session = vm.wait_for_login()

    test.log.info("Ensure the guest has at least two kernel versions")
    kernel_list = session.cmd_output(get_kernel_list_cmd).splitlines()
    if len(kernel_list) < 2:
        test.cancel("This test requires at least two kernel versions in the " "guest")
    if session.cmd_output("grubby --default-index").strip() != "0":
        test.log.info("Ensure that the default kernel index of the guest is 0.")
        session.cmd("grubby --set-default-index=0")
        session = vm.reboot()

    guest_kernels = get_kernels_info()
    error_context.context(
        "Set a next boot entry other than the default one and" " check it",
        test.log.info,
    )
    next_entry = guest_kernels[1]["title"]
    session.cmd("grub2-reboot '%s'" % next_entry)
    grub_env = dict(
        (
            item.split("=", 1)
            for item in session.cmd_output("grub2-editenv list").splitlines()
        )
    )
    grub_next_entry = grub_env["next_entry"]
    if grub_next_entry != next_entry:
        test.log.debug("The 'next_entry' is: %s", grub_next_entry)
        test.fail("The next boot entry is not expected as we set")

    error_context.base_context(
        "Reboot guest, check the kernel version and " "'next_entry'", test.log.info
    )
    session = vm.reboot(session)
    grub_env = dict(
        (
            item.split("=", 1)
            for item in session.cmd_output("grub2-editenv list").splitlines()
        )
    )
    check_kernel_version(1)
    grub_next_entry = grub_env["next_entry"]
    if grub_next_entry:
        test.log.debug("The 'next_entry' is: %s", grub_next_entry)
        test.fail("The 'next_entry' did not return to empty after reboot")

    error_context.context("Reboot guest again to check the kernel version")
    session = vm.reboot(session)
    check_kernel_version(0)

    session.close()
    vm.destroy(gracefully=True)
