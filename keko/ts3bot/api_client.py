"""HTTP client for the kellerkompanie-webpage TeamSpeak API.

The bot used to keep its own MariaDB connection plus call the webpage on
the side. After the rewrite the webpage owns ``keko_teamspeak`` and the
bot is a pure HTTP consumer of ``/teamspeak/*``. All persistent state -
account links, authkeys, welcome messages, squad.xml roster entries -
goes through this one client.

All methods are best-effort: they log a warning on network/4xx/5xx errors
and return ``None`` / a sentinel so the calling event handler can move on
without crashing. This matches the prior fail-graceful behaviour.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

from keko.ts3bot.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Account:
    teamspeak_uid: str
    user_id: int
    steam_id: str


class WebpageApi:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.api.base_url.rstrip("/")
        self._timeout = settings.api.timeout
        self._headers = {"Authorization": f"Bearer {settings.api.token}"}
        # Welcome-message cache (the message rarely changes; don't hammer
        # the webpage every time a guest joins).
        self._welcome_cache: tuple[float, str] | None = None
        self._welcome_ttl = settings.api.guest_welcome_cache_seconds

    # ------- account / link state ----------------------------------------

    def get_account_by_uid(self, teamspeak_uid: str) -> Optional[Account]:
        """Return the linked account for a TS UID, or None if not linked."""
        url = f"{self._base}/teamspeak/account/{teamspeak_uid}"
        try:
            r = requests.get(url, headers=self._headers, timeout=self._timeout)
        except requests.RequestException as exc:
            logger.warning("account lookup failed for %s: %s", teamspeak_uid, exc)
            return None
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            logger.warning("account lookup %s returned %s", teamspeak_uid, r.status_code)
            return None
        try:
            data = r.json()
            return Account(
                teamspeak_uid=data["teamspeak_uid"],
                user_id=int(data["user_id"]),
                steam_id=str(data["steam_id"]),
            )
        except (ValueError, KeyError) as exc:
            logger.warning("account lookup %s bad payload: %s", teamspeak_uid, exc)
            return None

    def request_link(self, teamspeak_uid: str) -> Optional[str]:
        """Mint a fresh authkey for this UID; returns the URL to PM the user."""
        url = f"{self._base}/teamspeak/link-request"
        try:
            r = requests.post(
                url, headers=self._headers, timeout=self._timeout,
                json={"teamspeak_uid": teamspeak_uid},
            )
        except requests.RequestException as exc:
            logger.warning("link-request failed for %s: %s", teamspeak_uid, exc)
            return None
        if r.status_code != 200:
            logger.warning("link-request returned %s for %s", r.status_code, teamspeak_uid)
            return None
        try:
            return str(r.json()["url"])
        except (ValueError, KeyError) as exc:
            logger.warning("link-request bad payload: %s", exc)
            return None

    # ------- stammspieler ------------------------------------------------

    def is_stammspieler(self, steam_id: str) -> Optional[bool]:
        """Return True/False for the user's Stammspieler status, or None if unknown
        (in which case the caller MUST skip the sync - do not assume False)."""
        url = f"{self._base}/teamspeak/stammspieler/{steam_id}"
        try:
            r = requests.get(url, headers=self._headers, timeout=self._timeout)
        except requests.RequestException as exc:
            logger.warning("stammspieler API unreachable for %s: %s", steam_id, exc)
            return None
        if r.status_code != 200:
            logger.warning("stammspieler returned %s for %s", r.status_code, steam_id)
            return None
        try:
            data = r.json()
            if "stammspieler" not in data:
                logger.warning("stammspieler key missing for %s", steam_id)
                return None
            return bool(data["stammspieler"])
        except ValueError as exc:
            logger.warning("stammspieler bad JSON for %s: %s", steam_id, exc)
            return None

    # ------- squad.xml ---------------------------------------------------

    def ensure_squad_xml_entry(self, teamspeak_uid: str) -> bool:
        """Ask the webpage to write a squad.xml row for the user behind this UID.

        The webpage resolves the linked user's display name internally and
        regenerates the on-disk squad.xml file as a background task. Returns
        True on success (created or already-exists), False on any failure.
        """
        url = f"{self._base}/teamspeak/squad-xml-entry"
        try:
            r = requests.post(
                url, headers=self._headers, timeout=self._timeout,
                json={"teamspeak_uid": teamspeak_uid},
            )
        except requests.RequestException as exc:
            logger.warning("squad-xml-entry failed for %s: %s", teamspeak_uid, exc)
            return False
        if r.status_code == 200:
            return True
        logger.warning("squad-xml-entry returned %s for %s", r.status_code, teamspeak_uid)
        return False

    # ------- guest welcome message --------------------------------------

    def get_guest_welcome(self) -> str:
        """Return the admin-edited guest welcome message, cached briefly."""
        now = time.monotonic()
        if self._welcome_cache is not None:
            cached_at, text = self._welcome_cache
            if now - cached_at < self._welcome_ttl:
                return text

        url = f"{self._base}/teamspeak/messages/guest-welcome"
        try:
            r = requests.get(url, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            text = str(r.json().get("text", ""))
        except (requests.RequestException, ValueError) as exc:
            logger.warning("guest-welcome fetch failed: %s", exc)
            text = ""

        self._welcome_cache = (now, text)
        return text
