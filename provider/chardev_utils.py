import os
import shutil

from avocado.utils import process
from virttest import utils_net
from virttest.utils_conn import build_CA, build_client_key, build_server_key


def setup_certs(params):
    """
    Generating certificates
    :param params:params
    """
    # Create tmp certificates dir
    cert_dir = params["cert_dir"]
    # Remove certificates dir.
    if os.path.exists(cert_dir):
        shutil.rmtree(cert_dir)

    # Setup the certificate authority.
    hostname = process.run(
        "hostname", ignore_status=False, shell=True, verbose=True
    ).stdout_text.strip()
    server_ip = utils_net.get_host_ip_address()
    cn = hostname
    ca_credential_dict = {}
    ca_credential_dict["cakey"] = "ca-key.pem"
    ca_credential_dict["cacert"] = "ca-cert.pem"
    if not os.path.exists(cert_dir):
        os.makedirs(cert_dir)
    build_CA(cert_dir, cn, certtool="certtool", credential_dict=ca_credential_dict)

    # Setup server certificates
    server_credential_dict = {}
    server_credential_dict["cakey"] = "ca-key.pem"
    server_credential_dict["cacert"] = "ca-cert.pem"
    server_credential_dict["serverkey"] = "server-key.pem"
    server_credential_dict["servercert"] = "server-cert.pem"
    server_credential_dict["ca_cakey_path"] = cert_dir
    # Build a server key.
    build_server_key(
        cert_dir,
        cn,
        server_ip,
        certtool="certtool",
        credential_dict=server_credential_dict,
        on_local=True,
    )

    # Setup client certificates
    client_credential_dict = {}
    client_credential_dict["cakey"] = "ca-key.pem"
    client_credential_dict["cacert"] = "ca-cert.pem"
    client_credential_dict["clientkey"] = "client-key.pem"
    client_credential_dict["clientcert"] = "client-cert.pem"
    server_credential_dict["ca_cakey_path"] = cert_dir

    # build a client key.
    build_client_key(
        cert_dir,
        client_cn=cn,
        certtool="certtool",
        credential_dict=client_credential_dict,
    )
