from collections.abc import Generator
from typing import Any
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.fal_common import MODELS, completed_generation, FalError, to_image_url

class ImageToVideoTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            first = to_image_url(tool_parameters.get('image_input'), tool_parameters.get('image_url'))
            last = to_image_url(tool_parameters.get('end_image_input'), tool_parameters.get('end_image_url'))
            if not first and not last:
                raise FalError('Provide a start frame or end frame. For no image use Text to Video.')
            prompt = str(tool_parameters.get('prompt') or '').strip()
            if not prompt:
                raise FalError('Prompt is required.')
            payload = {'prompt': prompt, 'duration': float(tool_parameters.get('duration') or 5),
                       'resolution': tool_parameters.get('resolution') or '480P',
                       'prompt_expansion_mode': tool_parameters.get('prompt_expansion_mode') or 'disabled',
                       'enable_safety_checker': True}
            if payload['duration'] < 2 or payload['duration'] > 15:
                raise FalError('Duration must be between 2 and 15 seconds.')
            if first:
                payload['image_url'] = first
            if last:
                payload['end_image_url'] = last
            yield from completed_generation(
                self, MODELS['i2v'], payload,
                wait_seconds=tool_parameters.get('wait_seconds', 540))
        except Exception as exc:
            raise ValueError(f'Fal image-to-video failed: {exc}') from exc
