"""
Bitmap-add test.

Add a bitmap with persistent on/off to drive with image raw/qcow2 and verify
its existence after system reboot.
"""

from virttest import error_context

from provider import block_dirty_bitmap


@error_context.context_aware
def run(test, params, env):
    """Bitmap test.

    1. get target image and drive.
    2. add bitmap.
    3. check bitmap existence.
        a) if existed, check after system_powerdown

    :param test: vt test object
    :param params: test parameters dictionary
    :param env: test environment
    """

    def check_bitmap_existence_as_expected(bitmaps, existence_param):
        """Check bitmaps' existence."""
        bitmap_dict = block_dirty_bitmap.get_bitmaps(vm.monitor.info("block"))
        test.log.debug("bitmaps:\n%s", bitmap_dict)
        msgs = []
        for bitmap_params in bitmaps:
            bitmap = bitmap_params.get("bitmap_name")
            existence = bitmap_params.get(existence_param, "yes") == "yes"
            if not block_dirty_bitmap.check_bitmap_existence(
                bitmap_dict, bitmap_params, existence
            ):
                msg = "bitmap %s %s exists" % (bitmap, "not" if existence else "")
                msgs.append(msg)
        if msgs:
            test.fail("\n".join(msgs))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    # wait till boot finishes
    vm.wait_for_login(timeout=int(params.get("login_timeout", 360))).close()

    bitmaps = block_dirty_bitmap.parse_params(vm, params)
    error_context.context("add dirty bitmap")
    for bitmap_params in bitmaps:
        block_dirty_bitmap.block_dirty_bitmap_add(vm, bitmap_params)

    error_context.context("check bitmap existence", test.log.info)
    check_bitmap_existence_as_expected(bitmaps, "existence")

    error_context.context("Shutting down the guest", test.log.info)
    vm.graceful_shutdown(params.get_numeric("shutdown_timeout", 360))
    if not vm.wait_for_shutdown():
        test.fail("guest refuses to go down")

    error_context.context("start vm", test.log.info)
    vm.create()
    vm.verify_alive()
    # wait till boot finishes
    vm.wait_for_login(timeout=int(params.get("login_timeout", 360))).close()

    error_context.context("check bitmap exsitence after shutdown", test.log.info)
    check_bitmap_existence_as_expected(bitmaps, "existence_after_shutdown")
