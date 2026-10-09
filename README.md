# Fal AIGC for Dify (v0.2.4)

中文优先 · A Dify Tool plugin for [fal.ai](https://fal.ai).

- **Z-Image Turbo**: `fal-ai/z-image/turbo` (only supported image model), default 16:9, 8 steps, 1 image, no prompt expansion, JPEG.
- **H3 Max T2V**: `minimax/h3-max/text-to-video`, default 5 sec, 480P, expansion disabled.
- **H3 Max I2V**: `minimax/h3-max/image-to-video`, optional Dify upload / HTTPS first and end frames, same defaults.
- **Merge videos**: `fal-ai/ffmpeg-api/merge-videos`, ordered JSON array or newline-separated HTTPS URL list (minimum 2, no arbitrary plugin-side count limit; Fal's service limits still apply).
- **Check Fal Job**: check an existing request ID without re-submitting (status-only calls may return IN_QUEUE / IN_PROGRESS, by design).

## **Completed-only behavior**

Image/video/merge nodes: submit to Fal queue, poll until COMPLETED and fetch the actual result, then finish the node. They never return an `IN_PROGRESS` result as success. The tool emits status text on every state transition (and occasional heartbeats) while running. The finished node JSON includes `status=COMPLETED`, `status_history`, URL and request ID. If the Fal job fails or the wait deadline passes, a **Dify node error** is raised with request ID. An errored/timeout Dify node does NOT mean Fal canceled the job! Use **Check Fal Job** to avoid re-paying for duplicates.

**Important Dify UI limitation:** A plugin cannot change the native Workflow node status badge. Dify displays the node as Running until it returns/throws, but real-time rendering of incremental tool text/log messages is version dependent. For a guaranteed live queue progress bar, a separate status-polling workflow/UI is required. Final run logs include the observed states.

## Setup

1. Download `.difypkg` from GitHub Actions or build with `dify-plugin plugin package . -o fal_aigc_0.2.4.difypkg`.
2. Dify → Plugins → Install Plugin → Local File; configure Fal API Key.
3. Add the tool node. It returns URL, JSON metadata, and an image preview or MP4 Dify File (up to 55MB) when `return_file=true`.
4. Connect `image_url` to H3 Max `image_url`, or add video URLs in a JSON array to FFmpeg merge.

Default `wait_seconds=540` (9 minutes), max 840 (14 minutes); the SDK request timeout is configured to 900 sec. **Your Dify edition, plugin daemon, ingress, and reverse proxy may impose shorter limits.** If so, reduce node timeout and use the Check Fal Job tool. No mechanism can guarantee unbounded blocking across a platform's timeouts.

## Build on GitHub, one click

Create public repo `lulu5049/dify-plugin-fal-aigc` (or change `repo` in manifest); upload the full source tree including `.github/workflows/build-plugin.yml`. In **Actions → Build Dify Plugin → Run workflow**, Dify's official CLI downloads and packages `.difypkg` as a GitHub Actions artifact. No Fal API Key is used at build time. Also builds automatically on pushes to main and tags `v*`.

## Model references

- https://fal.ai/models/fal-ai/z-image/turbo/api
- https://fal.ai/models/minimax/h3-max/text-to-video/api
- https://fal.ai/models/minimax/h3-max/image-to-video/api
- https://fal.ai/models/fal-ai/ffmpeg-api/merge-videos/api

## Security

- Fal API Key is stored as Dify plugin secret; it is never logged.
- Media uses HTTPS; URL parsing rejects localhost / raw IP literals and redirects when downloading finished MP4.
- Input images as Dify `file` are base64 encoded for the Fal API; avoid files over 15MB.
- API cost is determined by Fal billing, not the plugin.

## Installation compatibility and diagnostics

- The tools use ordinary Dify select fields with static options only. No `show_on` or `select_on` conditional parameter declarations.
- Dify's CLI packaging only verifies package structure; GitHub Actions also installs the actual Dify SDK and dependencies and tests all runtime module imports, mirroring the current TongYi AIGC repository build workflow.
- The plugin requires a compatible Dify runtime for the pinned SDK major/minor range (dify-plugin >=0.9, <0.11). Older Dify editions may require a lower SDK version.
- Slow *installation* usually happens in the plugin daemon when Python dependencies are fetched, not because Fal image/video tasks are slow. Inspect plugin daemon installation logs, Dify version, outbound access to PyPI, and allocated CPU/memory. A successful build cannot guarantee a particular Dify deployment's installation will finish.
- Generated media nodes wait for final success and provide Fal queue status messages; Dify may buffer progress output, depending on the frontend version.

Based on the TongYi AIGC branch merged by PR #3, which removed unsupported dynamic `show_on` conditions. This Fal plugin contains no such conditions.

## v0.2.4: Dify Cloud MP4 output fix

- Removed the unsupported `save_as` keyword from Dify SDK `create_blob_message` (the v0.9–v0.10 signature accepts only `blob` and `meta`).
- MP4 messages use the `video/mp4` MIME type and optional filename metadata.
- If the optional Dify attachment fails, the already-completed paid generation still succeeds with its Fal video URL and an explicit warning; it does not submit another generation task.
- CI tests the output path using the actual installed Dify SDK, preventing fake SDK mocks from masking signature differences.

## v0.2.4: Marketplace-style unconstrained SDK upper bound

- Match the original Dify Marketplace Tongyi AIGC requirements: `dify_plugin>=0.9.0` and `requests>=2.31.0,<3.0.0`.
- No artificial SDK upper limit. The plugin uses only public Dify Tool message factories and ToolProvider/DifyPluginEnv APIs.
- IMPORTANT: An unbounded SDK requirement does not guarantee Dify Cloud reuses a Marketplace plugin environment or avoids downloading packages. Installing a manually uploaded plugin may have different scheduling/caching behavior than installing a verified Marketplace plugin.
- This release retains the MP4 BLOB fix and requires real-SDK output and import tests to pass in CI.
