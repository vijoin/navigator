"""Navigator Auth.

Navigator Authentication/Authorization system.

AuthHandler is the Authentication/Authorization system for NAV,
Supporting:
 * multiple authentication backends
 * authorization exceptions via middlewares
 * Session Support (in the top of aiohttp-session)
"""
from textwrap import dedent
import importlib
import logging
from aiohttp import web
from typing import Dict, List, Iterable
from .authorizations import *
from navigator.functions import json_response

from navigator.auth.sessions.storages import (
    RedisStorage,
)

from navigator.exceptions import (
    NavException,
    UserDoesntExists,
    InvalidAuth,
    FailedAuth
)
from navigator.conf import (
    AUTHORIZATION_BACKENDS,
    CREDENTIALS_REQUIRED,
    SESSION_TIMEOUT,
    AUTHENTICATION_BACKENDS,
    AUTHORIZATION_MIDDLEWARES,
    DOMAIN,
    SESSION_NAME,
    SESSION_STORAGE,
    SESSION_TIMEOUT,
    SECRET_KEY,
    JWT_ALGORITHM
)
from navigator.auth.sessions import get_session, new_session

class AuthHandler(object):
    """Authentication Backend for Navigator."""

    _template = """
        <!doctype html>
            <head></head>
            <body>
                <p>{message}</p>
                <form action="/login" method="POST">
                  Login:
                  <input type="text" name="login">
                  Password:
                  <input type="password" name="password">
                  <input type="submit" value="Login">
                </form>
                <a href="/logout">Logout</a>
            </body>
    """
    backends: Dict = None
    _session = None
    _user_property: str = "user"
    _required: bool = False
    _middlewares: Iterable = []

    def __init__(
        self,
        auth_scheme="Bearer",
        **kwargs,
    ):
        self._template = dedent(self._template)
        authz_backends = self.get_authorization_backends(AUTHORIZATION_BACKENDS)
        args = {
            "credentials_required": CREDENTIALS_REQUIRED,
            "scheme": auth_scheme,
            "authorization_backends": authz_backends,
            **kwargs,
        }
        # get the authentication backends (all of the list)
        self.backends = self.get_backends(**args)
        self._middlewares = self.get_authorization_middlewares(
            AUTHORIZATION_MIDDLEWARES
        )
        # TODO: Session Support with parametrization:
        self._session = RedisStorage()

    def get_backends(self, **kwargs):
        backends = {}
        for backend in AUTHENTICATION_BACKENDS:
            try:
                parts = backend.split(".")
                bkname = parts[-1]
                classpath = ".".join(parts[:-1])
                module = importlib.import_module(classpath, package=bkname)
                obj = getattr(module, bkname)
                logging.debug(f'Loading Auth Backend {bkname}')
                backends[bkname] = obj(**kwargs)
            except ImportError:
                raise Exception(f"Error loading Auth Backend {backend}")
        return backends

    async def on_cleanup(self, app):
        """
        Cleanup the processes
        """
        pass

    def get_authorization_backends(self, backends: Iterable) -> tuple:
        b = []
        for backend in backends:
            # TODO: more automagic logic
            if backend == "hosts":
                b.append(authz_hosts())
            elif backend == "allow_hosts":
                b.append(authz_allow_hosts())
        return b

    def get_authorization_middlewares(self, backends: Iterable) -> tuple:
        b = []
        for backend in backends:
            try:
                parts = backend.split(".")
                bkname = parts[-1]
                classpath = ".".join(parts[:-1])
                module = importlib.import_module(classpath, package=bkname)
                obj = getattr(module, bkname)
                b.append(obj)
            except ImportError:
                raise Exception(
                    f"Error loading Authz Middleware {backend}"
                )
        return b

    async def api_logout(self, request: web.Request) -> web.Response:
        """Logout.
        API-based Logout.
        """
        try:
            await self._session.forgot(request)
            return web.json_response(
                {
                    "message": "Logout successful",
                    "state": 202
                },
                status=202
            )
        except Exception as err:
            print(err)
            raise web.HTTPUnauthorized(
                reason=f"Logout Error {err!s}"
            )

    async def api_login(self, request: web.Request) -> web.Response:
        """Login.

        API based login.
        """
        app = request.app
        # first: getting header for an existing backend
        method = request.headers.get('X-Auth-Method')
        if method:
            try:
                backend = self.backends[method]
            except KeyError:
                raise web.HTTPUnauthorized(
                    text=f"Unacceptable Auth Method {method}",
                    content_type="application/json"
                )
            try:
                userdata = await backend.authenticate(request)
                if not userdata:
                    raise InvalidAuth('User was not authenticated')
                # at now: create the user-session
                try:
                    session = await self._session.new_session(request, userdata)
                except Exception as err:
                    raise web.HTTPUnauthorized(
                        reason=f"Error Creating User Session: {err!s}"
                    )
                return json_response(userdata, state=200)
            except FailedAuth as err:
                raise web.HTTPClientError(
                    reason=f"Authentication Error: Bad Credentials: {err!s}",
                    status=err.state
                )
            except InvalidAuth as err:
                logging.exception(err)
                raise web.HTTPUnauthorized(
                    reason=f"Authentication Error: Invalid Authentication: {err!s}"
                )
            except UserDoesntExists as err:
                print('UD ', err)
                raise web.HTTPUnauthorized(
                    reason="Unauthorized: User Doesn't exists"
                )
            except Exception as err:
                raise web.HTTPClientError(
                    reason=f"Unauthorized Error {err!s}",
                    status=406
                )
        else:
            # second: if no backend declared, will iterate over all backends
            userdata = None
            for bk, backend in self.backends.items():
                try:
                    # check credentials for all backends
                    userdata = await backend.authenticate(request)
                    if userdata:
                        break
                except (
                    NavException,
                    UserDoesntExists,
                    InvalidAuth,
                    FailedAuth
                ) as err:
                    continue
                except Exception as err:
                    return web.HTTPClientError(
                        reason=err,
                        status=401
                    )
            # if not userdata, then raise an not Authorized
            if not userdata:
                raise web.HTTPUnauthorized(
                    reason="User not Authorized"
                )
            else:
                # at now: create the user-session
                try:
                    session = await self._session.new_session(request, userdata)
                except Exception as err:
                    print(err)
                    return web.HTTPUnauthorized(
                        reason=f"Error Creating User Session: {err!s}"
                    )
                return json_response(userdata, state=200)

    # Session Methods:
    async def forgot_session(self, request: web.Request):
        await self._session.forgot(request)

    async def create_session(self, request: web.Request, data: Iterable):
        return await self._session.new_session(request, data)

    async def get_session(self, request: web.Request) -> web.Response:
        """ Get user data from session."""
        session = None
        try:
            session = await self._session.get_session(request)
        except NavException as err:
            response = {
                "message": "Session Error",
                "error": err.message,
                "status": err.state,
            }
            return web.json_response(response, status=err.state)
        except Exception as err:
            return web.HTTPClientError(
                reason=err,
                status=401
            )
        if not session:
            try:
                session = await self._session.get_session(request)
            except Exception as e:
                print(e)
                # always return a null session for user:
                session = await self._session.new_session(request, {})
        userdata = dict(session)
        return web.json_response(userdata, status=200)

    def configure(self, app: web.Application) -> web.Application:
        router = app.router
        router.add_route(
            "GET",
            "/api/v1/login",
            self.api_login,
            name="api_login"
        )
        router.add_route(
            "POST",
            "/api/v1/login",
            self.api_login,
            name="api_login_post"
        )
        router.add_route(
            "GET",
            "/api/v1/logout",
            self.api_logout,
            name="api_logout"
        )
        # get the session information for a program (only)
        router.add_route(
            "GET",
            "/api/v1/session/{program}",
            self.get_session,
            name="api_session_tenant",
        )
        # get all user information
        router.add_route(
            "GET",
            "/api/v1/user/session",
            self.get_session,
            name="api_session"
        )
        # the backend add a middleware to the app
        mdl = app.middlewares
        # configuring Session Object
        self._session.configure_session(app)
        # if authentication backend needs initialization
        for name, backend in self.backends.items():
            try:
                backend.configure(app, router)
                if hasattr(backend, "auth_middleware"):
                    # add the middleware for Basic Authentication
                    mdl.append(backend.auth_middleware)
            except Exception as err:
                print(err)
                logging.exception(
                    f"Error on Auth Backend {name} init: {err!s}"
                )
        # at last: add other middleware support
        if self._middlewares:
            for mid in self._middlewares:
                mdl.append(mid)
        return app
