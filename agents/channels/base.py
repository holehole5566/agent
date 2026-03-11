"""Channel abstract base class."""

from abc import ABC, abstractmethod


class Channel(ABC):
    """Base class for all messaging channels.

    A channel connects a user-facing platform (Telegram, Slack, etc.)
    to the gateway. It receives messages from users and sends responses back.
    """

    def __init__(self, gateway):
        self.gateway = gateway

    @property
    @abstractmethod
    def name(self) -> str:
        """Channel identifier (e.g. 'telegram')."""
        ...

    @abstractmethod
    def start(self):
        """Start receiving messages. May block (runs in its own thread)."""
        ...

    @abstractmethod
    def stop(self):
        """Stop the channel."""
        ...

    @abstractmethod
    def send_response(self, user_id: str, text: str):
        """Send a complete response to the user."""
        ...

    def on_text_chunk(self, user_id: str, chunk: str):
        """Handle a streaming text chunk. Override for real-time output."""
        pass  # default: ignore streaming, wait for on_response_done

    def on_response_done(self, user_id: str, full_text: str):
        """Called when agent response is complete. Override to send full response."""
        self.send_response(user_id, full_text)

    def on_message(self, user_id: str, text: str):
        """Called when a message arrives. Routes to gateway."""
        self.gateway.handle_message(self, user_id, text)
