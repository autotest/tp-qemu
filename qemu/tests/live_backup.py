from virttest import error_context

from qemu.tests import live_backup_base


@error_context.context_aware
def run(test, params, env):
    """
    Live backup test:
    1). Pre full backup action, including stop vm
    2). Create bitmap and full backup, with transaction if defined.
    3). Post full backup action, including resume vm
        and make vm running for a while.
    4). Pre incremental backup action, including stop vm
    5). Create incremental backup image based on
        full backup
    6). Start incremental backup
    7). Post incremental backup actions
    8). check backup images.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    backup_test = live_backup_base.LiveBackup(test, params, env, tag)
    try:
        backup_test.before_full_backup()
        backup_test.create_backup("full")
        backup_test.after_full_backup()
        backup_test.before_incremental()
        incremental_image = backup_test.create_backup_image()
        backup_test.create_backup("incremental", incremental_image)
        backup_test.after_incremental()
        backup_test.backup_check()
    finally:
        backup_test.clean()
