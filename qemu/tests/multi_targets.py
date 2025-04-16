from virttest import data_dir
from virttest.iscsi import Iscsi


def run(test, params, env):
    """
    Usage of multi-targets iscsi.


    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    base_dir = data_dir.get_data_dir()
    mgr = Iscsi.create_iSCSI(params, base_dir)
    mgr.export_target()  # or mgr.export_target(target=xxx)
    mgr.login()  # or iscsi.login(target=xxx)
    targets = mgr.query_targets()  # or iscsi.query_targets(target=xxx)
    test.log.debug("mgr.query_targets() returns: ")
    test.log.debug(str(targets))

    dev_name = mgr.get_device_names()  # or iscsi.get_device_names(target=xxx)
    test.log.debug("mgr.get_device_names() returns: ")
    test.log.debug(str(dev_name))
    mgr.logout()

    mgr.cleanup()
