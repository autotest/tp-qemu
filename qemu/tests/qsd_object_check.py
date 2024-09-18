"""QSD throttle object test"""

from virttest import error_context

from provider.qsd import QsdDaemonDev


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Test QSD throttle object .
    Steps:
        1) Run QSD with throttle node.
        2) Check throttle object attribute.
    """
    logger = test.log
    qsd = None
    try:
        qsd = QsdDaemonDev("qsd1", params)
        qsd.start_daemon()

        qsd.monitor.cmd("query-block-exports")
        qsd.monitor.cmd("query-named-block-nodes")
        for tg in params["check_groups"].split():
            logger.info("Check throttle %s", tg)
            out = qsd.monitor.qom_get(tg, "limits")
            test.assertEqual(
                out[params["key_%s" % tg]],
                int(params["value_%s" % tg]),
                "Unexpected throttle values :%s" % tg,
            )
        qsd.stop_daemon()
        qsd = None
    finally:
        if qsd:
            qsd.stop_daemon()

    logger.info("Test Over")
