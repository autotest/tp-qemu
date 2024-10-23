from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    this case will:
    1) Boot guest with virtio devices and iommu is on.
    2) Check whether the iommu group is seperated correctly.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def verify_iommu_group():
        """Verify whether the iommu group is seperated correctly."""
        error_context.context(
            "Verify whether the iommu group is seperated correctly.", test.log.info
        )
        device_id = (
            session.cmd(
                "lspci | grep 'PCIe\\|Virtio\\|USB\\|VGA\\|PCI' | awk '{print $1}'"
            )
            .strip()
            .split()
        )
        group_id = []
        for id in device_id:
            g_id = session.cmd(
                """dmesg | grep "iommu group" | grep '%s' | awk -F " " '{print $NF}'"""
                % ("0000:" + id)
            ).strip()
            if g_id == "":
                test.fail("Device ID: '%s' didn't in iommu group" % id)
            else:
                group_id.append(g_id)
            test.log.info("Group ID of %s: %s", id, g_id)

        if len(set(group_id)) != len(group_id):
            test.fail("iommu group is not seperated correctly")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login()
    verify_iommu_group()

    session.close()
