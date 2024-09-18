from virttest import error_context

from qemu.tests import live_snapshot_basic


@error_context.context_aware
def run(test, params, env):
    """
    live_snapshot_simple test:
    1). Create snapshot with different configurations.
    2). Verify guest is fine when snapshot finished(optional)

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    simple_test = live_snapshot_basic.LiveSnapshot(test, params, env, tag)
    try:
        simple_test.create_snapshot()
        simple_test.action_after_finished()
    finally:
        simple_test.clean()
