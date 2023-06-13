from typing import Callable

import requests
from requests import Response
from typing_extensions import Literal

from helloasso_api.exceptions import (
    ApiV5BadRequest,
    ApiV5Conflict,
    ApiV5ConnectionError,
    ApiV5Forbidden,
    ApiV5IncorrectMethod,
    ApiV5NoConfig,
    ApiV5NotFound,
    ApiV5RateLimited,
    ApiV5ServerError,
    ApiV5Timeout,
    ApiV5Unauthorized,
)
from helloasso_api.oauth2 import OAuth2Api
from helloasso_api.utils import get_log


class ApiV5Client(object):
    """Manage all calls to Helloasso api (including authentication calls).
    The class must not be used directly but inherited from. See HaApiV5 in src/__init__.py
    """

    def __init__(
        self,
        api_base: str,
        client_id: str,
        client_secret: str,
        timeout: int = None,
        access_token: str = None,
        refresh_token: str = None,
        oauth2_token_getter: Callable[
            [Literal["access_token", "refresh_token"], str], str
        ] = None,
        oauth2_token_setter: Callable[
            [Literal["access_token", "refresh_token"], str, str], None
        ] = None,
    ):
        """
        :param api_base: url of api, example: :api.helloasso-dev.com
        :param client_id: client_id for authentication
        :param client_secret: client_secret for authentication
        :param timeout: (optional) How long to wait for the server to send
            data before giving up, as a float
        :param access_token: (optional) The OAuth access token if exist
        :param refresh_token: (optional) The OAuth refresh token if exist
        :param oauth2_token_getter: custom method to retrieve tokens (useful to share tokens across multiple instances).
        :param oauth2_token_setter: custom method to store tokens (useful to share tokens across multiple instances).
        """
        self.log = get_log("apiv5.apiv5client")

        self.api_base = api_base
        self.timeout = timeout

        self.client_id = client_id
        self.client_secret = client_secret

        if not self.client_id or not self.client_secret:
            raise ApiV5NoConfig("Missing client_id or client_secret.")
        if not self.api_base:
            raise ApiV5NoConfig("Missing Api Base.")

        self.auth = None
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.oauth2_token_getter = oauth2_token_getter
        self.oauth2_token_setter = oauth2_token_setter

        if (oauth2_token_getter is None) != (oauth2_token_setter is None):
            raise ApiV5NoConfig(
                "You must either specify both the oauth2 token setter and getter, or neither."
            )

        self.oauth = OAuth2Api(
            api_base=self.api_base,
            client_id=self.client_id,
            client_secret=self.client_secret,
            timeout=self.timeout,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            oauth2_token_getter=self.oauth2_token_getter,
            oauth2_token_setter=self.oauth2_token_setter,
        )

        if not self.oauth.access_token:
            self.oauth.get_token()

    def set_access_token(self, access_token: str):
        self.access_token = access_token
        self.oauth.access_token = access_token

    def set_refresh_token(self, refresh_token: str):
        self.refresh_token = refresh_token
        self.oauth.refresh_token = refresh_token

    @staticmethod
    def header() -> dict:
        """Return a base header for all requests."""
        return {"Content-Type": "application/json"}

    def prepare_request(
        self,
        sub_path: str,
        headers: dict,
        data: dict,
        json: dict,
        params: dict,
        include_auth: bool,
    ) -> (str, dict, dict, dict, dict):
        """Build all the elements of the the request."""
        url = f"https://{self.api_base}{sub_path}"
        self.log.debug(f"Prepare Request : {url}")
        data = data or {}
        json = json or {}
        params = params or {}
        headers = headers or {}
        self.auth = (
            {"Authorization": f"Bearer {self.oauth.access_token}"}
            if include_auth
            else {}
        )
        all_headers = {**self.header(), **self.auth, **headers}
        return url, all_headers, data, json, params

    def execute_request(
        self, url: str, method: str, headers: dict, data: dict, json: dict, params: dict
    ) -> Response:
        """Execute request based on method name. Map Api Error to python Exceptions."""
        try:
            self.log.debug(f"Execute Request : {method} : {url}")
            if method == "POST":
                result = requests.post(
                    url,
                    headers=headers,
                    params=params,
                    data=data,
                    json=json,
                    timeout=self.timeout,
                )
            elif method == "GET":
                result = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    data=data,
                    timeout=self.timeout,
                )
            elif method == "PATCH":
                result = requests.patch(
                    url,
                    headers=headers,
                    data=data,
                    timeout=self.timeout,
                )
            elif method == "PUT":
                result = requests.put(
                    url,
                    headers=headers,
                    data=data,
                    timeout=self.timeout,
                )
            elif method == "DELETE":
                result = requests.delete(
                    url,
                    headers=headers,
                    data=data,
                    timeout=self.timeout,
                )
            else:
                raise ApiV5IncorrectMethod(
                    "Incorrect Method: only POST,GET,PATCH,PUT,DELETE authorized."
                )
        except requests.exceptions.Timeout:
            raise ApiV5Timeout(f"{url} timeout : {str(self.timeout)} sec")
        except requests.exceptions.ConnectionError as e:
            raise ApiV5ConnectionError(
                f"Failed to establish a new connection: Name or service not known : {url}"
            )

        if result.status_code in (404, 410):
            raise ApiV5NotFound(result)
        elif result.status_code == 401:
            raise ApiV5Unauthorized(result)
        elif result.status_code == 403:
            raise ApiV5Forbidden(result)
        elif result.status_code == 409:
            raise ApiV5Conflict(result)
        elif result.status_code == 429:
            raise ApiV5RateLimited(result)
        elif 400 <= result.status_code < 500 or result.status_code == 501:
            raise ApiV5BadRequest(result)
        elif result.status_code >= 500:
            raise ApiV5ServerError(result)

        return result

    def call(
        self,
        sub_path: str,
        params: dict = None,
        method: str = "GET",
        data: dict = None,
        json: dict = None,
        headers: dict = None,
        include_auth: bool = True,
    ) -> Response:
        """Manage all api calls. It also handle re-authentication if necessary."""
        self.log.debug(f"Call : {method} : {sub_path}")
        url, all_headers, data, json, params = self.prepare_request(
            sub_path, headers, data, json, params, include_auth
        )

        try:
            result = self.execute_request(url, method, all_headers, data, json, params)
            return result
        except ApiV5Unauthorized:
            self.log.warning("401 Unauthorized response to API request.")
            if self.oauth.access_token:
                self.log.info("Refreshing access token")
                self.oauth.refresh_tokens()
            else:
                self.log.info("Get access token")
                self.oauth.get_token()
            return self.call(
                sub_path, params=params, method=method, data=data, headers=headers
            )
