from __future__ import annotations

import json
import os
from collections import deque
from typing import Any, Callable


EXCHANGE_NAME = "pawoom.events"


class BrokerUnavailableError(RuntimeError):
    """Raised when the message broker cannot be reached."""


class InMemoryEventBroker:
    """Deterministic in-memory message broker for isolated unit tests."""

    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.published: list[tuple[str, dict[str, Any]]] = []
        self._queues: dict[str, deque[dict[str, Any]]] = {}
        self._bindings: dict[str, list[str]] = {}
        self.closed = False

    def bind_queue(self, queue_name: str, routing_key: str) -> None:
        self._queues.setdefault(queue_name, deque())
        queues = self._bindings.setdefault(routing_key, [])
        if queue_name not in queues:
            queues.append(queue_name)

    def publish(self, routing_key: str, event: dict[str, Any]) -> None:
        if self.down:
            raise BrokerUnavailableError("RabbitMQ is unavailable")
        payload = json.loads(json.dumps(event))
        self.published.append((routing_key, payload))
        for queue_name in self._bindings.get(routing_key, []):
            self._queues.setdefault(queue_name, deque()).append(payload)

    def consume_available(
        self, queue_name: str, handler: Callable[[dict[str, Any]], None], limit: int = 50
    ) -> int:
        if self.down:
            raise BrokerUnavailableError("RabbitMQ is unavailable")
        queue = self._queues.setdefault(queue_name, deque())
        processed = 0
        while queue and processed < limit:
            message = queue[0]
            handler(message)
            queue.popleft()
            processed += 1
        return processed

    def close(self) -> None:
        self.closed = True


class RabbitEventBroker:
    """AMQP 0-9-1 publisher and consumer wrapper using pika."""

    def __init__(
        self,
        amqp_url: str | None = None,
        exchange_name: str = EXCHANGE_NAME,
    ) -> None:
        self.amqp_url = amqp_url or os.getenv(
            "RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672/%2F"
        )
        self.exchange_name = exchange_name

    def _open_connection(self):
        import pika

        params = pika.URLParameters(self.amqp_url)
        params.socket_timeout = 2.0
        # LAB5 (poprawka pakietu): pika (sprawdzone 1.4.4) ma atrybut blocked_connection_timeout;
        # "BlockedConnectionTimeout" rzucał AttributeError i przerywał start usługi.
        params.blocked_connection_timeout = 2.0
        try:
            return pika.BlockingConnection(params)
        except Exception as exc:
            raise BrokerUnavailableError("RabbitMQ is unavailable") from exc

    def bind_queue(self, queue_name: str, routing_key: str) -> None:
        connection = self._open_connection()
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=self.exchange_name,
                exchange_type="topic",
                durable=True,
            )
            channel.queue_declare(queue=queue_name, durable=True)
            channel.queue_bind(
                exchange=self.exchange_name,
                queue=queue_name,
                routing_key=routing_key,
            )
        except Exception as exc:
            raise BrokerUnavailableError("Failed to declare queue or binding") from exc
        finally:
            if connection.is_open:
                connection.close()

    def publish(self, routing_key: str, event: dict[str, Any]) -> None:
        import pika

        connection = self._open_connection()
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=self.exchange_name,
                exchange_type="topic",
                durable=True,
            )
            body = json.dumps(event).encode("utf-8")
            channel.basic_publish(
                exchange=self.exchange_name,
                routing_key=routing_key,
                body=body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,
                    message_id=str(event.get("event_id", "")),
                ),
            )
        except Exception as exc:
            raise BrokerUnavailableError("Failed to publish event to RabbitMQ") from exc
        finally:
            if connection.is_open:
                connection.close()

    def consume_available(
        self, queue_name: str, handler: Callable[[dict[str, Any]], None], limit: int = 50
    ) -> int:
        connection = self._open_connection()
        processed = 0
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=self.exchange_name,
                exchange_type="topic",
                durable=True,
            )
            channel.queue_declare(queue=queue_name, durable=True)
            while processed < limit:
                method_frame, _properties, body = channel.basic_get(
                    queue=queue_name, auto_ack=False
                )
                if method_frame is None:
                    break
                try:
                    event = json.loads(body.decode("utf-8"))
                    handler(event)
                except Exception:
                    channel.basic_nack(
                        delivery_tag=method_frame.delivery_tag, requeue=True
                    )
                    raise
                else:
                    channel.basic_ack(delivery_tag=method_frame.delivery_tag)
                    processed += 1
            return processed
        except BrokerUnavailableError:
            raise
        except (ValueError, LookupError):
            # LAB5 (zmiana względem pakietu): błąd treści zdarzenia zgłoszony przez handler
            # (po basic_nack) nie jest awarią brokera - przekazujemy go dalej (-> 422, nie 503).
            raise
        except Exception as exc:
            raise BrokerUnavailableError("Failed to consume from RabbitMQ") from exc
        finally:
            if connection.is_open:
                connection.close()

    def close(self) -> None:
        pass
