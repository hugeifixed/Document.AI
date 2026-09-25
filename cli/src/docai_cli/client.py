"""Small HTTP boundary for the independently installed CLI."""

from __future__ import annotations

import getpass
import os
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from requests import Response, Session
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor

from docai_cli.errors import (
    EXIT_AUTH,
    EXIT_NOT_FOUND,
    EXIT_SERVER,
    EXIT_TIMEOUT,
    EXIT_TRANSPORT,
    EXIT_VALIDATION,
    CliError,
)


class DocAIClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 30,
        *,
        username: str | None = None,
        password: str | None = None,
        password_stdin: bool = False,
        auth_mode: str = "session",
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CliError(
                "Base URL must be an absolute HTTP or HTTPS URL.",
                EXIT_VALIDATION,
                "INVALID_BASE_URL",
            )
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise CliError("Remote DocAI URLs must use HTTPS.", EXIT_VALIDATION, "HTTPS_REQUIRED")
        self.base_url = base_url.rstrip("/") + "/"
        self.api_root = urljoin(self.base_url, "api/v1/")
        self.timeout = timeout
        self.username = username or os.environ.get("DOCAI_USERNAME")
        self.password = password or os.environ.get("DOCAI_PASSWORD")
        self.password_stdin = password_stdin
        self.auth_mode = auth_mode or os.environ.get("DOCAI_AUTH", "session")
        self.session: Session = requests.Session()
        # Keep proxy env support while preventing requests from silently reading .netrc.
        self.session.trust_env = False
        self.session.proxies = requests.utils.get_environ_proxies(self.base_url)
        self.session.verify = os.environ.get("REQUESTS_CA_BUNDLE") or True
        self._authenticated = False
        self._closed = False
        self.deadline: float | None = None

    def request(self, method: str, path: str, *, api: bool = True, **kwargs: Any) -> Response:
        if not self._authenticated and path not in {"auth/session/", "auth/login/"} and api:
            self.authenticate()
        url = (
            path
            if path.startswith(("http://", "https://"))
            else urljoin(self.api_root if api else self.base_url, path.lstrip("/"))
        )
        self._validate_origin(url)
        timeout = self._request_timeout()
        try:
            # Do not let Requests follow redirects implicitly. Its redirect handler can
            # forward credentials or replay an authentication body before we inspect Location.
            kwargs["allow_redirects"] = False
            response = self.session.request(method, url, timeout=timeout, **kwargs)
        except requests.Timeout as exc:
            raise CliError(
                "The request timed out; the server may still be processing it.",
                EXIT_TIMEOUT,
                "REQUEST_TIMEOUT",
            ) from exc
        except requests.RequestException as exc:
            raise CliError(
                f"Could not reach DocAI: {exc.__class__.__name__}.", EXIT_TRANSPORT, "NETWORK_ERROR"
            ) from exc
        if _is_redirect(response.status_code, method):
            response.close()
            raise CliError(
                "DocAI returned a redirect; verify the configured base URL.",
                EXIT_VALIDATION,
                "UNEXPECTED_REDIRECT",
            )
        return response

    def authenticate(self) -> None:
        if self.auth_mode == "basic":
            if not self.username:
                raise CliError(
                    "Set DOCAI_USERNAME before using Basic authentication.",
                    EXIT_AUTH,
                    "CREDENTIALS_REQUIRED",
                )
            password = self._password()
            self.session.auth = (self.username, password)
            self._authenticated = True
            return
        if self.auth_mode != "session":
            raise CliError(
                "DOCAI_AUTH must be 'session' or 'basic'.", EXIT_VALIDATION, "INVALID_AUTH_MODE"
            )
        if not self.username:
            raise CliError(
                "Set DOCAI_USERNAME to sign in to DocAI.", EXIT_AUTH, "CREDENTIALS_REQUIRED"
            )
        csrf_response = self._request_raw("GET", urljoin(self.api_root, "auth/session/"))
        self._check_response(csrf_response)
        csrf = self.session.cookies.get("csrftoken") or ""
        if not csrf:
            raise CliError(
                "DocAI did not establish a CSRF cookie for session login.",
                EXIT_AUTH,
                "CSRF_COOKIE_MISSING",
            )
        username = self.username
        if not username:
            raise CliError(
                "Set DOCAI_USERNAME to sign in to DocAI.", EXIT_AUTH, "CREDENTIALS_REQUIRED"
            )
        login = self._request_raw(
            "POST",
            urljoin(self.api_root, "auth/login/"),
            json={"username": username, "password": self._password()},
            headers={"X-CSRFToken": csrf, "Referer": self.base_url},
        )
        self._check_response(login)
        self._authenticated = True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._authenticated and self.auth_mode == "session":
                csrf = self.session.cookies.get("csrftoken") or ""
                response = self.session.post(
                    urljoin(self.api_root, "auth/logout/"),
                    headers={"X-CSRFToken": csrf, "Referer": self.base_url},
                    # Logout is best-effort cleanup; an expired poll deadline must not
                    # replace the operation's original timeout error.
                    timeout=self.timeout,
                    allow_redirects=False,
                )
                # A local session is disposable. Cleanup failures must not mask a successful job.
                if not response.ok or _is_redirect(response.status_code, "POST"):
                    from docai_cli.output import diagnostic

                    diagnostic("Could not end the temporary API session; it will expire normally.")
        except requests.RequestException:
            pass
        finally:
            self.session.close()

    def get_json(
        self, path: str, *, api: bool = True, headers: Mapping[str, str] | None = None
    ) -> tuple[Any, Response]:
        response = self.request("GET", path, api=api, headers=dict(headers or {}))
        if response.status_code == 304:
            return None, response
        body = self._read_json(response)
        if not response.ok:
            raise self._api_error(response, body)
        return self._data(body), response

    def post_json(
        self, path: str, payload: Mapping[str, Any], *, headers: Mapping[str, str] | None = None
    ) -> tuple[Any, Response]:
        response = self.request("POST", path, json=dict(payload), headers=dict(headers or {}))
        body = self._read_json(response)
        data = self._data(body)
        partial_rejection = self._partial_upload_error(body, data)
        if partial_rejection is not None:
            raise partial_rejection
        if not response.ok:
            raise self._api_error(response, body, data=data)
        return data, response

    def upload(
        self,
        dataset_id: str,
        paths: list[Path],
        *,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[Any, Response]:
        fields: list[tuple[str, tuple[str, Any, str]]] = []
        try:
            for path in paths:
                fields.append(("files", (path.name, path.open("rb"), "application/octet-stream")))
            encoder = MultipartEncoder(fields=fields)
            body: MultipartEncoder | MultipartEncoderMonitor = encoder
            if on_progress is not None:
                on_progress(0, encoder.len)
                body = MultipartEncoderMonitor(
                    encoder, lambda monitor: on_progress(monitor.bytes_read, monitor.len)
                )
            response = self.request(
                "POST",
                f"datasets/{dataset_id}/upload/",
                data=body,
                headers={"Content-Type": encoder.content_type},
            )
        finally:
            for _, (_, file_obj, _) in fields:
                file_obj.close()
        body = self._read_json(response)
        data = self._data(body)
        partial_rejection = self._partial_upload_error(body, data)
        if partial_rejection is not None:
            raise partial_rejection
        if not response.ok:
            raise self._api_error(response, body, data=data)
        return data, response

    @staticmethod
    def _partial_upload_error(body: Any, data: Any) -> CliError | None:
        if not isinstance(data, dict) or not data.get("rejected"):
            return None
        trace_id = body.get("trace_id") if isinstance(body, dict) else None
        return CliError(
            "One or more files were rejected; inspect the returned data before invoking the accepted files.",
            EXIT_VALIDATION,
            "PARTIAL_UPLOAD_REJECTION",
            trace_id=trace_id,
            data=data,
        )

    def download(
        self,
        path: str,
        destination: Path,
        *,
        force: bool = False,
        on_progress: Callable[[int, int | None], None] | None = None,
    ) -> None:
        """Stream to a sibling temporary file, then publish without partial output."""
        if destination.exists() and not force:
            raise CliError(
                f"Output file already exists: {destination}", EXIT_VALIDATION, "OUTPUT_EXISTS"
            )
        if not destination.parent.is_dir():
            raise CliError(
                f"Output directory does not exist: {destination.parent}",
                EXIT_VALIDATION,
                "OUTPUT_DIRECTORY_MISSING",
            )
        response = self.request("GET", path, stream=True)
        try:
            if not response.ok:
                body = self._read_json(response)
                raise self._api_error(response, body)
            total: int | None = None
            if response.headers.get("Content-Encoding", "identity").lower() == "identity":
                with suppress(ValueError):
                    total = int(response.headers.get("Content-Length", "")) or None
            if on_progress is not None:
                on_progress(0, total)
            descriptor: int | None = None
            temporary: str | None = None
            try:
                descriptor, temporary = tempfile.mkstemp(prefix=".docai-", dir=destination.parent)
                output = os.fdopen(descriptor, "wb")
                descriptor = None  # The file object now owns the descriptor.
                with output:
                    transferred = 0
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            output.write(chunk)
                            transferred += len(chunk)
                            if on_progress is not None:
                                on_progress(transferred, total)
                    output.flush()
                    os.fsync(output.fileno())
                if force:
                    os.replace(temporary, destination)
                else:
                    # Hard-link creation is atomic and fails if a destination appeared meanwhile.
                    os.link(temporary, destination)
                    os.unlink(temporary)
            except OSError as exc:
                if descriptor is not None:
                    with suppress(OSError):
                        os.close(descriptor)
                if temporary is not None:
                    with suppress(FileNotFoundError):
                        os.unlink(temporary)
                if isinstance(exc, FileExistsError):
                    raise CliError(
                        f"Output file already exists: {destination}",
                        EXIT_VALIDATION,
                        "OUTPUT_EXISTS",
                    ) from exc
                raise CliError(
                    "Could not save the completed export.", EXIT_SERVER, "EXPORT_WRITE_FAILED"
                ) from exc
        finally:
            response.close()

    def list_all(
        self, path: str, *, page: int = 1, limit: int = 100, all_pages: bool = False
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 200:
            raise CliError(
                "--limit must be between 1 and 200 (the API hard maximum).",
                EXIT_VALIDATION,
                "INVALID_LIMIT",
            )
        query = f"page={page}&page_size={limit}"
        separator = "&" if "?" in path else "?"
        url = path + separator + query
        results: list[dict[str, Any]] = []
        pages = 0
        while url:
            data, _ = self.get_json(url)
            if isinstance(data, list):
                results.extend(item for item in data if isinstance(item, dict))
                break
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise CliError(
                    "The API returned an unexpected list response.",
                    EXIT_SERVER,
                    "INVALID_API_RESPONSE",
                )
            results.extend(item for item in data["results"] if isinstance(item, dict))
            next_url = data.get("next")
            if not all_pages or not next_url:
                break
            pages += 1
            if pages >= 1000:
                raise CliError(
                    "Stopped after 1,000 pages; narrow the list with a filter.",
                    EXIT_VALIDATION,
                    "PAGE_LIMIT_REACHED",
                    details={"partial_count": len(results)},
                    data=results,
                )
            url = self._same_origin(str(next_url))
        return results

    def _password(self) -> str:
        if self.password is not None:
            return self.password
        if self.password_stdin:
            if sys.stdin.isatty():
                raise CliError(
                    "--password-stdin requires piped input, not a terminal.",
                    EXIT_VALIDATION,
                    "PASSWORD_STDIN_REQUIRES_PIPE",
                )
            return sys.stdin.readline().rstrip("\r\n")
        if sys.stdin.isatty():
            return getpass.getpass("DocAI password: ")
        raise CliError(
            "Set DOCAI_PASSWORD or provide --password-stdin for non-interactive use.",
            EXIT_AUTH,
            "PASSWORD_REQUIRED",
        )

    def _request_raw(self, method: str, url: str, **kwargs: Any) -> Response:
        self._validate_origin(url)
        try:
            kwargs["allow_redirects"] = False
            response = self.session.request(method, url, timeout=self._request_timeout(), **kwargs)
        except requests.Timeout as exc:
            raise CliError(
                "The authentication request timed out.", EXIT_TIMEOUT, "REQUEST_TIMEOUT"
            ) from exc
        except requests.RequestException as exc:
            raise CliError(
                f"Could not reach DocAI: {exc.__class__.__name__}.", EXIT_TRANSPORT, "NETWORK_ERROR"
            ) from exc
        if _is_redirect(response.status_code, method):
            response.close()
            raise CliError(
                "DocAI returned a redirect; verify the configured base URL.",
                EXIT_VALIDATION,
                "UNEXPECTED_REDIRECT",
            )
        return response

    def _request_timeout(self) -> float | tuple[float, float]:
        remaining = self.timeout
        if self.deadline is not None:
            remaining = min(remaining, self.deadline - time.monotonic())
            if remaining <= 0:
                raise CliError(
                    "The operation exceeded its timeout; processing may continue.",
                    EXIT_TIMEOUT,
                    "OPERATION_TIMEOUT",
                )
        return (min(5.0, remaining), remaining)

    @staticmethod
    def _read_json(response: Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"message": "The API returned a non-JSON error response."}

    @staticmethod
    def _data(body: Any) -> Any:
        return body.get("data", body) if isinstance(body, dict) else body

    def _check_response(self, response: Response) -> None:
        body = self._read_json(response)
        if not response.ok:
            raise self._api_error(response, body)

    def _api_error(self, response: Response, body: Any, *, data: Any = None) -> CliError:
        envelope = body if isinstance(body, dict) else {}
        nested_error = envelope.get("error")
        error = nested_error if isinstance(nested_error, dict) else envelope
        trace_id = error.get("trace_id") or envelope.get("trace_id")
        code = str(error.get("error_code") or f"HTTP_{response.status_code}")
        message = str(
            error.get("message")
            or envelope.get("message")
            or f"DocAI returned HTTP {response.status_code}."
        )
        status_code = response.status_code
        exit_code = (
            EXIT_AUTH
            if status_code in (401, 403) or code == "INVALID_CREDENTIALS"
            else EXIT_NOT_FOUND
            if status_code == 404
            else EXIT_VALIDATION
            if status_code in (400, 409, 422)
            else EXIT_SERVER
            if status_code >= 500
            else EXIT_SERVER
        )
        operation = None
        details = error.get("details") or error.get("errors")
        if code == "INVOCATION_IN_PROGRESS":
            operation = {"retry_after": response.headers.get("Retry-After")}
        retryable = error.get("retryable")
        return CliError(
            message,
            exit_code,
            code,
            trace_id,
            details,
            operation=operation,
            data=data,
            retryable=retryable if isinstance(retryable, bool) else None,
        )

    def _validate_origin(self, url: str) -> None:
        base = urlparse(self.base_url)
        target = urlparse(url)
        if (target.scheme, target.netloc) != (base.scheme, base.netloc):
            raise CliError(
                "Refusing to send credentials to a different host.",
                EXIT_VALIDATION,
                "CROSS_ORIGIN_URL",
            )

    def _same_origin(self, url: str) -> str:
        if url.startswith("/"):
            url = urljoin(self.base_url, url.lstrip("/"))
        self._validate_origin(url)
        parsed = urlparse(url)
        prefix = urlparse(self.api_root)
        if parsed.path.startswith(prefix.path):
            return parsed.path.removeprefix(prefix.path) + (
                f"?{parsed.query}" if parsed.query else ""
            )
        return url


def _is_redirect(status_code: int, method: str) -> bool:
    """Refuse redirects while preserving 304 for conditional GET polling."""
    is_conditional_get = status_code == 304 and method.upper() == "GET"
    return 300 <= status_code < 400 and not is_conditional_get
