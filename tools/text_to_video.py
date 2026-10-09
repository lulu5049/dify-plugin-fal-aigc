from collections.abc import Generator
from typing import Any
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.fal_common import MODELS, completed_generation, FalError

class TextToVideoTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            prompt = str(tool_parameters.get('prompt') or '').strip()
            if not prompt:
                raise FalError('Prompt is required.')
            payload = {
                'prompt': prompt,
                'duration': float(tool_parameters.get('duration') or 5),
                'resolution': tool_parameters.get('resolution') or '480P',
                'aspect_ratio': tool_parameters.get('aspect_ratio') or '16:9',
                'prompt_expansion_mode': tool_parameters.get('prompt_expansion_mode') or 'disabled',
                'enable_safety_checker': True,
            }
            if payload['duration'] < 2 or payload['duration'] > 15:
                raise FalError('Duration must be between 2 and 15 seconds.')
            yield from completed_generation(
                self, MODELS['t2v'], payload,
                wait_seconds=tool_parameters.get('wait_seconds', 540),
                include_file=tool_parameters.get('return_file', True) is not False)
        except Exception as exc:
            raise ValueError(f'Fal text-to-video failed: {exc}') from exc
