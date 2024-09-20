"""QSD QMP commands test"""

import json

from virttest.qemu_monitor import QMPCmdError

from provider.qsd import QsdDaemonDev


def run(test, params, env):
    """
    Test QSD QMP commands .
    Steps:
        1) Run QSD with one export vhost-user-blk.
        2) Check the export id existence.
        3) Delete relevant object,blockdev nodes and export
        3) Add relevant object,blockdev nodes and export
        3) Delete relevant object,blockdev nodes and export
    """

    logger = test.log
    qsd = None

    try:
        qsd_name = params["qsd_namespaces"]
        qsd = QsdDaemonDev(qsd_name, params)
        qsd.start_daemon()
        img = params["qsd_images_qsd1"]
        monitor = qsd.monitor

        img_attrs = qsd.images[img]
        obj_iothread = json.loads(params["obj_iothread"])
        obj_throttle = json.loads(params["obj_throttle"])
        prot_opts = img_attrs["protocol"]
        fmt_opts = img_attrs["format"]
        export_opts = img_attrs["export"]
        logger.debug("Check the export list")
        out = monitor.cmd("query-block-exports")
        test.assertTrue(out[0]["id"] == export_opts["id"], "Can not find export")

        logger.debug("Delete the export,blockdev and object")
        monitor.block_export_del(export_opts["id"])
        monitor.blockdev_del(fmt_opts["node-name"])
        monitor.blockdev_del(prot_opts["node-name"])
        monitor.query_block_exports()
        monitor.query_named_block_nodes()
        monitor.cmd("object-del", {"id": obj_iothread["id"]})

        logger.debug("Re-Add the object,blockdev and export")
        monitor.cmd("object-add", obj_iothread)
        monitor.cmd("object-add", obj_throttle)
        monitor.blockdev_add(prot_opts)
        monitor.blockdev_add(fmt_opts)
        filter_opts = {
            "driver": "throttle",
            "node-name": "filter_node",
            "throttle-group": obj_throttle["id"],
            "file": fmt_opts["node-name"],
        }
        monitor.blockdev_add(filter_opts)
        out = monitor.query_named_block_nodes()
        test.assertTrue(len(out) == 3, "Can not find blockdev")
        export_opts["node-name"] = filter_opts["node-name"]
        monitor.cmd("block-export-add", export_opts)
        out = monitor.query_block_exports()
        test.assertTrue(out[0]["id"] == export_opts["id"], "Can not find export")

        logger.debug("Re-Delete the export,blockdev and object")
        monitor.block_export_del(export_opts["id"])
        out = monitor.query_block_exports()
        test.assertTrue(len(out) == 0, "Export list is not empty")

        monitor.blockdev_del(filter_opts["node-name"])
        monitor.blockdev_del(fmt_opts["node-name"])
        monitor.blockdev_del(prot_opts["node-name"])
        out = monitor.query_named_block_nodes()
        test.assertTrue(len(out) == 0, "Blockdev list is not empty")

        monitor.cmd("qom-list", {"path": obj_throttle["id"]})
        monitor.cmd("object-del", {"id": obj_iothread["id"]})
        monitor.cmd("object-del", {"id": obj_throttle["id"]})
        with test.assertRaises(QMPCmdError):
            monitor.cmd("qom-list", {"path": obj_iothread["id"]})
        with test.assertRaises(QMPCmdError):
            monitor.cmd("qom-list", {"path": obj_throttle["id"]})

        qsd.stop_daemon()
        qsd = None
    finally:
        if qsd:
            qsd.stop_daemon()

    logger.info("Test Over")
