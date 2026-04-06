import json
import logging

import requests

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
from keko.ts3bot.config import Settings
from keko.ts3bot.database import Database

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
        self.database = Database(self._settings)

    @property
    def ts3(self):
        """Shortcut to TS3 settings."""
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
        """Event handling method."""
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
                logger.debug(f"unhandled event: {event}")

    async def on_client_moved(self, event: ClientMovedEvent | ClientMovedSelfEvent) -> None:
        moved_client = self.get_client(event.client_id)
        target_channel_id = event.target_channel_id
        if target_channel_id == await self.current_channel_id():
            self.on_client_moved_to_own_channel(moved_client)

    async def on_text_message(self, event: TextMessageEvent) -> None:
        assert self.ts3conn is not None
        chat_partner = self.get_client(event.invoker_id)

        # Prevent the client from sending messages to itself
        if chat_partner.client_id != self.client_id:
            if event.message.startswith("!hi"):
                await self.ts3conn.sendtextmessage(
                    targetmode=1,
                    target=chat_partner.client_id,
                    msg=f"Hallo {chat_partner.client_name}!",
                )
            elif event.message.startswith("!edit"):
                await self.ts3conn.sendtextmessage(
                    targetmode=1,
                    target=chat_partner.client_id,
                    msg="OK! Und los...",
                )
            elif event.message.startswith("!link"):
                teamspeak_uid = chat_partner.client_uid
                has_user_id = self.database.has_user_id(teamspeak_uid)
                user_id = self.database.get_user_id(teamspeak_uid)
                await self.ts3conn.sendtextmessage(
                    targetmode=1,
                    target=chat_partner.client_id,
                    msg=f"has_user_id: {has_user_id}",
                )
                await self.ts3conn.sendtextmessage(
                    targetmode=1,
                    target=chat_partner.client_id,
                    msg=f"user_id: {user_id}",
                )
                authkey_link = self.database.generate_authkey(teamspeak_uid)
                await self.ts3conn.sendtextmessage(
                    targetmode=1,
                    target=chat_partner.client_id,
                    msg=authkey_link,
                )

    async def on_client_entered(self, event: ClientEnteredEvent) -> None:
        assert self.ts3conn is not None
        client_name = event.client_name
        client_uid = event.client_uid
        client_id = event.client_id
        client_dbid = event.client_dbid
        client = Client(
            client_id=client_id,
            client_uid=client_uid,
            client_name=client_name,
            client_dbid=client_dbid,
        )
        self.set_client(client_id, client)

        logger.info("client entered: %s", client)

        if await self.is_guest(client_id):
            message = self.database.get_guest_welcome_message()
            await self.ts3conn.sendtextmessage(targetmode=1, target=client_id, msg=message)
        elif not self.database.has_user_id(client_uid):
            await self.send_link_account_message(client)
        else:
            await self.update_squad_xml_entry(client)
            await self.update_stammspieler_status(client)

    async def is_guest(self, client_id: int) -> bool:
        return await self.is_client_in_group(client_id, 'Guest')

    async def get_server_group_by_name(self, group_name: str) -> int:
        assert self.ts3conn is not None
        server_groups = await self.ts3conn.servergrouplist()

        for server_group in server_groups:
            if server_group['type'] == '1' and server_group['name'] == group_name:
                return int(server_group['sgid'])

        raise ValueError(f"No group found for name '{group_name}'")

    async def is_client_in_group(self, client_id: int, group_name: str) -> bool:
        group_id = await self.get_server_group_by_name(group_name)
        client_groups = await self.get_client_groups(client_id)
        return group_id in client_groups

    async def get_client_groups(self, client_id: int) -> list[int]:
        assert self.ts3conn is not None
        client_info = await self.ts3conn.clientinfo(client_id)
        client_group_ids = [int(x) for x in client_info['client_servergroups'].split(',')]
        return client_group_ids

    async def update_squad_xml_entry(self, client: Client) -> None:
        steam_id = self.database.get_steam_id(client.client_uid)

        if not self.database.has_squad_xml_entry(steam_id):
            username_url = f"{self._settings.api.base_url}/username/{steam_id}"
            nick = requests.get(username_url, timeout=10).text
            if nick and len(nick) > 0:
                self.database.create_squad_xml_entry(steam_id, nick)

    async def update_stammspieler_status(self, client: Client) -> None:
        assert self.ts3conn is not None
        stammspieler_sgid = await self.get_server_group_by_name("Stammspieler")
        steam_id = self.database.get_steam_id(client.client_uid)
        stammspieler_url = f"{self._settings.api.base_url}/stammspieler/{steam_id}"
        response = requests.get(stammspieler_url, timeout=10)
        stammspieler_status = bool(json.loads(response.text)['stammspieler'])

        client_is_in_group = await self.is_client_in_group(client.client_id, "Stammspieler")

        if stammspieler_status and not client_is_in_group:
            logger.info("adding user %s to server group stammspieler", client.client_name)
            await self.ts3conn.servergroupaddclient(sgid=stammspieler_sgid, cldbid=client.client_dbid)
        elif not stammspieler_status and client_is_in_group:
            logger.info("removing user %s from server group stammspieler", client.client_name)
            await self.ts3conn.servergroupdelclient(sgid=stammspieler_sgid, cldbid=client.client_dbid)

    async def on_client_left(self, event: ClientLeftEvent) -> None:
        client_id = event.client_id
        client = self.get_client(client_id)
        del self.connected_clients[int(client_id)]
        logger.info("client left: %s", client)

    @staticmethod
    def on_client_moved_to_own_channel(client: Client) -> None:
        logger.debug("client entered own channel: %s", client)

    async def send_link_account_message(self, client: Client) -> None:
        assert self.ts3conn is not None
        authkey_link = self.database.generate_authkey(client.client_uid)
        message = (
            f"Hallo {client.client_name}! Deine Teamspeak Identität ist nicht mit der "
            f"Kellerkompanie Webseite verknüpft. Klicke auf folgenden Link um die Accounts "
            f"zu verknüpfen:\n\n{authkey_link}"
        )
        await self.ts3conn.sendtextmessage(targetmode=1, target=client.client_id, msg=message)

    async def start_bot(self) -> None:
        logger.info("Kellerkompanie Bot starting")
        logger.info("connecting to %s:%d as %s", self.ts3.host, self.ts3.port, self.ts3.nickname)

        async with TS3Connection(self.ts3.host, self.ts3.port) as conn:
            self.ts3conn = conn

            # Login with query credentials
            await conn.login(self.ts3.user, self.ts3.password)

            # Choose a virtual server
            await conn.use(self.ts3.server_id)

            # Find the channel to move the query client to
            channels = await conn.channelfind(pattern=self.ts3.default_channel)
            channel = int(channels[0]["cid"])

            # Give the Query Client a name
            try:
                await conn.clientupdate(client_nickname=self.ts3.nickname)
            except TS3QueryError:
                pass

            # Find own client id
            whoami = await conn.whoami()
            self.client_id = int(whoami["client_id"])

            # Iterate through all currently connected clients
            logger.info("currently connected clients:")
            for client_data in await conn.clientlist():
                client_id = int(client_data["clid"])
                client_name = client_data["client_nickname"]
                client_info = await conn.clientinfo(client_id)
                client_uid = client_info["client_unique_identifier"]
                client_dbid = int(client_info["client_database_id"])
                client = Client(
                    client_id=client_id,
                    client_uid=client_uid,
                    client_name=client_name,
                    client_dbid=client_dbid,
                )
                self.set_client(client_id, client)
                logger.info("  %s", client)

                if client_id == self.client_id:
                    continue

                if await self.is_guest(client_id):
                    message = self.database.get_guest_welcome_message()
                    await conn.sendtextmessage(targetmode=1, target=client_id, msg=message)
                elif not self.database.has_user_id(client_uid):
                    await self.send_link_account_message(client=client)
                else:
                    await self.update_squad_xml_entry(client=client)
                    await self.update_stammspieler_status(client=client)

            # Move the Query client
            await conn.clientmove(channel, self.client_id)

            # Register for events
            await conn.register_for_server_events()
            await conn.register_for_server_messages()
            await conn.register_for_channel_events(channel_id=channel)
            await conn.register_for_channel_messages()
            await conn.register_for_private_messages()

            # Start keepalive
            await conn.start_keepalive()

            # Event loop
            async for event in conn.events():
                await self.on_event(event)
