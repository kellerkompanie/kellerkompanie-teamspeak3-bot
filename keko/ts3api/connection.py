"""Async TS3 Query Connection."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Self

from keko.ts3api.events import TS3Event, parse_event
from keko.ts3api.exceptions import TS3ConnectionError, TS3QueryError, TS3TimeoutError
from keko.ts3api.protocol import build_command, parse_response_to_dict, parse_response_to_list, unescape

logger = logging.getLogger(__name__)


class TS3Connection:
    """
    Async TeamSpeak 3 Query connection.

    Usage:
        async with TS3Connection(host, port) as conn:
            await conn.login(user, password)
            await conn.use(server_id)
            async for event in conn.events():
                handle_event(event)
    """

    DEFAULT_TIMEOUT: float = 10.0
    KEEPALIVE_INTERVAL: float = 5.0

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 10011,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

        # Event queue for async iteration
        self._event_queue: asyncio.Queue[TS3Event] = asyncio.Queue()

        # Tasks
        self._recv_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None

        # Connection state
        self._connected = False
        self._closing = False

        # Lock for sending commands (one at a time)
        self._send_lock = asyncio.Lock()

        # Condition for response synchronization
        self._response_ready = asyncio.Condition()
        self._pending_response: list[bytes] = []
        self._response_error: TS3QueryError | None = None

    async def connect(self) -> None:
        """Establish connection to TS3 server."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as e:
            raise TS3TimeoutError(f"Connection to {self._host}:{self._port} timed out") from e
        except OSError as e:
            raise TS3ConnectionError(f"Failed to connect: {e}") from e

        # Read the two greeting lines
        await self._read_line()  # TS3
        await self._read_line()  # Welcome message

        self._connected = True

        # Start background receiver task
        self._recv_task = asyncio.create_task(self._receive_loop())

    async def close(self) -> None:
        """Close the connection gracefully."""
        self._closing = True

        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass

        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass

        if self._writer:
            try:
                self._writer.write(b"quit\n\r")
                await self._writer.drain()
            except Exception:
                pass
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

        self._connected = False

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @property
    def connected(self) -> bool:
        """Check if connection is active."""
        return self._connected and not self._closing

    async def _read_line(self) -> bytes:
        """Read a single line ending with \\n\\r."""
        if not self._reader:
            raise TS3ConnectionError("Not connected")

        try:
            line = await asyncio.wait_for(
                self._reader.readuntil(b"\n\r"),
                timeout=self._timeout,
            )
            return line[:-2]  # Strip \n\r
        except asyncio.TimeoutError as e:
            raise TS3TimeoutError("Read timed out") from e
        except asyncio.IncompleteReadError as e:
            raise TS3ConnectionError("Connection closed unexpectedly") from e

    async def _receive_loop(self) -> None:
        """Background task that receives and routes messages."""
        while not self._closing:
            try:
                line = await self._read_line()
                decoded = line.decode("utf-8")

                if decoded.startswith("notify"):
                    # Parse and queue event
                    event = self._parse_notify(decoded)
                    if event:
                        await self._event_queue.put(event)
                elif decoded.startswith("error"):
                    # Error response - signal waiting command
                    async with self._response_ready:
                        self._response_error = self._parse_error(decoded)
                        self._response_ready.notify_all()
                else:
                    # Data response - accumulate for waiting command
                    async with self._response_ready:
                        self._pending_response.append(line)
                        self._response_ready.notify_all()

            except asyncio.CancelledError:
                break
            except TS3ConnectionError:
                if not self._closing:
                    logger.error("Connection lost in receive loop")
                break
            except Exception as e:
                logger.exception(f"Error in receive loop: {e}")

    def _parse_notify(self, line: str) -> TS3Event | None:
        """Parse a notify line into an event."""
        parts = line.split(" ", 1)
        event_type = parts[0]
        data_str = parts[1] if len(parts) > 1 else ""

        data: dict[str, str] = {}
        for part in data_str.split(" "):
            if "=" in part:
                key, value = part.split("=", 1)
                data[key] = unescape(value)

        return parse_event(event_type, data)

    def _parse_error(self, line: str) -> TS3QueryError:
        """Parse error line. Always returns a TS3QueryError (id=0 means success)."""
        # Format: error id=X msg=Y
        parts = line.split(" ")
        error_id = 0
        error_msg = "ok"

        for part in parts[1:]:  # Skip "error"
            if part.startswith("id="):
                error_id = int(part[3:])
            elif part.startswith("msg="):
                error_msg = part[4:]

        return TS3QueryError(error_id, error_msg)

    async def _send(
        self,
        command: str,
        *args: str,
        **kwargs: str | int,
    ) -> bytes:
        """Send a command with proper locking and escaping."""
        if not self._writer:
            raise TS3ConnectionError("Not connected")

        cmd_bytes = build_command(command, *args, **kwargs)

        async with self._send_lock:
            # Clear any previous response state
            self._pending_response.clear()
            self._response_error = None

            logger.debug(f"Sending: {cmd_bytes!r}")
            self._writer.write(cmd_bytes)
            await self._writer.drain()

            # Wait for response (data lines followed by error line)
            async with self._response_ready:
                while self._response_error is None:
                    try:
                        await asyncio.wait_for(
                            self._response_ready.wait(),
                            timeout=self._timeout,
                        )
                    except asyncio.TimeoutError as e:
                        raise TS3TimeoutError("Command response timed out") from e

                # Check if error
                if self._response_error is not None:
                    error = self._response_error
                    self._response_error = None
                    if error.error_id != 0:
                        raise error

                # Return accumulated response
                result = b"".join(self._pending_response)
                self._pending_response.clear()
                return result

    # ============ High-level API methods ============

    async def login(self, username: str, password: str) -> None:
        """Login with query credentials."""
        await self._send("login", client_login_name=username, client_login_password=password)

    async def use(self, server_id: int) -> None:
        """Select virtual server by ID."""
        await self._send("use", sid=server_id)

    async def whoami(self) -> dict[str, str]:
        """Get info about current query client."""
        resp = await self._send("whoami")
        return parse_response_to_dict(resp.decode("utf-8")) if resp else {}

    async def clientlist(self, *params: str) -> list[dict[str, str]]:
        """Get list of connected clients."""
        resp = await self._send("clientlist", *params)
        return parse_response_to_list(resp.decode("utf-8")) if resp else []

    async def clientinfo(self, client_id: int) -> dict[str, str]:
        """Get detailed client information."""
        resp = await self._send("clientinfo", clid=client_id)
        return parse_response_to_dict(resp.decode("utf-8")) if resp else {}

    async def channelfind(self, pattern: str) -> list[dict[str, str]]:
        """Find channels by name pattern."""
        resp = await self._send("channelfind", pattern=pattern)
        return parse_response_to_list(resp.decode("utf-8")) if resp else []

    async def servergrouplist(self) -> list[dict[str, str]]:
        """Get list of server groups."""
        resp = await self._send("servergrouplist")
        return parse_response_to_list(resp.decode("utf-8")) if resp else []

    async def clientmove(self, channel_id: int, client_id: int) -> None:
        """Move client to a channel."""
        await self._send("clientmove", cid=channel_id, clid=client_id)

    async def sendtextmessage(
        self,
        targetmode: int,
        target: int,
        msg: str,
    ) -> None:
        """Send a text message."""
        await self._send("sendtextmessage", targetmode=targetmode, target=target, msg=msg)

    async def clientupdate(self, **properties: str) -> None:
        """Update query client properties."""
        await self._send("clientupdate", **properties)

    async def servergroupaddclient(self, sgid: int, cldbid: int) -> None:
        """Add client to server group."""
        await self._send("servergroupaddclient", sgid=sgid, cldbid=cldbid)

    async def servergroupdelclient(self, sgid: int, cldbid: int) -> None:
        """Remove client from server group."""
        await self._send("servergroupdelclient", sgid=sgid, cldbid=cldbid)

    # ============ Event Registration ============

    async def register_for_server_events(self) -> None:
        """Register for server-wide events (client enter/leave)."""
        await self._send("servernotifyregister", event="server")

    async def register_for_server_messages(self) -> None:
        """Register for server text messages."""
        await self._send("servernotifyregister", event="textserver")

    async def register_for_channel_events(self, channel_id: int) -> None:
        """Register for channel events."""
        await self._send("servernotifyregister", event="channel", id=channel_id)

    async def register_for_channel_messages(self) -> None:
        """Register for channel text messages."""
        await self._send("servernotifyregister", event="textchannel")

    async def register_for_private_messages(self) -> None:
        """Register for private messages."""
        await self._send("servernotifyregister", event="textprivate")

    # ============ Event Iteration ============

    async def events(self) -> AsyncIterator[TS3Event]:
        """
        Async iterator for receiving events.

        Usage:
            async for event in conn.events():
                match event:
                    case TextMessageEvent():
                        ...
        """
        while self._connected and not self._closing:
            try:
                event = await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=1.0,  # Check connection status periodically
                )
                yield event
            except asyncio.TimeoutError:
                continue

    # ============ Keepalive ============

    async def start_keepalive(self, interval: float = KEEPALIVE_INTERVAL) -> None:
        """Start background keepalive task."""
        self._keepalive_task = asyncio.create_task(self._keepalive_loop(interval))

    async def _keepalive_loop(self, interval: float) -> None:
        """Send periodic keepalive commands."""
        while not self._closing:
            try:
                await asyncio.sleep(interval)
                await self.whoami()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Keepalive failed: {e}")

    # ============ Dynamic command support ============

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        """
        Support arbitrary TS3 commands via attribute access.

        Example:
            result = await conn.channellist("topic", "flags")
            result = await conn.clientkick(clid=5, reasonid=4, reasonmsg="Bye")
        """

        async def command_wrapper(*args: str, **kwargs: str | int) -> Any:
            resp = await self._send(name, *args, **kwargs)
            if resp:
                decoded = resp.decode("utf-8")
                parsed = parse_response_to_list(decoded)
                return parsed[0] if len(parsed) == 1 else parsed
            return None

        return command_wrapper
