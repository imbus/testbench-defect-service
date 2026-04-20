"""Configuration management for TestBench Defect Service."""

import os
import ssl
import sys
from pathlib import Path

from pydantic import ValidationError
from sanic.config import Config
from sanic.http.tls.context import CIPHERS_TLS12

from testbench_defect_service.clients.utils import get_client_config_class
from testbench_defect_service.utils.config import (
    CONFIG_PREFIX,
    load_client_config_from_file,
    load_service_config,
    print_config_errors,
    resolve_config_file_path,
)


class AppConfig(Config):
    """Sanic configuration with uppercase attributes (Sanic requirement)."""

    def __init__(  # noqa: PLR0913
        self,
        config_path: Path | None = None,
        client_class: str | None = None,
        client_config_path: Path | None = None,
        host: str | None = None,
        port: int | None = None,
        debug: bool | None = None,
        ssl_cert: Path | None = None,
        ssl_key: Path | None = None,
        ssl_ca_cert: Path | None = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        # Sanic-specific settings
        self.FALLBACK_ERROR_FORMAT = "json"
        self.OAS_UI_DEFAULT = "swagger"
        self.OAS_UI_REDOC = False
        self.OAS_CUSTOM_FILE = (Path(__file__).parent / "openapi.yaml").resolve().as_posix()
        self.OAS_PATH_TO_SWAGGER_HTML = (
            (Path(__file__).parent / "static/swagger-ui/index.html").resolve().as_posix()
        )

        # Load and validate config from file
        self.CONFIG_PATH = resolve_config_file_path(config_path)
        service_config = load_service_config(self.CONFIG_PATH)

        # Map all validated settings to uppercase Sanic config attributes
        self.CLIENT_CLASS = service_config.client_class
        self.CLIENT_CONFIG_PATH = service_config.client_config_path
        self.HOST = service_config.host
        self.PORT = service_config.port
        self.DEBUG = service_config.debug
        self.LOG_CONFIG = service_config.logging
        # Auth credentials
        self.PASSWORD_HASH = service_config.password_hash or os.getenv("PASSWORD_HASH")
        self.SALT = service_config.salt or os.getenv("SALT")
        # SSL/TLS configuration
        self.SSL_CERT = service_config.ssl_cert
        self.SSL_KEY = service_config.ssl_key
        self.SSL_CA_CERT = service_config.ssl_ca_cert
        # Reverse proxy configuration
        self.PROXIES_COUNT = service_config.proxies_count
        self.REAL_IP_HEADER = service_config.real_ip_header
        self.FORWARDED_SECRET = service_config.forwarded_secret
        # Server process/worker configuration
        self.SERVER_CONFIG = service_config.server
        self.KEEP_ALIVE_TIMEOUT = self.SERVER_CONFIG.keep_alive_timeout

        self._client_config_inline = service_config.client_config

        # Override with CLI parameters (highest priority)
        if client_class:
            self.CLIENT_CLASS = client_class
        if client_config_path:
            self.CLIENT_CONFIG_PATH = client_config_path
        if host:
            self.HOST = host
        if port:
            self.PORT = port
        if debug is not None:
            self.DEBUG = debug
        if ssl_cert:
            self.SSL_CERT = ssl_cert
        if ssl_key:
            self.SSL_KEY = ssl_key
        if ssl_ca_cert:
            self.SSL_CA_CERT = ssl_ca_cert

        # Validate and store client config
        self.CLIENT_CONFIG = self._validate_client_config()

    def get_ssl_context(self) -> ssl.SSLContext | dict | None:
        """Get SSL configuration for HTTPS if certificates are configured.

        Returns:
            ssl.SSLContext: SSL context with mTLS (client certificate verification)
            dict: Simple cert/key dict for basic HTTPS (Sanic's built-in handling)
            None: If SSL is not configured
        """
        if not self.SSL_CERT or not self.SSL_KEY:
            return None

        # If no CA cert specified, return simple dict (Sanic's built-in handling)
        if not self.SSL_CA_CERT:
            return {
                "cert": str(self.SSL_CERT),
                "key": str(self.SSL_KEY),
            }

        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.set_ciphers(":".join(CIPHERS_TLS12))
        context.set_alpn_protocols(["http/1.1"])
        context.load_cert_chain(str(self.SSL_CERT), str(self.SSL_KEY))
        context.load_verify_locations(cafile=str(self.SSL_CA_CERT))
        context.verify_mode = ssl.CERT_REQUIRED

        return context

    def _validate_client_config(self):
        """Validate client_config dict against the client's CONFIG_CLASS."""
        try:
            client_config_class = get_client_config_class(self.CLIENT_CLASS)
        except ImportError:
            client_config_class = None
        if client_config_class is None:
            return {}

        separate_file = self.CLIENT_CONFIG_PATH is not None
        try:
            if separate_file:
                client_config = load_client_config_from_file(self.CLIENT_CONFIG_PATH)
            else:
                client_config = self._client_config_inline
            return client_config_class.model_validate(client_config)
        except ValidationError as e:
            if separate_file:
                print_config_errors(e, config_path=self.CLIENT_CONFIG_PATH, config_prefix=None)
            else:
                config_prefix = f"{CONFIG_PREFIX}.client_config"
                print_config_errors(e, config_path=self.CONFIG_PATH, config_prefix=config_prefix)
            sys.exit(1)
        except Exception as e:
            raise ValueError(f"Failed to validate client configuration: {e}") from e
