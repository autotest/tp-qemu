"""
slof_order.py include following case:
 1. After boot from disk failed, slof will try to boot from network.
 2. After boot from disk failed, slof will stop booting.
 3. Guest boot from network only on the first startup.
 4. Guest boot from cdrom with the network and the first hard disk
    are both not bootable.
"""

from virttest import env_process, error_context

from provider import slof


@error_context.context_aware
def run(test, params, env):
    """
    Verify the boot order from SLOF.

    Step:
     Scenario 1:
      1.1 Boot a guest with an empty disk, cdrom and nic, and don't
          specify disk bootindex=0, then set "order=cdn,once=n,menu=off,
          strict=off" for boot options.
      1.2 Check the boot order which should be nic->disk->cdrom->nic.
     Scenario 2:
      2.1 Boot a guest with an empty disk and nic, and don't specify
          this device bootindex=0, then set "order=cdn,once=n, menu=off,
          strict=off" for boot options.
      2.2 Check the boot order which should be nic->disk->nic.
     Scenario 3:
      3.1 Boot a guest with an empty disk, specify this device
          bootindex=0, then set "order=cdn,once=n,menu=off,strict=on" for
          boot options.
      3.2 Check the boot order which should be just disk.
     Scenario 4:
      4.1 Boot a guest with an empty disk and nic, specify this device
          bootindex=0, then set "order=cdn,once=n,menu=off,strict=off" for
          boot options.
      4.2 Check the boot order which should be disk->nic.

    :param test: Qemu test object.
    :param params: Dictionary with the test .
    :param env: Dictionary with test environment.
    """

    def _send_custom_key():
        """Send custom keyword to SLOF's user interface."""
        test.log.info('Sending "%s" to SLOF user interface.', send_key)
        for key in send_key:
            key = "minus" if key == "-" else key
            vm.send_key(key)
        vm.send_key("ret")

    def _verify_boot_order(order):
        """Verify the order of booted devices."""
        for index, dev in enumerate(order.split()):
            args = device_map[dev]
            details = "The device({}@{}) is not the {} bootable device.".format(
                args[1], args[2], index
            )
            if not slof.verify_boot_device(
                content, args[0], args[1], args[2], position=index
            ):
                test.fail("Fail: " + details)
            test.log.info("Pass: %s", details)

    parent_bus = params.get("parent_bus")
    child_bus = params.get("child_bus")
    parent_bus_nic = params.get("parent_bus_nic")
    child_bus_nic = params.get("child_bus_nic")
    send_key = params.get("send_key")
    device_map = {
        "c": (parent_bus, child_bus, params.get("disk_addr")),
        "d": (parent_bus, child_bus, params.get("cdrom_addr")),
        "n": (parent_bus_nic, child_bus_nic, params.get("nic_addr")),
    }
    env_process.process(
        test, params, env, env_process.preprocess_image, env_process.preprocess_vm
    )
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    content, next_pos = slof.wait_for_loaded(vm, test, end_str="0 >")
    _verify_boot_order(params["order_before_send_key"])
    if send_key in ("reset-all", "boot"):
        error_context.context("Reboot guest by sending key.", test.log.info)
        _send_custom_key()
        content, _ = slof.wait_for_loaded(vm, test, next_pos, end_str="0 >")
        _verify_boot_order(params["order_after_send_key"])
