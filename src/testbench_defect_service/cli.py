import sys
from functools import partial
from pathlib import Path
from ssl import SSLContext

import click
from dotenv import load_dotenv
from sanic import Sanic
from sanic.worker.loader import AppLoader

from testbench_defect_service import __title__, __version__
from testbench_defect_service.app import AppConfig, create_app
from testbench_defect_service.log import logger
from testbench_defect_service.utils.config_wizard import (
    configure_client_only,
    configure_credentials_only,
    configure_service_only,
    run_full_wizard,
    show_main_menu,
    view_current_config,
)


def print_service_banner():
    click.echo(rf"""  ______          __  ____                  __       ____  __  ___   _____                 _         
 /_  __/__  _____/ /_/ __ )___  ____  _____/ /_     / __ \/  |/  /  / ___/___  ______   __(_)_______ 
  / / / _ \/ ___/ __/ __  / _ \/ __ \/ ___/ __ \   / / / / /|_/ /   \__ \/ _ \/ ___/ | / / / ___/ _ \
 / / /  __(__  ) /_/ /_/ /  __/ / / / /__/ / / /  / /_/ / /  / /   ___/ /  __/ /   | |/ / / /__/  __/   version:
/_/  \___/____/\__/_____/\___/_/ /_/\___/_/ /_/  /_____/_/  /_/   /____/\___/_/    |___/_/\___/\___/    {__version__} 
                                                                                                     """)  # noqa: W291, E501


def print_wizard_banner():
    click.echo("╔════════════════════════════════════════════════════════╗")
    click.echo("║  TestBench Defect Service - Configuration Wizard       ║")
    click.echo("╚════════════════════════════════════════════════════════╝\n")


@click.group()
@click.version_option(version=__version__, prog_name=__title__, message="%(prog)s %(version)s")
@click.pass_context
def cli(ctx):
    ctx.max_content_width = 120
    load_dotenv()


@click.command()
@click.option(
    "--path",
    "config_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    metavar="PATH",
    default="config.toml",
    help="Path to the configuration file.",
)
def init(config_path: Path):
    """Initialize service configuration interactively."""
    print_wizard_banner()
    run_full_wizard(config_path)


