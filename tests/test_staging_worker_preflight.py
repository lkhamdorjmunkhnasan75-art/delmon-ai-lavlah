import unittest
from unittest.mock import patch
from lavlah import staging_worker_preflight as p

class StagingWorkerPreflightTests(unittest.TestCase):
    @patch.object(p.socket, "create_connection")
    @patch.object(p.ssl, "create_default_context")
    def test_validated_tls_only(self, context_factory, connect):
        sock = connect.return_value.__enter__.return_value
        sock.recv.return_value = b"S"
        context = context_factory.return_value
        context.wrap_socket.return_value.__enter__.return_value.version.return_value = "TLSv1.3"
        self.assertEqual(p.probe("ca.pem"), {"tls": "TLSv1.3", "peer_verified": True})
        connect.assert_called_once_with((p.HOST, 5432), timeout=5)
        context_factory.assert_called_once_with(cafile="ca.pem")
        self.assertEqual(context.minimum_version, p.ssl.TLSVersion.TLSv1_2)
        sock.sendall.assert_called_once_with(p.SSL_REQUEST)
        context.wrap_socket.assert_called_once_with(sock, server_hostname=p.HOST)

    @patch.object(p.socket, "create_connection")
    @patch.object(p.ssl, "create_default_context")
    def test_no_tls_denied(self, context_factory, connect):
        connect.return_value.__enter__.return_value.recv.return_value = b"N"
        with self.assertRaises(RuntimeError):
            p.probe()
        context_factory.return_value.wrap_socket.assert_not_called()

    @patch.object(p.socket, "create_connection")
    @patch.object(p.ssl, "create_default_context")
    def test_bad_certificate_denied(self, context_factory, connect):
        connect.return_value.__enter__.return_value.recv.return_value = b"S"
        context_factory.return_value.wrap_socket.side_effect = p.ssl.SSLCertVerificationError("invalid")
        with self.assertRaises(p.ssl.SSLCertVerificationError):
            p.probe()
