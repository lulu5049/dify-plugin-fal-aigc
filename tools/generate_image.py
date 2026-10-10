from collections.abc import Generator
from typing import Any
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from tools.fal_common import MODELS, FalError, completed_generation

class GenerateImageTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        try:
            prompt = str(tool_parameters.get('prompt') or '').strip()
            if not prompt:
                raise FalError('Image prompt is required.')
            payload = {
                'prompt': prompt,
                'image_size': tool_parameters.get('image_size') or 'landscape_16_9',
                'num_inference_steps': 8,
                'num_images': 1,
                'enable_safety_checker': True,
                'output_format': 'jpeg',
                'acceleration': 'regular',
                'enable_prompt_expansion': False,
                'sync_mode': False,
            }
            seed = tool_parameters.get('seed')
            if seed is not None and seed != '':
                payload['seed'] = int(seed)
            yield from completed_generation(
                self, MODELS['zimage'], payload,
                wait_seconds=tool_parameters.get('wait_seconds', 540),
                include_image_preview=tool_parameters.get('return_file', True) is not False)
        except Exception as exc:
            raise ValueError(f'Fal Z-Image Turbo failed: {exc}') from exc
