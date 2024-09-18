"""QSD blockdev option test"""

import json

from virttest import error_context

from provider.qsd import QsdDaemonDev


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Test pidfile option .
    Steps:
        1) Run QSD with different blockdev option.
        2) Check the blockdev option.
    """

    def _verify_blockdev(img, data):
        prot_attrs = json.loads(params.get("qsd_image_protocol_%s" % img, "{}"))
        fmt_attrs = json.loads(params.get("qsd_image_format_%s" % img, "{}"))
        prot_node = {}
        fmt_node = {}
        for node in data:
            if node["node-name"] == "prot_%s" % img:
                prot_node = node
            if node["node-name"] == "fmt_%s" % img:
                fmt_node = node
        if not fmt_node or not prot_node:
            test.fail("Can not find blockdev node")

        for attrs, node in zip((prot_attrs, fmt_attrs), (prot_node, fmt_node)):
            logger.info("Original attrs: %s", attrs)
            for k, v in attrs.items():
                if k in key_maps.keys():
                    k = key_maps[k]
                if k in node.keys():
                    logger.info("Checking img %s %s ", img, k)
                    if k == "cache":
                        v["writeback"] = True
                    test.assertEqual(v, node[k], "Find unequal key %s" % k)

    logger = test.log
    qsd = None
    try:
        key_maps = {"driver": "drv", "detect-zeroes": "detect_zeroes"}
        qsd_name = params["qsd_namespaces"]
        qsd = QsdDaemonDev(qsd_name, params)
        qsd.start_daemon()

        qsd.monitor.cmd("query-block-exports")
        out = qsd.monitor.cmd("query-named-block-nodes")
        qsd_params = params.object_params(qsd_name)
        qsd_images = qsd_params.get("qsd_images").split()
        for image in qsd_images:
            _verify_blockdev(image, out)
        qsd.stop_daemon()
        qsd = None
    finally:
        if qsd:
            qsd.stop_daemon()

    logger.info("Test Over")