@click.command()
@click.option(
    "--path",
    "config_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default="config.toml",
    help="Path to the app configuration file",
)
@click.option("--full", is_flag=True, help="Run full configuration wizard (skip menu)")
@click.option("--service-only", is_flag=True, help="Configure service settings only")
@click.option("--credentials-only", is_flag=True, help="Configure service credentials only")
@click.option("--client-only", is_flag=True, help="Configure client settings only")
@click.option("--view", is_flag=True, help="View current configuration")
def configure(  # noqa: PLR0911, PLR0913, C901
    config_path: Path,
    full: bool,
    service_only: bool,
    credentials_only: bool,
    client_only: bool,
    view: bool,
):
    """Create or update configuration files interactively."""
    print_wizard_banner()

    # Handle command flags (direct modes)
    if service_only:
        configure_service_only(config_path)
        return

    if credentials_only:
        configure_credentials_only(config_path)
        return

    if client_only:
        configure_client_only(config_path)
        return

    if view:
        view_current_config(config_path)
        return

    # Show menu if no flags specified
    if not full:
        mode = show_main_menu(config_path)
        if mode is None or mode == "quit":
            click.echo("\nConfiguration cancelled.")
            return

        if mode == "service":
            configure_service_only(config_path)
            return
        if mode == "credentials":
            configure_credentials_only(config_path)
            return
        if mode == "client":
            configure_client_only(config_path)
            return
        if mode == "view":
            view_current_config(config_path)
            return

    run_full_wizard(config_path)


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    metavar="PATH",
    help=("Path to the app config file  [default: config.toml]"),
)
@click.option(
    "--client-class",
    type=str,
    metavar="PATH",
    help="""Path or module string to the client class  \b
    [default: testbench_defect_service.clients.JsonlDefectClient]""",
)
@click.option(
    "--client-config",
    type=click.Path(dir_okay=False, path_type=Path),
    metavar="PATH",
    help="Path to the client config file  [default: client_config.toml]",
)
@click.option(
    "--host", type=str, metavar="HOST", help="Host to run the service on  [default: 127.0.0.1]"
)
@click.option(
    "--port", type=int, metavar="PORT", help="Port to run the service on  [default: 8000]"
)
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    show_default=True,
    help="Run the service in dev mode (debug + auto reload)",
)
@click.option(
    "--ssl-cert",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    metavar="PATH",
    help="Path to SSL certificate file for HTTPS",
)
@click.option(
    "--ssl-key",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    metavar="PATH",
    help="Path to SSL private key file for HTTPS",
)
@click.option(
    "--ssl-ca-cert",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    metavar="PATH",
    help="Path to CA certificate file for client verification (optional)",
)
def start(  # noqa: PLR0913
    config_path: Path | None = None,
    client_class: str | None = None,
    client_config: Path | None = None,
    host: str | None = None,
    port: int | None = None,
    dev: bool = False,
    ssl_cert: Path | None = None,
    ssl_key: Path | None = None,
    ssl_ca_cert: Path | None = None,
):
    """Start the TestBench Defect Service."""
    app_name = __title__
    app_config = AppConfig(
        config_path=config_path,
        client_class=client_class,
        client_config_path=client_config,
        host=host,
        port=port,
        debug=dev,
        ssl_cert=ssl_cert,
        ssl_key=ssl_key,
        ssl_ca_cert=ssl_ca_cert,
    )

    print_service_banner()

    factory = partial(create_app, app_name, app_config)
    loader = AppLoader(factory=factory)
    try:
        app = loader.load()
    except ImportError as e:
        raise click.ClickException(str(e)) from e

    logger.info("Starting %s v%s", app_name, __version__)

    if not host:
        host = getattr(app.config, "HOST", None)
    if not port:
        port = getattr(app.config, "PORT", None)

    server_config = app_config.SERVER_CONFIG
    ssl_context = app_config.get_ssl_context()

    use_single_process = server_config.single_process
    if dev and use_single_process:
        logger.info(
            "Dev mode enabled: switching to multi-process mode to support auto-reload. "
            "Set 'server.single_process = false' explicitly to suppress this message."
        )
        use_single_process = False
    if getattr(sys, "frozen", False) and not use_single_process:
        logger.warning(
            "Auto-reload is not supported in the executable. Falling back to single-process mode."
        )
        use_single_process = True
    if isinstance(ssl_context, SSLContext) and not use_single_process:
        logger.warning(
            "mTLS (ssl_ca_cert) requires single-process mode. "
            "Ignoring 'single_process = false' and running in single-process mode."
        )
        use_single_process = True

    common_kwargs: dict = {
        "host": host,
        "port": port,
        "debug": app_config.DEBUG,
        "access_log": True,
        "ssl": ssl_context,
        **server_config.run_kwargs,
    }

    try:
        if use_single_process:
            app.run(**common_kwargs, single_process=True)
        else:
            app.prepare(**common_kwargs, dev=dev)
            Sanic.serve(primary=app, app_loader=loader)
    except Exception as e:
        raise click.ClickException(f"Server could not start: {e}") from e


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    metavar="PATH",
    default="config.toml",
    help="Path to the app config file",
)
@click.option("--username", type=str, help="Username (prompts if not provided)")
@click.option("--password", type=str, help="Password (prompts if not provided)")
def set_credentials(config_path, username, password):
    """Set credentials for the TestBench Defect Service."""
    configure_credentials_only(config_path, username=username, password=password)


cli.add_command(init)
cli.add_command(configure)
cli.add_command(set_credentials)
cli.add_command(start)

if __name__ == "__main__":
    cli()
