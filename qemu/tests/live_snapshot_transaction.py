from virttest import error_context

from qemu.tests import live_snapshot_basic


@error_context.context_aware
def run(test, params, env):
    """
    live_snapshot_transaction test:

    1. Boot up guest with a system disk and 2 data disk.
    2. Create multiple live snapshots simultaneously for all 3 disks with transaction.
    3. Check guest which should boot up and reboot successfully.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    arg_list = []
    try:
        for image in params.objects("images"):
            image_params = params.object_params(image)
            transaction_test = live_snapshot_basic.LiveSnapshot(
                test, image_params, env, image
            )
            transaction_test.snapshot_args.update({"device": transaction_test.device})
            transaction_test.snapshot_file = image + "-snap"
            snapshot_file = transaction_test.get_snapshot_file()
            transaction_test.snapshot_args.update({"snapshot-file": snapshot_file})
            args = {
                "type": "blockdev-snapshot-sync",
                "data": transaction_test.snapshot_args,
            }
            arg_list.append(args)

        error_context.context(
            "Create multiple live snapshots simultaneously" " with transaction",
            test.log.info,
        )
        output = transaction_test.vm.monitor.transaction(arg_list)
        # return nothing on successful transaction
        if bool(output):
            test.fail(
                "Live snapshot transatcion failed,"
                " there should be nothing on success.\n"
                "More details: %s" % output
            )
        transaction_test.action_after_finished()
    finally:
        try:
            transaction_test.clean()
        except Exception:
            pass
