"""TS3 event loop for the Kellerkompanie bot.

The bot is a thin TS3 client. All persistent state (account links,
authkeys, welcome messages, squad.xml) lives in the
kellerkompanie-webpage's keko_teamspeak DB and is reached only through
the HTTP API in :mod:`keko.ts3bot.api_client`.
"""
import logging

from keko.ts3api import (
    ClientEnteredEvent,
    ClientLeftEvent,
    ClientMovedEvent,
    ClientMovedSelfEvent,
    TextMessageEvent,
    TS3Connection,
    TS3Event,
    TS3QueryError,
)
from keko.ts3bot.api_client import WebpageApi
from keko.ts3bot.config import Settings

logger = logging.getLogger(__name__)


class Client:
    def __init__(self, client_id: int, client_uid: str, client_name: str, client_dbid: int):
        self.client_id = client_id
        self.client_uid = client_uid
        self.client_name = client_name
        self.client_dbid = client_dbid

    def __repr__(self) -> str:
        return f"{self.client_name} [id:{self.client_id} uid:{self.client_uid}]"


class TS3Bot:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.connected_clients: dict[int, Client] = {}
        self.ts3conn: TS3Connection | None = None
        self.client_id: int | None = None
        self.api = WebpageApi(settings)

    @property
    def ts3(self):
        return self._settings.ts3

    async def current_channel_id(self) -> int:
        assert self.ts3conn is not None
        whoami = await self.ts3conn.whoami()
        return int(whoami["client_channel_id"])

    def get_client(self, client_id: int) -> Client:
        return self.connected_clients[int(client_id)]

    def set_client(self, client_id: int, client: Client) -> None:
        self.connected_clients[int(client_id)] = client

    async def on_event(self, event: TS3Event) -> None:
        match event:
            case TextMessageEvent():
                await self.on_text_message(event)
            case ClientEnteredEvent():
                await self.on_client_entered(event)
            case ClientLeftEvent():
                await self.on_client_left(event)
            case ClientMovedEvent() | ClientMovedSelfEvent():
                await self.on_client_moved(event)
            case _:
                logger.debug("unhandled event: %s", event)

    async def on_client_moved(self, event: ClientMovedEvent | ClientMovedSelfEvent) -> None:
        moved_client = self.get_client(event.client_id)
        if event.target_channel_id == await self.current_channel_id():
            logger.debug("client entered own channel: %s", moved_client)

    async def on_text_message(self, event: TextMessageEvent) -> None:
        assert self.ts3conn is not None
        chat_partner = self.get_client(event.invoker_id)
        if chat_partner.client_id == self.client_id:
            return

        if event.message.startswith("!hi"):
            await self.ts3conn.sendtextmessage(
                targetmode=1, target=chat_partner.client_id,
                msg=f"Hallo {chat_partner.client_name}!",
            )
        elif event.message.startswith("!link"):
            url = self.api.request_link(chat_partner.client_uid)
            if url is None:
                await self.ts3conn.sendtextmessage(
                    targetmode=1, target=chat_partner.client_id,
                    msg="Konnte gerade keinen Verknüpfungs-Link erzeugen, versuch es später nochmal.",
                )
            else:
                await self.ts3conn.sendtextmessage(
                    targetmode=1, target=chat_partner.client_id, msg=url,
                )

    async def on_client_entered(self, event: ClientEnteredEvent) -> None:
        assert self.ts3conn is not None
        client = Client(
            client_id=event.client_id,
            client_uid=event.client_uid,
            client_name=event.client_name,
            client_dbid=event.client_dbid,
        )
        self.set_client(client.client_id, client)
        logger.info("client entered: %s", client)

        if await self.is_guest(client.client_id):
            message = self.api.get_guest_welcome()
            if message:
                await self.ts3conn.sendtextmessage(
                    targetmode=1, target=client.client_id, msg=message,
                )
            return

        account = self.api.get_account_by_uid(client.client_uid)
        if account is None:
            await self.send_link_account_message(client)
            return

        self.api.ensure_squad_xml_entry(client.client_uid)
        await self.update_stammspieler_status(client, account)

    async def is_guest(self, client_id: int) -> bool:
        return await self.is_client_in_group(client_id, "Guest")

    async def get_server_group_by_name(self, group_name: str) -> int:
        assert self.ts3conn is not None
        server_groups = await self.ts3conn.servergrouplist()
        for server_group in server_groups:
            if server_group["type"] == "1" and server_group["name"] == group_name:
                return int(server_group["sgid"])
        raise ValueError(f"No group found for name '{group_name}'")

    async def is_client_in_group(self, client_id: int, group_name: str) -> bool:
        group_id = await self.get_server_group_by_name(group_name)
        client_groups = await self.get_client_groups(client_id)
        return group_id in client_groups

    async def get_client_groups(self, client_id: int) -> list[int]:
        assert self.ts3conn is not None
        client_info = await self.ts3conn.clientinfo(client_id)
        return [int(x) for x in client_info["client_servergroups"].split(",")]

    async def update_stammspieler_status(self, client: Client, account) -> None:
        assert self.ts3conn is not None
        status = self.api.is_stammspieler(account.steam_id)
        if status is None:
            # API unreachable / unknown - skip, do not assume False.
            return

        stammspieler_sgid = await self.get_server_group_by_name("Stammspieler")
        in_group = await self.is_client_in_group(client.client_id, "Stammspieler")

        if status and not in_group:
            logger.info("adding user %s to server group stammspieler", client.client_name)
            await self.ts3conn.servergroupaddclient(sgid=stammspieler_sgid, cldbid=client.client_dbid)
        elif not status and in_group:
            logger.info("removing user %s from server group stammspieler", client.client_name)
            await self.ts3conn.servergroupdelclient(sgid=stammspieler_sgid, cldbid=client.client_dbid)

    async def on_client_left(self, event: ClientLeftEvent) -> None:
        client = self.get_client(event.client_id)
        del self.connected_clients[int(event.client_id)]
        logger.info("client left: %s", client)

    async def send_link_account_message(self, client: Client) -> None:
        assert self.ts3conn is not None
        url = self.api.request_link(client.client_uid)
        if url is None:
            logger.warning("could not mint authkey for %s; skipping link PM", client)
            return
        message = (
            f"Hallo {client.client_name}! Deine TeamSpeak-Identität ist nicht mit der "
            f"Kellerkompanie-Webseite verknüpft. Klicke auf folgenden Link, um die Accounts "
            f"zu verknüpfen:\n\n{url}"
        )
        await self.ts3conn.sendtextmessage(targetmode=1, target=client.client_id, msg=message)

    async def start_bot(self) -> None:
        logger.info("Kellerkompanie Bot starting")
        logger.info("connecting to %s:%d as %s", self.ts3.host, self.ts3.port, self.ts3.nickname)

        async with TS3Connection(self.ts3.host, self.ts3.port) as conn:
            self.ts3conn = conn

            await conn.login(self.ts3.user, self.ts3.password)
            await conn.use(self.ts3.server_id)

            channels = await conn.channelfind(pattern=self.ts3.default_channel)
            channel = int(channels[0]["cid"])

            try:
                await conn.clientupdate(client_nickname=self.ts3.nickname)
            except TS3QueryError:
                pass

            whoami = await conn.whoami()
            self.client_id = int(whoami["client_id"])

            logger.info("currently connected clients:")
            for client_data in await conn.clientlist():
                client_id = int(client_data["clid"])
                client_info = await conn.clientinfo(client_id)
                client = Client(
                    client_id=client_id,
                    client_uid=client_info["client_unique_identifier"],
                    client_name=client_data["client_nickname"],
                    client_dbid=int(client_info["client_database_id"]),
                )
                self.set_client(client_id, client)
                logger.info("  %s", client)

                if client_id == self.client_id:
                    continue

                # Do NOT send welcome / link-account PMs on startup - those should
                # only fire on a genuine ClientEnteredEvent. We still refresh
                # stammspieler group membership silently for already-linked users.
                if not await self.is_guest(client_id):
                    account = self.api.get_account_by_uid(client.client_uid)
                    if account is not None:
                        self.api.ensure_squad_xml_entry(client.client_uid)
                        await self.update_stammspieler_status(client, account)

            await conn.clientmove(channel, self.client_id)

            await conn.register_for_server_events()
            await conn.register_for_server_messages()
            await conn.register_for_channel_events(channel_id=channel)
            await conn.register_for_channel_messages()
            await conn.register_for_private_messages()

            await conn.start_keepalive()

            async for event in conn.events():
                await self.on_event(event)
