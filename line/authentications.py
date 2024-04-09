import os
from pathlib import Path

import requests

class Authentication:

    def login(self):
        raise NotImplementedError


class CookieAuthentication(Authentication):

    def __init__(self, cookies):
        self.cookies = cookies

    @classmethod
    def cookie_str_to_dict(cls, cookie_str):
        cookie_dict = {}
        cookie_list = cookie_str.split("; ")
        for item in cookie_list:
            key, value = item.split("=", 1)
            cookie_dict[key] = value
        return cookie_dict

    def login(self):
        cookies = self.cookie_str_to_dict(self.cookies)
        return {
            "ses": cookies["ses"],
            "xsrf_token": cookies["XSRF-TOKEN"]
        }

    def __str__(self):
        return f"<CookieAuthentication(cookies=\"{self.cookies}\")>"


class BusinessAuthentication(Authentication):

    def __init__(self, username, password):
        self.username = username
        self.password = password

    @classmethod
    def get_login_cookies(cls):
        url = "https://account.line.biz/login"
        params = {
            "redirectUri": "https://manager.line.biz/"
        }
        response = requests.get(url, params=params)
        return response.cookies

    @classmethod
    def csrf_token(cls, session):
        url = "https://chat.line.biz/api/v1/csrfToken"
        response = session.get(url)
        return response.json()

    def login(self):
        login_cookies = self.get_login_cookies()
        rsession = login_cookies['RSESSION']
        x_xsrf_token = login_cookies['XSRF-TOKEN']
        session = requests.session()
        headers = {
            "X-XSRF-TOKEN": x_xsrf_token
        }
        cookies = {
            "RSESSION": rsession,
            "XSRF-TOKEN": x_xsrf_token
        }
        url = "https://account.line.biz/api/login/email"
        data = {
            "email": self.username,
            "password": self.password,
            "stayLoggedIn": False,
            "gRecaptchaResponse": ""
        }
        response = session.post(url, headers=headers, cookies=cookies, json=data)
        return {
            "ses": session.cookies["ses"],
            "xsrf_token": self.csrf_token(session)["token"]
        }

    def __str__(self):
        return f"<BusinessAuthentication(username=\"{self.username}\",password=\"{self.password}\")>"


class PersonQRCodeAuthentication(Authentication):

    def __init__(self, qrcode_path=None):
        if qrcode_path is None:
            self.qrcode_path = '.'
        else:
            self.qrcode_path = qrcode_path

    def get_qrcode(self, qr_code_path):
        qr_ses = qr_code_path.split('/')[-1]
        cookies = {
            "qrSes": qr_ses
        }
        url = f"https://access.line.me{qr_code_path}"
        response = requests.get(url, cookies=cookies)
        return response.content

    def get_qrcode_path(self):
        url = "https://access.line.me/qrlogin/v1/session"
        params = {
            "_": "1700539179160",
            "channelId": "1576775644",
            "returnUri": "/oauth2/v2.1/authorize/consent?response_type=code&client_id=1576775644&redirect_uri=https%3A%2F%2Faccount.line.biz%2Flogin%2Fline-callback&scope=profile&state=lz6UrmqJhYA3zHvpkJhFDE651SEbKtd"
        }
        response = requests.get(url, params=params)
        return response.json()

    def qr_wait(self, qr_ses):
        session = requests.Session()
        cookies = {
            "qrSes": qr_ses
        }
        url = "https://access.line.me/qrlogin/v1/qr/wait"
        params = {
            "_": "1700547780369",
            "channelId": "1576775644"
        }
        session.get(url, cookies=cookies, params=params)
        return session

    def login(self):
        qrcode_path = self.get_qrcode_path()['qrCodePath']
        qr_ses = qrcode_path.split('/')[-1]
        qrcode = self.get_qrcode(qrcode_path)
        path = Path(self.qrcode_path)
        path.mkdir(parents=True, exist_ok=True)

        filename = path / "qrcode.png"
        with open(filename, 'wb') as f:
            f.write(qrcode)

        os.system("start %s" % filename.absolute())

        self.qr_wait(qr_ses)

        return {
            "ses": "",
            "xsrf_token": ""
        }

    def __str__(self):
        return f"<PersonQRCodeAuthentication(qrcode_path=\"{self.qrcode_path}\")>"


class BrowserAuthentication(Authentication):

    def __init__(self, page):
        self.page = page
        self.page.goto("https://manager.line.biz/")

        while self.page.url.startswith("https://account.line.biz") or self.page.url.startswith(
                "https://access.line.me"):
            self.page.wait_for_timeout(1 * 1000)

        self.cookies = {item["name"]: item["value"] for item in self.page.context.cookies()}
        self.csrf_token = self.get_csrf_token()

    def get_csrf_token(self):
        url = "https://chat.line.biz/api/v1/csrfToken"
        response = requests.get(url, cookies=self.cookies)
        return response.json()

    def login(self):
        data = {
            "ses": self.cookies["ses"],
            "xsrf_token": self.csrf_token["token"]
        }
        return data

    def __str__(self):
        return f"<BrowserAuthentication(cookies=\"{self.cookies}\",csrf_token=\"{self.csrf_token}\")>"
