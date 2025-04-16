from virttest import data_dir
from virttest.iscsi import Iscsi


def run(test, params, env):
    """
    Usage of multi-targets iscsi.


    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    vm = None
    iscsi = None
    logger = test.log

    try:
        logger.info("Create iscsi disk.")
        base_dir = data_dir.get_data_dir()
        iscsi = Iscsi.create_iSCSI(params, base_dir)
        iscsi.export_target()  # or iscsi.export_target(target=["xxx"])
        iscsi.login()  # or iscsi.login(target=["xxx"])
        targets = iscsi.query_targets()  # or iscsi.query_targets(target=["xxx"])
        test.log.debug("iscsi.query_targets() returns: ")
        test.log.debug(str(targets))

        dev_name = iscsi.get_device_names()  # or iscsi.get_device_names(target=["xxx"])
        test.log.debug("iscsi.get_device_names() returns: ")
        test.log.debug(str(dev_name))
    finally:
        logger.info("cleanup")
        if vm and vm.is_alive():
            vm.destroy()
        if iscsi:
            iscsi.cleanup(confirmed=True)
