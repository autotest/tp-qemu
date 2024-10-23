from virttest import error_context

from qemu.tests import live_snapshot_stress


@error_context.context_aware
def run(test, params, env):
    """
    live_snapshot_integrity test:
       1). Boot up guest with cache=writethrough.
       2). Load stress in guest.
       3). dd file_base inside guest, record md5.
       4). do snapshot;
       5). dd file_sn1 inside guest, record md5.
       6). Unload stress, reboot guest with snapshot.
       7). Check file_base and file_sn1 md5.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    tag = params.get("source_image", "image1")
    stress_test = live_snapshot_stress.LiveSnapshotStress(test, params, env, tag)
    try:
        stress_test.action_before_start()
        file_names = params["file_names"].split()
        file_name_base = file_names[0]
        file_name_sn1 = file_names[1]
        stress_test.create_file(file_name_base)
        stress_test.create_snapshot()
        stress_test.create_file(file_name_sn1)
        stress_test.action_after_finished()
        format_postfix = ".%s" % params["image_format"]
        snapshot = stress_test.snapshot_file.replace(format_postfix, "")
        stress_test.reopen(snapshot)
        for name in file_names:
            stress_test.verify_md5(name)
    finally:
        stress_test.clean()
