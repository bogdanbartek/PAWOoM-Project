"""Konfiguracja klienta Eureka (LAB3) - wzorowana na pakiecie pomocniczym LAB3."""
import os

from py_eureka_client.eureka_client import EurekaClient

DEFAULT_EUREKA_SERVER_URL = "http://127.0.0.1:8761"


def create_eureka_client(service_name: str, default_port: int) -> EurekaClient:
    """Tworzy (ale nie uruchamia) klienta rejestru.

    Adres Eureki i dane własnej instancji pochodzą ze zmiennych środowiskowych.
    SERVICE_PORT musi być równy portowi Uvicorna (--port). Nie rejestrujemy 0.0.0.0.
    """
    return EurekaClient(
        eureka_server=os.getenv("EUREKA_SERVER_URL", DEFAULT_EUREKA_SERVER_URL),
        eureka_context="/eureka",
        app_name=os.getenv("SERVICE_NAME", service_name),
        instance_ip=os.getenv("INSTANCE_IP", "127.0.0.1"),
        instance_host=os.getenv("INSTANCE_HOST", "localhost"),
        instance_port=int(os.getenv("SERVICE_PORT", str(default_port))),
        # False: błędy HTTP zależności trafiają do naszego kodu jako HTTPError,
        # więc sami mapujemy je na 404/502/503.
        strict_service_error_policy=False,
    )
