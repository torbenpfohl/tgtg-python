import datetime
import random
import sys
import time
import json
from http import HTTPStatus
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from tgtg.google_play_scraper import get_last_apk_version
from tgtg.gmail import get_gmail_url

from .exceptions import TgtgAPIError, TgtgLoginError, TgtgPollingError

BASE_URL = "https://apptoogoodtogo.com/api/"
API_ITEM_ENDPOINT = "item/v8/"
FAVORITE_ITEM_ENDPOINT = "user/favorite/v1/{}/update"
AUTH_BY_EMAIL_ENDPOINT = "auth/v3/authByEmail"
AUTH_POLLING_ENDPOINT = "auth/v3/authByRequestPollingId"
AUTH_BY_REQUEST_PIN_ENDPOINT = "auth/v5/authByRequestPin"
SIGNUP_BY_EMAIL_ENDPOINT = "auth/v3/signUpByEmail"
REFRESH_ENDPOINT = "auth/v3/token/refresh"
ACTIVE_ORDER_ENDPOINT = "order/v7/active"
INACTIVE_ORDER_ENDPOINT = "order/v7/inactive"
CREATE_ORDER_ENDPOINT = "order/v7/create/"
ABORT_ORDER_ENDPOINT = "order/v7/{}/abort"
ORDER_STATUS_ENDPOINT = "order/v7/{}/status"
ORDER_PAY_ENDPOINT = "order/v7/{}/pay"
API_BUCKET_ENDPOINT = "discover/v1/bucket"
PAYMENT_STATUS_ENDPOINT = "payment/v3"
PAYMENT_METHOD_ENDPOINT = "paymentMethod/v1/item"
PRICE_SPECIFICATIONS_ENDPOINT = "item/v8/{}/getPriceSpecifications"
DEFAULT_APK_VERSION = "22.5.5"
USER_AGENTS = [
    "TGTG/{} Dalvik/2.1.0 (Linux; U; Android 9; Nexus 5 Build/M4B30Z)",
    "TGTG/{} Dalvik/2.1.0 (Linux; U; Android 10; SM-G935F Build/NRD90M)",
    "TGTG/{} Dalvik/2.1.0 (Linux; Android 12; SM-G920V Build/MMB29K)",
]
DEFAULT_ACCESS_TOKEN_LIFETIME = 3600 * 4  # 4 hours
MAX_POLLING_TRIES = 24  # 24 * POLLING_WAIT_TIME = 2 minutes
POLLING_WAIT_TIME = 5  # Seconds
MAX_PAYMENT_STATUS_TRIES = 10
REQUEST_WAIT_TIME = 3  # Seconds


