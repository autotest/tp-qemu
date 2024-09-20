"""QSD pidfile option test"""

import os

from avocado.utils import process
from virttest import error_context

from provider.qsd import QsdDaemonDev


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Test pidfile option .
    Steps:
        1) Run QSD with pidfile option.
        2) Check the pidfile exist.
        3) Check qsd process by content of pidfile.
        4) Kill QSD then check the pidfile whether exist.
    """
    logger = test.log
    qsd = None
    try:
        qsd = QsdDaemonDev("qsd1", params)
        qsd.start_daemon()

        pidfile = qsd.pidfile
        logger.info("Check pidfile %s", pidfile)
        test.assertTrue(os.path.exists(pidfile), "QSD pidfile is nonexistent")

        pid_check_cmd = params["pid_check_cmd"] % (pidfile, qsd.sock_path)
        process.system(pid_check_cmd, shell=True)

        qsd.monitor = None
        qsd.stop_daemon()
        test.assertFalse(os.path.exists(pidfile), "QSD pidfile still exist")
        qsd = None
    finally:
        if qsd:
            qsd.stop_daemon()

    logger.info("Test Over")
