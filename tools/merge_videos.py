from collections.abc import Generator
from typing import Any
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.fal_common import MODELS, completed_generation, parse_video_urls

class MergeVideosTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            urls = parse_video_urls(tool_parameters.get('video_urls'))
            payload = {'video_urls': urls}
            fps = tool_parameters.get('target_fps')
            if fps is not None and fps != '' and float(fps) > 0:
                payload['target_fps'] = float(fps)
            # Omitting resolution preserves the input dimensions and avoids unwanted upscale.
            yield from completed_generation(
                self, MODELS['merge'], payload,
                wait_seconds=tool_parameters.get('wait_seconds', 540),
                include_file=tool_parameters.get('return_file', True) is not False)
        except Exception as exc:
            raise ValueError(f'Fal merge-videos failed: {exc}') from exc
