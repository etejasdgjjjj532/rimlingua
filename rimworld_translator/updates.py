"""Anonymous, opt-in GitHub release lookup; never installs or rewrites files."""
from dataclasses import dataclass
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .version import __version__


@dataclass(frozen=True)
class UpdateResult:
    status: str
    current_version: str = __version__
    latest_version: str = ""
    release_url: str = ""
    message: str = ""


def _version_parts(value: str) -> tuple[tuple[int, int, int], str]:
    match = re.fullmatch(
        r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", value,
    )
    if not match:
        raise ValueError("The release does not use a semantic version.")
    return tuple(int(match.group(i)) for i in (1, 2, 3)), match.group(4) or ""


def check_for_update(repository: str | None = None, *, enabled: bool = False,
                     current_version: str = __version__, timeout: float = 4.0,
                     opener=urlopen) -> UpdateResult:
    """Check an explicitly configured ``owner/repository`` only after opting in.

    No repository is inferred from a user's Git remote. There is no token,
    telemetry, project upload, background polling, or automatic download.
    Call from a worker thread when used by a desktop UI.
    """
    if not enabled:
        return UpdateResult("disabled", current_version, message="Update checks are disabled.")
    if not repository:
        return UpdateResult("unconfigured", current_version,
                            message="No public release repository is configured.")
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Use a GitHub owner/repository name.")
        if repository.rsplit("/", 1)[1] in (".", ".."):
            raise ValueError("Use a GitHub owner/repository name.")
        current, _ = _version_parts(current_version)
        request = Request(
            f"https://api.github.com/repos/{repository}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": f"RimWorldTranslationEditor/{__version__}",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )
        with opener(request, timeout=timeout) as response:
            raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError("The release response is too large.")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("The release response is not an object.")
        tag = str(payload.get("tag_name", ""))
        latest, prerelease = _version_parts(tag)
        normalized = tag.removeprefix("v")
        if payload.get("draft") or payload.get("prerelease") or prerelease or latest <= current:
            return UpdateResult("current", current_version, normalized,
                                message="No newer stable release is available.")
        release_url = str(payload.get("html_url", ""))
        parsed = urlsplit(release_url)
        expected = f"/{repository}/releases/tag/".casefold()
        if (parsed.scheme != "https" or parsed.netloc != "github.com"
                or not parsed.path.casefold().startswith(expected) or parsed.query or parsed.fragment):
            raise ValueError("The release link does not belong to the configured repository.")
        return UpdateResult("available", current_version, normalized, release_url,
                            message=f"Version {normalized} is available.")
    except (OSError, ValueError, TypeError) as exc:
        return UpdateResult("error", current_version,
                            message=f"Update check unavailable: {exc}")
