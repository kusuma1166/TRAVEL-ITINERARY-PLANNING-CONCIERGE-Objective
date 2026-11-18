from __future__ import annotations

import ssl

import truststore


def create_system_ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
