"""QSD export vhost-user-blk option test"""

from virttest import error_context

from provider.qsd import QsdDaemonDev


@error_context.context_aware
def run(test, params, env):
    """
    Test pidfile option .
    Steps:
        1) Run QSD with different export vhost-user-blk option.
        2) Check the export number.
    """

    logger = test.log
    qsd = None
    try:
        qsd_name = params["qsd_namespaces"]
        qsd = QsdDaemonDev(qsd_name, params)
        qsd.start_daemon()

        out = qsd.monitor.cmd("query-block-exports")
        qsd_params = params.object_params(qsd_name)
        qsd_images = qsd_params.get("qsd_images").split()
        if len(qsd_images) != len(out):
            test.fail("Find mismatch number of export")
        qsd.stop_daemon()
        qsd = None
    finally:
        if qsd:
            qsd.stop_daemon()

    logger.info("Test Over")
