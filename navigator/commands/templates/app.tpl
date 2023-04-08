"""
App.py
This file will be auto-generated by code
"""
import asyncio
import uvloop
from navigator.handlers.types import AppHandler

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

class Main(AppHandler):
    """Main Class.
    Using this class as a boilerplate for starting new programs.
    """
    _middleware: list = []
    enable_notify: bool = False
    enable_static: bool = True
    enable_pgpool: bool = False
    enable_error_middleware: bool = False

    def configure(self):
        super(Main, self).configure()

    async def on_startup(self, app):
        """
        on_startup.
        description: Signal for customize the response when server is started
        """

    async def on_shutdown(self, app):
        """
        on_shutdown.
        description: Signal for customize the response when server is shutting down
        """
