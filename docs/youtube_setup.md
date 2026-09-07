# YouTube OAuth & Publishing Setup Guide

This guide walks you through setting up YouTube Data API v3 credentials to enable automatic publishing of generated videos (regular horizontal 16:9 videos or vertical 9:16 Shorts) directly from Curiosity On Demand.

---

## Overview

YouTube Data API v3 requires OAuth 2.0 user credentials with the `https://www.googleapis.com/auth/youtube.upload` scope to upload videos on behalf of a channel. Standard API keys cannot upload videos.

The pipeline supports two credential options:
1. **Direct Environment Variables (Recommended for Docker / Cloud Servers):** `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` set in `.env`.
2. **Token File (Recommended for Local Development):** An authorized token JSON file saved at `storage/youtube_token.json`.

---

## Step 1: Create OAuth Credentials in Google Cloud Console

1. **Open Google Cloud Console:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/).
   - Select an existing project or create a new one (e.g., `Curiosity On Demand`).

2. **Enable the YouTube Data API v3:**
   - In the left sidebar, navigate to **APIs & Services** > **Library**.
   - Search for `YouTube Data API v3`.
   - Click on it and click **Enable**.

3. **Configure the OAuth Consent Screen:**
   - In the left sidebar, go to **APIs & Services** > **OAuth consent screen**.
   - Select **User Type:** `External` and click **Create**.
   - Fill in the required application details:
     - **App name:** `Curiosity On Demand`
     - **User support email:** Your email address
     - **Developer contact information:** Your email address
   - Under **Scopes:** You can proceed without adding scopes manually (the authorization tool requests the upload scope automatically).
   - Under **Test Users** *(Crucial step while in development)*:
     - Click **+ Add Users**.
     - Enter the Gmail address associated with the YouTube channel where videos will be uploaded.
   - Click **Save and Continue**.

4. **Create Desktop OAuth Client ID:**
   - Go to **APIs & Services** > **Credentials**.
   - Click **+ Create Credentials** at the top and choose **OAuth client ID**.
   - Set **Application type:** `Desktop app`.
   - Set **Name:** `Curiosity Bot`.
   - Click **Create**.
   - In the confirmation dialog, click **Download JSON** and save the file.

---

## Step 2: Generate Authorization Tokens

Curiosity On Demand includes a CLI helper that automates the OAuth handshake, generates the refresh token, and saves the credentials.

1. **Place the secrets file in your project directory:**
   ```bash
   cp /path/to/downloaded/client_secret_xxx.json client_secrets.json
   ```
   *(Note: `client_secrets*.json` is git-ignored to prevent accidental commits).*

2. **Run the interactive authorization CLI:**
   ```bash
   source .venv/bin/activate
   python -m services.youtube_publisher --client-secrets client_secrets.json
   ```

3. **Complete the Browser Sign-in:**
   - A browser window will open asking you to sign in with your Google account.
   - Choose the account/channel you added as a test user in Step 1.
   - If prompted with *"Google hasn't verified this app"*, click **Advanced** > **Go to Curiosity On Demand (unsafe)**.
   - Click **Continue** to grant video upload permissions.

4. **Review Generated Credentials:**
   The tool will save the authorized token to `storage/youtube_token.json` and print your configuration variables to the terminal:
   ```text
   ✅ Authorization successful! Token saved to: storage/youtube_token.json

   To configure headless/Docker environments, add these to your .env file:
   YOUTUBE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   YOUTUBE_CLIENT_SECRET=your_client_secret
   YOUTUBE_REFRESH_TOKEN=your_refresh_token
   ```

---

## Step 3: Configure `.env`

Choose one of the two configuration approaches:

### Approach A: Direct Environment Variables (Recommended for Docker / Cloud)
Add the printed credentials directly to your `.env` file:
```dotenv
YOUTUBE_CLIENT_ID=your_client_id.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=your_client_secret
YOUTUBE_REFRESH_TOKEN=your_refresh_token
YOUTUBE_DEFAULT_PRIVACY_STATUS=public
YOUTUBE_DEFAULT_CATEGORY_ID=27
YOUTUBE_DEFAULT_TAGS=CuriosityOnDemand,Education,Animation
```
With these variables defined, the bot can run headlessly inside Docker or on remote servers without needing any JSON files on disk. The token will be automatically refreshed in-memory whenever expired.

### Approach B: Local Token File
If you ran the helper locally, `storage/youtube_token.json` is already created. You can leave the client tokens empty and set:
```dotenv
YOUTUBE_TOKEN_FILE=storage/youtube_token.json
YOUTUBE_DEFAULT_PRIVACY_STATUS=public
YOUTUBE_DEFAULT_CATEGORY_ID=27
YOUTUBE_DEFAULT_TAGS=CuriosityOnDemand,Education,Animation
```

---

## Step 4: Video Publishing Settings Reference

| Variable | Default | Description |
| :--- | :--- | :--- |
| `YOUTUBE_CLIENT_ID` | `""` | OAuth 2.0 Client ID |
| `YOUTUBE_CLIENT_SECRET` | `""` | OAuth 2.0 Client Secret |
| `YOUTUBE_REFRESH_TOKEN` | `""` | Long-lived refresh token for headless operation |
| `YOUTUBE_TOKEN_FILE` | `storage/youtube_token.json` | Path to local credentials token file |
| `YOUTUBE_DEFAULT_PRIVACY_STATUS` | `public` | Privacy status for uploads: `public`, `unlisted`, or `private` |
| `YOUTUBE_DEFAULT_CATEGORY_ID` | `27` | YouTube Category ID (`27` = Education, `28` = Science & Tech) |
| `YOUTUBE_DEFAULT_TAGS` | `CuriosityOnDemand,Education,Animation` | Comma-separated list of default video tags |

---

## Troubleshooting

- **`403: access_denied` during login:** Ensure the Gmail address signing in was explicitly added under **Test users** in the Google Cloud Console OAuth consent screen.
- **`Token has been expired or revoked`:** Run the authorization command again (`python -m services.youtube_publisher --client-secrets client_secrets.json`) to obtain a fresh refresh token.
- **YouTube API Daily Upload Limits:** Google accounts on the free quota tier have daily YouTube upload limits. If you reach quota limits, uploads will fail with a quota exceeded error until the daily reset.
