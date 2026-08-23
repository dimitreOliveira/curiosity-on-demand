"""YouTube video publishing service using YouTube Data API v3."""

import asyncio
import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"


class YouTubePublisher:
    """Publishes completed MP4 videos to YouTube with metadata and privacy controls."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._credentials: Credentials | None = None
        self._youtube_client = None

    def _get_authenticated_service(self):
        """Authenticate with OAuth2 credentials and return YouTube service client."""
        if self._youtube_client is not None:
            return self._youtube_client

        token_path = self.settings.youtube_token_file
        client_secrets_path = self.settings.youtube_client_secrets_file

        creds = None
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(token_path), YOUTUBE_UPLOAD_SCOPE
                )
            except (OSError, ValueError, KeyError) as e:
                logger.warning(
                    "Could not load existing YouTube token from %s: %s",
                    token_path,
                    e,
                )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired YouTube OAuth2 token...")
                creds.refresh(Request())
            elif client_secrets_path.exists():
                logger.info("Initiating OAuth2 flow using client secrets...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(client_secrets_path), YOUTUBE_UPLOAD_SCOPE
                )
                creds = flow.run_local_server(port=0)
            else:
                logger.warning(
                    "YouTube client secrets file not found at '%s'. YouTube publishing will run in simulated mode.",
                    client_secrets_path,
                )
                return None

            # Save refreshed credentials
            token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(token_path, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())

        self._credentials = creds
        self._youtube_client = build(
            YOUTUBE_API_SERVICE_NAME,
            YOUTUBE_API_VERSION,
            credentials=creds,
        )
        return self._youtube_client

    async def upload_video(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str] | None = None,
        privacy_status: str = "unlisted",
    ) -> str:
        """Upload video file to YouTube and return the video URL."""
        if not video_path.exists():
            raise FileNotFoundError(
                f"Video file to upload does not exist: {video_path}"
            )

        return await asyncio.to_thread(
            self._upload_video_sync,
            video_path,
            title,
            description,
            tags or [],
            privacy_status,
        )

    def _upload_video_sync(
        self,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        privacy_status: str,
    ) -> str:
        """Synchronous YouTube upload execution."""
        service = self._get_authenticated_service()

        if service is None:
            logger.warning(
                "YouTube API service not initialized. Simulating upload for '%s'",
                title,
            )
            # Simulated link for test and development without GCP credentials
            simulated_id = f"sim_{video_path.stem[:8]}"
            return f"https://youtu.be/{simulated_id}"

        body = {
            "snippet": {
                "title": title[:100],  # YouTube title limit
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": "27",  # Education category ID
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=1024 * 1024 * 5,  # 5MB chunks
        )

        logger.info("Starting YouTube upload for '%s' (%s)...", title, privacy_status)
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(
                    "YouTube upload progress: %d%%", int(status.progress() * 100)
                )

        video_id = response.get("id")
        video_url = f"https://youtu.be/{video_id}"
        logger.info("Video uploaded successfully to YouTube: %s", video_url)
        return video_url
