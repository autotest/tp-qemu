"""
rv_smartcard.py - Testing software smartcards using remote-viewer

Requires: connected binaries remote-viewer, Xorg, gnome session

The test also assumes that the guest is setup with the correct
options to handle smartcards.

"""


def run(test, params, env):
    """
    Tests disconnection of remote-viewer.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    # Get the required parameters needed for the tests
    cert_list = params.get("gencerts").split(",")
    cert_db = params.get("certdb")
    smartcard_testtype = params.get("smartcard_testtype")
    listcerts_output = ""
    certsinfo_output = ""
    searchstr = params.get("certcheckstr")
    certstr = params.get("certcheckstr2")
    certcheck1 = params.get("certcheck3")
    certcheck2 = params.get("certcheck4")

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)),
        username="root",
        password="123456",
    )

    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()

    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)),
        username="root",
        password="123456",
    )
    # Verify remote-viewer is running
    try:
        pid = client_session.cmd("pgrep remote-viewer")
        test.log.info("remote-viewer is running as PID %s", pid.strip())
    except:
        test.fail("remote-viewer is not running")

    # verify the smart card reader can be seen
    output = guest_session.cmd("lsusb")
    test.log.debug("lsusb output: %s", output)
    if "Gemalto (was Gemplus) GemPC433-Swap" in output:
        test.log.info("Smartcard reader, Gemalto GemPC433-Swap detected.")
    else:
        test.fail("No smartcard reader found")

    if smartcard_testtype == "pkcs11_listcerts":
        # pkcs11_listcerts not installed until Smart Card Support is installed
        try:
            output = guest_session.cmd_output("pkcs11_listcerts")
        except:
            # Expected to get a shell timeout error,
            # listing certs prompts for PIN
            try:
                # Send a carriage return for PIN for token
                listcerts_output = guest_session.cmd("")
            except:
                test.fail("Test failed trying to get the output of pkcs11_listcerts")

        test.log.info("Listing Certs available on the guest:  %s", listcerts_output)

        for cert in cert_list:
            subj_string = "CN=" + cert
            if subj_string in listcerts_output:
                test.log.debug(
                    "%s has been found as a listed cert in the guest", subj_string
                )
            else:
                test.fail(
                    "Certificate %s was not found as a listed"
                    " cert in the guest" % subj_string
                )
    elif smartcard_testtype == "pklogin_finder":
        # pkcs11_listcerts not installed until
        # Smart Card Support is installed
        try:
            certsinfo_output = guest_session.cmd("pklogin_finder debug")
        except:
            # Expected to get a shell timeout error,
            # listing certs prompts for PIN
            try:
                # Send a carriage return for PIN for token
                certsinfo_output = guest_session.cmd("", ok_status=[0, 1])
            except:
                test.fail("Test failed trying to get the output of pklogin_finder")
        testindex = certsinfo_output.find(searchstr)
        if testindex >= 0:
            string_aftercheck = certsinfo_output[testindex:]

            # Loop through the cert list. and check for the expected data, and
            for index, cert in enumerate(cert_list):
                subj_string = "CN=" + cert
                checkstr = certstr + str(index + 1)
                testindex = string_aftercheck.find(checkstr)
                # print testindex
                if testindex >= 0:
                    test.log.debug("Found %s in output of pklogin", checkstr)
                    string_aftercheck = string_aftercheck[testindex:]
                    testindex2 = string_aftercheck.find(subj_string)
                    if testindex >= 0:
                        test.log.debug("Found %s in output of pklogin", subj_string)
                        string_aftercheck = string_aftercheck[testindex2:]
                        testindex3 = string_aftercheck.find(certcheck1)
                        if testindex3 >= 0:
                            test.log.debug("Found %s in output of pklogin", certcheck1)
                            string_aftercheck = string_aftercheck[testindex3:]
                            testindex4 = string_aftercheck.find(certcheck2)
                            if testindex4 >= 0:
                                test.log.debug(
                                    "Found %s in output of pklogin", certcheck2
                                )
                            else:
                                test.fail(
                                    certcheck2 + " not found"
                                    " in output of pklogin "
                                    "on the guest"
                                )
                        else:
                            test.fail(
                                certcheck1 + " not found in "
                                "output of pklogin on the guest"
                            )
                    else:
                        test.fail(
                            "Common name %s, not found "
                            "in pkogin_finder after software "
                            "smartcard was inserted into the "
                            "guest" % subj_string
                        )

                else:
                    test.fail(checkstr + " not found in output of pklogin on the guest")

        else:
            test.fail(searchstr + " not found in output of pklogin on the guest")

        test.log.info("Certs Info on the guest:  %s", certsinfo_output)
    else:
        test.fail("Please specify a valid smartcard testype")

    # Do some cleanup, remove the certs on the client
    # for each cert listed by the test, create it on the client
    for cert in cert_list:
        cmd = "certutil "
        cmd += "-D -n '" + cert + "' -d " + cert_db
        try:
            output = client_session.cmd(cmd)
        except:
            test.log.warning("Deleting of %s certificate from the client failed", cert)
        test.log.debug("Output of %s: %s", cmd, output)

    client_session.close()
    guest_session.close()