class TgtgClient:
    def __init__(
        self,
        url=BASE_URL,
        email=None,
        access_token=None,
        refresh_token=None,
        user_id=None,
        user_agent=None,
        language="en-GB",
        proxies=None,
        timeout=None,
        last_time_token_refreshed=None,
        access_token_lifetime=DEFAULT_ACCESS_TOKEN_LIFETIME,
        device_type="ANDROID",
        cookie=None,
    ):
        self.base_url = url

        self.email = email

        self.access_token = access_token
        self.refresh_token = refresh_token
        self.user_id = user_id
        self.cookie = cookie

        self.last_time_token_refreshed = last_time_token_refreshed
        self.access_token_lifetime = access_token_lifetime

        self.device_type = device_type

        self.user_agent = user_agent if user_agent else self._get_user_agent()
        self.language = language
        self.proxies = proxies
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers = self._headers

    def _get_user_agent(self):
        try:
            self.version = get_last_apk_version()
        except Exception:
            self.version = DEFAULT_APK_VERSION
            sys.stdout.write("Failed to get last version\n")

        sys.stdout.write(f"Using version {self.version}\n")

        return random.choice(USER_AGENTS).format(self.version)

    def _get_url(self, path):
        return urljoin(self.base_url, path)

    def get_credentials(self):
        self.login()
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "user_id": self.user_id,
            "cookie": self.cookie,
        }

    @property
    def _headers(self):
        headers = {
            "accept": "application/json",
            "Accept-Encoding": "gzip",
            "accept-language": self.language,
            "content-type": "application/json; charset=utf-8",
            "user-agent": self.user_agent,
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.access_token:
            headers["authorization"] = f"Bearer {self.access_token}"
        return headers

    @property
    def _already_logged(self):
        return bool(self.access_token and self.refresh_token and self.user_id)

    def _refresh_token(self):
        if (
            self.last_time_token_refreshed
            and (datetime.datetime.now() - self.last_time_token_refreshed).seconds
            <= self.access_token_lifetime
        ):
            return

        response = self.session.post(
            self._get_url(REFRESH_ENDPOINT),
            json={"refresh_token": self.refresh_token},
            headers=self._headers,
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            self.access_token = response.json()["access_token"]
            self.refresh_token = response.json()["refresh_token"]
            self.last_time_token_refreshed = datetime.datetime.now()
            self.cookie = response.headers["Set-Cookie"]
        else:
            raise TgtgAPIError(response.status_code, response.content)
    
    def automatic_login(self, polling_id, cookie):
        """(gmail) Retrieve the 6-digit pin from the tgtg-email."""
        now = datetime.datetime.now()
        timestamp = int(now.timestamp()) - 60
        code = get_gmail_url(timestamp)
        if code:
            json = {
                "device_type": self.device_type,
                "email": self.email,
                "request_pin": code,
                "request_polling_id": polling_id,
            }
            headers = self._headers
            headers["Cookie"] = cookie
            time.sleep(5)
            response = self.session.post(
                self._get_url(AUTH_BY_REQUEST_PIN_ENDPOINT),
                headers=headers,
                json=json,
            )
            if response.status_code == 200:
                print("Automatic login worked!")
                return
            else:
                print(f"gmail >>> no new email yet. will try again in X seconds. {datetime.datetime.now().strftime('%H.%M.%S')}")

    def login(self):
        if not (
            self.email
            or self.access_token
            and self.refresh_token
            and self.user_id
            and self.cookie
        ):
            raise TypeError(
                "You must provide at least email or access_token, refresh_token, user_id and cookie"
            )
        if self._already_logged:
            self._refresh_token()
        else:
            response = self.session.post(
                self._get_url(AUTH_BY_EMAIL_ENDPOINT),
                headers=self._headers,
                json={
                    "device_type": self.device_type,
                    "email": self.email,
                },
                proxies=self.proxies,
                timeout=self.timeout,
            )
            if response.status_code == HTTPStatus.OK:
                first_login_response = response.json()
                if first_login_response["state"] == "TERMS":
                    raise TgtgPollingError(
                        f"This email {self.email} is not linked to a tgtg account. "
                        "Please signup with this email first."
                    )
                elif first_login_response["state"] == "WAIT":
                    self.start_polling(first_login_response["polling_id"])
                else:
                    raise TgtgLoginError(response.status_code, response.content)
            else:
                if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    raise TgtgAPIError(
                        response.status_code, "Too many requests. Try again later."
                    )
                else:
                    raise TgtgLoginError(response.status_code, response.content)

    def start_polling(self, polling_id):
        for _ in range(MAX_POLLING_TRIES):
            response = self.session.post(
                self._get_url(AUTH_POLLING_ENDPOINT),
                headers=self._headers,
                json={
                    "device_type": self.device_type,
                    "email": self.email,
                    "request_polling_id": polling_id,
                },
                proxies=self.proxies,
                timeout=self.timeout,
            )
            if response.status_code == HTTPStatus.ACCEPTED:
                sys.stdout.write(
                    "Check your mailbox on PC to continue... "
                    "(Opening email on mobile won't work, if you have installed tgtg app.)\n"
                )
                time.sleep(POLLING_WAIT_TIME)
                cookies = response.headers["Set-Cookie"]
                datadome_cookie = [cookie for cookie in cookies.split(";") if cookie.startswith("datadome=")]
                if len(datadome_cookie) == 1:
                    datadome_cookie = datadome_cookie[0]
                    self.automatic_login(polling_id, datadome_cookie)
                continue
            elif response.status_code == HTTPStatus.OK:
                sys.stdout.write("Logged in!\n")
                login_response = response.json()
                self.access_token = login_response["access_token"]
                self.refresh_token = login_response["refresh_token"]
                self.last_time_token_refreshed = datetime.datetime.now()
                self.user_id = login_response["startup_data"]["user"]["user_id"]
                self.cookie = response.headers["Set-Cookie"]
                return
            else:
                if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    raise TgtgAPIError(
                        response.status_code, "Too many requests. Try again later."
                    )
                else:
                    raise TgtgLoginError(response.status_code, response.content)

        raise TgtgPollingError(
            f"Max retries ({MAX_POLLING_TRIES * POLLING_WAIT_TIME} seconds) reached. Try again."
        )

    def get_items(
        self,
        *,
        latitude=0.0,
        longitude=0.0,
        radius=21,
        page_size=20,
        page=1,
        discover=False,
        favorites_only=True,
        item_categories=None,
        diet_categories=None,
        pickup_earliest=None,
        pickup_latest=None,
        search_phrase=None,
        with_stock_only=False,
        hidden_only=False,
        we_care_only=False,
    ):
        self.login()

        # fields are sorted like in the app
        data = {
            "user_id": self.user_id,
            "origin": {"latitude": latitude, "longitude": longitude},
            "radius": radius,
            "page_size": page_size,
            "page": page,
            "discover": discover,
            "favorites_only": favorites_only,
            "item_categories": item_categories if item_categories else [],
            "diet_categories": diet_categories if diet_categories else [],
            "pickup_earliest": pickup_earliest,
            "pickup_latest": pickup_latest,
            "search_phrase": search_phrase if search_phrase else None,
            "with_stock_only": with_stock_only,
            "hidden_only": hidden_only,
            "we_care_only": we_care_only,
        }
        response = self.session.post(
            self._get_url(API_ITEM_ENDPOINT),
            headers=self._headers,
            json=data,
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json()["items"]
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def get_item(self, item_id):
        self.login()
        response = self.session.post(
            urljoin(self._get_url(API_ITEM_ENDPOINT), str(item_id)),
            headers=self._headers,
            json={"user_id": self.user_id, "origin": None},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json()
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def get_favorites(
        self,
        latitude=0.0,
        longitude=0.0,
        radius=21,
        page_size=50,
        page=0,
    ):
        self.login()

        # fields are sorted like in the app
        data = {
            "origin": {"latitude": latitude, "longitude": longitude},
            "radius": radius,
            "user_id": self.user_id,
            "paging": {"page": page, "size": page_size},
            "bucket": {"filler_type": "Favorites"},
        }
        response = self.session.post(
            self._get_url(API_BUCKET_ENDPOINT),
            headers=self._headers,
            json=data,
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json().get("mobile_bucket", {}).get("items", [])
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def set_favorite(self, item_id, is_favorite):
        self.login()
        response = self.session.post(
            self._get_url(FAVORITE_ITEM_ENDPOINT.format(item_id)),
            headers=self._headers,
            json={"is_favorite": is_favorite},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code != HTTPStatus.OK:
            raise TgtgAPIError(response.status_code, response.content)

    def create_order(self, item_id, item_count):
        self.login()

        response = self.session.post(
            urljoin(self._get_url(CREATE_ORDER_ENDPOINT), str(item_id)),
            headers=self._headers,
            json={"item_count": item_count},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code != HTTPStatus.OK:
            raise TgtgAPIError(response.status_code, response.content)
        elif response.json()["state"] != "SUCCESS":
            raise TgtgAPIError(response.json()["state"], response.content)
        else:
            return response.json()["order"]

    def get_order_status(self, order_id):
        self.login()

        response = self.session.post(
            self._get_url(ORDER_STATUS_ENDPOINT.format(order_id)),
            headers=self._headers,
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json()
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def abort_order(self, order_id):
        """Use this when your order is not yet paid"""
        self.login()

        response = self.session.post(
            self._get_url(ABORT_ORDER_ENDPOINT.format(order_id)),
            headers=self._headers,
            json={"cancel_reason_id": 1},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code != HTTPStatus.OK:
            raise TgtgAPIError(response.status_code, response.content)
        elif response.json()["state"] != "SUCCESS":
            raise TgtgAPIError(response.json()["state"], response.content)
        else:
            return

    def signup_by_email(
        self,
        *,
        email,
        name="",
        country_id="GB",
        newsletter_opt_in=False,
        push_notification_opt_in=True,
    ):
        response = self.session.post(
            self._get_url(SIGNUP_BY_EMAIL_ENDPOINT),
            headers=self._headers,
            json={
                "country_id": country_id,
                "device_type": self.device_type,
                "email": email,
                "name": name,
                "newsletter_opt_in": newsletter_opt_in,
                "push_notification_opt_in": push_notification_opt_in,
            },
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            self.access_token = response.json()["login_response"]["access_token"]
            self.refresh_token = response.json()["login_response"]["refresh_token"]
            self.last_time_token_refreshed = datetime.datetime.now()
            self.user_id = response.json()["login_response"]["startup_data"]["user"][
                "user_id"
            ]
            return self
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def get_active(self):
        self.login()
        response = self.session.post(
            self._get_url(ACTIVE_ORDER_ENDPOINT),
            headers=self._headers,
            json={"user_id": self.user_id},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json()
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def get_inactive(self, page=0, page_size=20):
        self.login()
        response = self.session.post(
            self._get_url(INACTIVE_ORDER_ENDPOINT),
            headers=self._headers,
            json={"paging": {"page": page, "size": page_size}, "user_id": self.user_id},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json()
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def pay(self, item_id, item_count, payment_provider="paypal"):
        """currently only for adyen and paypal."""
        # Adyen
        self.login()
        
        order = self.create_order(item_id, item_count)
        order_id = order.get("id")
        print("Order is", order.get("state"))

        payment_method_data = self._get_payment_methods(item_id, payment_provider)
        price_specification = self._get_price_specifications(item_id)
        payment_info = self._initialise_payment_process(order_id, payment_method_data)
        payment_id = payment_info.get("payment_id")
        # user_id = payment_info.get("user_id")

        for _ in range(MAX_PAYMENT_STATUS_TRIES):
            payment_status = self._get_payment_status(payment_id)
            if payment_status.get("payload") != None:
                adyen_url_call = payment_status.get("payload")
                break
        else:
            raise TgtgAPIError("Did not get adyen-payload to start payment-process.")
        
        self._adyen(adyen_url_call)
        



    def _get_payment_methods(self, item_id, payment_provider):

        # from a tgtg-version 24.2.13 api-call
        json = {
            "supported_types": [
                {
                    "payment_types": [
                        "CREDITCARD",
                        "SOFORT",
                        "IDEAL",
                        "PAYPAL",
                        "BCMCMOBILE",
                        "BCMCCARD",
                        "VIPPS",
                        "TWINT",
                        "MBWAY",
                        "SWISH",
                        "BLIK",
                        "GOOGLEPAY"
                    ],
                    "provider": "ADYEN"
                },
                {
                    "payment_types": [
                        "VOUCHER",
                        "FAKE_DOOR"
                    ],
                    "provider": "VOUCHER"
                },
                {
                    "payment_types": [
                        "VENMO"
                    ],
                    "provider": "BRAINTREE"
                },
                {
                    "payment_types": [
                        "CHARITY"
                    ],
                    "provider": "CHARITY"
                },
                {
                    "payment_types": [
                        "SATISPAY"
                    ],
                    "provider": "SATISPAY"
                }
            ]
        }

        response = self.session.post(
            urljoin(self._get_url(PAYMENT_METHOD_ENDPOINT), str(item_id)),
            headers=self._headers,
            json=json,
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code != HTTPStatus.OK:
            raise TgtgAPIError(response.status_code, response.content)
        elif response.json()["payment_methods_state"] != "SUCCESS":
            raise TgtgAPIError(response.json()["payment_methods_state"], response.content)
        else:
            payment_methods = response.json()["payment_methods"]

        adyen_paypal = [method for method in payment_methods 
                                    if method.get("payment_provider").lower() == "adyen" 
                                        and method.get("payment_type").lower() == "paypal"]
        if len(adyen_paypal) == 0:
            raise TgtgAPIError("Adyen with Paypal not available.")

        return adyen_paypal[0]

    def _get_price_specifications(self, item_id):
        response = self.session.post(
            self._get_url(PRICE_SPECIFICATIONS_ENDPOINT).format(item_id),
            headers=self._headers,
            json={"get_full_list": False},
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code == HTTPStatus.OK:
            return response.json()["price_specifiations"][0]
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def _initialise_payment_process(self, order_id, payment_method_data):
        json = {
            "authorization": {
                "authorization_payload": {
                    "payload": payment_method_data.get("adyen_api_payload"),
                    "payment_type": payment_method_data.get("payment_type"),
                    "save_payment_method": False,
                    "type": "adyenAuthorizationPayload",
                },
                "payment_provider": payment_method_data.get("payment_provider"),
                "return_url": "adyencheckout://com.app.tgtg.itemview",
            }
        }

        response = self.session.post(
            self._get_url(ORDER_PAY_ENDPOINT).format(order_id),
            headers=self._headers,
            json=json,
            proxies=self.proxies,
            timeout=self.timeout,
        )
        if response.status_code != HTTPStatus.OK:
            raise TgtgAPIError(response.status_code, response.content)
        elif response.json()["state"] != "AUTHORIZATION_INITIATED":
            raise TgtgAPIError(response.json()["payment_methods_state"], response.content)
        else:
            return reponse.json()

    def _get_payment_status(self, payment_id):
        response = self.session.post(
            urljoin(self._get_url(PAYMENT_STATUS_ENDPOINT), str(payment_id)),
            headers=self._headers,
            proxies=self.proxies,
            timeout=self.timeout,
        )

        if response.status_code == HTTPStatus.OK:
            return respones.json()
        else:
            raise TgtgAPIError(response.status_code, response.content)

    def _adyen(self, adyen_url_call):
        adyen_url_call = json.loads(adyen_url_call)
        adyen_url = adyen_url_call.get("url")
        host = adyen_url.removeprefix("https://").split("/")[0]


        adyen_session = requests.Session()
        adyen_session.headers = {
            "Host": host,
            "user-agent": "Mozilla/5.0 (Linux; Android 11; sdk_gphone_x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36",
        }
        response = adyen_session.get(adyen_url)
        if response.status_code != 200:
            raise TgtgAPIError(response.status_code, response.content)
        response_parsed = BeautifulSoup(response.text, "html.parser")
        input_fields = response_parsed.find_all("input")
        action_url = response_parsed.find("form").get("action")
        action_url = adyen_url.split("/")[:-1].append(action_url)
        action_url = "/".join(action_url)
        
        data = dict()
        for field in input_fields:
            key = field.get("name")
            value = field.get("value")
            data.update({key: value})
        response = adyen_session.post(
            action_url,
            headers={"Referer": adyen_url, "Origin": "https://"+host},
            data=data,
        )
        if response.status_code != 200:
            raise TgtgAPIError(response.status_code, response.content)
        paypal_url = response.headers.get("location")

        paypal_session = requests.Session()
        paypal_session.headers = {
            "user-agent": "Mozilla/5.0 (Linux; Android 11; sdk_gphone_x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Mobile Safari/537.36",
        }
        response = paypal_session.get(
            paypal_url,
            headers={"referer": adyen_url},
        )
        if response.status_code != 200:
            raise TgtgAPIError(response.status_code, response.content)
        print("adyen api calls were successful.")
        # call paypal url
        # script -> data-csrf, data-sessionID, 




"""
{
    "_csrf": "Hrj0d7tp5qXMIUVstGYrYcwXihv5VP6eruKzA=",
    "_sessionID": "_sessionID=rYably31qJUmhNbBKK-_ud85AzvItJ5_",
    "fpti": {
        "captchaState": "CLIENT_SIDE_RECAPTCHA_V3_STATIC_SERVED",
        "page": "main:authchallenge::cgi-bin:webscr",
        "pgrp": "main:authchallenge::cgi-bin:webscr"
    }
}


"""

# for later: software_token_authenticator instead of sms_otp
#    and than use a custom build/ in code authenticator
#    https://stackoverflow.com/questions/8529265/google-authenticator-implementation-in-python

        
"""
ablauf (vorläufig):
1. weiterleitung von adyen zur paypal login seite.
   /cgi-bin/websrc...  eingeben von email und dann durch button-click Weiterleitung an /signin...
 - aufrufen des ersten createChallenge-js-scripts
 -> senden der lösung an auth/verifychallenge

2. aufrufen von /signin?intent=checkout...
 - post-request mit email + weitere sachen (token und so, denke ich)
 - holt json und bereitet so die seite für die Passwort-Eingabe vor.
 - post-request mit dem zusätzlich jetzt u.a. dem Passwort an die gleiche url.
 - antwort mit redirect zu 2FA-Seite

3. /authflow/twofactor  ist für 2FA zuständig/ ist die 2FA-Eingabe-Seite    
 -> hat auch ein createchallenge, aber mit recaptcha (siehe Recaptcha-Exkurs)
 - bei sms_otp wird eine put-request an authflow/twofactor/ gesendet (wahrscheinlich um loszutrete, dass eine sms versand wird.)
 --> web/res/.../js/app.js erzeugt Teile der put-request
 -> bei software_token_authenticator würde ich annehmen, dass dieser schritt übersprungen wird
 --> die put-request gibt ein json zurück, was vermutlich - wie bei /signin?intent... - die Seite entsprechend so verändert, dass das 2FA-Kennwort eingegeben werden kann.
 - die Bestätigung nach Eingabe des 2FA-Codes sorgt für eine post-request an authflow/twofactor 
 - die wiederum liefert eine redirect-url im json-body, die /webapps/hermes.. ist.

4. /webapps/hermes?... ist die eingeloggte seite, d.h. die seite, auf der man die zahlung bestätigt.
 -> hat auch ein createchallenge, aber mit recaptcha
 - hält auch schon die daten der bank und bankkonten

(5. /xoplatform/logger/api/logger/)

X. /graphql/  abschließende daten der der Bezahlung holen

Fragen:
- wann werden die challenges beantwortet?
- was sorgt dafür, dass die captchas nicht angezeigt werden?
- wie komme ich von webapps/hermes zur abgeschlossenen bezahlung?
 -> brauch ich api/logger-requests?


Recaptcha-Exkurs (für authflow/twofactor):
- authflow/twofactor ist die Hauptseite!
-> lädt auth/createchallenge/.../recaptchav3.js (das ist jetzt auf der authflow/twofactor-Seite)
--> das wiederum lädt auth/recaptcha/grcenterprise_v3.html
---> das lädt dann recaptcha.net/recaptcha/enterprise.js und 'rendert' bzw. führt es aus das
--> ...v_3.html erhebt u.a. die render-Dauer (Start- und Endzeit) und sendet die Daten an authflow/twofactor
-> die Hauptseite verarbeitet die Daten und sendet sie an auth/verifygrcenterprise


"""