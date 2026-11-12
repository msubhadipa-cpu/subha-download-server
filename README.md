# Subha VideoSave download server

The website is deployed separately. This Docker service must be deployed on a Docker-capable host before social downloads work. The Sites runtime cannot execute yt-dlp/FFmpeg.

1. Deploy this folder using its Dockerfile on your own Docker-capable host.
2. Set `DOWNLOAD_API_KEY` to a random secret of at least 24 characters. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
3. Set `SITE_ORIGIN` to `https://subha-video-save.msubhadipa.chatgpt.site` (no trailing slash).
4. Enable HTTPS for the service. Its `/health` route returns `service: subha-videosave`.
5. In the website's server connection panel, enter this HTTPS origin and the same secret. The website retains the secret in memory only, until page refresh.

Only public video URLs from the named platforms are accepted. No cookies, password access, private-video access, DRM handling or proxy bypass is included. Individual platform support depends on yt-dlp and the host's network/IP. YouTube may require additional supported JavaScript runtime configuration; rebuild with up-to-date yt-dlp and a supported runtime if its extractor reports failures. Do not promise every video or every platform works.

Jobs are limited to four pending, two simultaneous downloads, four-minute execution, 250 MB final file size, and videos shorter than one hour. Files expire after 30 minutes. Multi-process deployment is unsupported because job state is in memory; run one Uvicorn process. Rebuild the Docker image to update yt-dlp when extractors change.

Verification: API authentication, platform URL validation, queued job creation, status and completed file responses are tested using a mocked download. No live platform download has been verified without a running host.
