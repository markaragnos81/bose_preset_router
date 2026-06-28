"""Persistent WebSocket listener for Bose SoundTouch real-time events."""
from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Any, Callable

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# Bose SoundTouch WebSocket requires this sub-protocol header
_WS_SUBPROTOCOL = "gabbo"
_RECONNECT_DELAY = 10  # seconds between reconnect attempts


class BoseSoundTouchWebSocket:
    """Connects to the Bose SoundTouch WebSocket (port 8080) and dispatches events."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        on_event: Callable[[str, ET.Element], None],
    ) -> None:
        self.hass = hass
        self.host = host
        self._on_event = on_event
        self._task: asyncio.Task | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False

    async def async_start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._listen_loop(), name=f"bose_ws_{self.host}")
        _LOGGER.debug("WebSocket listener started for %s", self.host)

    async def async_stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()
        _LOGGER.debug("WebSocket listener stopped for %s", self.host)

    async def _listen_loop(self) -> None:
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as err:
                if self._running:
                    _LOGGER.debug(
                        "WebSocket error for %s: %s — reconnecting in %ss",
                        self.host, err, _RECONNECT_DELAY,
                    )
                    await asyncio.sleep(_RECONNECT_DELAY)

    async def _connect_and_listen(self) -> None:
        session = async_get_clientsession(self.hass)
        url = f"ws://{self.host}:8080/"
        _LOGGER.debug("Connecting to Bose WebSocket at %s", url)

        async with session.ws_connect(
            url,
            protocols=[_WS_SUBPROTOCOL],
            heartbeat=30,
            timeout=aiohttp.ClientWSTimeout(ws_close=5),
        ) as ws:
            self._ws = ws
            _LOGGER.debug("WebSocket connected to %s", self.host)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._dispatch(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

    def _dispatch(self, text: str) -> None:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as err:
            _LOGGER.debug("WebSocket XML parse error from %s: %s", self.host, err)
            return

        for child in root:
            try:
                self._on_event(child.tag, child)
            except Exception as err:
                _LOGGER.debug("Error handling WS event %s from %s: %s", child.tag, self.host, err)
