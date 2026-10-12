"""YouTube Data API v3 publishing service for Curiosity On Demand."""

import asyncio
import logging
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config.settings import Settings, get_settings
from core.models import AnimationStoryboard, Script, YouTubePublishResult

logger = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeAuthenticationError(Exception):
    """Raised when YouTube OAuth credentials are missing, invalid, or expired."""


class YouTubeUploadError(Exception):
    """Raised when an error occurs during YouTube video upload."""


def clean_topic_title(topic: str) -> str:
    """Strip duration markers and formatting artifacts from topic for a clean video title."""
    cleaned = topic.strip().strip("\"'")

    # 1. Strip leading duration/format prefix phrases
    # e.g., 'A 3-min video about dinosaurs' -> 'Dinosaurs'
    cleaned = re.sub(
        r"^(?:(?:a|an|quick)\s+)?(?:\d+(?:\.\d+)?\s*[-–—]?\s*(?:minutes?|mins?|m|seconds?|secs?|s)\s+)?(?:video|vid|short|shorts|overview|recap|explainer)\s+(?:about|on|of)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    cleaned = re.sub(
        r"^(?:(?:a|an|quick)\s+)?\d+(?:\.\d+)?\s*[-–—]?\s*(?:minutes?|mins?|m|seconds?|secs?|s)\s+(?:about|on|of)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # 2. Strip parenthesized / bracketed duration and video specifiers
    # e.g., (2 minute video), (5 min), [60s], (2m short), (video), (Shorts), (in 15 minutes)
    cleaned = re.sub(
        r"\s*[\(\[\{]\s*(?:in\s*)?(?:\d+(?:\.\d+)?\s*[-–—]?\s*(?:minutes?|mins?|m|seconds?|secs?|s)\b(?:\s*(?:video|vid|short|shorts|explainer))?|(?:video|vid|short|shorts|explainer))\s*[\)\]\}]",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # 3. Strip separator-prefixed duration and video specifiers
    # e.g., - 60s, — 5 min, - 3-minute, : 2 minute video, | 45 second short
    cleaned = re.sub(
        r"\s*[-–—:|]\s*(?:in\s*)?(?:\d+(?:\.\d+)?\s*[-–—]?\s*(?:minutes?|mins?|m|seconds?|secs?|s)\b(?:\s*(?:video|vid|short|shorts|explainer))?|(?:video|vid|short|shorts|explainer))\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # 4. Strip trailing duration and video specifiers without separators
    # e.g., 'Why Do Cats Purr 2 minute video', 'Black holes 2m short', 'History of Rome in 15 minutes'
    cleaned = re.sub(
        r"\s+(?:in\s+)?\d+(?:\.\d+)?\s*[-–—]?\s*(?:minutes?|mins?|m|seconds?|secs?|s)\s+(?:video|vid|short|shorts|explainer)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"\s+\d+(?:\.\d+)?\s*[-–—]?\s*(?:m|s)\s+(?:short|shorts)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"\s+in\s+\d+(?:\.\d+)?\s*[-–—]?\s*(?:minutes?|mins?|m|seconds?|secs?|s)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    # 5. Strip trailing punctuation left behind (dashes, colons, commas, pipes, quotes), preserving ? and !
    cleaned = re.sub(r"[\s\-–—:,|\"']+$", "", cleaned).strip()
    cleaned = cleaned.strip("\"'").strip()

    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]

    return cleaned or topic.strip()


def format_timestamp(seconds: float) -> str:
    """Format seconds into MM:SS or HH:MM:SS timestamp for YouTube chapter markers."""
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class YouTubePublisher:
    """Handles YouTube video upload and publishing via YouTube Data API v3."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def is_configured(self) -> bool:
        """Check if YouTube API credentials or saved token are available."""
        # Check direct env variables (headless / container deployment)
        if (
            self.settings.youtube_client_id
            and self.settings.youtube_client_secret
            and self.settings.youtube_refresh_token
        ):
            return True

        # Check saved credentials token file
        if (
            self.settings.youtube_token_file
            and self.settings.youtube_token_file.is_file()
        ):
            return True

        # Check client secrets file
        return bool(
            self.settings.youtube_client_secrets_file
            and self.settings.youtube_client_secrets_file.is_file()
        )

    def get_credentials(self) -> Credentials:
        """Load and refresh Google OAuth 2.0 credentials for YouTube uploading."""
        creds: Credentials | None = None

        # Strategy 1: Direct credentials from environment variables
        if (
            self.settings.youtube_client_id
            and self.settings.youtube_client_secret
            and self.settings.youtube_refresh_token
        ):
            creds = Credentials(
                token=None,
                refresh_token=self.settings.youtube_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.settings.youtube_client_id,
                client_secret=self.settings.youtube_client_secret,
                scopes=YOUTUBE_UPLOAD_SCOPE,
            )

        # Strategy 2: Stored token file
        elif (
            self.settings.youtube_token_file
            and self.settings.youtube_token_file.exists()
        ):
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.settings.youtube_token_file),
                    scopes=YOUTUBE_UPLOAD_SCOPE,
                )
            except Exception as e:
                raise YouTubeAuthenticationError(
                    f"Failed to load credentials from {self.settings.youtube_token_file}: {e}"
                ) from e

        if not creds:
            raise YouTubeAuthenticationError(
                "YouTube API credentials are not configured. Set YOUTUBE_CLIENT_ID, "
                "YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN (or YOUTUBE_TOKEN_FILE)."
            )

        # Refresh expired credentials if needed
        if not creds.valid or creds.expired:
            try:
                creds.refresh(Request())
                if (
                    self.settings.youtube_token_file
                    and self.settings.youtube_token_file.exists()
                ):
                    try:
                        self.settings.youtube_token_file.write_text(
                            creds.to_json(), encoding="utf-8"
                        )
                    except OSError as write_err:
                        logger.warning(
                            "Could not update refreshed token in %s: %s",
                            self.settings.youtube_token_file,
                            write_err,
                        )
            except Exception as ref_err:
                raise YouTubeAuthenticationError(
                    f"Failed to refresh YouTube OAuth token: {ref_err}"
                ) from ref_err

        return creds

    def format_metadata(
        self,
        topic: str,
        script: Script | None = None,
        storyboard: AnimationStoryboard | None = None,
        is_vertical: bool = False,
    ) -> tuple[str, str, list[str]]:
        """Formulate YouTube video title, description with chapter markers, and tags."""
        base_title = clean_topic_title(topic)

        # 1. Format Title (YouTube max 100 characters)
        if is_vertical:
            # YouTube Shorts format
            suffix = " #Shorts"
            max_title_len = 100 - len(suffix)
            title = f"{base_title[:max_title_len].strip()}{suffix}"
        else:
            title = base_title[:100].strip()

        # 2. Format Description
        desc_lines: list[str] = []
        if script and script.summary:
            desc_lines.append(script.summary.strip())
            desc_lines.append("")
        else:
            desc_lines.append(f"An animated educational exploration of: {base_title}")
            desc_lines.append("")

        # Add chapter timestamps for horizontal videos with multiple scenes
        if not is_vertical and storyboard and len(storyboard.scenes) > 1:
            desc_lines.append("⏱️ Chapters:")
            elapsed = 0.0
            for scene in storyboard.scenes:
                ts = format_timestamp(elapsed)
                scene_name = scene.title.strip() or f"Scene {scene.scene_number}"
                desc_lines.append(f"{ts} - {scene_name}")
                elapsed += scene.duration_seconds
            desc_lines.append("")

        if is_vertical:
            desc_lines.append("#Shorts #CuriosityOnDemand #Education #Animation")
        else:
            desc_lines.append("#CuriosityOnDemand #Education #Animation #Learning")

        desc_lines.append("")
        desc_lines.append(
            "Created automatically with Curiosity On Demand — AI-powered research, narration & animation."
        )

        description = "\n".join(desc_lines)

        # 3. Format Tags (YouTube max total character length is 500)
        default_tags = list(self.settings.youtube_default_tags)
        words = re.findall(r"\b[A-Za-z]{4,}\b", base_title)
        tags_set: list[str] = []
        for t in default_tags + words:
            tag_clean = t.strip()
            if tag_clean and tag_clean.lower() not in [x.lower() for x in tags_set]:
                tags_set.append(tag_clean)

        # Ensure tags stay under YouTube length budget
        tags: list[str] = []
        total_len = 0
        for tag in tags_set:
            if total_len + len(tag) + 1 <= 450:
                tags.append(tag)
                total_len += len(tag) + 1

        return title, description, tags

    def _upload_captions_sync(
        self,
        youtube: object,
        video_id: str,
        captions_path: Path,
        language: str = "en",
        name: str = "English",
    ) -> bool:
        """Upload a synchronized .srt subtitle track to an existing YouTube video."""
        if not captions_path.exists() or captions_path.stat().st_size == 0:
            return False

        try:
            captions_resource = getattr(youtube, "captions", None)
            if captions_resource is None:
                return False

            body = {
                "snippet": {
                    "videoId": video_id,
                    "language": language,
                    "name": name,
                    "isDraft": False,
                }
            }
            media = MediaFileUpload(
                str(captions_path),
                mimetype="application/x-subrip",
                resumable=False,
            )
            request = captions_resource().insert(
                part="snippet",
                body=body,
                media_body=media,
            )
            request.execute()
            logger.info(
                "Successfully uploaded SRT captions (%s) for YouTube video ID %s",
                captions_path.name,
                video_id,
            )
            return True
        except Exception as cap_err:  # noqa: BLE001
            logger.warning(
                "Could not upload SRT captions to YouTube for video %s (video upload succeeded): %s",
                video_id,
                cap_err,
            )
            return False

    def _upload_video_sync(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
        privacy_status: str,
        is_vertical: bool,
        captions_path: Path | None = None,
    ) -> YouTubePublishResult:
        """Synchronous method to upload video with resumable chunks and optional SRT captions."""
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found at: {video_path}")

        creds = self.get_credentials()
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            chunksize=5 * 1024 * 1024,  # 5MB chunks
            resumable=True,
        )

        logger.info(
            "Initiating YouTube video upload for '%s' (size=%.2f MB, privacy=%s)",
            title,
            video_path.stat().st_size / (1024 * 1024),
            privacy_status,
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info("YouTube upload progress for '%s': %d%%", title, pct)

        video_id = response.get("id")
        if not video_id:
            raise YouTubeUploadError(
                f"YouTube upload response missing video id: {response}"
            )

        if is_vertical:
            video_url = f"https://www.youtube.com/shorts/{video_id}"
        else:
            video_url = f"https://youtu.be/{video_id}"

        captions_uploaded = False
        if captions_path is not None and captions_path.exists():
            captions_uploaded = self._upload_captions_sync(
                youtube=youtube,
                video_id=video_id,
                captions_path=captions_path,
            )

        logger.info(
            "Successfully published video to YouTube! ID: %s, URL: %s (captions=%s)",
            video_id,
            video_url,
            captions_uploaded,
        )

        return YouTubePublishResult(
            video_id=video_id,
            video_url=video_url,
            title=title,
            privacy_status=privacy_status,
            is_short=is_vertical,
            captions_uploaded=captions_uploaded,
        )

    async def publish_video(
        self,
        video_path: Path | str,
        topic: str,
        script: Script | None = None,
        storyboard: AnimationStoryboard | None = None,
        is_vertical: bool = False,
        privacy_status: str | None = None,
        category_id: str | None = None,
        captions_path: Path | str | None = None,
    ) -> YouTubePublishResult:
        """Asynchronously publish a video to YouTube using non-blocking thread execution."""
        v_path = Path(video_path)
        resolved_captions: Path | None = None
        if captions_path is not None:
            resolved_captions = Path(captions_path)
        elif storyboard is not None and storyboard.captions_path:
            resolved_captions = Path(storyboard.captions_path)

        title, description, tags = self.format_metadata(
            topic=topic,
            script=script,
            storyboard=storyboard,
            is_vertical=is_vertical,
        )
        priv_status = privacy_status or self.settings.youtube_default_privacy_status
        cat_id = category_id or self.settings.youtube_default_category_id

        return await asyncio.to_thread(
            self._upload_video_sync,
            video_path=v_path,
            title=title,
            description=description,
            tags=tags,
            category_id=cat_id,
            privacy_status=priv_status,
            is_vertical=is_vertical,
            captions_path=resolved_captions,
        )


def main() -> None:
    """Interactive CLI to authenticate with Google OAuth and generate token file."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Curiosity On Demand - YouTube OAuth Interactive Setup"
    )
    parser.add_argument(
        "--client-secrets",
        type=str,
        default="client_secrets.json",
        help="Path to downloaded client_secrets.json from Google Cloud Console",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="storage/youtube_token.json",
        help="Path where the authorized token JSON will be saved",
    )
    args = parser.parse_args()

    client_secrets_path = Path(args.client_secrets)
    if not client_secrets_path.exists():
        print(f"Error: Client secrets file '{client_secrets_path}' not found.")
        print(
            "Download your OAuth 2.0 Client ID credentials from Google Cloud Console:"
        )
        print("https://console.cloud.google.com/apis/credentials")
        return

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets_path),
        scopes=YOUTUBE_UPLOAD_SCOPE,
    )
    creds = flow.run_local_server(port=8080)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(creds.to_json(), encoding="utf-8")

    print(f"\n✅ Authorization successful! Token saved to: {out_path.resolve()}")
    print("\nTo configure headless/Docker environments, add these to your .env file:")
    print(f"YOUTUBE_CLIENT_ID={creds.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={creds.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
